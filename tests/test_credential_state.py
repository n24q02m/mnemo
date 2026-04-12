"""Tests for mnemo_mcp.credential_state -- state machine, resolve, relay, sharing."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

from mnemo_mcp.credential_state import (
    CLOUD_KEYS,
    CredentialState,
    _share_cloud_keys_to_peers,
    get_setup_url,
    get_state,
    reset_state,
    resolve_credential_state,
    set_state,
    trigger_relay_setup,
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
            "mcp_core.storage.config_file.read_config",
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
                "mcp_core.storage.config_file.read_config",
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
                "mcp_core.storage.config_file.read_config",
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
                "mcp_core.storage.config_file.read_config",
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
                "mcp_core.storage.config_file.read_config",
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
                "mcp_core.storage.config_file.read_config",
                return_value=None,
            ),
            patch("mcp_core.get_mode", side_effect=Exception("no mode")),
        ):
            result = resolve_credential_state()

        assert result == CredentialState.AWAITING_SETUP

    def test_config_shares_keys_to_peers(self, monkeypatch):
        """When config loaded, shares cloud keys to peers."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)
        set_state(CredentialState.AWAITING_SETUP)

        mock_config = {"JINA_AI_API_KEY": "key1", "GEMINI_API_KEY": "key2"}
        with (
            patch(
                "mcp_core.storage.config_file.read_config",
                return_value=mock_config,
            ),
            patch(
                "mnemo_mcp.credential_state._share_cloud_keys_to_peers"
            ) as mock_share,
        ):
            resolve_credential_state()
            mock_share.assert_called_once_with(mock_config)

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


# ---------------------------------------------------------------------------
# trigger_relay_setup
# ---------------------------------------------------------------------------


class TestTriggerRelaySetup:
    async def test_not_awaiting_returns_existing_url(self):
        """When not in AWAITING_SETUP, returns existing setup URL."""
        import mnemo_mcp.credential_state as cs

        set_state(CredentialState.CONFIGURED)
        cs._setup_url = "https://existing.url"
        result = await trigger_relay_setup()
        assert result == "https://existing.url"
        cs._setup_url = None

    async def test_force_starts_new_session(self):
        """Force=True starts relay even if not AWAITING_SETUP."""
        set_state(CredentialState.CONFIGURED)

        mock_session = MagicMock()
        mock_session.session_id = "sess-123"
        mock_session.relay_url = "https://relay.url/setup"

        with (
            patch(
                "mcp_core.acquire_session_lock",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "mcp_core.relay.client.create_session",
                new_callable=AsyncMock,
                return_value=mock_session,
            ),
            patch(
                "mcp_core.write_session_lock",
                new_callable=AsyncMock,
            ),
            patch("mcp_core.try_open_browser"),
            patch("asyncio.create_task"),
        ):
            result = await trigger_relay_setup(force=True)

        assert result == "https://relay.url/setup"

    async def test_reuses_existing_session(self):
        """When session lock exists, reuses existing relay session."""
        set_state(CredentialState.AWAITING_SETUP)

        existing_session = MagicMock()
        existing_session.relay_url = "https://reused.url"

        with patch(
            "mcp_core.acquire_session_lock",
            new_callable=AsyncMock,
            return_value=existing_session,
        ):
            result = await trigger_relay_setup()

        assert result == "https://reused.url"

    async def test_relay_setup_exception_returns_none(self):
        """When relay fails, returns None and resets state."""
        set_state(CredentialState.AWAITING_SETUP)

        with patch(
            "mcp_core.acquire_session_lock",
            new_callable=AsyncMock,
            side_effect=Exception("network error"),
        ):
            result = await trigger_relay_setup()

        assert result is None
        assert get_state() == CredentialState.AWAITING_SETUP


# ---------------------------------------------------------------------------
# _poll_relay_background
# ---------------------------------------------------------------------------


class TestPollRelayBackground:
    async def test_success_path(self):
        """Successful poll applies config and sets CONFIGURED."""
        from mnemo_mcp.credential_state import _poll_relay_background

        set_state(CredentialState.SETUP_IN_PROGRESS)

        mock_session = MagicMock()
        mock_session.session_id = "sess-123"
        config = {"JINA_AI_API_KEY": "key1"}

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=config,
            ),
            patch("mcp_core.storage.config_file.write_config"),
            patch("mnemo_mcp.credential_state._share_cloud_keys_to_peers"),
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
            ),
            patch(
                "mcp_core.relay.client.send_message",
                new_callable=AsyncMock,
            ),
            patch(
                "mcp_core.release_session_lock",
                new_callable=AsyncMock,
            ),
        ):
            mock_settings.google_drive_client_id = None
            mock_settings.setup_providers.return_value = "sdk"
            await _poll_relay_background("https://relay", mock_session, 10.0)

        assert get_state() == CredentialState.CONFIGURED

    async def test_relay_skipped_sets_local(self):
        """When poll raises RELAY_SKIPPED, sets LOCAL mode."""
        from mnemo_mcp.credential_state import _poll_relay_background

        set_state(CredentialState.SETUP_IN_PROGRESS)

        with patch(
            "mcp_core.relay.client.poll_for_result",
            new_callable=AsyncMock,
            side_effect=RuntimeError("RELAY_SKIPPED"),
        ):
            await _poll_relay_background("https://relay", MagicMock(), None)

        assert get_state() == CredentialState.LOCAL

    async def test_runtime_error_non_skipped(self):
        """Non-RELAY_SKIPPED RuntimeError sets AWAITING_SETUP."""
        from mnemo_mcp.credential_state import _poll_relay_background

        set_state(CredentialState.SETUP_IN_PROGRESS)

        with patch(
            "mcp_core.relay.client.poll_for_result",
            new_callable=AsyncMock,
            side_effect=RuntimeError("some other error"),
        ):
            await _poll_relay_background("https://relay", MagicMock(), None)

        assert get_state() == CredentialState.AWAITING_SETUP

    async def test_generic_exception(self):
        """Generic exception sets AWAITING_SETUP."""
        from mnemo_mcp.credential_state import _poll_relay_background

        set_state(CredentialState.SETUP_IN_PROGRESS)

        with patch(
            "mcp_core.relay.client.poll_for_result",
            new_callable=AsyncMock,
            side_effect=Exception("connection lost"),
        ):
            await _poll_relay_background("https://relay", MagicMock(), None)

        assert get_state() == CredentialState.AWAITING_SETUP

    async def test_gdrive_client_id_applied(self):
        """When config has GOOGLE_DRIVE_CLIENT_ID, applies to settings."""
        from mnemo_mcp.credential_state import _poll_relay_background

        set_state(CredentialState.SETUP_IN_PROGRESS)

        mock_session = MagicMock()
        mock_session.session_id = "sess-123"
        config = {"GOOGLE_DRIVE_CLIENT_ID": "gdrive-id"}

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=config,
            ),
            patch("mcp_core.storage.config_file.write_config"),
            patch("mnemo_mcp.credential_state._share_cloud_keys_to_peers"),
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
            ),
            patch(
                "mcp_core.relay.client.send_message",
                new_callable=AsyncMock,
            ),
            patch(
                "mcp_core.release_session_lock",
                new_callable=AsyncMock,
            ),
        ):
            mock_settings.google_drive_client_id = None
            mock_settings.setup_providers.return_value = "sdk"
            await _poll_relay_background("https://relay", mock_session, 10.0)

        assert get_state() == CredentialState.CONFIGURED

    async def test_gdrive_oauth_exception_nonfatal(self):
        """GDrive OAuth failure is non-fatal."""
        from mnemo_mcp.credential_state import _poll_relay_background

        set_state(CredentialState.SETUP_IN_PROGRESS)

        mock_session = MagicMock()
        mock_session.session_id = "sess-456"
        config = {"JINA_AI_API_KEY": "key"}

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=config,
            ),
            patch("mcp_core.storage.config_file.write_config"),
            patch("mnemo_mcp.credential_state._share_cloud_keys_to_peers"),
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                side_effect=Exception("OAuth failed"),
            ),
            patch(
                "mcp_core.relay.client.send_message",
                new_callable=AsyncMock,
            ),
            patch(
                "mcp_core.release_session_lock",
                new_callable=AsyncMock,
            ),
        ):
            mock_settings.google_drive_client_id = None
            mock_settings.setup_providers.return_value = "sdk"
            await _poll_relay_background("https://relay", mock_session, 10.0)

        # Should still be CONFIGURED despite OAuth error
        assert get_state() == CredentialState.CONFIGURED

    async def test_send_message_exception_nonfatal(self):
        """send_message failure is non-fatal."""
        from mnemo_mcp.credential_state import _poll_relay_background

        set_state(CredentialState.SETUP_IN_PROGRESS)

        mock_session = MagicMock()
        mock_session.session_id = "sess-789"
        config = {"JINA_AI_API_KEY": "key"}

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=config,
            ),
            patch("mcp_core.storage.config_file.write_config"),
            patch("mnemo_mcp.credential_state._share_cloud_keys_to_peers"),
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
            ),
            patch(
                "mcp_core.relay.client.send_message",
                new_callable=AsyncMock,
                side_effect=Exception("send failed"),
            ),
            patch(
                "mcp_core.release_session_lock",
                new_callable=AsyncMock,
            ),
        ):
            mock_settings.google_drive_client_id = None
            mock_settings.setup_providers.return_value = "sdk"
            await _poll_relay_background("https://relay", mock_session, 10.0)

        assert get_state() == CredentialState.CONFIGURED

    async def test_set_local_mode_exception_nonfatal(self):
        """When RELAY_SKIPPED but set_local_mode fails, still sets LOCAL."""
        from mnemo_mcp.credential_state import _poll_relay_background

        set_state(CredentialState.SETUP_IN_PROGRESS)

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                side_effect=RuntimeError("RELAY_SKIPPED"),
            ),
            patch(
                "mcp_core.set_local_mode",
                side_effect=Exception("fs error"),
            ),
        ):
            await _poll_relay_background("https://relay", MagicMock(), None)

        assert get_state() == CredentialState.LOCAL

    async def test_no_session_id_skips_oauth_and_message(self):
        """When session has no session_id, skips GDrive OAuth and message."""
        from mnemo_mcp.credential_state import _poll_relay_background

        set_state(CredentialState.SETUP_IN_PROGRESS)

        mock_session = MagicMock(spec=[])  # No session_id attribute
        config = {"JINA_AI_API_KEY": "key"}

        with (
            patch(
                "mcp_core.relay.client.poll_for_result",
                new_callable=AsyncMock,
                return_value=config,
            ),
            patch("mcp_core.storage.config_file.write_config"),
            patch("mnemo_mcp.credential_state._share_cloud_keys_to_peers"),
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mcp_core.release_session_lock",
                new_callable=AsyncMock,
            ),
        ):
            mock_settings.google_drive_client_id = None
            mock_settings.setup_providers.return_value = "sdk"
            await _poll_relay_background("https://relay", mock_session, 10.0)

        assert get_state() == CredentialState.CONFIGURED


# ---------------------------------------------------------------------------
# _share_cloud_keys_to_peers
# ---------------------------------------------------------------------------


class TestShareCloudKeysToPeers:
    def test_shares_keys_to_peers(self):
        """Shares cloud keys to wet-mcp and better-code-review-graph."""
        config = {"JINA_AI_API_KEY": "key1", "GEMINI_API_KEY": "key2"}

        with patch("mcp_core.storage.config_file.write_config") as mock_write:
            _share_cloud_keys_to_peers(config)

        assert mock_write.call_count == 2
        mock_write.assert_any_call(
            "wet-mcp", {"JINA_AI_API_KEY": "key1", "GEMINI_API_KEY": "key2"}
        )
        mock_write.assert_any_call(
            "better-code-review-graph",
            {"JINA_AI_API_KEY": "key1", "GEMINI_API_KEY": "key2"},
        )

    def test_no_cloud_keys_returns_early(self):
        """When no cloud keys in config, returns early."""
        config = {"GOOGLE_DRIVE_CLIENT_ID": "some-id"}

        with patch("mcp_core.storage.config_file.write_config") as mock_write:
            _share_cloud_keys_to_peers(config)

        mock_write.assert_not_called()

    def test_write_config_exception_nonfatal(self):
        """Exception writing to one peer doesn't affect the other."""
        config = {"JINA_AI_API_KEY": "key1"}

        with patch(
            "mcp_core.storage.config_file.write_config",
            side_effect=[Exception("fs error"), None],
        ):
            # Should not raise
            _share_cloud_keys_to_peers(config)

    def test_import_exception_nonfatal(self):
        """Exception importing write_config is non-fatal."""
        config = {"JINA_AI_API_KEY": "key1"}

        with patch(
            "mcp_core.storage.config_file.write_config",
            side_effect=ImportError("module not found"),
        ):
            # Should not raise
            _share_cloud_keys_to_peers(config)

    def test_empty_values_filtered(self):
        """Empty string values are not shared."""
        config = {"JINA_AI_API_KEY": "", "GEMINI_API_KEY": "key2"}

        with patch("mcp_core.storage.config_file.write_config") as mock_write:
            _share_cloud_keys_to_peers(config)

        # Only GEMINI_API_KEY should be shared
        for call_args in mock_write.call_args_list:
            shared = call_args[0][1]
            assert shared == {"GEMINI_API_KEY": "key2"}


# ---------------------------------------------------------------------------
# reset_state
# ---------------------------------------------------------------------------


class TestResetState:
    def test_resets_state_and_url(self):
        """Resets state to AWAITING_SETUP and clears URL."""
        import mnemo_mcp.credential_state as cs

        set_state(CredentialState.CONFIGURED)
        cs._setup_url = "https://some.url"

        with (
            patch("mcp_core.clear_mode"),
            patch("mcp_core.storage.config_file.delete_config"),
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
                "mcp_core.storage.config_file.delete_config",
                side_effect=Exception("err"),
            ),
        ):
            reset_state()

        assert get_state() == CredentialState.AWAITING_SETUP
