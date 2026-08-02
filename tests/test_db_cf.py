"""Tests for ``mnemo_mcp.db_cf`` -- the Cloudflare D1 memory backend.

The centrepiece is :class:`TestBackendParity`: every scenario there runs twice,
once against a real ``MemoryDB`` on a temp SQLite file and once against
``MemoryDBCfBackend``, and asserts the two agree. A surface that merely *looks*
substitutable is what this is meant to catch.

How the D1 side is exercised
----------------------------

``D1Backend`` takes an injectable transport (``http=``) whose contract is
``request(method, url, body, headers) -> (status, bytes)``. :class:`FakeD1Worker`
implements that transport by transcribing ``src/worker.ts``'s ``d1Outbound``
handler -- ``POST /query`` runs ``prepare(sql).bind(...params).all()`` and
answers ``Response.json({ results })``; every other route 404s -- against a real
SQLite database that has ``migrations/0001_init.sql`` applied.

What that reproduces faithfully: the SQL text and bound parameters actually sent,
the JSON request/response envelope, rows as JSON objects, one statement per
request with no client-side transaction, the real D1 schema (including the FTS5
external-content triggers), and the absence of ``sqlite-vec``. Also the route
surface -- ``test_fake_worker_matches_worker_ts`` pins the transcription against
``src/worker.ts`` so the double cannot drift away from the Worker it stands in
for, and ``test_only_query_route_is_used`` proves the backend never calls a route
the Worker does not serve.

What it does not reproduce: the network hop itself, D1's exact SQLite build,
Cloudflare's per-query limits (the 100-bound-parameter cap is enforced in the
backend and asserted separately here rather than by the double), and
concurrency. Driving a real local D1 through ``wrangler`` would add the network
hop at the cost of a node + wrangler subprocess per query, which cannot live in
the default pytest run; the SQL-level fidelity above is what the parity claim
rests on, and it is the part that can silently break.
"""

from __future__ import annotations

import json
import pathlib
import re
import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

# The Vectorize double lives next to the fidelity test that pins it against
# `src/worker.ts`. Imported here so the two suites cannot describe two different
# Workers.
from test_db_cf_vectors import FakeVectorizeWorker

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.db_cf import (
    D1_MAX_BOUND_PARAMS,
    MemoryDBCfBackend,
    open_memory_db,
)
from mnemo_mcp.exceptions import EmbeddingModelMismatch

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_MIGRATION = _REPO_ROOT / "migrations" / "0001_init.sql"
_WORKER_TS = _REPO_ROOT / "src" / "worker.ts"


class FakeD1Worker:
    """In-process stand-in for ``d1Outbound`` in ``src/worker.ts``.

    Deliberately literal: it serves ``POST /query`` and nothing else, exactly
    like the handler it transcribes, so a backend that reaches for ``/batch``
    fails here the same way it would fail in production.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.requests: list[tuple[str, str, list]] = []

    def request(self, method, url, data=None, headers=None):
        path = url.split("//", 1)[-1].split("/", 1)[-1]
        self.requests.append((method, "/" + path, []))
        if path != "query" or method != "POST":
            # `return new Response('not found', { status: 404 })`
            return (404, b"not found")

        payload = json.loads(data.decode())
        sql, params = payload["sql"], payload.get("params") or []
        self.requests[-1] = (method, "/" + path, params)
        cursor = self.conn.execute(sql, params)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        results = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        return (200, json.dumps({"results": results}).encode())


@pytest.fixture
def d1_conn(tmp_path) -> sqlite3.Connection:
    """A SQLite database carrying the real D1 schema.

    ``isolation_level=None`` puts pysqlite in autocommit, which is how D1
    behaves: every statement is committed on its own and there is no
    client-side transaction to roll back. sqlite-vec is never loaded, matching
    D1's inability to load extensions.

    ``check_same_thread=False`` because the real D1 is reached over HTTP and so
    is thread-agnostic: server handlers call the store through
    ``asyncio.to_thread``, and pysqlite's default thread check would fail the
    double where the wire would not.
    """
    conn = sqlite3.connect(
        tmp_path / "d1.sqlite", isolation_level=None, check_same_thread=False
    )
    conn.executescript(_MIGRATION.read_text(encoding="utf-8"))
    return conn


@pytest.fixture
def fake_worker(d1_conn: sqlite3.Connection) -> FakeD1Worker:
    return FakeD1Worker(d1_conn)


@pytest.fixture
def fake_vectorize() -> FakeVectorizeWorker:
    return FakeVectorizeWorker()


def _cf_db(
    worker: FakeD1Worker,
    vectorize: FakeVectorizeWorker | None = None,
    **kwargs,
) -> MemoryDBCfBackend:
    """Open a D1-backed store. Text-only unless a Vectorize double is passed.

    Vectors are the subject of ``tests/test_db_cf_vectors.py``; here an index is
    attached only where ``embedding_dims > 0`` makes one mandatory.
    """
    from mcp_core.storage.d1 import D1Backend
    from mcp_core.storage.vectorize import VectorizeBackend

    vectors = (
        None
        if vectorize is None
        else VectorizeBackend(
            base_url="http://vectorize.internal", idx="mnemo-test", http=vectorize
        )
    )
    return MemoryDBCfBackend(
        D1Backend(base_url="http://d1.internal", http=worker),
        vectors=vectors,
        **kwargs,
    )


@pytest.fixture
def cf_db(fake_worker: FakeD1Worker) -> MemoryDBCfBackend:
    return _cf_db(fake_worker)


@pytest.fixture
def sqlite_db(tmp_path) -> Generator[MemoryDB]:
    db = MemoryDB(tmp_path / "memories.db", embedding_dims=0)
    yield db
    db.close()


@pytest.fixture(params=["sqlite", "cf-d1"])
def either_db(request, tmp_path, fake_worker: FakeD1Worker):
    """The same scenario, once per backend."""
    if request.param == "sqlite":
        db = MemoryDB(tmp_path / "memories.db", embedding_dims=0)
        yield db
        db.close()
    else:
        db = _cf_db(fake_worker)
        yield db
        db.close()


# Age of the rows `_seed_aged` inserts. Doubles as the `archive_after_days`
# denominator in the archive-by-score test, which pins recency_factor at 1.0 so
# only importance separates the two rows.
_AGE_DAYS = 1000


def _seed_aged(db) -> None:
    """Insert two rows dated ``_AGE_DAYS`` in the past.

    ``add()`` always stamps "now", and the archive policies key off
    ``last_accessed`` / ``updated_at``, so ageing a row means importing one:
    ``import_jsonl`` honours explicit timestamps.
    """
    old = (datetime.now(UTC) - timedelta(days=_AGE_DAYS)).isoformat()
    db.import_jsonl(
        "\n".join(
            json.dumps(
                {
                    "id": mid,
                    "content": content,
                    "category": "tech",
                    "importance": importance,
                    "created_at": old,
                    "updated_at": old,
                    "last_accessed": old,
                }
            )
            for mid, content, importance in (
                ("aged-forgettable", "a forgotten note about a kangaroo", 0.1),
                ("aged-important", "an important note about a kangaroo", 0.9),
            )
        )
    )


def _seed(db) -> dict[str, str]:
    return {
        "python": db.add(
            "Python is a programming language", category="tech", tags=["python", "lang"]
        ),
        "typescript": db.add(
            "TypeScript is used for web development",
            category="tech",
            tags=["typescript", "web"],
        ),
        "groceries": db.add(
            "Remember to buy groceries", category="personal", tags=["todo"]
        ),
    }


class TestFakeWorkerFidelity:
    """The double is only evidence if it matches the Worker it replaces."""

    def test_fake_worker_matches_worker_ts(self):
        """``d1Outbound`` serves POST /query and 404s everything else.

        Pinned against the real file so a new route in the Worker (or a removed
        one) breaks this test instead of silently invalidating the parity suite.
        """
        source = _WORKER_TS.read_text(encoding="utf-8")
        handler = source.split("const d1Outbound", 1)[1].split("\nconst ", 1)[0]
        routes = set(re.findall(r"url\.pathname === '([^']+)'", handler))
        assert routes == {"/query"}, (
            f"src/worker.ts d1Outbound now serves {routes}; FakeD1Worker and "
            "MemoryDBCfBackend's single-route assumption need updating together"
        )
        assert "Response.json({ results })" in handler
        assert "status: 404" in handler

    def test_only_query_route_is_used(self, cf_db, fake_worker: FakeD1Worker):
        """Every backend operation must stay on the one route D1 serves.

        ``D1Backend.executemany`` falls back to ``POST /batch``, which this
        Worker 404s -- so the backend must never reach it.
        """
        mid = cf_db.add("route check", category="tech")
        cf_db.search("route")
        cf_db.list_memories()
        cf_db.stats()
        cf_db.import_jsonl(
            "\n".join(
                json.dumps({"id": f"i{i}", "content": f"row {i}"}) for i in range(25)
            )
        )
        cf_db.update(mid, content="route check edited")
        cf_db.export_jsonl()
        assert {path for _, path, _ in fake_worker.requests} == {"/query"}

    def test_unknown_route_404s_like_the_worker(self, fake_worker: FakeD1Worker):
        status, _ = fake_worker.request("POST", "http://d1.internal/batch", b"[]")
        assert status == 404

    def test_import_respects_d1_bound_parameter_cap(
        self, cf_db, fake_worker: FakeD1Worker
    ):
        """D1 rejects any query with more than 100 bound parameters.

        The chunking that keeps imports under that cap is invisible in the
        result, so assert it on the wire.
        """
        payload = "\n".join(
            json.dumps({"id": f"m{i}", "content": f"memory number {i}"})
            for i in range(60)
        )
        cf_db.import_jsonl(payload)
        widest = max(len(params) for _, _, params in fake_worker.requests)
        assert widest <= D1_MAX_BOUND_PARAMS, (
            f"a query carried {widest} bound parameters; D1 caps them at "
            f"{D1_MAX_BOUND_PARAMS}"
        )


class TestBackendParity:
    """Same scenario, both backends, results compared."""

    def test_add_then_get_roundtrip(self, either_db):
        mid = either_db.add(
            "Python is a programming language", category="tech", tags=["python"]
        )
        row = either_db.get(mid)
        assert row["content"] == "Python is a programming language"
        assert row["category"] == "tech"
        assert json.loads(row["tags"]) == ["python"]
        assert row["access_count"] == 0

    def test_add_rejects_oversized_content(self, either_db):
        with pytest.raises(ValueError, match="exceeds limit"):
            either_db.add("x" * 5001)

    def test_search_finds_by_full_text(self, either_db):
        ids = _seed(either_db)
        hits = either_db.search("programming language")
        assert [h["id"] for h in hits][:1] == [ids["python"]]

    def test_search_filters_by_category(self, either_db):
        _seed(either_db)
        hits = either_db.search("Python", category="personal")
        assert hits == []

    def test_search_filters_by_tags(self, either_db):
        ids = _seed(either_db)
        hits = either_db.search("development", tags=["web"])
        assert [h["id"] for h in hits] == [ids["typescript"]]

    def test_search_increments_access_count(self, either_db):
        ids = _seed(either_db)
        either_db.search("groceries")
        assert either_db.get(ids["groceries"])["access_count"] == 1

    def test_search_scores_are_identical_across_backends(
        self, sqlite_db, cf_db, monkeypatch
    ):
        """Scoring is borrowed rather than re-implemented; prove it agrees.

        Recency decay makes the absolute score time-dependent, so compare the
        ordering and the score values the two backends produce for the same
        corpus inserted in the same order.
        """
        for db in (sqlite_db, cf_db):
            _seed(db)
        left = sqlite_db.search("web development programming")
        right = cf_db.search("web development programming")
        assert [h["content"] for h in left] == [h["content"] for h in right]
        for a, b in zip(left, right, strict=True):
            assert a["score"] == pytest.approx(b["score"], rel=1e-6)

    def test_search_returns_nothing_for_unmatched_query(self, either_db):
        _seed(either_db)
        assert either_db.search("kangaroo") == []

    def test_list_memories_orders_by_updated_desc(self, either_db):
        _seed(either_db)
        rows = either_db.list_memories()
        assert len(rows) == 3
        assert [r["updated_at"] for r in rows] == sorted(
            (r["updated_at"] for r in rows), reverse=True
        )

    def test_list_memories_filters_by_category(self, either_db):
        _seed(either_db)
        assert len(either_db.list_memories(category="tech")) == 2

    def test_update_supersedes_and_changes_id(self, either_db):
        ids = _seed(either_db)
        new_id = either_db.update(ids["python"], content="Python 3.13 is current")
        assert new_id and new_id != ids["python"]
        assert either_db.get(ids["python"]) is None
        assert either_db.get(new_id)["content"] == "Python 3.13 is current"

    def test_update_carries_unspecified_fields_forward(self, either_db):
        ids = _seed(either_db)
        new_id = either_db.update(ids["python"], importance=0.9)
        row = either_db.get(new_id)
        assert row["content"] == "Python is a programming language"
        assert row["category"] == "tech"
        assert row["importance"] == pytest.approx(0.9)
        assert row["access_count"] == 0

    def test_update_of_missing_id_returns_none(self, either_db):
        assert either_db.update("does-not-exist", content="x") is None

    def test_update_twice_supersedes_the_successor(self, either_db):
        ids = _seed(either_db)
        first = either_db.update(ids["python"], content="v2")
        second = either_db.update(first, content="v3")
        assert either_db.get(first) is None
        assert either_db.get(second)["content"] == "v3"

    def test_updated_row_is_searchable_and_old_text_is_not(self, either_db):
        """FTS5 is external-content; the triggers are what keep it honest."""
        ids = _seed(either_db)
        either_db.update(ids["groceries"], content="Remember to buy stationery")
        assert either_db.search("stationery")
        assert either_db.search("groceries") == []

    def test_delete_hides_the_row(self, either_db):
        ids = _seed(either_db)
        assert either_db.delete(ids["groceries"]) is True
        assert either_db.get(ids["groceries"]) is None
        assert len(either_db.list_memories()) == 2

    def test_delete_of_missing_id_is_false(self, either_db):
        assert either_db.delete("does-not-exist") is False

    def test_delete_twice_is_false_the_second_time(self, either_db):
        ids = _seed(either_db)
        assert either_db.delete(ids["python"]) is True
        assert either_db.delete(ids["python"]) is False

    def test_stats_counts_current_rows_only(self, either_db):
        ids = _seed(either_db)
        either_db.delete(ids["groceries"])
        stats = either_db.stats()
        assert stats["total_memories"] == 2
        assert stats["categories"] == {"tech": 2}
        assert stats["vec_enabled"] is False

    def test_export_jsonl_roundtrips_through_import(self, either_db):
        _seed(either_db)
        payload, count = either_db.export_jsonl()
        assert count == 3
        lines = [json.loads(line) for line in payload.strip().split("\n")]
        assert {line["content"] for line in lines} == {
            "Python is a programming language",
            "TypeScript is used for web development",
            "Remember to buy groceries",
        }

    def test_import_merge_skips_existing_ids(self, either_db):
        _seed(either_db)
        payload, _ = either_db.export_jsonl()
        assert either_db.import_jsonl(payload) == {
            "imported": 0,
            "skipped": 3,
            "rejected": 0,
        }

    def test_import_merge_adds_new_ids(self, either_db):
        _seed(either_db)
        payload = json.dumps({"id": "brand-new", "content": "a fresh memory"})
        assert either_db.import_jsonl(payload) == {
            "imported": 1,
            "skipped": 0,
            "rejected": 0,
        }
        assert either_db.get("brand-new")["content"] == "a fresh memory"

    def test_import_replace_clears_first(self, either_db):
        _seed(either_db)
        payload = json.dumps({"id": "only-one", "content": "sole survivor"})
        result = either_db.import_jsonl(payload, mode="replace")
        assert result["imported"] == 1
        assert [r["id"] for r in either_db.list_memories()] == ["only-one"]

    def test_import_rejects_oversized_and_malformed_rows(self, either_db):
        payload = "\n".join(
            [
                json.dumps({"id": "ok", "content": "fine"}),
                json.dumps({"id": "big", "content": "x" * 5001}),
                "{not json",
            ]
        )
        assert either_db.import_jsonl(payload) == {
            "imported": 1,
            "skipped": 0,
            "rejected": 2,
        }

    def test_import_chunks_beyond_one_statement(self, either_db):
        """More rows than fit in a single D1 statement must all land."""
        payload = "\n".join(
            json.dumps({"id": f"bulk{i}", "content": f"bulk memory {i}"})
            for i in range(45)
        )
        assert either_db.import_jsonl(payload)["imported"] == 45
        assert either_db.stats()["total_memories"] == 45

    def test_archive_leaves_fresh_rows_alone(self, either_db):
        _seed(either_db)
        assert either_db.archive_old_memories(days=90) == 0
        assert len(either_db.list_memories()) == 3

    def test_archive_old_memories_by_age(self, either_db):
        _seed_aged(either_db)
        assert either_db.archive_old_memories(days=90) == 1
        assert {r["id"] for r in either_db.list_memories()} == {"aged-important"}

    def test_archive_respects_importance_threshold(self, either_db):
        _seed_aged(either_db)
        assert either_db.archive_old_memories(days=90, importance_threshold=0.95) == 2

    def test_archive_by_score_weights_importance(self, either_db):
        """score = (days_old / archive_after_days) * (1 - importance).

        Both rows are the same age, so only importance separates them: at
        recency_factor 1.0 the low-importance row scores 0.9 and the
        high-importance one 0.1.
        """
        _seed_aged(either_db)
        assert (
            either_db.archive_by_score(
                archive_after_days=_AGE_DAYS, score_threshold=0.5
            )
            == 1
        )
        assert {r["id"] for r in either_db.list_memories()} == {"aged-important"}

    def test_archived_rows_drop_out_of_search_and_list(self, either_db):
        _seed_aged(either_db)
        either_db.archive_old_memories(days=90, importance_threshold=1.0)
        assert either_db.list_memories() == []
        assert either_db.search("kangaroo") == []
        assert len(either_db.list_memories(include_archived=True)) == 2

    def test_list_archived_and_restore(self, either_db):
        _seed_aged(either_db)
        either_db.archive_old_memories(days=90, importance_threshold=1.0)
        archived = either_db.list_archived()
        assert {a["id"] for a in archived} == {"aged-forgettable", "aged-important"}
        # list_archived parses the JSON tags column into a real list.
        assert all(isinstance(a["tags"], list) for a in archived)
        assert either_db.restore_memory("aged-important") is True
        assert [r["id"] for r in either_db.list_memories()] == ["aged-important"]

    def test_restore_of_active_row_is_false(self, either_db):
        ids = _seed(either_db)
        assert either_db.restore_memory(ids["python"]) is False

    def test_update_importance_clamps_and_reports(self, either_db):
        ids = _seed(either_db)
        assert either_db.update_importance(ids["python"], 5.0) is True
        assert either_db.get(ids["python"])["importance"] == pytest.approx(1.0)
        assert either_db.update_importance("missing", 0.5) is False

    def test_check_duplicate_detects_repeat(self, either_db):
        either_db.add("Python is a programming language", category="tech")
        hit = either_db.check_duplicate("Python is a programming language")
        assert hit and hit["duplicate"] is True

    def test_check_duplicate_returns_none_for_novel_text(self, either_db):
        _seed(either_db)
        assert either_db.check_duplicate("entirely unrelated kangaroo content") is None

    def test_add_with_context_type(self, either_db):
        mid = either_db.add_with_context_type(
            "prefers dark mode", context_type="preference", importance=0.8
        )
        row = either_db.get(mid)
        assert row["context_type"] == "preference"
        assert row["importance"] == pytest.approx(0.8)

    def test_rrf_fuse_agrees(self, either_db):
        fused = either_db.rrf_fuse(["a", "b"], ["b", "c"])
        assert fused[0][0] == "b"

    def test_vec_enabled_is_false_without_embeddings(self, either_db):
        assert either_db.vec_enabled is False

    def test_public_surface_matches_memorydb(self, either_db):
        """No method may be missing from either backend."""
        expected = {
            name
            for name in vars(MemoryDB)
            if not name.startswith("_") and not name.startswith("run_")
        }
        assert expected <= {n for n in dir(either_db) if not n.startswith("_")}


class TestVectorPathIsLoud:
    """A text-only store must refuse a vector, never quietly discard it.

    ``cf_db`` is opened with ``embedding_dims=0``, which declares the store
    text-only: no Vectorize index is attached and there is nowhere for a vector
    to go, since D1 has no ``memories_vec``. The wired path -- what happens once
    an index *is* attached -- is ``tests/test_db_cf_vectors.py``.
    """

    def test_add_with_embedding_raises(self, cf_db):
        with pytest.raises(NotImplementedError, match="embedding_dims=0"):
            cf_db.add("with a vector", embedding=[0.1] * 768)

    def test_add_with_context_type_with_embedding_raises(self, cf_db):
        with pytest.raises(NotImplementedError, match="embedding_dims=0"):
            cf_db.add_with_context_type("with a vector", embedding=[0.1] * 768)

    def test_search_with_embedding_raises(self, cf_db):
        _seed(cf_db)
        with pytest.raises(NotImplementedError, match="embedding_dims=0"):
            cf_db.search("anything", embedding=[0.1] * 768)

    def test_update_with_embedding_raises(self, cf_db):
        ids = _seed(cf_db)
        with pytest.raises(NotImplementedError, match="embedding_dims=0"):
            cf_db.update(ids["python"], embedding=[0.1] * 768)

    def test_search_without_embedding_still_works(self, cf_db):
        """Rejecting vectors must not break the FTS-only path."""
        _seed(cf_db)
        assert cf_db.search("Python")


class TestUnavailableSurface:
    """Methods this backend cannot serve raise and say what is missing."""

    def test_get_sync_state_raises(self, cf_db):
        with pytest.raises(NotImplementedError, match="sync_state"):
            cf_db.get_sync_state("gdrive")

    def test_upsert_sync_state_raises(self, cf_db):
        with pytest.raises(NotImplementedError, match="sync_state"):
            cf_db.upsert_sync_state("gdrive", last_sync_at=1.0)

    def test_sync_state_is_genuinely_absent_from_the_d1_schema(self, d1_conn):
        """The NotImplementedError above states a fact; check the fact."""
        names = {
            r[0] for r in d1_conn.execute("SELECT name FROM sqlite_master").fetchall()
        }
        assert "sync_state" not in names
        assert "memories" in names

    def test_rollback_is_not_silently_a_noop(self, cf_db):
        with pytest.raises(NotImplementedError, match="ROLLBACK"):
            cf_db._conn.rollback()

    def test_schema_creation_is_wranglers_job(self, cf_db):
        with pytest.raises(NotImplementedError, match="wrangler"):
            cf_db._conn.executescript("CREATE TABLE t (x)")


class TestFailLoud:
    """Nothing here may report success, emptiness, or zero for a failure."""

    def test_missing_schema_fails_at_open(self, tmp_path):
        blank = sqlite3.connect(tmp_path / "blank.sqlite", isolation_level=None)
        with pytest.raises(RuntimeError, match="migrations apply"):
            _cf_db(FakeD1Worker(blank))

    def test_transport_failure_during_search_raises(self, cf_db, fake_worker):
        """A dead D1 must not look like "no matches".

        ``MemoryDB._search_fts`` catches per-tier exceptions and logs them; on
        this backend that would turn an outage into an empty result set.
        """
        _seed(cf_db)

        def dead(method, url, data=None, headers=None):
            return (500, b"internal error")

        fake_worker.request = dead
        with pytest.raises(RuntimeError, match="must not be treated as 'no matches'"):
            cf_db.search("Python")

    def test_transport_failure_during_add_raises(self, cf_db, fake_worker):
        def dead(method, url, data=None, headers=None):
            return (500, b"internal error")

        fake_worker.request = dead
        with pytest.raises(RuntimeError):
            cf_db.add("this write cannot land")

    def test_failed_successor_insert_reopens_the_predecessor(self, cf_db, fake_worker):
        """A half-applied supersession must not leave a row closed forever."""
        ids = _seed(cf_db)
        real_request = fake_worker.request

        def fail_the_insert(method, url, data=None, headers=None):
            payload = json.loads(data.decode())
            if payload["sql"].startswith("INSERT INTO memories"):
                return (500, b"insert exploded")
            return real_request(method, url, data, headers)

        fake_worker.request = fail_the_insert
        with pytest.raises(RuntimeError):
            cf_db.update(ids["python"], content="never lands")

        fake_worker.request = real_request
        row = cf_db.get(ids["python"])
        assert row is not None, "predecessor was left closed with no successor"
        assert row["content"] == "Python is a programming language"

    def test_use_after_close_raises(self, cf_db):
        cf_db.close()
        with pytest.raises(RuntimeError, match="closed"):
            cf_db.list_memories()

    def test_embedding_identity_mismatch_raises(self, fake_worker, fake_vectorize):
        db = _cf_db(
            fake_worker, fake_vectorize, embedding_dims=768, embedding_model="model-a"
        )
        db.close()
        with pytest.raises(EmbeddingModelMismatch):
            _cf_db(
                fake_worker,
                fake_vectorize,
                embedding_dims=768,
                embedding_model="model-b",
            )

    def test_embedding_identity_is_stamped_on_a_fresh_store(
        self, fake_worker, fake_vectorize
    ):
        db = _cf_db(
            fake_worker, fake_vectorize, embedding_dims=768, embedding_model="model-a"
        )
        assert db.get_store_meta("embedding_dims") == "768"
        assert db.get_store_meta("embedding_model") == "model-a"

    def test_rejects_non_integer_dims(self, fake_worker):
        with pytest.raises(ValueError, match="must be an integer"):
            _cf_db(fake_worker, embedding_dims=768.0)


class TestBackendSelection:
    """``MEMORY_DB_BACKEND`` is read in exactly one place."""

    def test_defaults_to_sqlite(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MEMORY_DB_BACKEND", raising=False)
        db = open_memory_db(tmp_path / "memories.db")
        try:
            assert isinstance(db, MemoryDB)
        finally:
            db.close()

    def test_explicit_sqlite(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MEMORY_DB_BACKEND", "sqlite")
        db = open_memory_db(tmp_path / "memories.db")
        try:
            assert isinstance(db, MemoryDB)
        finally:
            db.close()

    def test_cf_d1_selects_the_d1_backend(self, tmp_path, monkeypatch, fake_worker):
        monkeypatch.setenv("MEMORY_DB_BACKEND", "cf-d1")
        monkeypatch.setattr(
            "mnemo_mcp.db_cf.d1_backend_from_env",
            lambda: __import__("mcp_core.storage.d1", fromlist=["D1Backend"]).D1Backend(
                base_url="http://d1.internal", http=fake_worker
            ),
        )
        db = open_memory_db(tmp_path / "memories.db")
        try:
            assert isinstance(db, MemoryDBCfBackend)
        finally:
            db.close()

    def test_unknown_backend_raises_rather_than_falling_back(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("MEMORY_DB_BACKEND", "cf-dl")
        with pytest.raises(ValueError, match="Unknown MEMORY_DB_BACKEND"):
            open_memory_db(tmp_path / "memories.db")

    def test_selection_kwargs_reach_the_sqlite_backend(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MEMORY_DB_BACKEND", raising=False)
        db = open_memory_db(tmp_path / "memories.db", recency_half_life_days=3.0)
        try:
            assert db._recency_half_life == 3.0
        finally:
            db.close()


class TestStatusNamesTheStoreItRead:
    """``config(action="status")`` must name the store it actually queried.

    It used to print ``settings.get_db_path()`` -- the SQLite path -- whatever
    ``MEMORY_DB_BACKEND`` selected, so a D1-backed deployment reported a file
    inside its container while serving memories that live in D1. The field is a
    diagnostic, so a backend-blind value sends the next investigation to the
    wrong store.
    """

    @staticmethod
    def _ctx(db):
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {
            "db": db,
            "embedding_model": None,
            "embedding_dims": 0,
        }
        return ctx

    async def test_sqlite_status_names_the_sqlite_file(self, sqlite_db, tmp_path):
        from mnemo_mcp.server import _handle_config_status

        status = await _handle_config_status(self._ctx(sqlite_db))
        assert status["database"]["path"] == str(tmp_path / "memories.db")

    async def test_cf_d1_status_names_d1_not_a_sqlite_file(self, cf_db):
        from mnemo_mcp.config import settings
        from mnemo_mcp.server import _handle_config_status

        status = await _handle_config_status(self._ctx(cf_db))
        assert status["database"]["path"] == "cf-d1:http://d1.internal"
        # The regression this pins: the SQLite path from settings, which a D1
        # deployment never opens.
        assert status["database"]["path"] != str(settings.get_db_path())

    async def test_status_and_memory_stats_cannot_disagree(self, either_db):
        """The invariant the bug broke: one container, one answer.

        ``memory_stats`` and ``config status`` read the same store in the same
        process, so they may not name two different ones.
        """
        from mnemo_mcp.server import _handle_config_status, _handle_stats

        ctx = self._ctx(either_db)
        status = await _handle_config_status(ctx)
        stats = await _handle_stats(ctx)
        assert status["database"]["path"] == stats["db_path"]
        assert status["database"]["total_memories"] == stats["total_memories"]


def test_docs_db_backend_is_gone_from_the_repo():
    """The old name is dead config; nothing may reintroduce it.

    It was copied in from the wet-mcp Worker template and no Python in this repo
    (nor in mcp-core) ever read it, so it was renamed rather than aliased.
    """
    tracked = [
        _REPO_ROOT / "src" / "worker.ts",
        _REPO_ROOT / "wrangler.jsonc",
        _REPO_ROOT / "wrangler.deploy.jsonc",
        _REPO_ROOT / "wrangler.deploy.template.jsonc",
        _REPO_ROOT / "README.md",
    ]
    for path in tracked:
        body = path.read_text(encoding="utf-8")
        assert "DOCS_DB_BACKEND" not in body, f"{path.name} still names DOCS_DB_BACKEND"
        assert "MEMORY_DB_BACKEND" in body, f"{path.name} lost MEMORY_DB_BACKEND"
