"""Additional tests for relay_setup -- covering ensure_config edge cases.

Targets: apply_config, load_relay_config error/edge paths,
ensure_config (env vars present, relay skipped, timed out, runtime errors),
ensure_config GDrive OAuth path, relay message sending.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

from mnemo_mcp.relay_setup import (
    CLOUD_KEYS,
    apply_config,
    ensure_config,
    load_relay_config,
)

# ---------------------------------------------------------------------------
# apply_config
# ---------------------------------------------------------------------------


class TestApplyConfig:
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

    def test_skips_existing_env_vars(self, monkeypatch):
        """Does not overwrite existing env vars."""
        monkeypatch.setenv("JINA_AI_API_KEY", "existing_key")

        config = {"JINA_AI_API_KEY": "new_key"}
        apply_config(config)

        assert os.environ.get("JINA_AI_API_KEY") == "existing_key"

    def test_skips_empty_values(self, monkeypatch):
        """Does not set empty string values."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        config = {"GEMINI_API_KEY": "", "OPENAI_API_KEY": "sk_test"}
        apply_config(config)

        assert os.environ.get("GEMINI_API_KEY") is None
        assert os.environ.get("OPENAI_API_KEY") == "sk_test"

    def test_multiple_keys_with_mixed_states(self, monkeypatch):
        """Handles a mix of new, existing, and empty values."""
        monkeypatch.setenv("COHERE_API_KEY", "existing")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)

        config = {
            "COHERE_API_KEY": "should_not_overwrite",
            "OPENAI_API_KEY": "new_openai",
            "JINA_AI_API_KEY": "",
        }
        apply_config(config)

        assert os.environ.get("COHERE_API_KEY") == "existing"
        assert os.environ.get("OPENAI_API_KEY") == "new_openai"
        assert os.environ.get("JINA_AI_API_KEY") is None


# ---------------------------------------------------------------------------
# load_relay_config edge cases
# ---------------------------------------------------------------------------


class TestLoadRelayConfigCoverage:
    @patch("mcp_core.storage.config_file.read_config")
    def test_returns_none_on_import_error(self, mock_read):
        """Returns None when mcp_core raises."""
        mock_read.side_effect = ImportError("No module named 'mcp_core'")
        result = load_relay_config()
        assert result is None

    @patch("mcp_core.storage.config_file.read_config")
    def test_returns_none_on_generic_exception(self, mock_read):
        """Returns None on any exception."""
        mock_read.side_effect = RuntimeError("Unexpected error")
        result = load_relay_config()
        assert result is None

    @patch("mcp_core.storage.config_file.read_config")
    def test_returns_config_with_gdrive_key(self, mock_read):
        """Returns config when only GOOGLE_DRIVE_CLIENT_ID is present."""
        mock_read.return_value = {"GOOGLE_DRIVE_CLIENT_ID": "client123"}
        result = load_relay_config()
        assert result == {"GOOGLE_DRIVE_CLIENT_ID": "client123"}

    @patch("mcp_core.storage.config_file.read_config")
    def test_returns_none_when_all_values_empty(self, mock_read):
        """Returns None when saved config has keys but all values are empty."""
        mock_read.return_value = {
            "JINA_AI_API_KEY": "",
            "GEMINI_API_KEY": "",
            "GOOGLE_DRIVE_CLIENT_ID": "",
        }
        result = load_relay_config()
        assert result is None


# ---------------------------------------------------------------------------
# ensure_config
# ---------------------------------------------------------------------------


class TestEnsureConfigCoverage:
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
    @patch("mcp_core.storage.config_file.read_config")
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
    @patch("mcp_core.storage.config_file.read_config")
    async def test_relay_timed_out(
        self, mock_read, mock_session, mock_poll, monkeypatch
    ):
        """Returns None when relay times out."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_read.return_value = None
        mock_session.return_value = MagicMock(relay_url="https://example.com")
        mock_poll.side_effect = RuntimeError("Session timed out after 300s")

        result = await ensure_config()
        assert result is None

    @patch("mcp_core.relay.client.poll_for_result", new_callable=AsyncMock)
    @patch("mcp_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_core.storage.config_file.read_config")
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
    @patch("mcp_core.storage.config_file.write_config")
    @patch("mcp_core.relay.client.poll_for_result", new_callable=AsyncMock)
    @patch("mcp_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_core.storage.config_file.read_config")
    async def test_relay_success_with_gdrive_oauth(
        self, mock_read, mock_session, mock_poll, mock_write, mock_apply, monkeypatch
    ):
        """Relay success triggers GDrive OAuth when client_id is configured."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_read.return_value = None
        mock_session.return_value = MagicMock(
            relay_url="https://mnemo-mcp.n24q02m.com/#k=abc",
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
            relay_url="https://mnemo-mcp.n24q02m.com",
            session_id="sess-123",
        )

    @patch("mnemo_mcp.relay_setup.apply_config")
    @patch("mcp_core.storage.config_file.write_config")
    @patch("mcp_core.relay.client.poll_for_result", new_callable=AsyncMock)
    @patch("mcp_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_core.storage.config_file.read_config")
    async def test_relay_success_gdrive_oauth_fails(
        self, mock_read, mock_session, mock_poll, mock_write, mock_apply, monkeypatch
    ):
        """GDrive OAuth failure doesn't prevent config return."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_read.return_value = None
        mock_session.return_value = MagicMock(
            relay_url="https://mnemo-mcp.n24q02m.com/#k=abc",
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
    @patch("mcp_core.storage.config_file.read_config")
    async def test_relay_create_session_connection_error(
        self, mock_read, mock_session, monkeypatch
    ):
        """Returns None when create_session raises any exception."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_read.return_value = None
        mock_session.side_effect = Exception("DNS resolution failed")

        result = await ensure_config()
        assert result is None

    @patch("mnemo_mcp.relay_setup.apply_config")
    @patch("mcp_core.storage.config_file.write_config")
    @patch("mcp_core.relay.client.poll_for_result", new_callable=AsyncMock)
    @patch("mcp_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_core.storage.config_file.read_config")
    async def test_relay_success_httpx_message_fails_silently(
        self, mock_read, mock_session, mock_poll, mock_write, mock_apply, monkeypatch
    ):
        """Relay message sending failure doesn't prevent config return."""
        for key in CLOUD_KEYS:
            monkeypatch.delenv(key, raising=False)
        mock_read.return_value = None
        mock_session.return_value = MagicMock(
            relay_url="https://mnemo-mcp.n24q02m.com/#k=abc",
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
