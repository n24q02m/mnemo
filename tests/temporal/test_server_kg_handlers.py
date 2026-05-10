"""Tests for Phase 3 KG handlers in server.py: entity_search / entity_graph /
history dispatch + memory() routing."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.graph import (
    create_relations,
    link_memory_entities,
    upsert_entities,
)
from mnemo_mcp.server import (
    _handle_entity_graph,
    _handle_entity_search,
    _handle_history,
    memory,
)


def _seed_kg(db, content, entities, relations=None):
    mid = db.add(content)
    eids = upsert_entities(db._conn, entities)
    name_to_id = {ent["name"]: eid for ent, eid in zip(entities, eids, strict=False)}
    if relations:
        create_relations(db._conn, relations, name_to_id)
    link_memory_entities(db._conn, mid, eids)
    db._conn.commit()
    return mid, name_to_id


def _make_ctx(db: MemoryDB):
    """Build a minimal MagicMock Context whose lifespan_context yields ``db``."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "db": db,
        "embedding_model": None,
        "embedding_dims": 768,
    }
    return ctx


class TestEntitySearchHandler:
    async def test_missing_name_returns_error(self, tmp_db: MemoryDB):
        ctx = _make_ctx(tmp_db)
        result = await _handle_entity_search(ctx, name=None, entity_type=None)
        data = json.loads(result)
        assert "error" in data
        assert "name" in data["error"].lower()

    async def test_returns_results(self, tmp_db: MemoryDB):
        _seed_kg(tmp_db, "FastAPI is fast", [{"name": "FastAPI", "type": "tool"}])
        ctx = _make_ctx(tmp_db)
        result = await _handle_entity_search(ctx, name="FastAPI", entity_type=None)
        data = json.loads(result)
        assert data["count"] == 1
        assert data["matched_name"] == "FastAPI"


class TestEntityGraphHandler:
    async def test_missing_anchor_returns_error(self, tmp_db: MemoryDB):
        ctx = _make_ctx(tmp_db)
        result = await _handle_entity_graph(ctx, entity_id=None, name=None)
        data = json.loads(result)
        assert "error" in data

    async def test_returns_subgraph_for_known_anchor(self, tmp_db: MemoryDB):
        _seed_kg(
            tmp_db,
            "Alice on Project X",
            [
                {"name": "Alice", "type": "person"},
                {"name": "Project X", "type": "project"},
            ],
            relations=[
                {"source": "Alice", "target": "Project X", "type": "works_on"},
            ],
        )
        ctx = _make_ctx(tmp_db)
        result = await _handle_entity_graph(ctx, entity_id=None, name="Alice")
        data = json.loads(result)
        assert data["nodes"]
        assert data["edges"]


class TestHistoryHandler:
    async def test_missing_entity_id_returns_error(self, tmp_db: MemoryDB):
        ctx = _make_ctx(tmp_db)
        result = await _handle_history(ctx, entity_id=None)
        data = json.loads(result)
        assert "error" in data

    async def test_returns_timeline(self, tmp_db: MemoryDB):
        _, ents = _seed_kg(tmp_db, "First", [{"name": "Z", "type": "concept"}])
        _seed_kg(tmp_db, "Second", [{"name": "Z", "type": "concept"}])
        eid = ents["Z"]
        ctx = _make_ctx(tmp_db)
        result = await _handle_history(ctx, entity_id=eid)
        data = json.loads(result)
        assert data["entity_id"] == eid
        assert data["count"] == 2


class TestMemoryDispatchKGActions:
    async def test_dispatch_entity_search(self, tmp_db: MemoryDB):
        _seed_kg(tmp_db, "About Python", [{"name": "Python", "type": "tool"}])
        ctx = _make_ctx(tmp_db)
        result = await memory(action="entity_search", name="Python", ctx=ctx)
        data = json.loads(result)
        assert data["count"] == 1

    async def test_dispatch_entity_graph(self, tmp_db: MemoryDB):
        _seed_kg(tmp_db, "About Python", [{"name": "Python", "type": "tool"}])
        ctx = _make_ctx(tmp_db)
        result = await memory(action="entity_graph", name="Python", ctx=ctx)
        data = json.loads(result)
        assert "nodes" in data
        assert "edges" in data

    async def test_dispatch_history(self, tmp_db: MemoryDB):
        _, ents = _seed_kg(tmp_db, "h1", [{"name": "EntH", "type": "concept"}])
        ctx = _make_ctx(tmp_db)
        result = await memory(action="history", entity_id=ents["EntH"], ctx=ctx)
        data = json.loads(result)
        assert "timeline" in data

    async def test_unknown_action_lists_kg_actions(self, tmp_db: MemoryDB):
        ctx = _make_ctx(tmp_db)
        result = await memory(action="bogus_action_xyz", ctx=ctx)
        data = json.loads(result)
        assert "valid_actions" in data
        assert "entity_search" in data["valid_actions"]
        assert "entity_graph" in data["valid_actions"]
        assert "history" in data["valid_actions"]
