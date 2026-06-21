"""Tests for relay_setup module."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.relay_setup import (
    CLOUD_KEYS,
    apply_config,
    ensure_config,
    load_relay_config,
)


class TestConstants:
    """Test module constants."""

    def test_cloud_keys(self):
        assert "JINA_AI_API_KEY" in CLOUD_KEYS
        assert "GEMINI_API_KEY" in CLOUD_KEYS
        assert "OPENAI_API_KEY" in CLOUD_KEYS
        assert "COHERE_API_KEY" in CLOUD_KEYS


class TestApplyConfig:
    """Test apply_config function."""

    def test_applies_new_keys(self, monkeypatch):
        """Sets environment variables for keys not already in env."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)

        config = {
            "JINA_AI_API_KEY": "jina_test_key",
            "GEMINI_API_KEY": "AIza_test_key",
        }
        apply_config(config)

        assert os.environ.get("JINA_AI_API_KEY") == "jina_test_key"
        assert os.environ.get("GEMINI_API_KEY") == "AIza_test_key"

    def test_overwrites_existing_env_var_on_differing_value(self, monkeypatch):
        """Single-user reconfigure: a differing value overwrites the stale env
        var so a rotated key actually takes effect (the old ``key not in
        os.environ`` guard silently dropped the new value)."""
        monkeypatch.setenv("JINA_AI_API_KEY", "existing_key")

        config = {"JINA_AI_API_KEY": "new_key"}
        apply_config(config)

        assert os.environ.get("JINA_AI_API_KEY") == "new_key"

    def test_noop_when_value_unchanged(self, monkeypatch):
        """An identical value is a no-op (no needless rewrite)."""
        monkeypatch.setenv("JINA_AI_API_KEY", "same_key")

        config = {"JINA_AI_API_KEY": "same_key"}
        apply_config(config)

        assert os.environ.get("JINA_AI_API_KEY") == "same_key"

    def test_skips_empty_values(self, monkeypatch):
        """Does not set empty string values."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        config = {"GEMINI_API_KEY": "", "OPENAI_API_KEY": "sk_test"}
        apply_config(config)

        assert os.environ.get("GEMINI_API_KEY") is None
        assert os.environ.get("OPENAI_API_KEY") == "sk_test"

    def test_multiple_keys_with_mixed_states(self, monkeypatch):
        """Handles a mix of new, changed, and empty values: a changed value
        overwrites the stale env var, a new value is set, an empty value is
        skipped."""
        monkeypatch.setenv("COHERE_API_KEY", "existing")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)

        config = {
            "COHERE_API_KEY": "rotated",
            "OPENAI_API_KEY": "new_openai",
            "JINA_AI_API_KEY": "",
        }
        apply_config(config)

        assert os.environ.get("COHERE_API_KEY") == "rotated"
        assert os.environ.get("OPENAI_API_KEY") == "new_openai"
        assert os.environ.get("JINA_AI_API_KEY") is None


class TestLoadRelayConfig:
    """Test load_relay_config function."""

    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    def test_returns_config_from_file(self, mock_read):
        mock_read.return_value = {"GEMINI_API_KEY": "AIza_test"}
        result = load_relay_config()
        assert result == {"GEMINI_API_KEY": "AIza_test"}
        mock_read.assert_called_once()

    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    def test_returns_none_when_no_config(self, mock_read):
        mock_read.return_value = None
        result = load_relay_config()
        assert result is None

    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    def test_returns_none_when_no_cloud_keys(self, mock_read):
        mock_read.return_value = {"UNKNOWN_KEY": "value"}
        result = load_relay_config()
        assert result is None

    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    def test_returns_none_on_import_error(self, mock_read):
        """Returns None when mcp_core raises."""
        mock_read.side_effect = ImportError("No module named 'mcp_core'")
        result = load_relay_config()
        assert result is None

    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    def test_returns_none_on_generic_exception(self, mock_read):
        """Returns None on any exception."""
        mock_read.side_effect = RuntimeError("Unexpected error")
        result = load_relay_config()
        assert result is None

    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    def test_returns_config_with_gdrive_key(self, mock_read):
        """Returns config when only GOOGLE_DRIVE_CLIENT_ID is present."""
        mock_read.return_value = {"GOOGLE_DRIVE_CLIENT_ID": "client123"}
        result = load_relay_config()
        assert result == {"GOOGLE_DRIVE_CLIENT_ID": "client123"}

    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    def test_returns_none_when_all_values_empty(self, mock_read):
        """Returns None when saved config has keys but all values are empty."""
        mock_read.return_value = {
            "JINA_AI_API_KEY": "",
            "GEMINI_API_KEY": "",
            "GOOGLE_DRIVE_CLIENT_ID": "",
        }
        result = load_relay_config()
        assert result is None


class TestEnsureConfig:
    """Test ensure_config async function."""

    @pytest.fixture(autouse=True)
    def _relay_url(self, monkeypatch):
        """Set MCP_RELAY_URL for tests exercising the relay path.

        Per mode-matrix 2.5, mnemo-mcp remote-relay mode requires explicit
        MCP_RELAY_URL (no DEFAULT_RELAY_URL fallback).
        """
        monkeypatch.setenv("MCP_RELAY_URL", "https://relay.example.com")

    async def test_missing_relay_url_raises(self, monkeypatch):
        """Remote-relay without MCP_RELAY_URL must raise per matrix 2.5."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv("MCP_RELAY_URL", raising=False)

        with (
            patch(
                "mcp_core.storage.per_plugin_store.PerPluginStore.load",
                return_value=None,
            ),
            pytest.raises(RuntimeError, match="MCP_RELAY_URL"),
        ):
            await ensure_config()

    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    async def test_returns_config_from_file(self, mock_read, monkeypatch):
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_read.return_value = {"GEMINI_API_KEY": "AIza_test"}
        result = await ensure_config()
        assert result == {"GEMINI_API_KEY": "AIza_test"}

    @patch("mcp_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    async def test_relay_setup_fails_gracefully(self, mock_read, mock_session):
        mock_read.return_value = None
        mock_session.side_effect = ConnectionError("Cannot reach server")
        result = await ensure_config()
        assert result is None

    @patch("mnemo_mcp.relay_setup.apply_config")
    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.save")
    @patch("mcp_core.relay.client.poll_for_result", new_callable=AsyncMock)
    @patch("mcp_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    async def test_relay_setup_success(
        self, mock_read, mock_session, mock_poll, mock_save, mock_apply, monkeypatch
    ):
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_read.return_value = None
        mock_session.return_value = MagicMock(
            relay_url="https://relay.example.com/#k=abc&p=xyz",
            session_id="test-session",
        )
        config = {
            "JINA_AI_API_KEY": "jina_test",
            "GEMINI_API_KEY": "AIza_test",
        }
        mock_poll.return_value = config

        with (
            patch("httpx.AsyncClient") as mock_httpx,
            patch("mnemo_mcp.config.settings") as mock_settings,
        ):
            mock_client = AsyncMock()
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_settings.google_drive_client_id = ""

            result = await ensure_config()

        assert result == config
        mock_save.assert_called_once_with(config)
        mock_apply.assert_called_once_with(config)

    @patch("mcp_core.relay.client.poll_for_result", new_callable=AsyncMock)
    @patch("mcp_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    async def test_relay_setup_timeout(self, mock_read, mock_session, mock_poll):
        mock_read.return_value = None
        mock_session.return_value = MagicMock(relay_url="https://example.com")
        mock_poll.side_effect = RuntimeError("Timeout")
        result = await ensure_config()
        assert result is None

    async def test_returns_none_when_env_keys_present(self, monkeypatch):
        """Skips relay when cloud API keys are already in environment."""
        monkeypatch.setenv("JINA_AI_API_KEY", "jina_existing")
        result = await ensure_config()
        assert result is None

    async def test_returns_none_when_any_cloud_key_present(self, monkeypatch):
        """Skips relay when any single cloud key exists."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("COHERE_API_KEY", "co_test")
        result = await ensure_config()
        assert result is None

    @patch("mcp_core.relay.client.poll_for_result", new_callable=AsyncMock)
    @patch("mcp_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    async def test_relay_skipped_by_user(
        self, mock_read, mock_session, mock_poll, monkeypatch
    ):
        """Returns None when user skips relay setup."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_read.return_value = None
        mock_session.return_value = MagicMock(relay_url="https://example.com")
        mock_poll.side_effect = RuntimeError("RELAY_SKIPPED by user")

        result = await ensure_config()
        assert result is None

    @patch("mcp_core.relay.client.poll_for_result", new_callable=AsyncMock)
    @patch("mcp_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    async def test_relay_timed_out_extended(
        self, mock_read, mock_session, mock_poll, monkeypatch
    ):
        """Returns None when relay times out with extended message."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_read.return_value = None
        mock_session.return_value = MagicMock(relay_url="https://example.com")
        mock_poll.side_effect = RuntimeError("Session timed out after 300s")

        result = await ensure_config()
        assert result is None

    @patch("mcp_core.relay.client.poll_for_result", new_callable=AsyncMock)
    @patch("mcp_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    async def test_relay_generic_runtime_error(
        self, mock_read, mock_session, mock_poll, monkeypatch
    ):
        """Returns None on generic RuntimeError (neither skip nor timeout)."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_read.return_value = None
        mock_session.return_value = MagicMock(relay_url="https://example.com")
        mock_poll.side_effect = RuntimeError("Some other error")

        result = await ensure_config()
        assert result is None

    @patch("mnemo_mcp.relay_setup.apply_config")
    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.save")
    @patch("mcp_core.relay.client.poll_for_result", new_callable=AsyncMock)
    @patch("mcp_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    async def test_relay_success_with_gdrive_oauth(
        self, mock_read, mock_session, mock_poll, mock_save, mock_apply, monkeypatch
    ):
        """Relay success triggers GDrive OAuth when client_id is configured."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_read.return_value = None
        mock_session.return_value = MagicMock(
            relay_url="https://relay.example.com/#k=abc",
            session_id="sess-123",
        )
        config = {"JINA_AI_API_KEY": "jina_test"}
        mock_poll.return_value = config

        with (
            patch("httpx.AsyncClient") as mock_httpx,
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_gdrive,
        ):
            mock_client = AsyncMock()
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_settings.google_drive_client_id = "client123"

            result = await ensure_config()

        assert result == config
        mock_gdrive.assert_called_once_with(
            relay_url="https://relay.example.com",
            session_id="sess-123",
        )

    @patch("mnemo_mcp.relay_setup.apply_config")
    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.save")
    @patch("mcp_core.relay.client.poll_for_result", new_callable=AsyncMock)
    @patch("mcp_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    async def test_relay_success_gdrive_oauth_fails(
        self, mock_read, mock_session, mock_poll, mock_save, mock_apply, monkeypatch
    ):
        """GDrive OAuth failure doesn't prevent config return."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_read.return_value = None
        mock_session.return_value = MagicMock(
            relay_url="https://relay.example.com/#k=abc",
            session_id="sess-456",
        )
        config = {"GEMINI_API_KEY": "AIza_test"}
        mock_poll.return_value = config

        with (
            patch("httpx.AsyncClient") as mock_httpx,
            patch("mnemo_mcp.config.settings") as mock_settings,
            patch(
                "mnemo_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                side_effect=Exception("GDrive OAuth failed"),
            ),
        ):
            mock_client = AsyncMock()
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_settings.google_drive_client_id = "client123"

            result = await ensure_config()

        assert result == config

    @patch("mcp_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    async def test_relay_create_session_connection_error_extended(
        self, mock_read, mock_session, monkeypatch
    ):
        """Returns None when create_session raises any exception (extended test)."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_read.return_value = None
        mock_session.side_effect = Exception("DNS resolution failed")

        result = await ensure_config()
        assert result is None

    @patch("mnemo_mcp.relay_setup.apply_config")
    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.save")
    @patch("mcp_core.relay.client.poll_for_result", new_callable=AsyncMock)
    @patch("mcp_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_core.storage.per_plugin_store.PerPluginStore.load")
    async def test_relay_success_httpx_message_fails_silently(
        self, mock_read, mock_session, mock_poll, mock_save, mock_apply, monkeypatch
    ):
        """Relay message sending failure doesn't prevent config return."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_read.return_value = None
        mock_session.return_value = MagicMock(
            relay_url="https://relay.example.com/#k=abc",
            session_id="sess-789",
        )
        config = {"OPENAI_API_KEY": "sk_test"}
        mock_poll.return_value = config

        with (
            patch("httpx.AsyncClient") as mock_httpx,
            patch("mnemo_mcp.config.settings") as mock_settings,
        ):
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Network error")
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_settings.google_drive_client_id = ""

            result = await ensure_config()

        assert result == config
