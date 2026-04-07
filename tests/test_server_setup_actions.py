"""Tests for server.py setup_* config actions and AWAITING_SETUP paths.

Covers: setup_status, setup_start, setup_skip, setup_reset, setup_complete,
setup_relay, _maybe_include_setup_hint URL branch, _init_embedding_backend
and _init_reranker_backend AWAITING_SETUP paths, lifespan credential
resolution exception.
"""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.credential_state import CredentialState, get_state, set_state
from mnemo_mcp.db import MemoryDB
from mnemo_mcp.server import (
    _init_embedding_backend,
    _init_reranker_backend,
    _maybe_include_setup_hint,
    config,
)


@pytest.fixture
def ctx_with_db(tmp_path: Path) -> Generator[tuple[MagicMock, MemoryDB]]:
    """Mock MCP Context with fresh DB."""
    db = MemoryDB(tmp_path / "setup_test.db", embedding_dims=0)
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "db": db,
        "embedding_model": None,
        "embedding_dims": 0,
    }
    yield ctx, db
    db.close()


# ---------------------------------------------------------------------------
# setup_status action
# ---------------------------------------------------------------------------


class TestSetupStatus:
    async def test_returns_state_and_url(self, ctx_with_db):
        """setup_status returns credential state and setup URL."""
        ctx, _ = ctx_with_db
        set_state(CredentialState.CONFIGURED)

        with patch(
            "mnemo_mcp.credential_state.get_setup_url",
            return_value="https://setup.url",
        ):
            result = json.loads(await config(action="setup_status", ctx=ctx))

        assert result["state"] == "configured"
        assert result["setup_url"] == "https://setup.url"
        assert "cloud_keys_in_env" in result

    async def test_with_env_keys(self, ctx_with_db, monkeypatch):
        """setup_status lists cloud keys present in env."""
        ctx, _ = ctx_with_db
        monkeypatch.setenv("GEMINI_API_KEY", "test_key")
        set_state(CredentialState.CONFIGURED)

        result = json.loads(await config(action="setup_status", ctx=ctx))

        assert "GEMINI_API_KEY" in result["cloud_keys_in_env"]


# ---------------------------------------------------------------------------
# setup_start action
# ---------------------------------------------------------------------------


class TestSetupStart:
    async def test_already_configured_no_force(self, ctx_with_db):
        """setup_start returns already_configured when CONFIGURED and no force."""
        ctx, _ = ctx_with_db
        set_state(CredentialState.CONFIGURED)

        result = json.loads(await config(action="setup_start", ctx=ctx))

        assert result["status"] == "already_configured"

    async def test_force_reconfigure(self, ctx_with_db):
        """setup_start with key='force' triggers relay even when CONFIGURED."""
        ctx, _ = ctx_with_db
        set_state(CredentialState.CONFIGURED)

        with patch(
            "mnemo_mcp.credential_state.trigger_relay_setup",
            new_callable=AsyncMock,
            return_value="https://relay.url/new",
        ):
            result = json.loads(
                await config(action="setup_start", key="force", ctx=ctx)
            )

        assert result["status"] == "setup_started"
        assert result["setup_url"] == "https://relay.url/new"

    async def test_awaiting_setup_triggers_relay(self, ctx_with_db):
        """setup_start in AWAITING_SETUP state triggers relay."""
        ctx, _ = ctx_with_db
        set_state(CredentialState.AWAITING_SETUP)

        with patch(
            "mnemo_mcp.credential_state.trigger_relay_setup",
            new_callable=AsyncMock,
            return_value="https://relay.url",
        ):
            result = json.loads(await config(action="setup_start", ctx=ctx))

        assert result["status"] == "setup_started"

    async def test_relay_fails(self, ctx_with_db):
        """setup_start returns error when relay setup fails."""
        ctx, _ = ctx_with_db
        set_state(CredentialState.AWAITING_SETUP)

        with patch(
            "mnemo_mcp.credential_state.trigger_relay_setup",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = json.loads(await config(action="setup_start", ctx=ctx))

        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# setup_skip action
# ---------------------------------------------------------------------------


class TestSetupSkip:
    async def test_sets_local_mode(self, ctx_with_db):
        """setup_skip sets LOCAL state and local mode marker."""
        ctx, _ = ctx_with_db

        with patch("mcp_relay_core.set_local_mode") as mock_set:
            result = json.loads(await config(action="setup_skip", ctx=ctx))

        assert result["status"] == "ok"
        assert get_state() == CredentialState.LOCAL
        mock_set.assert_called_once_with("mnemo-mcp")


# ---------------------------------------------------------------------------
# setup_reset action
# ---------------------------------------------------------------------------


class TestSetupReset:
    async def test_resets_credentials(self, ctx_with_db):
        """setup_reset clears credentials and returns to AWAITING_SETUP."""
        ctx, _ = ctx_with_db
        set_state(CredentialState.CONFIGURED)

        with (
            patch("mcp_relay_core.clear_mode"),
            patch("mcp_relay_core.storage.config_file.delete_config"),
        ):
            result = json.loads(await config(action="setup_reset", ctx=ctx))

        assert result["status"] == "ok"
        assert get_state() == CredentialState.AWAITING_SETUP


# ---------------------------------------------------------------------------
# setup_complete action
# ---------------------------------------------------------------------------


class TestSetupComplete:
    async def test_refreshes_state(self, ctx_with_db):
        """setup_complete re-resolves credential state."""
        ctx, _ = ctx_with_db

        with patch(
            "mnemo_mcp.credential_state.resolve_credential_state",
            return_value=CredentialState.CONFIGURED,
        ):
            set_state(CredentialState.CONFIGURED)
            result = json.loads(await config(action="setup_complete", ctx=ctx))

        assert result["status"] == "ok"
        assert result["state"] == "configured"

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    async def test_reinits_embedding_when_configured(
        self, mock_init, _mock_thread, ctx_with_db
    ):
        """setup_complete re-inits embedding when state is CONFIGURED and model is None."""
        ctx, _ = ctx_with_db

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init.return_value = mock_backend

        with (
            patch(
                "mnemo_mcp.credential_state.resolve_credential_state",
                return_value=CredentialState.CONFIGURED,
            ),
            patch("mnemo_mcp.server.settings") as mock_settings,
        ):
            set_state(CredentialState.CONFIGURED)
            mock_settings.setup_providers.return_value = "sdk"
            mock_settings.resolve_embedding_model.return_value = "test/model"
            mock_settings.resolve_embedding_dims.return_value = 768
            mock_settings.resolve_embedding_backend.return_value = "cloud"

            result = json.loads(await config(action="setup_complete", ctx=ctx))

        assert result["status"] == "ok"

    async def test_local_state_no_reinit(self, ctx_with_db):
        """setup_complete with LOCAL state does not re-init embedding."""
        ctx, _ = ctx_with_db

        with patch(
            "mnemo_mcp.credential_state.resolve_credential_state",
            return_value=CredentialState.LOCAL,
        ):
            set_state(CredentialState.LOCAL)
            result = json.loads(await config(action="setup_complete", ctx=ctx))

        assert result["status"] == "ok"
        assert result["state"] == "local"


# ---------------------------------------------------------------------------
# setup_relay action (backward compat alias)
# ---------------------------------------------------------------------------


class TestSetupRelay:
    async def test_relay_success(self, ctx_with_db):
        """setup_relay triggers relay and returns URL."""
        ctx, _ = ctx_with_db

        with patch(
            "mnemo_mcp.credential_state.trigger_relay_setup",
            new_callable=AsyncMock,
            return_value="https://relay.url",
        ):
            result = json.loads(await config(action="setup_relay", ctx=ctx))

        assert result["status"] == "setup_started"
        assert result["setup_url"] == "https://relay.url"

    async def test_relay_fails(self, ctx_with_db):
        """setup_relay returns error when relay fails."""
        ctx, _ = ctx_with_db

        with patch(
            "mnemo_mcp.credential_state.trigger_relay_setup",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = json.loads(await config(action="setup_relay", ctx=ctx))

        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# _maybe_include_setup_hint
# ---------------------------------------------------------------------------


class TestMaybeIncludeSetupHint:
    async def test_adds_hint_when_awaiting(self):
        """Adds setup hint when in AWAITING_SETUP and URL available."""
        set_state(CredentialState.AWAITING_SETUP)

        with patch(
            "mnemo_mcp.credential_state.trigger_relay_setup",
            new_callable=AsyncMock,
            return_value="https://setup.url",
        ):
            result = await _maybe_include_setup_hint({"data": "test"})

        assert "_setup_hint" in result
        assert "https://setup.url" in result["_setup_hint"]

    async def test_no_hint_when_configured(self):
        """No hint added when already CONFIGURED."""
        set_state(CredentialState.CONFIGURED)

        result = await _maybe_include_setup_hint({"data": "test"})

        assert "_setup_hint" not in result

    async def test_no_hint_when_relay_returns_none(self):
        """No hint added when relay returns None."""
        set_state(CredentialState.AWAITING_SETUP)

        with patch(
            "mnemo_mcp.credential_state.trigger_relay_setup",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _maybe_include_setup_hint({"data": "test"})

        assert "_setup_hint" not in result


# ---------------------------------------------------------------------------
# _init_embedding_backend AWAITING_SETUP path
# ---------------------------------------------------------------------------


class TestInitEmbeddingBackendAwaitingSetup:
    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.server.settings")
    async def test_awaiting_setup_skips_embedding(self, mock_settings, _mock_thread):
        """When in AWAITING_SETUP, embedding init is skipped."""
        set_state(CredentialState.AWAITING_SETUP)

        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "cloud"

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}
        await _init_embedding_backend("sdk", ctx)

        # Model should remain None since init was skipped
        assert ctx["embedding_model"] is None


# ---------------------------------------------------------------------------
# _init_reranker_backend AWAITING_SETUP path
# ---------------------------------------------------------------------------


class TestInitRerankerBackendAwaitingSetup:
    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.server.settings")
    async def test_awaiting_setup_skips_reranker(self, mock_settings, _mock_thread):
        """When in AWAITING_SETUP, reranker init is skipped."""
        set_state(CredentialState.AWAITING_SETUP)

        mock_settings.resolve_rerank_backend.return_value = "cloud"

        await _init_reranker_backend("sdk")

        # Should not try to init anything

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.reranker.init_reranker")
    @patch("mnemo_mcp.server.settings")
    async def test_local_state_uses_local_reranker(
        self, mock_settings, mock_init, _mock_thread
    ):
        """When in LOCAL state, uses local reranker path."""
        set_state(CredentialState.LOCAL)

        mock_settings.resolve_rerank_backend.return_value = "cloud"
        mock_settings.resolve_local_rerank_model.return_value = "local/rerank"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = True
        mock_init.return_value = mock_backend

        await _init_reranker_backend("sdk")

        mock_init.assert_called_once_with("local", "local/rerank")
