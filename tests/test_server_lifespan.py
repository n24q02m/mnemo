"""Tests for server.py -- reranker init, config actions, _enrich_memory.

Targets: _init_reranker_backend (cell success, cell fallback to local,
disabled, local not available, local init failed), config warmup/unknown
actions, and the background enrichment error guards.
"""

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.reranker import clear_reranker, get_reranker
from mnemo_mcp.server import _enrich_memory, _init_reranker_backend, config


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


@pytest.fixture(autouse=True)
def _fresh_reranker_singleton():
    clear_reranker()
    yield
    clear_reranker()


def _passthrough_to_thread():
    return patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )


# ---------------------------------------------------------------------------
# _init_reranker_backend
# ---------------------------------------------------------------------------


class TestInitRerankerBackend:
    async def test_reranker_disabled_returns_early(self):
        """Disabled reranker clears the singleton and never initializes."""
        with (
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.reranker.init_reranker") as mock_init,
        ):
            mock_settings.rerank_enabled = False
            await _init_reranker_backend()
        mock_init.assert_not_called()
        assert get_reranker() is None

    async def test_cloud_cell_success(self):
        """Configured rerank cell + available probe keeps the cloud backend."""
        cloud_backend = MagicMock()
        cloud_backend.check_available.return_value = True
        with (
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.server.cell_configured", return_value=True),
            _passthrough_to_thread(),
            patch("mnemo_mcp.reranker.init_reranker", return_value=cloud_backend) as mock_init,
        ):
            mock_settings.rerank_enabled = True
            await _init_reranker_backend()
        mock_init.assert_called_once_with("cloud")

    async def test_cloud_cell_unavailable_falls_back_to_local(self):
        """Unavailable rerank cell clears and falls back to the local ONNX leg."""
        cloud_backend = MagicMock()
        cloud_backend.check_available.return_value = False
        local_backend = MagicMock()
        local_backend.check_available.return_value = True

        def fake_init(backend_type, model=None, **kwargs):
            return cloud_backend if backend_type == "cloud" else local_backend

        with (
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.server.cell_configured", return_value=True),
            _passthrough_to_thread(),
            patch(
                "mnemo_mcp.server._maybe_register_custom_rerank"
            ),
            patch("mnemo_mcp.reranker.init_reranker", side_effect=fake_init) as mock_init,
        ):
            mock_settings.rerank_enabled = True
            mock_settings.disable_local_rerank = False
            mock_settings.resolve_local_rerank_model.return_value = "local/reranker"
            await _init_reranker_backend()
        assert [c.args[0] for c in mock_init.call_args_list] == ["cloud", "local"]

    async def test_cloud_cell_probe_exception_falls_back_to_local(self):
        """A raising cell probe is contained and the local leg still runs."""
        local_backend = MagicMock()
        local_backend.check_available.return_value = True

        def fake_init(backend_type, model=None, **kwargs):
            if backend_type == "cloud":
                raise RuntimeError("cell down")
            return local_backend

        with (
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.server.cell_configured", return_value=True),
            _passthrough_to_thread(),
            patch("mnemo_mcp.server._maybe_register_custom_rerank"),
            patch(
                "mnemo_mcp.reranker.init_reranker", side_effect=fake_init
            ) as mock_init,
        ):
            mock_settings.rerank_enabled = True
            mock_settings.disable_local_rerank = False
            mock_settings.resolve_local_rerank_model.return_value = "local/reranker"
            await _init_reranker_backend()  # must not raise
        # The local leg still ran after the cell probe blew up.
        assert mock_init.call_args_list[-1].args[0] == "local"

    async def test_local_leg_disabled_when_disable_local_rerank(self):
        """DISABLE_LOCAL_RERANK with no usable cell initializes nothing."""
        with (
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.server.cell_configured", return_value=False),
            patch("mnemo_mcp.reranker.init_reranker") as mock_init,
        ):
            mock_settings.rerank_enabled = True
            mock_settings.disable_local_rerank = True
            await _init_reranker_backend()
        mock_init.assert_not_called()
        assert get_reranker() is None

    async def test_local_reranker_not_available(self):
        """Local reranker that reports unavailable leaves the singleton empty."""
        local_backend = MagicMock()
        local_backend.check_available.return_value = False
        with (
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.server.cell_configured", return_value=False),
            _passthrough_to_thread(),
            patch("mnemo_mcp.server._maybe_register_custom_rerank"),
            patch("mnemo_mcp.reranker.init_reranker", return_value=local_backend),
        ):
            mock_settings.rerank_enabled = True
            mock_settings.disable_local_rerank = False
            mock_settings.resolve_local_rerank_model.return_value = "local/reranker"
            await _init_reranker_backend()
        assert get_reranker() is None

    async def test_local_reranker_init_fails(self):
        """Local reranker init raising is contained (no crash, empty singleton)."""
        with (
            patch("mnemo_mcp.server.settings") as mock_settings,
            patch("mnemo_mcp.server.cell_configured", return_value=False),
            _passthrough_to_thread(),
            patch("mnemo_mcp.server._maybe_register_custom_rerank"),
            patch(
                "mnemo_mcp.reranker.init_reranker",
                side_effect=Exception("ONNX not installed"),
            ),
        ):
            mock_settings.rerank_enabled = True
            mock_settings.disable_local_rerank = False
            mock_settings.resolve_local_rerank_model.return_value = "local/reranker"
            await _init_reranker_backend()  # must not raise
        assert get_reranker() is None


# ---------------------------------------------------------------------------
# config -- warmup / unknown actions
# ---------------------------------------------------------------------------


class TestConfigActions:
    async def test_config_warmup(self):
        """Config warmup action calls run_warmup."""
        with patch(
            "mnemo_mcp.setup_tool.run_warmup",
            new_callable=AsyncMock,
            return_value={"status": "ok", "warmup": True},
        ):
            result = await config(action="warmup")
            assert result["status"] == "ok"

    async def test_config_unknown_action(self):
        """Config with unknown action returns error with suggestion."""
        result = await config(action="statuss")
        assert "error" in result
        assert "Unknown action" in result["error"]
        assert result["valid_actions"] == [
            "backfill_embeddings",
            "set",
            "status",
            "warmup",
        ]
        assert "suggestion" in result

    async def test_config_unknown_action_no_match(self):
        """Config with completely invalid action returns the action list."""
        result = await config(action="xyzxyzxyz")
        assert "Unknown action" in result["error"]
        assert "Available actions are:" in result["suggestion"]

    async def test_setup_sync_action_removed(self):
        """The old setup_sync action is gone with the de-host."""
        result = await config(action="setup_sync")
        assert "Unknown action 'setup_sync'" in result["error"]
        assert "setup_sync" not in result["valid_actions"]


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
