"""Tests for ``mnemo_mcp.temporal.queries`` -- entity_search / entity_graph /
history / as_of bitemporal lookups."""

from __future__ import annotations

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.graph import (
    create_relations,
    link_memory_entities,
    upsert_entities,
)
from mnemo_mcp.temporal.queries import (
    entity_graph,
    entity_search,
    history_for_entity,
    memories_as_of,
)


def _seed_kg(db: MemoryDB, content: str, entities, relations=None):
    """Helper: insert memory + link entities + edges."""
    mid = db.add(content)
    eids = upsert_entities(db._conn, entities)
    name_to_id = {}
    for ent, eid in zip(entities, eids, strict=False):
        name_to_id[ent["name"]] = eid
    if relations:
        create_relations(db._conn, relations, name_to_id)
    link_memory_entities(db._conn, mid, eids)
    db._conn.commit()
    return mid, name_to_id


class TestEntitySearch:
    def test_returns_empty_when_name_blank(self, tmp_db: MemoryDB):
        assert entity_search(tmp_db, name="") == []
        assert entity_search(tmp_db, name=None) == []

    def test_returns_empty_when_unknown_entity(self, tmp_db: MemoryDB):
        result = entity_search(tmp_db, name="NotFound")
        assert result == []

    def test_finds_memory_via_entity_name(self, tmp_db: MemoryDB):
        mid, _ = _seed_kg(
            tmp_db,
            "FastAPI is a Python web framework",
            [{"name": "FastAPI", "type": "tool"}],
        )
        results = entity_search(tmp_db, name="FastAPI")
        assert len(results) == 1
        assert results[0]["id"] == mid
        assert results[0]["matched_entity"] == "FastAPI"

    def test_filters_by_entity_type(self, tmp_db: MemoryDB):
        _seed_kg(tmp_db, "Python the snake", [{"name": "Python", "type": "concept"}])
        _seed_kg(tmp_db, "Python the language", [{"name": "Python", "type": "tool"}])
        # Only tool-type
        results = entity_search(tmp_db, name="Python", entity_type="tool")
        assert len(results) == 1
        assert "language" in results[0]["content"]

    def test_case_insensitive_name(self, tmp_db: MemoryDB):
        _seed_kg(tmp_db, "Kubernetes content", [{"name": "Kubernetes", "type": "tool"}])
        results = entity_search(tmp_db, name="kubernetes")
        assert len(results) == 1

    def test_fuzzy_substring_fallback(self, tmp_db: MemoryDB):
        _seed_kg(tmp_db, "About FastAPI", [{"name": "FastAPI", "type": "tool"}])
        results = entity_search(tmp_db, name="API")
        assert len(results) >= 1


class TestEntityGraph:
    def test_returns_empty_for_unknown_anchor(self, tmp_db: MemoryDB):
        result = entity_graph(tmp_db, name="Nope")
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_returns_neighbourhood(self, tmp_db: MemoryDB):
        _seed_kg(
            tmp_db,
            "Alice works on Project X using Python",
            [
                {"name": "Alice", "type": "person"},
                {"name": "Project X", "type": "project"},
                {"name": "Python", "type": "tool"},
            ],
            relations=[
                {"source": "Alice", "target": "Project X", "type": "works_on"},
                {"source": "Project X", "target": "Python", "type": "uses"},
            ],
        )
        result = entity_graph(tmp_db, name="Alice", depth=2)
        names = {n["name"] for n in result["nodes"]}
        assert "Alice" in names
        assert "Project X" in names
        # Python reachable via depth=2
        assert "Python" in names
        # Edges captured
        assert any(e["relation_type"] == "works_on" for e in result["edges"])

    def test_depth_bounded(self, tmp_db: MemoryDB):
        _seed_kg(
            tmp_db,
            "Chain test",
            [
                {"name": "A", "type": "concept"},
                {"name": "B", "type": "concept"},
                {"name": "C", "type": "concept"},
            ],
            relations=[
                {"source": "A", "target": "B", "type": "related_to"},
                {"source": "B", "target": "C", "type": "related_to"},
            ],
        )
        result = entity_graph(tmp_db, name="A", depth=1)
        names = {n["name"] for n in result["nodes"]}
        # depth=1 should reach A + B but not C
        assert "A" in names
        assert "B" in names
        assert "C" not in names


class TestHistoryForEntity:
    def test_returns_all_memories_linked(self, tmp_db: MemoryDB):
        mid1, ents1 = _seed_kg(
            tmp_db, "First mention", [{"name": "X", "type": "concept"}]
        )
        mid2, _ = _seed_kg(tmp_db, "Second mention", [{"name": "X", "type": "concept"}])
        eid = ents1["X"]
        timeline = history_for_entity(tmp_db, eid)
        ids = {m["id"] for m in timeline}
        assert mid1 in ids
        assert mid2 in ids


class TestMemoriesAsOf:
    def test_returns_currently_valid_when_no_as_of(self, tmp_db: MemoryDB):
        mid = tmp_db.add("currently valid")
        # Backfill: ensure valid_from set + valid_to NULL.
        tmp_db._conn.execute(
            "UPDATE memories SET valid_from = created_at WHERE id = ?", (mid,)
        )
        tmp_db._conn.commit()
        result = memories_as_of(tmp_db, as_of=None)
        ids = {m["id"] for m in result}
        assert mid in ids

    def test_excludes_superseded_at_default(self, tmp_db: MemoryDB):
        mid = tmp_db.add("old fact")
        # Mark superseded.
        tmp_db._conn.execute(
            "UPDATE memories SET valid_to = '2026-01-01T00:00:00' WHERE id = ?",
            (mid,),
        )
        tmp_db._conn.commit()
        result = memories_as_of(tmp_db, as_of=None)
        ids = {m["id"] for m in result}
        assert mid not in ids

    def test_as_of_returns_historical(self, tmp_db: MemoryDB):
        mid = tmp_db.add("captured at t=10")
        tmp_db._conn.execute(
            "UPDATE memories SET valid_from = '2026-01-01T00:00:00', "
            "valid_to = '2026-02-01T00:00:00' WHERE id = ?",
            (mid,),
        )
        tmp_db._conn.commit()
        # Query at t=15 — within validity window.
        result = memories_as_of(tmp_db, as_of="2026-01-15T00:00:00")
        ids = {m["id"] for m in result}
        assert mid in ids
        # Query at t=20 — after valid_to.
        result = memories_as_of(tmp_db, as_of="2026-03-01T00:00:00")
        ids = {m["id"] for m in result}
        assert mid not in ids
