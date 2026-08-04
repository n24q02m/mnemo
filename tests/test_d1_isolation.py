"""Regression tests for the Cloudflare D1/Vectorize tenant contract."""

from __future__ import annotations

import json
import pathlib
import sqlite3
from types import SimpleNamespace
from typing import cast

import pytest
from mcp.server.fastmcp import Context
from test_db_cf import FakeD1Worker
from test_db_cf_vectors import DIMS, FakeVectorizeWorker

from mnemo_mcp.credential_state import set_current_sub
from mnemo_mcp.db_cf import MemoryDBCfBackend
from mnemo_mcp.server import _get_ctx

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_MIGRATION_1 = _REPO_ROOT / "migrations" / "0001_init.sql"
_MIGRATION_2 = _REPO_ROOT / "migrations" / "0002_per_sub_isolation.sql"


def _apply_migrations(conn: sqlite3.Connection) -> None:
    conn.executescript(_MIGRATION_1.read_text(encoding="utf-8"))
    conn.executescript(_MIGRATION_2.read_text(encoding="utf-8"))


def _memory_row(memory_id: str, content: str) -> dict[str, str]:
    return {"id": memory_id, "content": content}


def _make_backend(
    conn: sqlite3.Connection,
    vectors: FakeVectorizeWorker,
    sub: str,
) -> MemoryDBCfBackend:
    from mcp_core.storage.d1 import D1Backend
    from mcp_core.storage.vectorize import VectorizeBackend

    return MemoryDBCfBackend(
        D1Backend(base_url="http://d1.internal", http=FakeD1Worker(conn)),
        vectors=VectorizeBackend(
            base_url="http://vectorize.internal", idx="mnemo-test", http=vectors
        ),
        embedding_dims=DIMS,
        sub=sub,
    )


def test_fresh_upgrade_schema_is_scoped_and_0001_stays_legacy(tmp_path):
    """A fresh 0001 database becomes scoped only through the additive upgrade."""
    conn = sqlite3.connect(tmp_path / "fresh.sqlite", isolation_level=None)
    _apply_migrations(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()}
    assert "sub" in columns
    assert (
        conn.execute("SELECT sub FROM memories WHERE id = ?", ("missing",)).fetchone()
        is None
    )

    conn.execute(
        "INSERT INTO memories (sub, id, content, created_at, updated_at, last_accessed) "
        "VALUES (?, ?, ?, datetime('now'), datetime('now'), datetime('now'))",
        ("sub-a", "same-id", "A"),
    )
    conn.execute(
        "INSERT INTO memories (sub, id, content, created_at, updated_at, last_accessed) "
        "VALUES (?, ?, ?, datetime('now'), datetime('now'), datetime('now'))",
        ("sub-b", "same-id", "B"),
    )
    assert conn.execute(
        "SELECT sub, content FROM memories WHERE id = ? ORDER BY sub", ("same-id",)
    ).fetchall() == [("sub-a", "A"), ("sub-b", "B")]


def test_upgrade_preserves_0001_rows_under_default_sub(tmp_path):
    """Rows present before 0002 remain readable and are explicitly default-scoped."""
    conn = sqlite3.connect(tmp_path / "upgrade.sqlite", isolation_level=None)
    conn.executescript(_MIGRATION_1.read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES (?, ?, datetime('now'), datetime('now'), datetime('now'))",
        ("legacy-id", "legacy content"),
    )
    conn.executescript(_MIGRATION_2.read_text(encoding="utf-8"))

    assert conn.execute(
        "SELECT sub, content FROM memories WHERE id = ?", ("legacy-id",)
    ).fetchone() == ("default", "legacy content")


def test_d1_backend_cannot_read_another_subs_rows(tmp_path):
    """D1 reads and Vectorize candidates are both restricted to the request sub."""
    conn = sqlite3.connect(tmp_path / "d1.sqlite", isolation_level=None)
    _apply_migrations(conn)
    vectors = FakeVectorizeWorker()
    sub_a = _make_backend(conn, vectors, "sub-a")
    sub_b = _make_backend(conn, vectors, "sub-b")

    shared_a = sub_a.import_jsonl(json.dumps(_memory_row("same-id", "alpha secret")))
    shared_b = sub_b.import_jsonl(json.dumps(_memory_row("same-id", "beta secret")))
    assert shared_a["imported"] == 1
    assert shared_b["imported"] == 1

    a_id = sub_a.add("alpha vector secret", embedding=[1.0] + [0.0] * (DIMS - 1))
    b_id = sub_b.add("beta vector secret", embedding=[0.0, 1.0] + [0.0] * (DIMS - 2))
    vectors.settle()

    row_a = sub_a.get("same-id")
    row_b = sub_b.get("same-id")
    assert row_a is not None
    assert row_b is not None
    assert row_a["content"] == "alpha secret"
    assert row_b["content"] == "beta secret"
    assert sub_a.get(b_id) is None
    assert sub_b.get(a_id) is None
    assert {row["content"] for row in sub_a.list_memories()} == {
        "alpha secret",
        "alpha vector secret",
    }
    assert {row["content"] for row in sub_b.list_memories()} == {
        "beta secret",
        "beta vector secret",
    }
    assert all(
        row["content"] != "beta vector secret"
        for row in sub_a.search(
            "unmatched vector query", embedding=[0.0, 1.0] + [0.0] * (DIMS - 2)
        )
    )
    assert all(
        request[2].get("filter") == {"sub": "sub-a"}
        for request in vectors.requests
        if request[0] == "POST" and request[1] == "/query"
    )


def test_d1_vector_search_rejects_foreign_vector_id_with_matching_metadata(tmp_path):
    """A matching Vectorize tenant filter cannot authorize a foreign ID prefix."""
    conn = sqlite3.connect(tmp_path / "d1.sqlite", isolation_level=None)
    _apply_migrations(conn)
    vectors = FakeVectorizeWorker()
    db = _make_backend(conn, vectors, "sub-a")

    assert (
        db.import_jsonl(json.dumps(_memory_row("same-id", "alpha secret")))["imported"]
        == 1
    )
    vectors.visible["sub-b:same-id"] = [1.0] + [0.0] * (DIMS - 1)
    vectors.visible_metadata["sub-b:same-id"] = {"sub": "sub-a"}

    assert (
        db.search(
            "unmatched vector query",
            embedding=[1.0] + [0.0] * (DIMS - 1),
            candidate_pool=1,
        )
        == []
    )
    conn.close()


def test_d1_related_memory_ids_stay_within_sub(tmp_path):
    """Recursive graph traversal must not follow another sub's same-ID edges."""
    from mnemo_mcp.graph import (
        create_relations,
        find_related_memory_ids,
        link_memory_entities,
        upsert_entities,
    )

    conn = sqlite3.connect(tmp_path / "d1.sqlite", isolation_level=None)
    _apply_migrations(conn)
    sub_a = _make_backend(conn, FakeVectorizeWorker(), "sub-a")
    sub_b = _make_backend(conn, FakeVectorizeWorker(), "sub-b")

    for db, source_id, related_id in (
        (sub_a, "a-source", "a-related"),
        (sub_b, "b-source", "b-related"),
    ):
        assert (
            db.import_jsonl(json.dumps(_memory_row(source_id, source_id)))["imported"]
            == 1
        )
        assert (
            db.import_jsonl(json.dumps(_memory_row(related_id, related_id)))["imported"]
            == 1
        )

    entity_ids = upsert_entities(
        sub_a._conn,
        [
            {"name": "Alice", "type": "person"},
            {"name": "Mnemo", "type": "tool"},
        ],
    )
    for entity_id, name, entity_type in zip(
        entity_ids,
        ("Alice", "Mnemo"),
        ("person", "tool"),
        strict=True,
    ):
        sub_b._conn.execute(
            "INSERT INTO memory_entities "
            "(id, name, entity_type, created_at, updated_at) "
            "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            [entity_id, name, entity_type],
        )

    relations = [{"source": "Alice", "target": "Mnemo", "type": "uses"}]
    entity_name_to_id = {"Alice": entity_ids[0], "Mnemo": entity_ids[1]}
    create_relations(sub_a._conn, relations, entity_name_to_id)
    create_relations(sub_b._conn, relations, entity_name_to_id)
    link_memory_entities(sub_a._conn, "a-source", [entity_ids[0]])
    link_memory_entities(sub_a._conn, "a-related", [entity_ids[1]])
    link_memory_entities(sub_b._conn, "b-source", [entity_ids[0]])
    link_memory_entities(sub_b._conn, "b-related", [entity_ids[1]])

    assert find_related_memory_ids(sub_a._conn, "a-source") == ["a-related"]
    assert find_related_memory_ids(sub_b._conn, "b-source") == ["b-related"]
    conn.close()


def test_server_binds_request_sub_to_a_fresh_backend(monkeypatch, tmp_path):
    """The HTTP request context, not Worker comments, chooses the D1 scope."""
    conn = sqlite3.connect(tmp_path / "d1.sqlite", isolation_level=None)
    _apply_migrations(conn)
    base = _make_backend(conn, FakeVectorizeWorker(), "default")
    ctx = SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context={
                "db": base,
                "embedding_model": None,
                "embedding_dims": DIMS,
            }
        )
    )
    monkeypatch.setenv("PUBLIC_URL", "https://mnemo.example")

    set_current_sub("sub-a")
    try:
        scoped, _, _ = _get_ctx(cast(Context, ctx))
        assert scoped is not base
        assert scoped.sub == "sub-a"
    finally:
        set_current_sub(None)

    with pytest.raises(RuntimeError, match="JWT sub"):
        _get_ctx(cast(Context, ctx))


def test_temporal_graph_updates_use_the_d1_query_only_route(tmp_path):
    """Bitemporal edge backfills stay on the Worker's supported /query route."""
    from mnemo_mcp.temporal.store import store_kg_with_memory_id

    conn = sqlite3.connect(tmp_path / "temporal.sqlite", isolation_level=None)
    _apply_migrations(conn)
    worker = FakeD1Worker(conn)
    from mcp_core.storage.d1 import D1Backend
    from mcp_core.storage.vectorize import VectorizeBackend

    db = MemoryDBCfBackend(
        D1Backend(base_url="http://d1.internal", http=worker),
        vectors=VectorizeBackend(
            base_url="http://vectorize.internal",
            idx="mnemo-test",
            http=FakeVectorizeWorker(),
        ),
        embedding_dims=DIMS,
        sub="sub-a",
    )

    result = store_kg_with_memory_id(
        db._conn,
        "memory-temporal",
        {
            "entities": [
                {"name": "Alice", "type": "person"},
                {"name": "Mnemo", "type": "tool"},
            ],
            "relations": [{"source": "Alice", "target": "Mnemo", "type": "uses"}],
        },
    )

    assert result == {"entities": 2, "edges": 1, "links": 2}
    row = conn.execute("SELECT sub, memory_id, valid_from FROM memory_edges").fetchone()
    assert row is not None
    assert row[0:2] == ("sub-a", "memory-temporal")
    assert row[2]
    assert worker.requests
    assert all(
        method == "POST" and path == "/query" for method, path, _ in worker.requests
    )
