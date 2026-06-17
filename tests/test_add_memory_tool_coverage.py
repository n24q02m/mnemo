"""Coverage tests for add_memory tool and _handle_add/history in server.py."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.server import _handle_add, _handle_history, add_memory


@pytest.fixture
def mock_ctx(tmp_path):
    """Mock MCP Context with DB."""
    db = MemoryDB(tmp_path / "test_add.db", embedding_dims=0)
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "db": db,
        "embedding_model": None,
        "embedding_dims": 0,
    }
    yield ctx, db
    db.close()


class TestAddMemoryCoverage:
    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    async def test_add_memory_wrapper(self, _mock_thread, mock_ctx):
        """Verify add_memory tool wrapper calls _handle_add."""
        ctx, db = mock_ctx
        result = await add_memory(content="wrapper test", ctx=ctx)
        data = json.loads(result)
        assert data["status"] == "saved"
        assert data["id"]

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    async def test_handle_add_success(self, _mock_thread, mock_ctx):
        """Verify _handle_add with full metadata."""
        ctx, db = mock_ctx
        result = await _handle_add(
            ctx, content="full metadata", category="test", tags=["a", "b"]
        )
        data = json.loads(result)
        assert data["status"] == "saved"
        assert data["category"] == "test"

        # Verify it's actually in DB
        mem = db.get(data["id"])
        assert mem["content"] == "full metadata"
        assert mem["category"] == "test"
        assert json.loads(mem["tags"]) == ["a", "b"]

    async def test_handle_add_missing_content(self, mock_ctx):
        """Verify error when content is missing (covers line 443)."""
        ctx, db = mock_ctx
        result = await _handle_add(ctx, content="")
        data = json.loads(result)
        assert "error" in data
        assert "content is required" in data["error"]

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    async def test_handle_add_dedup_warning(self, _mock_thread, mock_ctx):
        """Verify dedup warnings (covers lines 460-462)."""
        ctx, db = mock_ctx

        # Mock check_duplicate to return a duplicate warning
        with patch.object(db, "check_duplicate") as mock_check:
            mock_check.return_value = {"duplicate": True, "id": "old-id"}
            result = await _handle_add(ctx, content="duplicate content")
            data = json.loads(result)
            assert data["dedup_warning"] == {"duplicate": True, "id": "old-id"}

        # Mock check_duplicate to return a similar warning
        with patch.object(db, "check_duplicate") as mock_check:
            mock_check.return_value = {"similar": True, "id": "sim-id"}
            result = await _handle_add(ctx, content="similar content")
            data = json.loads(result)
            assert data["dedup_warning"] == {"similar": True, "id": "sim-id"}

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    async def test_handle_add_dedup_exception(self, _mock_thread, mock_ctx):
        """Verify dedup exception handling (covers lines 461-462)."""
        ctx, db = mock_ctx
        with patch.object(db, "check_duplicate", side_effect=Exception("Dedup boom")):
            with patch("mnemo_mcp.server.logger") as mock_logger:
                result = await _handle_add(ctx, content="dedup exception test")
                data = json.loads(result)
                assert data["status"] == "saved"
                mock_logger.warning.assert_called()

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    async def test_handle_add_value_error(self, _mock_thread, mock_ctx):
        """Verify ValueError handling (covers lines 496-501)."""
        ctx, db = mock_ctx
        with patch.object(db, "add", side_effect=ValueError("Test value error")):
            result = await _handle_add(ctx, content="test content")
            data = json.loads(result)
            assert data["error"] == "Test value error"

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    async def test_handle_add_unexpected_exception(self, _mock_thread, mock_ctx):
        """Verify unexpected Exception handling (covers lines 502-508)."""
        ctx, db = mock_ctx
        with patch.object(db, "add", side_effect=Exception("Unexpected boom")):
            result = await _handle_add(ctx, content="test content")
            data = json.loads(result)
            assert "Internal error" in data["error"]

    @patch("mnemo_mcp.server._enrich_memory", new_callable=AsyncMock)
    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    async def test_handle_add_triggers_enrich(
        self, _mock_thread, mock_enrich, mock_ctx
    ):
        """Verify background enrichment is triggered."""
        ctx, db = mock_ctx
        await _handle_add(ctx, content="trigger enrich")
        mock_enrich.assert_called_once()

    async def test_handle_history_missing_entity_id(self, mock_ctx):
        """Verify error when entity_id is missing in _handle_history (covers line 1117)."""
        ctx, db = mock_ctx
        result = await _handle_history(ctx, entity_id=None)
        data = json.loads(result)
        assert "error" in data
        assert "entity_id required" in data["error"]

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    async def test_handle_history_success(self, _mock_thread, mock_ctx):
        """Verify _handle_history success case (covers lines 1124-1127)."""
        ctx, db = mock_ctx
        # We need to mock history_for_entity because it's imported inside the function
        with patch(
            "mnemo_mcp.temporal.queries.history_for_entity",
            return_value=[{"id": "mem1"}],
        ):
            result = await _handle_history(ctx, entity_id="ent1")
            data = json.loads(result)
            assert data["entity_id"] == "ent1"
            assert data["count"] == 1
