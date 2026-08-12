"""Tests for the Cloudflare Vectorize arm of ``mnemo_mcp.db_cf`` (S2 Task 4).

``tests/test_db_cf.py`` covers the D1 + FTS5 half of ``MemoryDBCfBackend`` and
owns the backend-parity suite. This file covers what happens once a Vectorize
index is attached, and it is organised around the four places where the D1 build
cannot simply behave like the SQLite one:

1. Cloudflare returns at most 50 vector matches per query, and
   ``VectorizeBackend.query`` applies that cap with a bare ``min(top_k, 50)`` --
   no exception, no warning. ``TestTopKCeiling`` pins the announcement.
2. Vectorize is eventually consistent while D1 is not, so a just-added memory is
   text-searchable before it is vector-searchable. ``TestEventualConsistency``
   asserts that behaviour rather than hiding it behind a retry, and pins the
   reason the obvious fix does not work.
3. ``delete`` and ``update`` only move ``valid_to``, which Vectorize knows nothing
   about. ``TestSupersededRowsStayGone`` proves a closed row cannot come back --
   including when its vector is still sitting in the index.
4. ``REINDEX_ON_MODEL_CHANGE`` has real vectors to drop now.
   ``TestReindexDropsVectors`` covers the success and the failure path.

How the Vectorize side is exercised
-----------------------------------

Same approach as ``FakeD1Worker``: :class:`FakeVectorizeWorker` implements the
``request(method, url, body, headers) -> (status, bytes)`` transport that
``VectorizeBackend`` takes via ``http=``, transcribing ``vectorizeOutbound`` from
``src/worker.ts`` route for route -- including its unconditional
``GET -> {ready: true}``, which is the whole reason
``wait_until_indexed()`` is useless here.
``test_fake_worker_matches_worker_ts`` pins the transcription against the real
file so a new route cannot drift away from the double.

What it adds beyond transcription: a two-stage index (``pending`` then
``visible``) so eventual consistency can be exercised deterministically instead
of by sleeping, and a ``fail_delete`` switch so the read-side supersession filter
can be tested with the write-side deliberately broken. What it does not
reproduce: Cloudflare's actual ANN recall (the double is an exact cosine scan, so
ranking is exact where production is approximate), real propagation timing, and
metadata-filter behaviour -- the latter is exercised by the tenant-isolation
regression tests.
"""

from __future__ import annotations

import json
import math
import pathlib
import re
import sqlite3
from collections.abc import Generator
from urllib.parse import urlparse

import pytest
from loguru import logger

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.db_cf import (
    VECTORIZE_MAX_TOP_K,
    MemoryDBCfBackend,
    VectorCandidateCap,
)
from mnemo_mcp.exceptions import EmbeddingModelMismatch

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_MIGRATION = _REPO_ROOT / "migrations" / "0001_init.sql"
_MIGRATION_2 = _REPO_ROOT / "migrations" / "0002_per_sub_isolation.sql"
_MIGRATION_3 = _REPO_ROOT / "migrations" / "0003_vector_state.sql"
_WORKER_TS = _REPO_ROOT / "src" / "worker.ts"

# Test vectors are 8-wide for readability. `test_wire_carries_full_width_vector`
# covers the real 768 the store_meta of the live store records.
DIMS = 8


def _unit(axis: int, dims: int = DIMS) -> list[float]:
    """A one-hot vector, so cosine similarity between test vectors is obvious."""
    vec = [0.0] * dims
    vec[axis] = 1.0
    return vec


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


class FakeVectorizeWorker:
    """In-process stand-in for ``vectorizeOutbound`` in ``src/worker.ts``.

    Serves ``/upsert``, ``/query`` and ``/deleteByIds``, answers any GET with
    ``{ready: true}``, and 404s the rest -- exactly the route surface of the
    handler it transcribes.

    An upsert lands in ``pending`` and only becomes queryable on
    :meth:`settle`, which is how Vectorize behaves and how the read-after-write
    gap is tested without sleeping. ``settle_immediately`` collapses that for the
    tests where indexing lag is not the subject.
    """

    def __init__(self, *, settle_immediately: bool = True) -> None:
        self.visible: dict[str, list[float]] = {}
        self.pending: dict[str, list[float]] = {}
        self.visible_metadata: dict[str, dict] = {}
        self.pending_metadata: dict[str, dict] = {}
        self.settle_immediately = settle_immediately
        self.fail_delete = False
        self.requests: list[tuple[str, str, object]] = []

    def settle(self) -> None:
        """Make every pending upsert queryable, as Vectorize eventually does."""
        self.visible.update(self.pending)
        self.visible_metadata.update(self.pending_metadata)
        self.pending.clear()
        self.pending_metadata.clear()

    def request(self, method, url, data=None, headers=None):
        path = urlparse(url).path

        if method == "POST" and path == "/upsert":
            # `(await request.text()).split('\n').filter(Boolean).map(JSON.parse)`
            vectors = [json.loads(line) for line in data.decode().split("\n") if line]
            self.requests.append((method, path, vectors))
            target = self.visible if self.settle_immediately else self.pending
            metadata_target = (
                self.visible_metadata
                if self.settle_immediately
                else self.pending_metadata
            )
            for vector in vectors:
                target[vector["id"]] = vector["values"]
                metadata_target[vector["id"]] = vector.get("metadata") or {}
            return (200, json.dumps({"mutationId": "m-upsert"}).encode())

        if method == "POST" and path == "/query":
            payload = json.loads(data.decode())
            self.requests.append((method, path, payload))
            vector, top_k = payload["vector"], payload["topK"]
            metadata_filter = payload.get("filter") or {}
            ranked = sorted(
                (
                    (mid, _cosine(vector, v))
                    for mid, v in self.visible.items()
                    if all(
                        self.visible_metadata.get(mid, {}).get(key) == value
                        for key, value in metadata_filter.items()
                    )
                ),
                key=lambda kv: kv[1],
                reverse=True,
            )
            matches = [
                {
                    "id": m,
                    "score": s,
                    "metadata": self.visible_metadata.get(m, {}),
                }
                for m, s in ranked[:top_k]
            ]
            return (200, json.dumps({"matches": matches}).encode())

        if method == "POST" and path == "/deleteByIds":
            payload = json.loads(data.decode())
            self.requests.append((method, path, payload))
            if self.fail_delete:
                return (500, b"internal error")
            for mid in payload["ids"]:
                self.visible.pop(mid, None)
                self.pending.pop(mid, None)
                self.visible_metadata.pop(mid, None)
                self.pending_metadata.pop(mid, None)
            return (200, json.dumps({"mutationId": "m-delete"}).encode())

        self.requests.append((method, path, None))
        if method == "GET":
            # `if (request.method === 'GET') return Response.json({ ready: true })`
            # -- unconditional, which is the point.
            return (200, json.dumps({"ready": True}).encode())

        return (404, b"not found")


class FakeD1Worker:
    """``d1Outbound`` stand-in. Mirrors the one in ``tests/test_db_cf.py``."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.requests: list[tuple[str, str, list]] = []

    def request(self, method, url, data=None, headers=None):
        path = urlparse(url).path
        if path != "/query" or method != "POST":
            return (404, b"not found")
        payload = json.loads(data.decode())
        sql, params = payload["sql"], payload.get("params") or []
        self.requests.append((method, path, params))
        cursor = self.conn.execute(sql, params)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        results = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        return (200, json.dumps({"results": results}).encode())


@pytest.fixture
def fake_worker(tmp_path) -> FakeD1Worker:
    conn = sqlite3.connect(tmp_path / "d1.sqlite", isolation_level=None)
    conn.executescript(_MIGRATION.read_text(encoding="utf-8"))
    conn.executescript(_MIGRATION_2.read_text(encoding="utf-8"))
    conn.executescript(_MIGRATION_3.read_text(encoding="utf-8"))
    return FakeD1Worker(conn)


@pytest.fixture
def fake_vectorize() -> FakeVectorizeWorker:
    return FakeVectorizeWorker()


@pytest.fixture
def lagging_vectorize() -> FakeVectorizeWorker:
    return FakeVectorizeWorker(settle_immediately=False)


def _cf_db(
    worker: FakeD1Worker,
    vectorize: FakeVectorizeWorker | None,
    *,
    embedding_dims: int = DIMS,
    **kwargs,
) -> MemoryDBCfBackend:
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
        embedding_dims=embedding_dims,
        **kwargs,
    )


@pytest.fixture
def cf_db(fake_worker, fake_vectorize) -> MemoryDBCfBackend:
    return _cf_db(fake_worker, fake_vectorize)


@pytest.fixture
def captured_logs() -> Generator[list[dict]]:
    """Collect loguru records; loguru does not route through pytest's caplog."""
    records: list[dict] = []
    sink_id = logger.add(
        lambda message: records.append(
            {
                "level": message.record["level"].name,
                "message": message.record["message"],
            }
        ),
        level="WARNING",
        format="{message}",
    )
    yield records
    logger.remove(sink_id)


def _messages(records: list[dict], level: str) -> str:
    return "\n".join(r["message"] for r in records if r["level"] == level)


class TestFakeVectorizeFidelity:
    """The double is only evidence if it matches the Worker it replaces."""

    def test_fake_worker_matches_worker_ts(self):
        """``vectorizeOutbound`` serves exactly these three POST routes."""
        source = _WORKER_TS.read_text(encoding="utf-8")
        handler = source.split("const vectorizeOutbound", 1)[1].split("\nconst ", 1)[0]
        routes = set(re.findall(r"url\.pathname === '([^']+)'", handler))
        assert routes == {"/upsert", "/query", "/deleteByIds"}, (
            f"src/worker.ts vectorizeOutbound now serves {routes}; "
            "FakeVectorizeWorker and MemoryDBCfBackend need updating together"
        )
        assert "status: 404" in handler

    def test_ready_probe_is_unconditional_in_the_worker(self):
        """The readiness GET reports nothing about whether an upsert landed.

        This pins the reason ``MemoryDBCfBackend`` never calls
        ``VectorizeBackend.wait_until_indexed()``: the Worker answers every GET
        with ``{ready: true}`` regardless of index state, so waiting on it would
        return an "indexed" signal that means only "the handler is wired". If
        this assertion ever fails because the Worker grew a real mutation probe,
        the read-after-write behaviour documented in ``db_cf`` can be revisited.
        """
        source = _WORKER_TS.read_text(encoding="utf-8")
        handler = source.split("const vectorizeOutbound", 1)[1].split("\nconst ", 1)[0]
        assert (
            "if (request.method === 'GET') return Response.json({ ready: true })"
            in handler
        )

    def test_ready_probe_lies_about_pending_upserts(self, lagging_vectorize):
        """The same thing, demonstrated on the double rather than by reading."""
        from mcp_core.storage.vectorize import VectorizeBackend

        backend = VectorizeBackend(
            base_url="http://vectorize.internal", idx="i", http=lagging_vectorize
        )
        backend.upsert([{"id": "a", "values": _unit(0)}])
        assert backend.wait_until_indexed(poll_interval=0, max_wait=0.1) is True
        assert lagging_vectorize.visible == {}, (
            "wait_until_indexed() returned True while nothing was queryable"
        )


class TestVectorWiring:
    """A vector handed to the store reaches the index, and comes back."""

    def test_add_upserts_the_vector_under_the_memory_id(self, cf_db, fake_vectorize):
        mid = cf_db.add("Python is a programming language", embedding=_unit(0))
        assert fake_vectorize.visible == {cf_db._vectorize_id(mid): _unit(0)}

    def test_vector_ledger_closes_the_backfill_gap(self, cf_db, fake_vectorize):
        """A successful remote write is the only thing that clears a backfill row."""
        mid = cf_db.add("Python is a programming language")

        assert [row["id"] for row in cf_db.rows_without_vectors(10)] == [mid]

        cf_db.write_vector(mid, _unit(0))

        assert cf_db.rows_without_vectors(10) == []
        assert fake_vectorize.visible == {cf_db._vectorize_id(mid): _unit(0)}

    def test_vector_ledger_reopens_after_model_or_width_drift(self, cf_db):
        """The ledger is a version stamp, not a permanent "has vector" flag."""
        mid = cf_db.add("Python is a programming language", embedding=_unit(0))
        assert cf_db.rows_without_vectors(10) == []

        cf_db._conn.execute(
            "UPDATE memory_vectors SET embedding_model = ?, embedding_dims = ? "
            "WHERE sub = ? AND memory_id = ?",
            ["old-model", DIMS + 1, cf_db.sub, mid],
        )

        assert [row["id"] for row in cf_db.rows_without_vectors(10)] == [mid]

    def test_search_finds_a_memory_by_vector_alone(self, cf_db):
        """Text the FTS index cannot match; only the vector arm can answer.

        Both rows come back -- a nearest-neighbour query ranks the whole index
        rather than filtering it, on Vectorize as on ``sqlite-vec``. Their fused
        scores tie (each is rank 1 in one arm and rank 2 in the other), and the
        order is still deterministic *here* because ``_vector_candidates``
        preserves Vectorize's ranking, which the stable sort then keeps. That is
        the property under test; the parity suite deliberately does not assert
        it across backends.
        """
        mid = cf_db.add("Python is a programming language", embedding=_unit(0))
        other = cf_db.add("Remember to buy groceries", embedding=_unit(1))

        hits = cf_db.search("zzzz-unmatchable-token", embedding=_unit(0))
        assert [h["id"] for h in hits] == [mid, other]

    def test_add_with_context_type_upserts_too(self, cf_db, fake_vectorize):
        mid = cf_db.add_with_context_type(
            "User prefers dark mode", context_type="preference", embedding=_unit(2)
        )
        assert fake_vectorize.visible[cf_db._vectorize_id(mid)] == _unit(2)

    def test_hybrid_search_fuses_both_arms(self, cf_db):
        """Both arms contribute; the fused list is the borrowed RRF's output."""
        text_only = cf_db.add("Python is a programming language", embedding=_unit(3))
        vector_only = cf_db.add("totally unrelated wording", embedding=_unit(0))

        hits = cf_db.search("Python programming", embedding=_unit(0), limit=5)
        found = {h["id"] for h in hits}
        assert text_only in found, "FTS arm did not contribute"
        assert vector_only in found, "vector arm did not contribute"

    def test_row_survives_a_failed_vector_write(self, cf_db, fake_vectorize):
        """D1 is written first, so a Vectorize outage cannot orphan a vector.

        The failure is raised, not swallowed; what it leaves behind is a row with
        no vector -- text-searchable now, repaired by a reindex -- rather than a
        vector pointing at a row that was never written.
        """
        fake_vectorize.request = lambda *a, **k: (503, b"unavailable")
        with pytest.raises(RuntimeError, match="upsert failed"):
            cf_db.add("ordering check", embedding=_unit(0))
        assert [h["id"] for h in cf_db.search("ordering check")] != []
        assert [row["content"] for row in cf_db.rows_without_vectors(10)] == [
            "ordering check"
        ]

    def test_wire_carries_full_width_vector(self, fake_worker, fake_vectorize):
        """768 is what the live store's ``store_meta`` records."""
        db = _cf_db(fake_worker, fake_vectorize, embedding_dims=768)
        mid = db.add("real-width vector", embedding=[0.5] * 768)
        assert len(fake_vectorize.visible[db._vectorize_id(mid)]) == 768

    def test_oversized_vector_is_reshaped_like_sqlite(self, cf_db, fake_vectorize):
        """``db._serialize_f32`` truncates/pads; parity means doing the same."""
        long_id = cf_db.add("too long", embedding=[1.0] * (DIMS + 4))
        short_id = cf_db.add("too short", embedding=[1.0, 1.0])
        assert fake_vectorize.visible[cf_db._vectorize_id(long_id)] == [1.0] * DIMS
        assert fake_vectorize.visible[cf_db._vectorize_id(short_id)] == [
            1.0,
            1.0,
        ] + [0.0] * (DIMS - 2)

    def test_vec_enabled_reflects_the_attached_index(self, cf_db, fake_worker):
        assert cf_db.vec_enabled is True
        assert cf_db.stats()["vec_enabled"] is True
        text_only = _cf_db(fake_worker, None, embedding_dims=0)
        assert text_only.vec_enabled is False
        assert text_only.stats()["vec_enabled"] is False

    def test_transport_failure_is_not_swallowed(self, cf_db, fake_vectorize):
        """``MemoryDB.search`` logs its vector branch's errors at debug and
        carries on; against a network backend that turns an outage into an
        FTS-only result set that looks healthy."""
        cf_db.add("Python is a programming language", embedding=_unit(0))
        fake_vectorize.request = lambda *a, **k: (503, b"unavailable")
        with pytest.raises(RuntimeError, match="query failed"):
            cf_db.search("Python", embedding=_unit(0))


class TestNoIndexAttached:
    """``embedding_dims=0`` means text-only, and says so when handed a vector."""

    @pytest.mark.parametrize("method", ["add", "add_with_context_type"])
    def test_write_with_embedding_raises(self, fake_worker, method):
        db = _cf_db(fake_worker, None, embedding_dims=0)
        with pytest.raises(NotImplementedError, match="embedding_dims=0"):
            getattr(db, method)("content", embedding=_unit(0))

    def test_update_with_embedding_raises(self, fake_worker):
        db = _cf_db(fake_worker, None, embedding_dims=0)
        mid = db.add("content")
        with pytest.raises(NotImplementedError, match="embedding_dims=0"):
            db.update(mid, content="new", embedding=_unit(0))

    def test_search_with_embedding_raises(self, fake_worker):
        db = _cf_db(fake_worker, None, embedding_dims=0)
        db.add("Python is a programming language")
        with pytest.raises(NotImplementedError, match="embedding_dims=0"):
            db.search("Python", embedding=_unit(0))

    def test_text_only_search_still_works(self, fake_worker):
        db = _cf_db(fake_worker, None, embedding_dims=0)
        mid = db.add("Python is a programming language")
        assert [h["id"] for h in db.search("Python")] == [mid]

    def test_attaching_an_index_to_a_text_only_store_is_rejected(
        self, fake_worker, fake_vectorize
    ):
        with pytest.raises(ValueError, match="embedding_dims=0"):
            _cf_db(fake_worker, fake_vectorize, embedding_dims=0)

    def test_missing_index_name_names_the_variable(self, fake_worker, monkeypatch):
        """A bare ``KeyError('MCP_VECTORIZE_IDX')`` explains nothing."""
        monkeypatch.delenv("MCP_VECTORIZE_IDX", raising=False)
        with pytest.raises(RuntimeError, match="MCP_VECTORIZE_IDX is not set"):
            _cf_db(fake_worker, None, embedding_dims=DIMS)

    def test_reindex_without_an_index_raises(self, fake_worker):
        db = _cf_db(fake_worker, None, embedding_dims=0)
        with pytest.raises(NotImplementedError, match="no Vectorize index"):
            db._drop_vectors_for_reindex()


class TestTopKCeiling:
    """Hard spot 1: Cloudflare serves at most 50 candidates, silently."""

    def test_mcp_core_clamps_without_a_word(self, fake_vectorize):
        """The premise this whole class exists for, pinned on the real client.

        If ``mcp_core`` ever grows a warning or an exception here, this fails and
        the local announcement can be reconsidered.
        """
        from mcp_core.storage.vectorize import VectorizeBackend

        backend = VectorizeBackend(
            base_url="http://vectorize.internal", idx="i", http=fake_vectorize
        )
        backend.query(_unit(0), top_k=500)
        _, _, payload = fake_vectorize.requests[-1]
        assert payload["topK"] == VECTORIZE_MAX_TOP_K

    def test_truncation_is_recorded_and_warned(self, cf_db, captured_logs):
        """``limit=10`` asks for a pool of 100 and can only get 50."""
        cf_db.add("Python is a programming language", embedding=_unit(0))

        cf_db.search("Python", embedding=_unit(0), limit=10)

        assert cf_db.last_vector_cap == VectorCandidateCap(requested=100, served=50)
        assert cf_db.last_vector_cap.truncated is True
        warning = _messages(captured_logs, "WARNING")
        assert "100" in warning and "50" in warning, warning

    def test_default_limit_is_not_truncated(self, cf_db, captured_logs):
        """``limit=5`` -> pool of exactly 50: both arms see the same depth."""
        cf_db.add("Python is a programming language", embedding=_unit(0))

        cf_db.search("Python", embedding=_unit(0))

        assert cf_db.last_vector_cap == VectorCandidateCap(requested=50, served=50)
        assert cf_db.last_vector_cap.truncated is False
        assert "Vectorize" not in _messages(captured_logs, "WARNING")

    def test_truncation_actually_drops_candidates(self, cf_db):
        """Not just bookkeeping: the 51st-best vector match never arrives.

        60 memories, all vector-matched, none text-matched. A pool of 100 would
        rank all 60; the ceiling means the vector arm ranks 50.
        """
        ids = [
            cf_db.add(
                f"row number {i}", embedding=[1.0, float(i) / 100, 0, 0, 0, 0, 0, 0]
            )
            for i in range(60)
        ]
        assert len(ids) == 60

        hits = cf_db.search(
            "zzzz-unmatchable-token", embedding=_unit(0), candidate_pool=100
        )

        assert cf_db.last_vector_cap == VectorCandidateCap(requested=100, served=50)
        assert len(hits) == VECTORIZE_MAX_TOP_K, (
            "60 rows match the query vector and a pool of 100 was requested, but "
            "only 50 can ever come back from Vectorize"
        )

    def test_explicit_small_pool_is_honoured_unclamped(self, cf_db, captured_logs):
        cf_db.add("Python is a programming language", embedding=_unit(0))
        cf_db.search("Python", embedding=_unit(0), candidate_pool=20)
        assert cf_db.last_vector_cap == VectorCandidateCap(requested=20, served=20)
        assert "Vectorize" not in _messages(captured_logs, "WARNING")

    def test_cap_is_not_recorded_when_the_vector_arm_did_not_run(self, cf_db):
        cf_db.add("Python is a programming language")
        cf_db.search("Python", limit=10)
        assert cf_db.last_vector_cap is None


class TestEventualConsistency:
    """Hard spot 2: D1 is immediate, Vectorize is not -- documented, not hidden."""

    @pytest.fixture
    def lagging_db(self, fake_worker, lagging_vectorize) -> MemoryDBCfBackend:
        return _cf_db(fake_worker, lagging_vectorize)

    def test_new_memory_is_text_searchable_immediately(self, lagging_db):
        mid = lagging_db.add("Python is a programming language", embedding=_unit(0))
        hits = lagging_db.search("Python", embedding=_unit(0))
        assert [h["id"] for h in hits] == [mid], (
            "D1 is strongly consistent; the row must be findable by text at once"
        )

    def test_new_memory_is_not_yet_vector_searchable(
        self, lagging_db, lagging_vectorize
    ):
        """The documented gap, asserted rather than retried away.

        A query only the vector arm can answer returns nothing until Vectorize
        indexes the upsert. Papering over this with a silent retry loop is what
        the docstring in ``db_cf`` refuses to do.
        """
        lagging_db.add("Python is a programming language", embedding=_unit(0))

        assert lagging_db.search("zzzz-unmatchable-token", embedding=_unit(0)) == []

        lagging_vectorize.settle()
        hits = lagging_db.search("zzzz-unmatchable-token", embedding=_unit(0))
        assert len(hits) == 1

    def test_backend_never_polls_the_ready_endpoint(
        self, lagging_db, lagging_vectorize
    ):
        """``wait_until_indexed`` cannot mean what its name says here.

        ``vectorizeOutbound`` answers every GET with ``{ready: true}``, so polling
        it after an upsert would produce a confident "indexed" that is really
        "the handler is reachable" -- a manufactured success signal. The backend
        must therefore issue no GET at all.
        """
        lagging_db.add("Python is a programming language", embedding=_unit(0))
        lagging_db.search("Python", embedding=_unit(0))
        assert [m for m, _, _ in lagging_vectorize.requests if m == "GET"] == []

    def test_lag_does_not_suppress_the_row_itself(self, lagging_db):
        """The row is fully readable while only its vector is in flight."""
        mid = lagging_db.add("Python is a programming language", embedding=_unit(0))
        assert lagging_db.get(mid)["content"] == "Python is a programming language"
        assert [r["id"] for r in lagging_db.list_memories()] == [mid]


class TestSupersededRowsStayGone:
    """Hard spot 3: a closed row must never come back through the vector arm."""

    def test_delete_removes_the_vector(self, cf_db, fake_vectorize):
        mid = cf_db.add("Python is a programming language", embedding=_unit(0))
        assert cf_db.delete(mid) is True
        assert fake_vectorize.visible == {}

    def test_deleted_row_is_absent_from_vector_search(self, cf_db):
        mid = cf_db.add("Python is a programming language", embedding=_unit(0))
        cf_db.delete(mid)
        assert cf_db.search("zzzz-unmatchable-token", embedding=_unit(0)) == []

    def test_deleted_row_stays_gone_even_with_its_vector_still_indexed(
        self, cf_db, fake_vectorize, captured_logs
    ):
        """The load-bearing test: the read-side filter, with the write side broken.

        ``fail_delete`` makes ``/deleteByIds`` return 500, so the vector survives
        the delete exactly as it would if the call had failed or not yet
        propagated. Search must still not return the row, because every Vectorize
        hit is re-checked against D1's ``valid_to IS NULL``.
        """
        mid = cf_db.add("Python is a programming language", embedding=_unit(0))
        fake_vectorize.fail_delete = True

        assert cf_db.delete(mid) is True
        assert cf_db._vectorize_id(mid) in fake_vectorize.visible, (
            "precondition: the vector must survive"
        )
        assert "[AUDIT]" in _messages(captured_logs, "ERROR")

        assert cf_db.search("zzzz-unmatchable-token", embedding=_unit(0)) == []
        assert cf_db.search("Python", embedding=_unit(0)) == []

    def test_update_returns_the_successor_not_the_predecessor(self, cf_db):
        old_id = cf_db.add("Python is a programming language", embedding=_unit(0))
        new_id = cf_db.update(old_id, content="Python is a great language")

        hits = cf_db.search("Python", embedding=_unit(0))
        found = {h["id"] for h in hits}
        assert old_id not in found
        assert found == {new_id}

    def test_superseded_row_stays_gone_with_its_vector_still_indexed(
        self, cf_db, fake_vectorize
    ):
        """Same as the delete case, for the id ``update`` closes."""
        old_id = cf_db.add("Python is a programming language", embedding=_unit(0))
        fake_vectorize.fail_delete = True
        new_id = cf_db.update(old_id, content="Python is a great language")

        assert cf_db._vectorize_id(old_id) in fake_vectorize.visible, (
            "precondition: the vector survives"
        )
        assert new_id is not None
        assert cf_db.search("zzzz-unmatchable-token", embedding=_unit(0)) == []

    def test_update_with_an_embedding_vectorises_the_successor(
        self, cf_db, fake_vectorize
    ):
        old_id = cf_db.add("Python is a programming language", embedding=_unit(0))
        new_id = cf_db.update(old_id, content="Python rules", embedding=_unit(1))

        assert fake_vectorize.visible == {cf_db._vectorize_id(new_id): _unit(1)}
        hits = cf_db.search("zzzz-unmatchable-token", embedding=_unit(1))
        assert [h["id"] for h in hits] == [new_id]

    def test_metadata_only_update_says_the_successor_lost_its_vector(
        self, cf_db, fake_vectorize, captured_logs
    ):
        """SQLite carries the vector forward; Vectorize cannot be read back.

        The successor is unvectorised until something re-embeds it, and that is
        announced rather than left to show up as recall that quietly got worse.
        """
        old_id = cf_db.add("Python is a programming language", embedding=_unit(0))
        new_id = cf_db.update(old_id, category="tech")

        assert fake_vectorize.visible == {}
        warning = _messages(captured_logs, "WARNING")
        assert new_id in warning and "no vector" in warning, warning

        # Still reachable by text -- the degradation is bounded and stated.
        assert [h["id"] for h in cf_db.search("Python")] == [new_id]

    def test_archived_row_is_excluded_from_the_vector_arm(self, cf_db):
        """The re-authorisation applies every caller filter, not just valid_to."""
        mid = cf_db.add("Python is a programming language", embedding=_unit(0))
        cf_db._backend.execute(
            "UPDATE memories SET archived_at = ? WHERE id = ?", ["2020-01-01", mid]
        )
        assert cf_db.search("zzzz-unmatchable-token", embedding=_unit(0)) == []
        hits = cf_db.search(
            "zzzz-unmatchable-token", embedding=_unit(0), include_archived=True
        )
        assert [h["id"] for h in hits] == [mid]

    def test_category_filter_applies_to_the_vector_arm(self, cf_db):
        cf_db.add(
            "Python is a programming language", category="tech", embedding=_unit(0)
        )
        personal = cf_db.add("buy groceries", category="personal", embedding=_unit(0))
        hits = cf_db.search(
            "zzzz-unmatchable-token", embedding=_unit(0), category="personal"
        )
        assert [h["id"] for h in hits] == [personal]


class TestReindexDropsVectors:
    """Hard spot 4: ``REINDEX_ON_MODEL_CHANGE`` has something to drop now."""

    def test_model_change_without_reindex_still_raises(
        self, fake_worker, fake_vectorize
    ):
        _cf_db(fake_worker, fake_vectorize, embedding_model="model-a")
        with pytest.raises(EmbeddingModelMismatch):
            _cf_db(fake_worker, fake_vectorize, embedding_model="model-b")

    def test_reindex_deletes_every_vector(self, fake_worker, fake_vectorize):
        db = _cf_db(fake_worker, fake_vectorize, embedding_model="model-a")
        db.add("Python is a programming language", embedding=_unit(0))
        db.add("Remember to buy groceries", embedding=_unit(1))
        assert len(fake_vectorize.visible) == 2

        reindexed = _cf_db(
            fake_worker,
            fake_vectorize,
            embedding_model="model-b",
            reindex_on_model_change=True,
        )

        assert fake_vectorize.visible == {}
        assert reindexed.get_store_meta("embedding_model") == "model-b"

    def test_reindex_keeps_the_rows(self, fake_worker, fake_vectorize):
        """Only vectors are destroyed; the rows re-embed on the next pass."""
        db = _cf_db(fake_worker, fake_vectorize, embedding_model="model-a")
        mid = db.add("Python is a programming language", embedding=_unit(0))

        reindexed = _cf_db(
            fake_worker,
            fake_vectorize,
            embedding_model="model-b",
            reindex_on_model_change=True,
        )
        row = reindexed.get(mid)
        assert row is not None, "the reindex destroyed the row, not just its vector"
        assert row["content"] == "Python is a programming language"

    def test_failed_reindex_raises_and_keeps_the_old_stamp(
        self, fake_worker, fake_vectorize
    ):
        """A half-done reindex must not re-stamp the new model.

        Re-stamping over an index still holding the old model's vectors is the
        mixed-vector-space corruption the identity guard exists to prevent -- and
        at equal width it degrades search with no error anywhere. The guard
        stamps only after this returns, so raising leaves the old identity in
        place and the next boot retries.
        """
        db = _cf_db(fake_worker, fake_vectorize, embedding_model="model-a")
        db.add("Python is a programming language", embedding=_unit(0))
        fake_vectorize.fail_delete = True

        with pytest.raises(RuntimeError, match="deleteByIds failed"):
            _cf_db(
                fake_worker,
                fake_vectorize,
                embedding_model="model-b",
                reindex_on_model_change=True,
            )

        assert db.get_store_meta("embedding_model") == "model-a"
        assert len(fake_vectorize.visible) == 1


class TestReplaceImportClearsVectors:
    """``import_jsonl(mode='replace')`` must not leave the old vectors behind."""

    def test_replace_import_deletes_vectors(self, cf_db, fake_vectorize):
        cf_db.add("Python is a programming language", embedding=_unit(0))
        cf_db.import_jsonl(
            json.dumps({"id": "fresh", "content": "a fresh row"}), mode="replace"
        )
        assert fake_vectorize.visible == {}
        assert [r["id"] for r in cf_db.list_memories()] == ["fresh"]

    def test_merge_import_keeps_vectors(self, cf_db, fake_vectorize):
        mid = cf_db.add("Python is a programming language", embedding=_unit(0))
        cf_db.import_jsonl(json.dumps({"id": "extra", "content": "another row"}))
        assert fake_vectorize.visible == {cf_db._vectorize_id(mid): _unit(0)}


class TestVectorParityWithSqlite:
    """The same vector scenario on both backends, results compared.

    ``tests/test_db_cf.py``'s ``either_db`` runs the text-only surface against
    both stores. This is the vector counterpart: it cannot compare scores (one
    ranks by ``sqlite-vec`` distance, the other by Vectorize similarity) but it
    can compare which memories come back and, where the fused scores differ at
    all, in what order.

    Exactly-tied fused scores are deliberately not compared. Two candidates that
    are (FTS rank 1, vector rank 2) and (FTS rank 2, vector rank 1) get identical
    RRF sums, and the stable sort then settles them on insertion order -- which
    is Vectorize's ranking here but SQLite's table order there, because
    ``MemoryDB.search`` re-reads its vector matches with ``WHERE id IN (...)``.
    Asserting an order that neither backend defines would be a test of
    coincidence. See ``MemoryDBCfBackend._vector_candidates``.
    """

    @pytest.fixture(params=["sqlite", "cf-d1"])
    def either_vec_db(self, request, tmp_path, fake_worker, fake_vectorize):
        if request.param == "sqlite":
            db = MemoryDB(tmp_path / "memories.db", embedding_dims=DIMS)
            if not db.vec_enabled:
                # macOS hosted runners build Python without
                # --enable-loadable-sqlite-extensions, so sqlite-vec cannot load
                # and MemoryDB has no vector arm to compare against (see
                # tests/test_db_vec_coverage.py, which documents the same
                # constraint). Skipped rather than asserted around: forcing
                # `_vec_enabled = True` over a stand-in table, as that file does
                # for branch coverage, would compare this backend against a fake
                # ranking and call the result parity. The cf-d1 half of this
                # class still runs here; the parity claim itself rests on the
                # runners where sqlite-vec is real.
                db.close()
                pytest.skip(
                    "sqlite-vec is unavailable on this interpreter "
                    "(sqlite3 built without loadable-extension support), so "
                    "there is no SQLite vector arm to compare against"
                )
            yield db
            db.close()
        else:
            db = _cf_db(fake_worker, fake_vectorize)
            yield db
            db.close()

    def test_vector_only_recall_agrees(self, either_vec_db):
        """Rows the FTS arm cannot reach are reached, on both backends."""
        mid = either_vec_db.add("Python is a programming language", embedding=_unit(0))
        other = either_vec_db.add("Remember to buy groceries", embedding=_unit(1))

        assert either_vec_db.search("zzzz-unmatchable-token") == [], (
            "precondition: the query text must be unreachable by FTS alone"
        )
        hits = either_vec_db.search("zzzz-unmatchable-token", embedding=_unit(0))
        assert {h["id"] for h in hits} == {mid, other}

    def test_untied_ranking_agrees(self, either_vec_db):
        """Where the fused scores actually differ, both backends order alike.

        ``mid`` is first in both arms -- it is the only text match and the exact
        vector match -- so its RRF sum strictly beats ``other``'s and the result
        does not depend on either backend's tie-break.
        """
        mid = either_vec_db.add("Python is a programming language", embedding=_unit(0))
        other = either_vec_db.add("Remember to buy groceries", embedding=_unit(1))

        hits = either_vec_db.search("Python programming", embedding=_unit(0))
        assert [h["id"] for h in hits] == [mid, other]

    def test_deleted_memory_disappears_from_both(self, either_vec_db):
        mid = either_vec_db.add("Python is a programming language", embedding=_unit(0))
        assert either_vec_db.delete(mid) is True
        assert either_vec_db.search("zzzz-unmatchable-token", embedding=_unit(0)) == []

    def test_superseded_version_never_returns_on_either(self, either_vec_db):
        old_id = either_vec_db.add("Python is a language", embedding=_unit(0))
        new_id = either_vec_db.update(old_id, content="Python is a great language")

        hits = either_vec_db.search("Python", embedding=_unit(0))
        assert [h["id"] for h in hits] == [new_id]

    def test_hybrid_search_returns_both_arms_on_both(self, either_vec_db):
        text_only = either_vec_db.add(
            "Python is a programming language", embedding=_unit(3)
        )
        vector_only = either_vec_db.add("totally unrelated wording", embedding=_unit(0))

        found = {
            h["id"]
            for h in either_vec_db.search("Python programming", embedding=_unit(0))
        }
        assert found == {text_only, vector_only}

    def test_vec_enabled_agrees(self, either_vec_db):
        assert either_vec_db.vec_enabled is True
