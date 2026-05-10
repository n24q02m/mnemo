"""Tests for ``mnemo_mcp.temporal.resolve`` -- entity resolution dedup."""

from __future__ import annotations

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.temporal.resolve import (
    _resolve_threshold,
    find_similar_entity,
    insert_entity_with_embedding,
    resolve_entity,
)


class TestResolveThreshold:
    def test_default_is_0_85(self, monkeypatch):
        monkeypatch.delenv("TEMPORAL_ENTITY_RESOLUTION_THRESHOLD", raising=False)
        assert _resolve_threshold() == 0.85

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("TEMPORAL_ENTITY_RESOLUTION_THRESHOLD", "0.95")
        assert _resolve_threshold() == 0.95

    def test_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("TEMPORAL_ENTITY_RESOLUTION_THRESHOLD", "not-a-number")
        assert _resolve_threshold() == 0.85

    def test_clamped_to_0_1_range(self, monkeypatch):
        monkeypatch.setenv("TEMPORAL_ENTITY_RESOLUTION_THRESHOLD", "1.5")
        assert _resolve_threshold() == 1.0
        monkeypatch.setenv("TEMPORAL_ENTITY_RESOLUTION_THRESHOLD", "-0.2")
        assert _resolve_threshold() == 0.0


class TestExactNameMatch:
    def test_first_call_inserts_then_second_dedupes(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        eid1 = resolve_entity(conn, "FastAPI", "tool")
        eid2 = resolve_entity(conn, "FastAPI", "tool")
        assert eid1 == eid2
        # Only one row exists.
        count = conn.execute(
            "SELECT COUNT(*) FROM memory_entities WHERE name = 'FastAPI'"
        ).fetchone()[0]
        assert count == 1

    def test_different_type_creates_new_entity(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        eid1 = resolve_entity(conn, "Python", "tool")
        eid2 = resolve_entity(conn, "Python", "concept")
        assert eid1 != eid2

    def test_find_similar_returns_none_for_unknown_name(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        result = find_similar_entity(conn, "NeverSeen", "concept", embedding=None)
        assert result is None

    def test_insert_returns_id(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        new_id = insert_entity_with_embedding(conn, "NewTool", "tool", None)
        assert isinstance(new_id, str)
        assert len(new_id) > 0


class TestNoVecTableFallback:
    """When memory_entities_vec is absent (e.g. fresh tmp_db without sqlite-vec
    in migration runner), resolve falls back to exact-match dedup only."""

    def test_unknown_with_embedding_inserts(self, tmp_db: MemoryDB):
        conn = tmp_db._conn
        eid = resolve_entity(conn, "Kubernetes", "tool", embedding=[0.1] * 768)
        ent = conn.execute(
            "SELECT name, entity_type FROM memory_entities WHERE id = ?", (eid,)
        ).fetchone()
        assert ent is not None
        assert ent["name"] == "Kubernetes"
        assert ent["entity_type"] == "tool"
