"""Additional tests for mnemo_mcp.server — covering uncovered lines.

Targets: _embed backend is None, _format_memory tags parse error,
config sync action, config set sync_interval, config set generic,
stats_resource, recent_resource, main function, _init_embedding_backend
candidate exception.
"""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.server import (
    _embed,
    _format_memory,
    config,
    main,
    memory,
    recent_resource,
    stats_resource,
)


@pytest.fixture
def ctx_with_db(tmp_path: Path) -> Generator[tuple[MagicMock, MemoryDB]]:
    """Mock MCP Context with fresh DB."""
    db = MemoryDB(tmp_path / "server_test.db", embedding_dims=0)
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "db": db,
        "embedding_model": None,
        "embedding_dims": 0,
    }
    yield ctx, db
    db.close()


# ---------------------------------------------------------------------------
# _embed edge cases
# ---------------------------------------------------------------------------


class TestEmbed:
    async def test_no_model_returns_none(self):
        """Returns None when model is None (embedding not ready)."""
        result = await _embed("test text", None, 768)
        assert result is None

    async def test_backend_is_none_returns_none(self):
        """Returns None when backend singleton is None despite model being set."""
        with patch("mnemo_mcp.embedder.get_backend", return_value=None):
            result = await _embed("test text", "some-model", 768)
            assert result is None

    async def test_embed_exception_returns_none(self):
        """Returns None when embedding raises an exception."""
        mock_backend = MagicMock()
        mock_backend.embed_single = AsyncMock(side_effect=Exception("API error"))

        with patch("mnemo_mcp.embedder.get_backend", return_value=mock_backend):
            result = await _embed("test text", "some-model", 768)
            assert result is None

    async def test_embed_with_qwen3_query(self):
        """Uses query_embed for Qwen3 backend with is_query=True."""
        from mnemo_mcp.embedder import Qwen3EmbedBackend

        mock_backend = MagicMock(spec=Qwen3EmbedBackend)
        mock_backend.embed_single_query = AsyncMock(return_value=[0.1, 0.2])

        with patch("mnemo_mcp.embedder.get_backend", return_value=mock_backend):
            result = await _embed("search query", "__local__", 768, is_query=True)
            assert result == [0.1, 0.2]
            mock_backend.embed_single_query.assert_called_once_with("search query", 768)

    async def test_embed_with_non_qwen3_query(self):
        """Uses regular embed_single for non-Qwen3 backends even with is_query."""
        mock_backend = MagicMock()
        mock_backend.embed_single = AsyncMock(return_value=[0.3, 0.4])

        with patch("mnemo_mcp.embedder.get_backend", return_value=mock_backend):
            result = await _embed("search query", "some-model", 768, is_query=True)
            assert result == [0.3, 0.4]
            mock_backend.embed_single.assert_called_once_with("search query", 768)


# ---------------------------------------------------------------------------
# _format_memory edge cases
# ---------------------------------------------------------------------------


class TestFormatMemory:
    def test_tags_parse_error(self):
        """Invalid JSON in tags is left as-is."""
        mem = {"tags": "not-valid-json", "content": "test"}
        result = _format_memory(mem)
        assert result["tags"] == "not-valid-json"

    def test_tags_none_type_error(self):
        """None tags with TypeError don't crash."""
        mem = {"tags": None, "content": "test"}
        result = _format_memory(mem)
        assert result["tags"] is None

    def test_score_rounding(self):
        """Score is rounded to 3 decimal places."""
        mem = {"score": 0.123456789, "content": "test"}
        result = _format_memory(mem)
        assert result["score"] == 0.123

    def test_no_score_no_crash(self):
        """Memories without score are handled."""
        mem = {"content": "test", "tags": '["a"]'}
        result = _format_memory(mem)
        assert "score" not in result


# ---------------------------------------------------------------------------
# config tool — sync and set actions
# ---------------------------------------------------------------------------


class TestConfigSync:
    async def test_config_sync_action(self, ctx_with_db):
        """Config sync action triggers sync_full."""
        ctx, db = ctx_with_db
        mock_result = {"status": "ok", "pull": None, "push": None}

        with patch(
            "mnemo_mcp.sync.sync_full", new_callable=AsyncMock, return_value=mock_result
        ):
            result = json.loads(await config(action="sync", ctx=ctx))
            assert result["status"] == "ok"

    async def test_config_set_sync_interval(self, ctx_with_db):
        """Config set sync_interval updates the setting."""
        ctx, _ = ctx_with_db
        result = json.loads(
            await config(action="set", key="sync_interval", value="120", ctx=ctx)
        )
        assert result["status"] == "updated"
        assert result["key"] == "sync_interval"

    async def test_config_set_log_level(self, ctx_with_db):
        """Config set log_level updates logger configuration."""
        ctx, _ = ctx_with_db
        result = json.loads(
            await config(action="set", key="log_level", value="DEBUG", ctx=ctx)
        )
        assert result["status"] == "updated"
        assert result["key"] == "log_level"

    async def test_config_set_invalid_log_level(self, ctx_with_db):
        """Config set with invalid log level returns error."""
        ctx, _ = ctx_with_db
        result = json.loads(
            await config(action="set", key="log_level", value="INVALID", ctx=ctx)
        )
        assert "error" in result
        assert "valid_levels" in result


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class TestResources:
    async def test_stats_resource(self, ctx_with_db):
        """stats_resource returns database stats."""
        ctx, db = ctx_with_db
        db.add("test memory")
        result = json.loads(await stats_resource(ctx=ctx))
        assert result["total_memories"] == 1
        assert "embedding_model" in result
        assert "sync_enabled" in result

    async def test_recent_resource(self, ctx_with_db):
        """recent_resource returns recent memories."""
        ctx, db = ctx_with_db
        db.add("memory 1")
        db.add("memory 2")
        result = json.loads(await recent_resource(ctx=ctx))
        assert len(result) == 2


# ---------------------------------------------------------------------------
# main function
# ---------------------------------------------------------------------------


class TestMainFunction:
    def test_main_calls_mcp_run(self):
        """main() configures logger and calls mcp.run()."""
        with (
            patch("mnemo_mcp.server.logger") as mock_logger,
            patch("mnemo_mcp.server.mcp") as mock_mcp,
            patch("mnemo_mcp.server.settings") as mock_settings,
        ):
            mock_settings.log_level = "INFO"
            main()
            mock_logger.remove.assert_called_once()
            mock_logger.add.assert_called_once()
            mock_mcp.run.assert_called_once()


# ---------------------------------------------------------------------------
# _init_embedding_backend — candidate exception path
# ---------------------------------------------------------------------------


class TestInitEmbeddingBackendCandidate:
    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_candidate_exception_continues(
        self, mock_settings, mock_init, _mock_thread
    ):
        """When a candidate raises exception, continues to next."""
        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "litellm"
        mock_settings.resolve_local_embedding_model.return_value = "local/m"
        mock_settings.get_embedding_litellm_kwargs.return_value = {}

        # All candidates raise exception
        mock_init.side_effect = Exception("API Error")

        # Local backend also fails
        ctx: dict = {"embedding_model": None, "embedding_dims": 768}
        await _init_embedding_backend("sdk", ctx)

        # Should have tried multiple candidates + local
        assert mock_init.call_count >= 2

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_local_backend_zero_dims(
        self, mock_settings, mock_init, _mock_thread
    ):
        """When local backend check_available returns 0, logs error."""
        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "local/m"
        mock_settings.get_embedding_litellm_kwargs.return_value = {}

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 0  # Not available
        mock_init.return_value = mock_backend

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}
        await _init_embedding_backend("local", ctx)

        # Model should remain None since local returned 0 dims
        assert ctx["embedding_model"] is None


# ---------------------------------------------------------------------------
# Memory tool limit clamping
# ---------------------------------------------------------------------------


class TestMemoryLimitClamping:
    async def test_limit_clamped_to_min(self, ctx_with_db):
        """Limit below 1 is clamped to 1."""
        ctx, db = ctx_with_db
        db.add("test")
        result = json.loads(await memory(action="list", limit=0, ctx=ctx))
        assert result["count"] <= 1

    async def test_limit_clamped_to_max(self, ctx_with_db):
        """Limit above 100 is clamped to 100."""
        ctx, db = ctx_with_db
        result = json.loads(await memory(action="list", limit=1000, ctx=ctx))
        # Should not crash, limit is clamped
        assert isinstance(result["results"], list)
