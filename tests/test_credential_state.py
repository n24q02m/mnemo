"""Tests for mnemo_mcp.credential_state -- state machine, resolve, relay, sharing."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

from mnemo_mcp.credential_state import (
    CLOUD_KEYS,
    CredentialState,
    get_setup_url,
    get_state,
    reset_state,
    resolve_credential_state,
    set_state,
)

# ---------------------------------------------------------------------------
# Basic state helpers
# ---------------------------------------------------------------------------


class TestCredentialStateEnum:
    def test_all_states(self):
        assert CredentialState.AWAITING_SETUP.value == "awaiting_setup"
        assert CredentialState.SETUP_IN_PROGRESS.value == "setup_in_progress"
        assert CredentialState.CONFIGURED.value == "configured"
        assert CredentialState.LOCAL.value == "local"


class TestGetState:
    def test_returns_current_state(self):
        set_state(CredentialState.LOCAL)
        assert get_state() == CredentialState.LOCAL
        set_state(CredentialState.CONFIGURED)


class TestGetSetupUrl:
    def test_returns_none_by_default(self):
        import mnemo_mcp.credential_state as cs

        old = cs._setup_url
        cs._setup_url = None
        assert get_setup_url() is None
        cs._setup_url = old

    def test_returns_url_when_set(self):
        import mnemo_mcp.credential_state as cs

        old = cs._setup_url
        cs._setup_url = "https://example.com/setup"
        assert get_setup_url() == "https://example.com/setup"
        cs._setup_url = old


# ---------------------------------------------------------------------------
# resolve_credential_state
# ---------------------------------------------------------------------------


class TestResolveCredentialState:
    def test_env_vars_present(self, monkeypatch):
        """When cloud keys in env, returns CONFIGURED."""
        set_state(CredentialState.AWAITING_SETUP)
        monkeypatch.setenv("JINA_AI_API_KEY", "test_key")
        result = resolve_credential_state()
        assert result == CredentialState.CONFIGURED
        assert get_state() == CredentialState.CONFIGURED

    def test_no_env_vars_config_file_present(self, monkeypatch):
        """When config file has keys, loads them and returns CONFIGURED."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)
        set_state(CredentialState.AWAITING_SETUP)

        mock_config = {"JINA_AI_API_KEY": "from_config", "GEMINI_API_KEY": "gem_key"}
        with patch(
            "mcp_core.storage.per_plugin_store.PerPluginStore.load",
            return_value=mock_config,
        ):
            result = resolve_credential_state()

        assert result == CredentialState.CONFIGURED
        # Env vars should be applied
        assert os.environ.get("JINA_AI_API_KEY") == "from_config"
        # Cleanup
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def test_config_file_empty(self, monkeypatch):
        """When config file has no cloud keys, continues to local mode check."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)
        set_state(CredentialState.AWAITING_SETUP)

        with (
            patch(
                "mcp_core.storage.per_plugin_store.PerPluginStore.load",
                return_value=None,
            ),
            patch("mcp_core.get_mode", return_value="local"),
        ):
            result = resolve_credential_state()

        assert result == CredentialState.LOCAL

    def test_local_mode_marker(self, monkeypatch):
        """When local mode marker exists, returns LOCAL."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)
        set_state(CredentialState.AWAITING_SETUP)

        with (
            patch(
                "mcp_core.storage.per_plugin_store.PerPluginStore.load",
                return_value=None,
            ),
            patch("mcp_core.get_mode", return_value="local"),
        ):
            result = resolve_credential_state()

        assert result == CredentialState.LOCAL

    def test_nothing_found(self, monkeypatch):
        """When nothing found, returns AWAITING_SETUP."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)
        set_state(CredentialState.AWAITING_SETUP)

        with (
            patch(
                "mcp_core.storage.per_plugin_store.PerPluginStore.load",
                return_value=None,
            ),
            patch("mcp_core.get_mode", return_value=None),
        ):
            result = resolve_credential_state()

        assert result == CredentialState.AWAITING_SETUP

    def test_config_file_read_exception(self, monkeypatch):
        """When config file read raises, falls through to local mode check."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)
        set_state(CredentialState.AWAITING_SETUP)

        with (
            patch(
                "mcp_core.storage.per_plugin_store.PerPluginStore.load",
                side_effect=Exception("read error"),
            ),
            patch("mcp_core.get_mode", return_value=None),
        ):
            result = resolve_credential_state()

        assert result == CredentialState.AWAITING_SETUP

    def test_get_mode_exception(self, monkeypatch):
        """When get_mode raises, falls through to AWAITING_SETUP."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)
        set_state(CredentialState.AWAITING_SETUP)

        with (
            patch(
                "mcp_core.storage.per_plugin_store.PerPluginStore.load",
                return_value=None,
            ),
            patch("mcp_core.get_mode", side_effect=Exception("no mode")),
        ):
            result = resolve_credential_state()

        assert result == CredentialState.AWAITING_SETUP

    def test_config_does_not_write_to_peer_servers(self, monkeypatch):
        """resolve_credential_state must not push keys to other MCP servers.

        Replaces the prior `_share_cloud_keys_to_peers` behavior. Per-server
        isolation: mnemo-mcp keeps only its own credentials, never writes
        to wet-mcp / better-code-review-graph configs.
        """
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)
        set_state(CredentialState.AWAITING_SETUP)

        mock_config = {"JINA_AI_API_KEY": "key1", "GEMINI_API_KEY": "key2"}
        with (
            patch(
                "mcp_core.storage.per_plugin_store.PerPluginStore.load",
                return_value=mock_config,
            ),
            patch("mcp_core.storage.per_plugin_store.PerPluginStore.save") as mock_save,
        ):
            result = resolve_credential_state()
            assert result == CredentialState.CONFIGURED
            assert mock_save.call_count == 0

        # Cleanup
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)

    def test_env_var_not_overwritten_by_config(self, monkeypatch):
        """Existing env vars are not overwritten by config file values."""
        monkeypatch.setenv("JINA_AI_API_KEY", "existing_value")
        set_state(CredentialState.AWAITING_SETUP)

        # resolve sees env var and returns CONFIGURED immediately
        result = resolve_credential_state()
        assert result == CredentialState.CONFIGURED
        assert os.environ.get("JINA_AI_API_KEY") == "existing_value"


class TestCredentialIsolation:
    """Per-server isolation regression guard.

    Replaces the prior `_share_cloud_keys_to_peers` helper which propagated
    cloud keys to wet-mcp + crg. The transparent-bridge architecture
    mandates that each server owns its own credentials; mnemo-mcp must
    never write to a peer's `config.enc`.
    """

    def test_no_share_helper_exists(self):
        import mnemo_mcp.credential_state as mod

        assert not hasattr(mod, "_share_cloud_keys_to_peers")


# ---------------------------------------------------------------------------
# reset_state
# ---------------------------------------------------------------------------


class TestGDriveFailedCallback:
    """Covers set_gdrive_failed_callback + wire_gdrive_callbacks + _notify_failed
    paths added for Bug #2 fix (ported from wet-mcp)."""

    def test_set_gdrive_failed_callback_registers(self):
        import mnemo_mcp.credential_state as cs
        from mnemo_mcp.credential_state import set_gdrive_failed_callback

        cb = MagicMock()
        set_gdrive_failed_callback(cb)
        assert cs._on_gdrive_failed is cb
        cs._on_gdrive_failed = None

    def test_wire_gdrive_callbacks_legacy_one_arg(self):
        """Legacy mcp-core (<1.3.0) passes only mark_complete; mark_failed stays None."""
        import mnemo_mcp.credential_state as cs
        from mnemo_mcp.credential_state import wire_gdrive_callbacks

        complete_cb = MagicMock()
        wire_gdrive_callbacks(complete_cb)

        # Complete callback is wrapped to schedule spawn cleanup; verify by
        # invocation rather than identity.
        assert cs._on_gdrive_complete is not None
        cs._on_gdrive_complete()
        complete_cb.assert_called_once()
        assert cs._on_gdrive_failed is None
        cs._on_gdrive_complete = None

    def test_wire_gdrive_callbacks_modern_two_args(self):
        """Modern mcp-core (>=1.3.0) passes both callbacks; mark_failed wraps into
        a (key, error) -> mark_failed('gdrive', error) shim."""
        import mnemo_mcp.credential_state as cs
        from mnemo_mcp.credential_state import wire_gdrive_callbacks

        complete_cb = MagicMock()
        mark_failed = MagicMock()
        wire_gdrive_callbacks(complete_cb, mark_failed)

        # Complete callback is wrapped; verify by invocation.
        assert cs._on_gdrive_complete is not None
        cs._on_gdrive_complete()
        complete_cb.assert_called_once()
        shim = cs._on_gdrive_failed
        assert shim is not None
        # Exercise the wrapping shim
        shim("gdrive", "invalid_grant")
        mark_failed.assert_called_once_with("gdrive", "invalid_grant")
        cs._on_gdrive_complete = None
        cs._on_gdrive_failed = None

    def test_wire_gdrive_callbacks_mark_failed_swallows_exception(self):
        """If mark_failed raises, shim logs and swallows so callers don't crash."""
        import mnemo_mcp.credential_state as cs
        from mnemo_mcp.credential_state import wire_gdrive_callbacks

        mark_failed = MagicMock(side_effect=RuntimeError("boom"))
        wire_gdrive_callbacks(MagicMock(), mark_failed)

        shim = cs._on_gdrive_failed
        assert shim is not None
        # Should NOT raise
        shim("gdrive", "expired")
        cs._on_gdrive_complete = None
        cs._on_gdrive_failed = None


class TestGDriveTokenPoll:
    """Covers _gdrive_token_poll error/terminal paths added for Bug #2 fix."""

    async def test_save_token_failure_notifies_and_returns(self):
        """save_token raising after successful exchange -> WARNING log + notify
        failed callback + return (no retry; device_code cannot be re-exchanged)."""
        import mnemo_mcp.credential_state as cs
        from mnemo_mcp.credential_state import (
            _gdrive_token_poll,
            set_gdrive_failed_callback,
        )

        failed_cb = MagicMock()
        set_gdrive_failed_callback(failed_cb)

        token_response = MagicMock()
        token_response.json.return_value = {
            "access_token": "tok",
            "refresh_token": "refresh",
        }

        async def fake_post(*args, **kwargs):
            return token_response

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch(
                "mnemo_mcp.token_store.async_save_token",
                new_callable=AsyncMock,
                side_effect=OSError("disk full"),
            ),
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            await _gdrive_token_poll("cid", "csec", "devcode", 0, 5)

        failed_cb.assert_called_once()
        args, _ = failed_cb.call_args
        assert args[0] == "gdrive"
        assert "save_token failed" in args[1]
        cs._on_gdrive_failed = None

    async def test_terminal_google_error_notifies(self):
        """Terminal Google error (invalid_grant, access_denied) -> notify + return."""
        import mnemo_mcp.credential_state as cs
        from mnemo_mcp.credential_state import (
            _gdrive_token_poll,
            set_gdrive_failed_callback,
        )

        failed_cb = MagicMock()
        set_gdrive_failed_callback(failed_cb)

        response = MagicMock()
        response.json.return_value = {
            "error": "access_denied",
            "error_description": "user rejected",
        }

        async def fake_post(*args, **kwargs):
            return response

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            await _gdrive_token_poll("cid", "csec", "devcode", 0, 5)

        failed_cb.assert_called_once_with("gdrive", "user rejected")
        cs._on_gdrive_failed = None

    async def test_deadline_expired_notifies(self):
        """Loop exits via deadline without success -> notify with 'expired'."""
        import mnemo_mcp.credential_state as cs
        from mnemo_mcp.credential_state import (
            _gdrive_token_poll,
            set_gdrive_failed_callback,
        )

        failed_cb = MagicMock()
        set_gdrive_failed_callback(failed_cb)

        # expires_in = 0 -> loop body is never entered, deadline branch fires.
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            await _gdrive_token_poll("cid", "csec", "devcode", 0, 0)

        failed_cb.assert_called_once_with("gdrive", "expired")
        cs._on_gdrive_failed = None

    async def test_notify_failed_swallows_callback_exception(self):
        """If _on_gdrive_failed raises, the helper logs and does not propagate."""
        import mnemo_mcp.credential_state as cs
        from mnemo_mcp.credential_state import (
            _gdrive_token_poll,
            set_gdrive_failed_callback,
        )

        failed_cb = MagicMock(side_effect=RuntimeError("callback boom"))
        set_gdrive_failed_callback(failed_cb)

        # Terminal error triggers _notify_failed which catches callback errors.
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            # expires_in=0 -> immediate deadline -> _notify_failed('expired')
            await _gdrive_token_poll("cid", "csec", "devcode", 0, 0)

        failed_cb.assert_called_once()
        cs._on_gdrive_failed = None

    async def test_success_fires_complete_callback_no_failed(self):
        """Happy path: access_token -> save_token OK -> complete_cb fired, failed_cb NOT."""
        import mnemo_mcp.credential_state as cs
        from mnemo_mcp.credential_state import (
            _gdrive_token_poll,
            set_gdrive_complete_callback,
            set_gdrive_failed_callback,
        )

        complete_cb = MagicMock()
        failed_cb = MagicMock()
        set_gdrive_complete_callback(complete_cb)
        set_gdrive_failed_callback(failed_cb)

        response = MagicMock()
        response.json.return_value = {"access_token": "tok"}

        async def fake_post(*args, **kwargs):
            return response

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch(
                "mnemo_mcp.token_store.async_save_token",
                new_callable=AsyncMock,
            ),
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            await _gdrive_token_poll("cid", "csec", "devcode", 0, 5)

        complete_cb.assert_called_once()
        failed_cb.assert_not_called()
        cs._on_gdrive_complete = None
        cs._on_gdrive_failed = None


class TestResetState:
    def test_resets_state_and_url(self):
        """Resets state to AWAITING_SETUP and clears URL."""
        import mnemo_mcp.credential_state as cs

        set_state(CredentialState.CONFIGURED)
        cs._setup_url = "https://some.url"

        with (
            patch("mcp_core.clear_mode"),
            patch("mcp_core.storage.per_plugin_store.PerPluginStore.clear"),
        ):
            reset_state()

        assert get_state() == CredentialState.AWAITING_SETUP
        assert cs._setup_url is None

    def test_reset_exception_nonfatal(self):
        """Exception during reset doesn't raise."""
        set_state(CredentialState.CONFIGURED)

        with (
            patch("mcp_core.clear_mode", side_effect=Exception("err")),
            patch(
                "mcp_core.storage.per_plugin_store.PerPluginStore.clear",
                side_effect=Exception("err"),
            ),
        ):
            reset_state()

        assert get_state() == CredentialState.AWAITING_SETUP
