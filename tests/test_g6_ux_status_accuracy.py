"""G6 UX bug fixes — _handle_config_setup_status accuracy for mnemo-mcp.

Bug: setup_status returned stale module-level _state even when no
credentials were actually loadable via PerPluginStore.

Fix: _handle_config_setup_status now derives state from live PerPluginStore
load + env, and always includes providers_configured in the response.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest


def _call_config_setup_status_sync() -> dict[str, Any]:
    """Invoke the async setup_status handler and return parsed dict."""
    import asyncio

    from mnemo_mcp.server import _handle_config_setup_status

    raw = asyncio.run(_handle_config_setup_status())
    return json.loads(raw)


class TestSetupStatusLiveDerivedState:
    """setup_status derives state from live PerPluginStore, not stale _state."""

    def test_returns_configured_when_store_has_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """setup_status returns configured when PerPluginStore has cloud keys."""
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

        with patch(
            "mcp_core.storage.per_plugin_store.PerPluginStore.load",
            return_value={"GEMINI_API_KEY": "test-key-123"},
        ):
            result = _call_config_setup_status_sync()

        assert result["state"] == "configured"
        assert "GEMINI_API_KEY" in result["providers_configured"]

    def test_returns_needs_setup_when_store_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """setup_status returns awaiting_setup when store empty and no env vars."""
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

        # Force module-level state to CONFIGURED (stale) to reproduce the bug
        import mnemo_mcp.credential_state as cs

        cs.set_state(cs.CredentialState.CONFIGURED)

        with patch(
            "mcp_core.storage.per_plugin_store.PerPluginStore.load",
            return_value={},
        ):
            result = _call_config_setup_status_sync()

        # State must be derived from live creds, NOT stale _state
        assert result["state"] != "configured"
        assert result["providers_configured"] == []

        # Restore state
        cs.set_state(cs.CredentialState.AWAITING_SETUP)

    def test_env_vars_take_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """setup_status includes env-var keys in providers_configured."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

        with patch(
            "mcp_core.storage.per_plugin_store.PerPluginStore.load",
            return_value={},
        ):
            result = _call_config_setup_status_sync()

        assert result["state"] == "configured"
        assert "OPENAI_API_KEY" in result["providers_configured"]
        assert "OPENAI_API_KEY" in result["cloud_keys_in_env"]

    def test_response_includes_providers_configured_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """setup_status always includes providers_configured key in response."""
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)

        with patch(
            "mcp_core.storage.per_plugin_store.PerPluginStore.load",
            return_value={},
        ):
            result = _call_config_setup_status_sync()

        assert "providers_configured" in result
        assert isinstance(result["providers_configured"], list)

    def test_no_duplicate_providers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If same key appears in both env and store, it should appear only once."""
        monkeypatch.setenv("GEMINI_API_KEY", "key-from-env")

        with patch(
            "mcp_core.storage.per_plugin_store.PerPluginStore.load",
            return_value={"GEMINI_API_KEY": "key-from-store"},
        ):
            result = _call_config_setup_status_sync()

        assert result["providers_configured"].count("GEMINI_API_KEY") == 1

    def test_gdrive_only_store_counts_as_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A store with only GOOGLE_DRIVE_CLIENT_ID is reported as configured.

        Pre-fix the handler counted only CLOUD_KEYS, so a GDrive-only saved
        config wrongly reported awaiting_setup with an empty providers list.
        The fix uses ALL_CONFIG_KEYS (incl GDrive) so the status is accurate.
        """
        for k in (
            "JINA_AI_API_KEY",
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "COHERE_API_KEY",
            "ANTHROPIC_API_KEY",
            "XAI_API_KEY",
            "GOOGLE_DRIVE_CLIENT_ID",
        ):
            monkeypatch.delenv(k, raising=False)

        with patch(
            "mcp_core.storage.per_plugin_store.PerPluginStore.load",
            return_value={"GOOGLE_DRIVE_CLIENT_ID": "client-id-123"},
        ):
            result = _call_config_setup_status_sync()

        assert result["state"] == "configured"
        assert "GOOGLE_DRIVE_CLIENT_ID" in result["providers_configured"]
        # GDrive is not a cloud LLM/embedding key, so it must not leak into
        # the cloud-keys-in-env summary even when present in the env.
        assert "GOOGLE_DRIVE_CLIENT_ID" not in result["cloud_keys_in_env"]

    def test_gdrive_env_not_listed_as_cloud_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GOOGLE_DRIVE_CLIENT_ID in env counts as a provider but is not a
        cloud key in the ``cloud_keys_in_env`` summary."""
        for k in (
            "JINA_AI_API_KEY",
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "COHERE_API_KEY",
            "ANTHROPIC_API_KEY",
            "XAI_API_KEY",
        ):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("GOOGLE_DRIVE_CLIENT_ID", "client-id-456")

        with patch(
            "mcp_core.storage.per_plugin_store.PerPluginStore.load",
            return_value={},
        ):
            result = _call_config_setup_status_sync()

        assert "GOOGLE_DRIVE_CLIENT_ID" in result["providers_configured"]
        assert "GOOGLE_DRIVE_CLIENT_ID" not in result["cloud_keys_in_env"]
