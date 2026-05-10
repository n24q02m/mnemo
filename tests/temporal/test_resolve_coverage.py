"""Coverage tests for ``mnemo_mcp.temporal.resolve`` -- vec KNN code paths."""

from __future__ import annotations

import sqlite_vec

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.temporal.resolve import (
    find_similar_entity,
    insert_entity_with_embedding,
    resolve_entity,
)


def _enable_vec(db: MemoryDB) -> None:
    """Load sqlite-vec extension on the live DB connection so the
    memory_entities_vec virtual table can be created."""
    db._conn.enable_load_extension(True)
    sqlite_vec.load(db._conn)
    db._conn.enable_load_extension(False)
    db._conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS memory_entities_vec "
        "USING vec0(embedding float[768])"
    )
    db._conn.commit()


class TestVecKnnPath:
    def test_insert_with_vec_table(self, tmp_db: MemoryDB):
        _enable_vec(tmp_db)
        eid = insert_entity_with_embedding(
            tmp_db._conn, "VecEntity", "concept", [0.1] * 768
        )
        assert eid
        # Verify embedding row exists.
        count = tmp_db._conn.execute(
            "SELECT COUNT(*) FROM memory_entities_vec"
        ).fetchone()[0]
        assert count >= 1

    def test_resolve_finds_via_vec_when_exact_misses(self, tmp_db: MemoryDB):
        _enable_vec(tmp_db)
        # Seed: name "FastAPI" with embedding v1.
        v1 = [0.5] * 768
        eid1 = insert_entity_with_embedding(tmp_db._conn, "FastAPI", "tool", v1)
        # Resolve different name "Fast API" with very similar embedding.
        # Since we use squared L2 distance ≈ 0 for identical normalised
        # vectors, similarity = 1 - 0/2 = 1.0 ≥ threshold.
        eid2 = resolve_entity(
            tmp_db._conn, "Fast API", "tool", embedding=v1, threshold=0.5
        )
        # Stage 1 misses (different name); stage 2 hits via vec.
        assert eid2 == eid1

    def test_resolve_creates_new_when_below_threshold(self, tmp_db: MemoryDB):
        _enable_vec(tmp_db)
        v1 = [1.0, 0.0] + [0.0] * 766
        v2 = [0.0, 1.0] + [0.0] * 766  # orthogonal
        insert_entity_with_embedding(tmp_db._conn, "EntA", "concept", v1)
        # Threshold 0.99 → new orthogonal embedding can't pass.
        eid_new = resolve_entity(
            tmp_db._conn, "EntB", "concept", embedding=v2, threshold=0.99
        )
        # Different entity created.
        ent = tmp_db._conn.execute(
            "SELECT name FROM memory_entities WHERE id = ?", (eid_new,)
        ).fetchone()
        assert ent["name"] == "EntB"

    def test_find_similar_returns_none_when_threshold_high(self, tmp_db: MemoryDB):
        _enable_vec(tmp_db)
        v1 = [1.0, 0.0] + [0.0] * 766
        insert_entity_with_embedding(tmp_db._conn, "X", "concept", v1)
        # Query with orthogonal embedding + tight threshold.
        v2 = [0.0, 1.0] + [0.0] * 766
        result = find_similar_entity(tmp_db._conn, "Y", "concept", v2, threshold=0.99)
        assert result is None
