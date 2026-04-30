"""Tests for ``save_credentials`` single-user branch (no ``PUBLIC_URL``).

Covers ``credential_state.py:412-490`` -- the local-mode persistence + GDrive
Device Code flow. Multi-user remote branch is exercised in
``test_credential_state_multi_user.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def reset_module_state():
    """Reset module-level state and unset PUBLIC_URL before each test."""
    import mnemo_mcp.credential_state as cs

    old_state = cs._state
    yield cs
    cs._state = old_state


def _settings_no_gdrive():
    """Settings stub with no GDrive client credentials."""
    s = MagicMock()
    s.google_drive_client_id = ""
    s.google_drive_client_secret = ""
    s.setup_providers = MagicMock()
    return s


def _settings_with_gdrive():
    """Settings stub configured to trigger Device Code flow."""
    s = MagicMock()
    s.google_drive_client_id = "test-client-id.apps.googleusercontent.com"
    s.google_drive_client_secret = "test-client-secret"
    s.setup_providers = MagicMock()
    return s


class TestSaveCredentialsSingleUserNoGDrive:
    """Single-user branch when GDrive is NOT configured -- no Device Code POST."""

    def test_writes_config_and_returns_none(self, reset_module_state, monkeypatch):
        cs = reset_module_state
        monkeypatch.delenv("PUBLIC_URL", raising=False)

        write_config = MagicMock()
        apply_config = MagicMock()
        schedule_cleanup = MagicMock()

        with (
            patch(
                "mcp_core.storage.per_plugin_store.PerPluginStore.save", write_config
            ),
            patch("mnemo_mcp.relay_setup.apply_config", apply_config),
            patch("mnemo_mcp.config.settings", _settings_no_gdrive()),
            patch.object(cs, "_schedule_spawn_cleanup", schedule_cleanup),
        ):
            result = cs.save_credentials(
                {"JINA_AI_API_KEY": "abc"}, context={"sub": "ignored"}
            )

        assert result is None
        # Per-server isolation: only mnemo-mcp's own config touched, never peers.
        assert write_config.call_count == 1
        assert write_config.call_args.args[0] == {"JINA_AI_API_KEY": "abc"}
        apply_config.assert_called_once_with({"JINA_AI_API_KEY": "abc"})
        schedule_cleanup.assert_called_once()
        assert cs._state == cs.CredentialState.CONFIGURED

    def test_provider_setup_failure_is_nonfatal(self, reset_module_state, monkeypatch):
        cs = reset_module_state
        monkeypatch.delenv("PUBLIC_URL", raising=False)

        bad_settings = _settings_no_gdrive()
        bad_settings.setup_providers.side_effect = RuntimeError("boom")

        with (
            patch("mcp_core.storage.per_plugin_store.PerPluginStore.save", MagicMock()),
            patch("mnemo_mcp.relay_setup.apply_config", MagicMock()),
            patch("mnemo_mcp.config.settings", bad_settings),
            patch.object(cs, "_schedule_spawn_cleanup", MagicMock()),
        ):
            # Must not raise -- the helper swallows provider re-init failures.
            assert cs.save_credentials({"JINA_AI_API_KEY": "abc"}, context=None) is None


class TestSaveCredentialsSingleUserWithGDrive:
    """Single-user branch when GDrive IS configured -- Device Code POST runs."""

    def _mock_response(self, status_code: int, json_body: dict | None = None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_body or {}
        return resp

    def test_device_code_success_returns_oauth_payload(
        self, reset_module_state, monkeypatch
    ):
        cs = reset_module_state
        monkeypatch.delenv("PUBLIC_URL", raising=False)

        device_payload = {
            "device_code": "DC-123",
            "user_code": "ABCD-EFGH",
            "verification_url": "https://www.google.com/device",
            "interval": 5,
            "expires_in": 1800,
        }
        post_mock = MagicMock(return_value=self._mock_response(200, device_payload))
        thread_started = MagicMock()
        thread_cls = MagicMock()
        thread_cls.return_value.start = thread_started
        try_open_browser = MagicMock()

        with (
            patch("mcp_core.storage.per_plugin_store.PerPluginStore.save", MagicMock()),
            patch("mnemo_mcp.relay_setup.apply_config", MagicMock()),
            patch("mnemo_mcp.config.settings", _settings_with_gdrive()),
            patch("httpx.post", post_mock),
            patch("threading.Thread", thread_cls),
            patch("mcp_core.try_open_browser", try_open_browser),
        ):
            result = cs.save_credentials(
                {"JINA_AI_API_KEY": "abc", "GOOGLE_DRIVE_CLIENT_ID": "x"},
                context=None,
            )

        assert result == {
            "type": "oauth_device_code",
            "verification_url": "https://www.google.com/device",
            "user_code": "ABCD-EFGH",
        }
        post_mock.assert_called_once()
        post_url = post_mock.call_args.args[0]
        assert post_url == "https://oauth2.googleapis.com/device/code"
        thread_started.assert_called_once()
        try_open_browser.assert_called_once_with("https://www.google.com/device")

    def test_device_code_non_200_falls_through_to_cleanup(
        self, reset_module_state, monkeypatch
    ):
        cs = reset_module_state
        monkeypatch.delenv("PUBLIC_URL", raising=False)

        post_mock = MagicMock(return_value=self._mock_response(500, {"err": "boom"}))
        cleanup = MagicMock()

        with (
            patch("mcp_core.storage.per_plugin_store.PerPluginStore.save", MagicMock()),
            patch("mnemo_mcp.relay_setup.apply_config", MagicMock()),
            patch("mnemo_mcp.config.settings", _settings_with_gdrive()),
            patch("httpx.post", post_mock),
            patch.object(cs, "_schedule_spawn_cleanup", cleanup),
        ):
            result = cs.save_credentials({"JINA_AI_API_KEY": "abc"}, context=None)

        assert result is None
        cleanup.assert_called_once()

    def test_device_code_post_exception_is_nonfatal(
        self, reset_module_state, monkeypatch
    ):
        cs = reset_module_state
        monkeypatch.delenv("PUBLIC_URL", raising=False)

        post_mock = MagicMock(side_effect=RuntimeError("network down"))
        cleanup = MagicMock()

        with (
            patch("mcp_core.storage.per_plugin_store.PerPluginStore.save", MagicMock()),
            patch("mnemo_mcp.relay_setup.apply_config", MagicMock()),
            patch("mnemo_mcp.config.settings", _settings_with_gdrive()),
            patch("httpx.post", post_mock),
            patch.object(cs, "_schedule_spawn_cleanup", cleanup),
        ):
            # Must not raise; cleanup still runs after the swallowed exception.
            result = cs.save_credentials({"JINA_AI_API_KEY": "abc"}, context=None)

        assert result is None
        cleanup.assert_called_once()
