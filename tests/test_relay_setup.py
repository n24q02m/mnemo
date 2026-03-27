"""Tests for relay_setup module."""

from unittest.mock import AsyncMock, MagicMock, patch

from mnemo_mcp.relay_setup import (
    ALL_POSSIBLE_FIELDS,
    DEFAULT_RELAY_URL,
    REQUIRED_FIELDS,
    ensure_config,
    load_relay_config,
)


class TestConstants:
    """Test module constants."""

    def test_default_relay_url(self):
        assert DEFAULT_RELAY_URL == "https://mnemo-mcp.n24q02m.com"

    def test_required_fields(self):
        assert REQUIRED_FIELDS == ["JINA_AI_API_KEY"]

    def test_all_possible_fields(self):
        assert "JINA_AI_API_KEY" in ALL_POSSIBLE_FIELDS
        assert "GEMINI_API_KEY" in ALL_POSSIBLE_FIELDS
        assert "OPENAI_API_KEY" in ALL_POSSIBLE_FIELDS
        assert "COHERE_API_KEY" in ALL_POSSIBLE_FIELDS


class TestLoadRelayConfig:
    """Test load_relay_config function."""

    @patch("mcp_relay_core.storage.resolver.resolve_config")
    def test_returns_config_from_file(self, mock_resolve):
        mock_resolve.return_value = MagicMock(
            config={"JINA_AI_API_KEY": "jina_test"},
            source="file",
        )
        result = load_relay_config()
        assert result == {"JINA_AI_API_KEY": "jina_test"}
        mock_resolve.assert_called_once_with("mnemo-mcp", REQUIRED_FIELDS)

    @patch("mcp_relay_core.storage.resolver.resolve_config")
    def test_returns_none_when_no_config(self, mock_resolve):
        mock_resolve.return_value = MagicMock(config=None, source=None)
        result = load_relay_config()
        assert result is None


class TestEnsureConfig:
    """Test ensure_config async function."""

    @patch("mcp_relay_core.storage.resolver.resolve_config")
    async def test_returns_config_from_file(self, mock_resolve):
        mock_resolve.return_value = MagicMock(
            config={"GEMINI_API_KEY": "AIza_test"},
            source="file",
        )
        result = await ensure_config()
        assert result == {"GEMINI_API_KEY": "AIza_test"}

    @patch("mcp_relay_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_relay_core.storage.resolver.resolve_config")
    async def test_relay_setup_fails_gracefully(self, mock_resolve, mock_session):
        mock_resolve.return_value = MagicMock(config=None, source=None)
        mock_session.side_effect = ConnectionError("Cannot reach server")
        result = await ensure_config()
        assert result is None

    @patch("mcp_relay_core.storage.config_file.write_config")
    @patch("mcp_relay_core.relay.client.poll_for_result", new_callable=AsyncMock)
    @patch("mcp_relay_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_relay_core.storage.resolver.resolve_config")
    async def test_relay_setup_success(
        self, mock_resolve, mock_session, mock_poll, mock_write
    ):
        mock_resolve.return_value = MagicMock(config=None, source=None)
        mock_session.return_value = MagicMock(
            relay_url="https://mnemo-mcp.n24q02m.com/#k=abc&p=xyz"
        )
        mock_poll.return_value = {
            "JINA_AI_API_KEY": "jina_test",
            "GEMINI_API_KEY": "AIza_test",
        }
        result = await ensure_config()
        assert result == {
            "JINA_AI_API_KEY": "jina_test",
            "GEMINI_API_KEY": "AIza_test",
        }
        mock_write.assert_called_once_with(
            "mnemo-mcp",
            {"JINA_AI_API_KEY": "jina_test", "GEMINI_API_KEY": "AIza_test"},
        )

    @patch("mcp_relay_core.relay.client.poll_for_result", new_callable=AsyncMock)
    @patch("mcp_relay_core.relay.client.create_session", new_callable=AsyncMock)
    @patch("mcp_relay_core.storage.resolver.resolve_config")
    async def test_relay_setup_timeout(self, mock_resolve, mock_session, mock_poll):
        mock_resolve.return_value = MagicMock(config=None, source=None)
        mock_session.return_value = MagicMock(relay_url="https://example.com")
        mock_poll.side_effect = RuntimeError("Timeout")
        result = await ensure_config()
        assert result is None
