"""Coverage tests for the individual @mcp.tool wrappers in server.py.

Each wrapper is a thin delegator to the corresponding `_handle_*`
function. These tests invoke them via the FastMCP `.fn` attribute so
the bodies (return await _handle_X(...)) are covered.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.server import (
    add_memory,
    archived_memories,
    consolidate_memories,
    delete_memory,
    export_memories,
    import_memories,
    list_memories,
    memory_stats,
    restore_memory,
    search_memory,
    update_memory,
)


def _make_ctx(db: MemoryDB):
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "db": db,
        "embedding_model": None,
        "embedding_dims": 768,
    }
    return ctx


def _call(tool, **kwargs):
    """Invoke FastMCP tool's underlying function directly."""
    fn = getattr(tool, "fn", tool)
    return fn(**kwargs)


class TestToolWrappers:
    async def test_add_memory_wrapper(self, tmp_db: MemoryDB):
        ctx = _make_ctx(tmp_db)
        result = await _call(add_memory, content="hello", ctx=ctx)
        data = json.loads(result)
        assert data["status"] == "saved"

    async def test_search_memory_wrapper(self, tmp_db: MemoryDB):
        tmp_db.add("Find me")
        ctx = _make_ctx(tmp_db)
        result = await _call(search_memory, query="Find", ctx=ctx)
        data = json.loads(result)
        assert "results" in data

    async def test_list_memories_wrapper(self, tmp_db: MemoryDB):
        tmp_db.add("listed")
        ctx = _make_ctx(tmp_db)
        result = await _call(list_memories, ctx=ctx)
        data = json.loads(result)
        assert "results" in data

    async def test_update_memory_wrapper(self, tmp_db: MemoryDB):
        mid = tmp_db.add("original")
        ctx = _make_ctx(tmp_db)
        result = await _call(update_memory, memory_id=mid, content="updated", ctx=ctx)
        data = json.loads(result)
        assert data["status"] == "updated"

    async def test_delete_memory_wrapper(self, tmp_db: MemoryDB):
        mid = tmp_db.add("to delete")
        ctx = _make_ctx(tmp_db)
        result = await _call(delete_memory, memory_id=mid, ctx=ctx)
        data = json.loads(result)
        assert data["status"] == "deleted"

    async def test_export_memories_wrapper(self, tmp_db: MemoryDB):
        tmp_db.add("export me")
        ctx = _make_ctx(tmp_db)
        result = await _call(export_memories, ctx=ctx)
        data = json.loads(result)
        assert data["count"] == 1

    async def test_import_memories_wrapper(self, tmp_db: MemoryDB):
        ctx = _make_ctx(tmp_db)
        payload = json.dumps(
            {
                "id": "imp-1",
                "content": "imported",
                "category": "general",
                "tags": [],
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
                "last_accessed": "2026-01-01",
            }
        )
        result = await _call(import_memories, data=payload, mode="merge", ctx=ctx)
        data = json.loads(result)
        assert data["imported"] == 1

    async def test_memory_stats_wrapper(self, tmp_db: MemoryDB):
        ctx = _make_ctx(tmp_db)
        result = await _call(memory_stats, ctx=ctx)
        data = json.loads(result)
        assert "total_memories" in data

    async def test_restore_memory_wrapper(self, tmp_db: MemoryDB):
        mid = tmp_db.add("to archive then restore")
        # Soft-archive directly.
        tmp_db._conn.execute(
            "UPDATE memories SET archived_at = '2026-01-01' WHERE id = ?", (mid,)
        )
        tmp_db._conn.commit()
        ctx = _make_ctx(tmp_db)
        result = await _call(restore_memory, memory_id=mid, ctx=ctx)
        data = json.loads(result)
        assert data["status"] == "restored"

    async def test_archived_memories_wrapper(self, tmp_db: MemoryDB):
        ctx = _make_ctx(tmp_db)
        result = await _call(archived_memories, ctx=ctx)
        data = json.loads(result)
        assert "results" in data

    async def test_consolidate_memories_wrapper_no_llm(
        self, tmp_db: MemoryDB, monkeypatch
    ):
        # Without LLM provider, consolidate should return error -- but only
        # when category is provided. Without category it hits earlier guard.
        tmp_db.add("about A", category="testcat")
        tmp_db.add("about A2", category="testcat")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        from mnemo_mcp.config import settings

        monkeypatch.setattr(settings, "api_keys", None)
        ctx = _make_ctx(tmp_db)
        result = await _call(consolidate_memories, category="testcat", ctx=ctx)
        data = json.loads(result)
        assert "error" in data
