"""Additional tests for mnemo_mcp.server — covering uncovered lines.

Targets: _embed backend is None, _format_memory tags parse error,
config sync action, config set sync_interval, config set generic,
stats_resource, main function, _init_embedding_backend
candidate exception.
"""

import json
import os
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.server import (
    _embed,
    _format_memory,
    _json,
    config,
    main,
    memory,
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


# ---------------------------------------------------------------------------
# main function
# ---------------------------------------------------------------------------


class TestMainFunction:
    def test_main_calls_mcp_run(self):
        """main() in stdio mode runs FastMCP stdio server directly (no bridge)."""
        from mnemo_mcp import server as server_mod

        with (
            patch("mnemo_mcp.server.logger") as mock_logger,
            patch.object(server_mod.mcp, "run") as mock_run,
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch.dict(os.environ, {"MCP_TRANSPORT": "stdio"}),
        ):
            mock_settings.log_level = "INFO"
            main()
            mock_logger.remove.assert_called_once()
            mock_logger.add.assert_called_once()
            mock_run.assert_called_once_with(transport="stdio")


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
        """When a candidate raises exception, continues to next (no local fallback)."""
        from mnemo_mcp.server import _init_embedding_backend

        embedding_chain = [
            "jina_ai/jina-embeddings-v5-text-small",
            "gemini/gemini-embedding-001",
            "text-embedding-3-large",
            "embed-multilingual-v3.0",
        ]
        mock_settings.embedding_chain.return_value = embedding_chain
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "cloud"

        # All candidates raise exception
        mock_init.side_effect = Exception("API Error")

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}
        await _init_embedding_backend("sdk", ctx)

        # Should have tried all cloud candidates only -- no local fallback
        assert mock_init.call_count == len(embedding_chain)

    @patch("mnemo_mcp.server._maybe_register_custom_embed")
    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_local_backend_zero_dims(
        self, mock_settings, mock_init, _mock_thread, _mock_register
    ):
        """When local backend check_available returns 0, logs error."""
        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.embedding_chain.return_value = []
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "local/m"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 0  # Not available
        mock_init.return_value = mock_backend

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}
        await _init_embedding_backend("local", ctx)

        # Model should remain None since local returned 0 dims
        assert ctx["embedding_model"] is None


# ---------------------------------------------------------------------------
# _init_reranker_backend -- exception paths
# ---------------------------------------------------------------------------


class TestInitRerankerBackend:
    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.reranker.init_reranker")
    @patch("mnemo_mcp.server.settings")
    async def test_local_reranker_init_fails(
        self, mock_settings, mock_init, _mock_thread
    ):
        """When local reranker init raises exception, logs error."""
        from mnemo_mcp.server import _init_reranker_backend

        mock_settings.resolve_rerank_backend.return_value = "local"
        mock_settings.resolve_local_rerank_model.return_value = "local/r"

        mock_init.side_effect = Exception("reranker init failed test error")

        with patch("mnemo_mcp.server.logger") as mock_logger:
            await _init_reranker_backend("local")
            mock_logger.error.assert_called_with(
                "Local reranker init failed: reranker init failed test error"
            )

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.reranker.init_reranker")
    @patch("mnemo_mcp.server.settings")
    async def test_local_reranker_not_available(
        self, mock_settings, mock_init, _mock_thread
    ):
        """When local reranker check_available returns False, logs error."""
        from mnemo_mcp.server import _init_reranker_backend

        mock_settings.resolve_rerank_backend.return_value = "local"
        mock_settings.resolve_local_rerank_model.return_value = "local/r"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = False
        mock_init.return_value = mock_backend

        with patch("mnemo_mcp.server.logger") as mock_logger:
            await _init_reranker_backend("local")
            mock_logger.error.assert_called_with("Local reranker not available")

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.server.settings")
    async def test_reranker_disabled(self, mock_settings, _mock_thread):
        """When reranker is disabled, logs debug message."""
        from mnemo_mcp.server import _init_reranker_backend

        mock_settings.resolve_rerank_backend.return_value = None

        with patch("mnemo_mcp.server.logger") as mock_logger:
            await _init_reranker_backend("sdk")
            mock_logger.debug.assert_called_with("Reranking disabled")

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.reranker.init_reranker")
    @patch("mnemo_mcp.server.settings")
    async def test_cloud_reranker_not_available_no_local_fallback(
        self, mock_settings, mock_init, _mock_thread
    ):
        """When cloud reranker is not available, logs error (no local fallback)."""
        from mnemo_mcp.server import _init_reranker_backend

        mock_settings.resolve_rerank_backend.return_value = "cloud"
        mock_settings.rerank_chain.return_value = ["cloud-model"]

        mock_init.side_effect = Exception("Cloud failed")

        with patch("mnemo_mcp.server.logger") as mock_logger:
            await _init_reranker_backend("sdk")
            mock_logger.warning.assert_called_with(
                "Reranker cloud-model not available: Cloud failed"
            )
            mock_logger.error.assert_called_with(
                "Cloud reranker not available and local fallback is disabled"
            )


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

    @patch("mnemo_mcp.server._maybe_register_custom_embed")
    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_local_backend_init_fails(
        self, mock_settings, mock_init, _mock_thread, _mock_register
    ):
        """When local backend init raises exception, logs error."""

        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.embedding_chain.return_value = []
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "local/m"

        # Have init_backend throw an exception
        mock_init.side_effect = Exception("init failed test error")

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}

        with patch("mnemo_mcp.server.logger") as mock_logger:
            await _init_embedding_backend("local", ctx)
            mock_logger.error.assert_called_with(
                "Local embedding init failed: init failed test error"
            )

        # Model should remain None
        assert ctx["embedding_model"] is None


class TestWarmupInitEmbeddingBackend:
    """Tests for _init_embedding_backend in server.py (background init).

    Must patch "mnemo_mcp.server.settings" (not config.settings) because
    server.py imports settings at module level. Also must patch
    asyncio.to_thread to avoid threading issues in tests.
    """

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_cloud_explicit_model_success(
        self, mock_settings, mock_init, _mock_thread
    ):
        """When explicit model works, ctx is updated in-place."""
        from unittest.mock import MagicMock

        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.embedding_chain.return_value = ["gemini/model"]
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "cloud"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 3072
        mock_init.return_value = mock_backend

        ctx: dict = {
            "embedding_model": None,
            "embedding_dims": 768,
        }

        await _init_embedding_backend("sdk", ctx)

        assert ctx["embedding_model"] == "gemini/model"
        assert ctx["embedding_dims"] == 768  # DEFAULT_EMBEDDING_DIMS

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_cloud_auto_detect_candidates(
        self, mock_settings, mock_init, _mock_thread
    ):
        """Auto-detect iterates through the embedding chain."""
        from unittest.mock import MagicMock

        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.embedding_chain.return_value = [
            "jina_ai/jina-embeddings-v5-text-small",
            "gemini/gemini-embedding-001",
        ]
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "cloud"

        # First candidate fails, second succeeds
        backend_fail = MagicMock()
        backend_fail.check_available.return_value = 0
        backend_ok = MagicMock()
        backend_ok.check_available.return_value = 768
        mock_init.side_effect = [backend_fail, backend_ok]

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}

        await _init_embedding_backend("sdk", ctx)

        assert ctx["embedding_model"] is not None
        assert ctx["embedding_dims"] == 768

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_cloud_unavailable_no_local_fallback(
        self, mock_settings, mock_init, _mock_thread
    ):
        """When cloud model not available, no local fallback in CONFIGURED state."""
        from unittest.mock import MagicMock

        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.embedding_chain.return_value = ["model"]
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "cloud"

        # Cloud returns 0 dims (not available)
        cloud_backend = MagicMock()
        cloud_backend.check_available.return_value = 0
        mock_init.return_value = cloud_backend

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}

        await _init_embedding_backend("sdk", ctx)

        # No local fallback -- model stays None
        assert ctx["embedding_model"] is None
        # Only cloud was tried (1 call)
        assert mock_init.call_count == 1

    @patch("mnemo_mcp.server._maybe_register_custom_embed")
    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_direct_local_backend(
        self, mock_settings, mock_init, _mock_thread, _mock_register
    ):
        """When backend_type is "local", skips cloud entirely."""
        from unittest.mock import MagicMock

        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.embedding_chain.return_value = []
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "local/m"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 1024
        mock_init.return_value = mock_backend

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}

        await _init_embedding_backend("local", ctx)

        mock_init.assert_called_once_with("local", "local/m")
        assert ctx["embedding_model"] == "__local__"

    @patch("mnemo_mcp.server._maybe_register_custom_embed")
    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_local_backend_failure_logs_error(
        self, mock_settings, mock_init, _mock_thread, _mock_register
    ):
        """When local backend also fails, ctx stays with None model."""
        from unittest.mock import MagicMock

        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.embedding_chain.return_value = []
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "local/m"

        mock_backend = MagicMock()
        mock_backend.check_available.side_effect = Exception("import error")
        mock_init.return_value = mock_backend

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}

        await _init_embedding_backend("local", ctx)

        assert ctx["embedding_model"] is None

    @patch("mnemo_mcp.server._maybe_register_custom_embed")
    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.server.logger")
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_local_backend_init_raises_exception(
        self, mock_settings, mock_init, mock_logger, _mock_thread, _mock_register
    ):
        """When init_backend raises exception, logs error and ctx stays None."""
        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.embedding_chain.return_value = []
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "local/m"

        mock_init.side_effect = Exception("Init Backend Failed")

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}
        await _init_embedding_backend("local", ctx)

        assert ctx["embedding_model"] is None
        mock_logger.error.assert_called_with(
            "Local embedding init failed: Init Backend Failed"
        )


class TestJsonHelper:
    """Tests for the _json formatting helper."""

    def test_json_indentation(self):
        """Verify _json serializes with indent=2."""
        data = {"a": 1, "b": [2, 3]}
        result = _json(data)
        expected = json.dumps(data, indent=2)
        assert result == expected
        assert "\n  " in result  # Check for 2-space indentation
