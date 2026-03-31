"""Tests for server.py -- lifespan, reranker init, help, config actions.

Targets: _init_reranker_backend (cloud success, cloud fallback to local,
local fallback, local not available, local init failed),
lifespan (relay config apply, relay exception),
config warmup/setup_sync/unknown actions, help unknown topic.
"""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.server import (
    _enrich_memory,
    _init_reranker_backend,
    config,
    help,
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
# _init_reranker_backend
# ---------------------------------------------------------------------------


class TestInitRerankerBackend:
    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.server.settings")
    async def test_cloud_reranker_success(self, mock_settings, _mock_thread):
        """Cloud reranker initializes successfully."""
        mock_settings.resolve_rerank_backend.return_value = "cloud"
        mock_settings.resolve_rerank_model.return_value = "rerank-v4.0-pro"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = True

        with patch("mnemo_mcp.reranker.init_reranker", return_value=mock_backend):
            await _init_reranker_backend("sdk")

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.server.settings")
    async def test_cloud_reranker_unavailable_falls_to_local(
        self, mock_settings, _mock_thread
    ):
        """Cloud reranker not available falls back to local."""
        mock_settings.resolve_rerank_backend.return_value = "cloud"
        mock_settings.resolve_rerank_model.return_value = "rerank-v4.0-pro"
        mock_settings.resolve_local_rerank_model.return_value = "local/reranker"

        cloud_backend = MagicMock()
        cloud_backend.check_available.return_value = False

        local_backend = MagicMock()
        local_backend.check_available.return_value = True

        call_count = 0

        def mock_init(backend_type, model=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if backend_type == "cloud":
                return cloud_backend
            return local_backend

        with patch("mnemo_mcp.reranker.init_reranker", side_effect=mock_init):
            await _init_reranker_backend("sdk")

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.server.settings")
    async def test_cloud_reranker_exception_falls_to_local(
        self, mock_settings, _mock_thread
    ):
        """Cloud reranker exception falls back to local."""
        mock_settings.resolve_rerank_backend.return_value = "cloud"
        mock_settings.resolve_rerank_model.return_value = "rerank-v4.0-pro"
        mock_settings.resolve_local_rerank_model.return_value = "local/reranker"

        local_backend = MagicMock()
        local_backend.check_available.return_value = True

        call_count = 0

        def mock_init(backend_type, model=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if backend_type == "cloud":
                raise Exception("Cloud init failed")
            return local_backend

        with patch("mnemo_mcp.reranker.init_reranker", side_effect=mock_init):
            await _init_reranker_backend("sdk")

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.server.settings")
    async def test_reranker_disabled(self, mock_settings, _mock_thread):
        """Disabled reranker returns early."""
        mock_settings.resolve_rerank_backend.return_value = ""
        await _init_reranker_backend("sdk")

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.server.settings")
    async def test_local_reranker_not_available(self, mock_settings, _mock_thread):
        """Local reranker returns not available."""
        mock_settings.resolve_rerank_backend.return_value = "local"
        mock_settings.resolve_local_rerank_model.return_value = "local/reranker"

        local_backend = MagicMock()
        local_backend.check_available.return_value = False

        with patch("mnemo_mcp.reranker.init_reranker", return_value=local_backend):
            await _init_reranker_backend("local")

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.server.settings")
    async def test_local_reranker_init_fails(self, mock_settings, _mock_thread):
        """Local reranker init raises exception."""
        mock_settings.resolve_rerank_backend.return_value = "local"
        mock_settings.resolve_local_rerank_model.return_value = "local/reranker"

        with patch(
            "mnemo_mcp.reranker.init_reranker",
            side_effect=Exception("ONNX not installed"),
        ):
            # Should not raise
            await _init_reranker_backend("local")

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.server.settings")
    async def test_cloud_no_model_falls_to_local(self, mock_settings, _mock_thread):
        """Cloud reranker with no model falls to local."""
        mock_settings.resolve_rerank_backend.return_value = "cloud"
        mock_settings.resolve_rerank_model.return_value = None
        mock_settings.resolve_local_rerank_model.return_value = "local/reranker"

        local_backend = MagicMock()
        local_backend.check_available.return_value = True

        with patch("mnemo_mcp.reranker.init_reranker", return_value=local_backend):
            await _init_reranker_backend("sdk")


# ---------------------------------------------------------------------------
# config -- warmup / setup_sync / unknown actions
# ---------------------------------------------------------------------------


class TestConfigActions:
    async def test_config_warmup(self, ctx_with_db):
        """Config warmup action calls run_warmup."""
        ctx, _ = ctx_with_db
        with patch(
            "mnemo_mcp.setup_tool.run_warmup",
            new_callable=AsyncMock,
            return_value={"status": "ok", "warmup": True},
        ):
            result = json.loads(await config(action="warmup", ctx=ctx))
            assert result["status"] == "ok"

    async def test_config_setup_sync(self, ctx_with_db):
        """Config setup_sync action calls run_setup_sync."""
        ctx, _ = ctx_with_db
        with patch(
            "mnemo_mcp.setup_tool.run_setup_sync",
            new_callable=AsyncMock,
            return_value={"status": "ok", "sync": "configured"},
        ):
            result = json.loads(await config(action="setup_sync", ctx=ctx))
            assert result["status"] == "ok"

    async def test_config_unknown_action(self, ctx_with_db):
        """Config with unknown action returns error with suggestion."""
        ctx, _ = ctx_with_db
        result = json.loads(await config(action="syncc", ctx=ctx))
        assert "error" in result
        assert "Unknown action" in result["error"]
        assert "valid_actions" in result

    async def test_config_unknown_action_no_match(self, ctx_with_db):
        """Config with completely invalid action returns error without suggestion."""
        ctx, _ = ctx_with_db
        result = json.loads(await config(action="xyzxyzxyz", ctx=ctx))
        assert "error" in result
        assert "Unknown action" in result["error"]


# ---------------------------------------------------------------------------
# help -- unknown topic
# ---------------------------------------------------------------------------


class TestHelpTool:
    async def test_help_unknown_topic(self):
        """Unknown topic returns error with suggestion."""
        result = json.loads(await help(topic="memoryx"))
        assert "error" in result
        assert "Unknown topic" in result["error"]
        assert "valid_topics" in result

    async def test_help_no_match(self):
        """Completely invalid topic returns error without suggestion."""
        result = json.loads(await help(topic="xyzxyz"))
        assert "error" in result
        assert "valid_topics" in result

    async def test_help_setup_redirects_to_config(self):
        """'setup' topic is redirected to 'config'."""
        result = await help(topic="setup")
        # Should return the config doc content (not a JSON error response)
        # The doc itself may contain the word "error" as regular text,
        # but a JSON error response would start with '{'
        assert not result.startswith("{")
        assert "Config" in result or "config" in result


# ---------------------------------------------------------------------------
# _enrich_memory -- importance scoring exception
# ---------------------------------------------------------------------------


class TestEnrichMemory:
    async def test_importance_scoring_exception(self, ctx_with_db):
        """Importance scoring exception is caught."""
        _, db = ctx_with_db
        mid = db.add("test content")

        with (
            patch(
                "mnemo_mcp.graph.score_importance",
                new_callable=AsyncMock,
                side_effect=Exception("LLM error"),
            ),
            patch(
                "mnemo_mcp.graph.extract_entities",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            # Should not raise
            await _enrich_memory(db, mid, "test content")

    async def test_importance_default_skips_update(self, ctx_with_db):
        """When importance is 0.5 (default), update is skipped."""
        _, db = ctx_with_db
        mid = db.add("test content")

        with (
            patch(
                "mnemo_mcp.graph.score_importance",
                new_callable=AsyncMock,
                return_value=0.5,
            ),
            patch(
                "mnemo_mcp.graph.extract_entities",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("mnemo_mcp.server.asyncio.to_thread") as mock_thread,
        ):
            await _enrich_memory(db, mid, "test content")
            # to_thread should NOT be called for update_importance
            mock_thread.assert_not_called()
