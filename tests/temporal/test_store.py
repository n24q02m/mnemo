"""Tests for ``mnemo_mcp.temporal.store`` -- Phase 3 KG persistence helper.

Verifies:
- Wraps Phase 1 graph helpers + extends with bitemporal bookkeeping.
- Backfills ``memory_edges.memory_id`` to the capture id.
- Sets ``memory_edges.valid_from`` to capture time.
- Returns count dict for audit / monitoring.
"""

from __future__ import annotations

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.temporal.store import store_kg_with_memory_id


class TestStoreKgWithMemoryId:
    def test_returns_zero_counts_when_no_entities(self, tmp_db: MemoryDB):
        result = store_kg_with_memory_id(
            tmp_db._conn, "memory-x", {"entities": [], "relations": []}
        )
        assert result == {"entities": 0, "edges": 0, "links": 0}

    def test_returns_zero_counts_for_none(self, tmp_db: MemoryDB):
        result = store_kg_with_memory_id(tmp_db._conn, "memory-x", None)
        assert result == {"entities": 0, "edges": 0, "links": 0}

    def test_persists_entities_and_links(self, tmp_db: MemoryDB):
        mid = tmp_db.add("Project X uses Postgres")
        extracted = {
            "entities": [
                {"name": "Project X", "type": "project"},
                {"name": "Postgres", "type": "tool"},
            ],
            "relations": [],
        }
        result = store_kg_with_memory_id(tmp_db._conn, mid, extracted)
        assert result["entities"] == 2
        assert result["links"] == 2
        # Verify entities + links exist
        ent_count = tmp_db._conn.execute(
            "SELECT COUNT(*) FROM memory_entities"
        ).fetchone()[0]
        assert ent_count == 2
        link_count = tmp_db._conn.execute(
            "SELECT COUNT(*) FROM memory_entity_links WHERE memory_id = ?", (mid,)
        ).fetchone()[0]
        assert link_count == 2

    def test_persists_edges_with_memory_id_and_valid_from(self, tmp_db: MemoryDB):
        mid = tmp_db.add("Alice works on Project X")
        extracted = {
            "entities": [
                {"name": "Alice", "type": "person"},
                {"name": "Project X", "type": "project"},
            ],
            "relations": [
                {"source": "Alice", "target": "Project X", "type": "works_on"},
            ],
        }
        result = store_kg_with_memory_id(tmp_db._conn, mid, extracted)
        assert result["edges"] == 1
        # Verify edge stored with memory_id + valid_from + valid_to NULL
        edge = tmp_db._conn.execute(
            "SELECT memory_id, valid_from, valid_to, relation_type FROM memory_edges"
        ).fetchone()
        assert edge is not None
        assert edge["memory_id"] == mid
        assert edge["valid_from"] is not None
        assert edge["valid_to"] is None
        assert edge["relation_type"] == "works_on"

    def test_skips_edges_with_missing_entities(self, tmp_db: MemoryDB):
        mid = tmp_db.add("only Alice mentioned")
        extracted = {
            "entities": [{"name": "Alice", "type": "person"}],
            "relations": [
                # Bob is not in entities → skipped
                {"source": "Alice", "target": "Bob", "type": "related_to"},
            ],
        }
        result = store_kg_with_memory_id(tmp_db._conn, mid, extracted)
        assert result["entities"] == 1
        assert result["edges"] == 0

    def test_idempotent_replay(self, tmp_db: MemoryDB):
        mid = tmp_db.add("Same content twice")
        extracted = {
            "entities": [
                {"name": "X", "type": "concept"},
                {"name": "Y", "type": "concept"},
            ],
            "relations": [{"source": "X", "target": "Y", "type": "related_to"}],
        }
        store_kg_with_memory_id(tmp_db._conn, mid, extracted)
        # Replay: entities upsert, relations INSERT OR IGNORE → same count.
        store_kg_with_memory_id(tmp_db._conn, mid, extracted)
        ent_count = tmp_db._conn.execute(
            "SELECT COUNT(*) FROM memory_entities"
        ).fetchone()[0]
        edge_count = tmp_db._conn.execute(
            "SELECT COUNT(*) FROM memory_edges"
        ).fetchone()[0]
        assert ent_count == 2
        assert edge_count == 1
