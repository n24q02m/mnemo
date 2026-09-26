"""Tests for the `memory` composite tool's deprecation warning.

W6.4: `memory` stays fully functional (no behavior change) but now surfaces
a deprecation notice pointing callers at the granular tools -- in the tool
description (static, seen at `tools/list` time) and in a `_deprecation`
field added to every response (seen at call time, action-aware).
"""

from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.server import add_memory, mcp, memory, search_memory

_DEPRECATION_TAG = (
    "[DEPRECATED — use the granular tools (add_memory, search_memory, ...) "
    "instead; this composite tool will be removed in a future release]"
)


@pytest.fixture
def ctx_with_db(tmp_path: Path) -> Generator[tuple[MagicMock, MemoryDB]]:
    """Mock MCP Context with fresh DB (mirrors tests/test_server.py)."""
    db = MemoryDB(tmp_path / "deprecation_test.db", embedding_dims=0)
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "db": db,
        "embedding_model": None,
        "embedding_dims": 0,
    }
    yield ctx, db
    db.close()


class TestMemoryToolDescriptionDeprecated:
    """(a) The `memory` tool description leads with a `[DEPRECATED` tag."""

    async def test_description_starts_with_deprecated_tag(self):
        tools = await mcp.list_tools()
        memory_tool = next(t for t in tools if t.name == "memory")
        assert memory_tool.description is not None
        assert memory_tool.description.startswith(_DEPRECATION_TAG)

    async def test_description_still_documents_actions(self):
        # Existing action-guide content must survive -- only prepended to,
        # not replaced.
        tools = await mcp.list_tools()
        memory_tool = next(t for t in tools if t.name == "memory")
        assert memory_tool.description is not None
        assert "ACTION GUIDE" in memory_tool.description
        assert "action='add'" in memory_tool.description


class TestMemoryResponseDeprecationField:
    """(b) Representative actions (add/search/as_of) get `_deprecation`."""

    async def test_add_response_suggests_add_memory(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = await memory(action="add", content="test memory", ctx=ctx)
        assert "_deprecation" in result
        assert result["_deprecation"]["use_instead"] == "add_memory"
        assert "add_memory" in result["_deprecation"]["message"]

    async def test_search_response_suggests_search_memory(self, ctx_with_db):
        ctx, db = ctx_with_db
        db.add("Python is great for AI and machine learning")
        result = await memory(action="search", query="Python AI", ctx=ctx)
        assert result["_deprecation"]["use_instead"] == "search_memory"
        assert "search_memory" in result["_deprecation"]["message"]

    async def test_as_of_response_has_no_granular_equivalent(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = await memory(action="as_of", as_of="2026-01-01T00:00:00", ctx=ctx)
        assert "_deprecation" in result
        assert result["_deprecation"]["use_instead"] is None
        assert "as_of" in result["_deprecation"]["message"]

    async def test_as_of_guard_error_path_also_has_deprecation(self, ctx_with_db):
        """The early-return guard (as_of + non-as_of action) is also a
        `memory()` response and must carry the same field."""
        ctx, _ = ctx_with_db
        result = await memory(
            action="search", query="x", as_of="2026-01-01T00:00:00", ctx=ctx
        )
        assert "error" in result
        assert "_deprecation" in result
        assert result["_deprecation"]["use_instead"] == "search_memory"

    async def test_unknown_action_response_has_deprecation(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = await memory(action="invalid", ctx=ctx)
        assert "error" in result
        assert "_deprecation" in result
        assert result["_deprecation"]["use_instead"] is None

    async def test_none_action_response_has_deprecation(self):
        result = await memory(action=None)
        assert "error" in result
        assert "_deprecation" in result


class TestMemoryDeprecationBehaviorUnchanged:
    """(c) Regression: only a new field is added; nothing else changes."""

    async def test_add_existing_fields_unchanged(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = await memory(action="add", content="test memory", ctx=ctx)
        assert result["status"] == "saved"
        assert result["id"]
        assert result["semantic"] is False
        assert set(result) == {"id", "status", "category", "semantic", "_deprecation"}

    async def test_add_no_content_error_path_unchanged(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = await memory(action="add", ctx=ctx)
        assert "error" in result
        assert "suggestion" in result
        assert "_deprecation" in result

    async def test_unknown_action_valid_actions_list_unchanged(self, ctx_with_db):
        ctx, _ = ctx_with_db
        result = await memory(action="invalid", ctx=ctx)
        assert "valid_actions" in result
        assert "add" in result["valid_actions"]
        assert "Available actions are:" in result["suggestion"]

    async def test_granular_add_memory_tool_unaffected(self, ctx_with_db):
        """The specialized tools share `_handle_*` with `memory()` but must
        NOT pick up the deprecation field -- only the composite dispatcher
        is deprecated, not its handlers."""
        ctx, _ = ctx_with_db
        result = await add_memory(content="direct call", ctx=ctx)
        assert "_deprecation" not in result

    async def test_granular_search_memory_tool_unaffected(self, ctx_with_db):
        ctx, db = ctx_with_db
        db.add("direct search target")
        result = await search_memory(query="direct search", ctx=ctx)
        assert "_deprecation" not in result
