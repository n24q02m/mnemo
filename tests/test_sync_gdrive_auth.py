"""Tests for sync.py -- Google Drive OAuth Device Code flow and auto-sync loop.

Targets: setup_google_auth success/failure paths, _auto_sync_loop error
during loop iteration, _load_token/_save_token wrappers, _refresh_token
exception path, sync_full merge success, setup_google_auth no_client_secret.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from mnemo_mcp.sync import (
    _auto_sync_loop,
    _load_token,
    _save_token,
    setup_google_auth,
    sync_full,
)

# ---------------------------------------------------------------------------
# _load_token / _save_token wrappers
# ---------------------------------------------------------------------------


class TestTokenWrappers:
    def test_load_token_delegates_to_store(self):
        """_load_token calls token_store.load_token with 'google_drive'."""
        with patch(
            "mnemo_mcp.token_store.load_token", return_value={"access_token": "abc"}
        ) as mock:
            result = _load_token()
            assert result == {"access_token": "abc"}
            mock.assert_called_once_with("google_drive")

    def test_save_token_delegates_to_store(self):
        """_save_token calls token_store.save_token with 'google_drive'."""
        token = {"access_token": "xyz"}
        with patch("mnemo_mcp.token_store.save_token") as mock:
            _save_token(token)
            mock.assert_called_once_with("google_drive", token)


# ---------------------------------------------------------------------------
# _refresh_token exception path
# ---------------------------------------------------------------------------


class TestRefreshTokenException:
    async def test_refresh_token_network_exception(self):
        """Returns None when httpx raises during refresh."""
        from mnemo_mcp.sync import _refresh_token

        token = {
            "access_token": "old",
            "refresh_token": "refresh123",
            "client_id": "client123",
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await _refresh_token(token)

        assert result is None


# ---------------------------------------------------------------------------
# setup_google_auth
# ---------------------------------------------------------------------------


class TestSetupGoogleAuthFull:
    async def test_no_client_secret(self):
        """Returns False when client_secret is not set."""
        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = ""
            result = await setup_google_auth()
        assert result is False

    async def test_success_flow_via_relay(self):
        """Full success flow: device code request, relay message, token poll success."""
        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev_code_123",
            "user_code": "ABCD-1234",
            "verification_url": "https://www.google.com/device",
            "interval": 1,
            "expires_in": 10,
        }

        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "test_new_access_token",
            "refresh_token": "refresh_new",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        # Relay message response
        relay_response = MagicMock()
        relay_response.status_code = 200

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("mnemo_mcp.sync._save_token") as mock_save,
            patch("mnemo_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret123"

            mock_client = AsyncMock()
            # First call: device code request
            # Second call: relay message post
            # Third call: token poll
            mock_client.post.side_effect = [
                device_response,  # device code
                relay_response,  # relay message
                token_response,  # token poll
            ]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await setup_google_auth(
                relay_url="https://relay.example.com",
                session_id="sess-123",
            )

        assert result is True
        mock_save.assert_called_once()
        saved_token = mock_save.call_args[0][0]
        assert saved_token["access_token"] == "test_new_access_token"

    async def test_success_flow_no_relay(self):
        """Success flow without relay (prints to stderr)."""
        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev_code_456",
            "user_code": "EFGH-5678",
            "verification_url": "https://www.google.com/device",
            "interval": 1,
            "expires_in": 10,
        }

        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "test_no_relay_token",
            "refresh_token": "refresh_456",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("mnemo_mcp.sync._save_token"),
            patch("mnemo_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret123"

            mock_client = AsyncMock()
            mock_client.post.side_effect = [device_response, token_response]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await setup_google_auth()

        assert result is True

    async def test_authorization_pending_then_success(self):
        """Handles authorization_pending then eventually succeeds."""
        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev_code",
            "user_code": "CODE",
            "verification_url": "https://google.com/device",
            "interval": 1,
            "expires_in": 30,
        }

        pending_response = MagicMock()
        pending_response.status_code = 428
        pending_response.json.return_value = {"error": "authorization_pending"}

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "access_token": "test_pending_then_success",
            "expires_in": 3600,
        }

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("mnemo_mcp.sync._save_token"),
            patch("mnemo_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret123"

            mock_client = AsyncMock()
            mock_client.post.side_effect = [
                device_response,
                pending_response,
                success_response,
            ]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await setup_google_auth()

        assert result is True

    async def test_slow_down_increases_interval(self):
        """Handles slow_down by increasing interval then succeeds."""
        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev_code",
            "user_code": "CODE",
            "verification_url": "https://google.com/device",
            "interval": 1,
            "expires_in": 30,
        }

        slow_down_response = MagicMock()
        slow_down_response.status_code = 428
        slow_down_response.json.return_value = {"error": "slow_down"}

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "access_token": "test_slowed_token",
            "expires_in": 3600,
        }

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("mnemo_mcp.sync._save_token"),
            patch("mnemo_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret123"

            mock_client = AsyncMock()
            mock_client.post.side_effect = [
                device_response,
                slow_down_response,
                success_response,
            ]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await setup_google_auth()

        assert result is True

    async def test_access_denied(self):
        """Returns False when user denies access."""
        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev_code",
            "user_code": "CODE",
            "verification_url": "https://google.com/device",
            "interval": 1,
            "expires_in": 30,
        }

        denied_response = MagicMock()
        denied_response.status_code = 403
        denied_response.json.return_value = {"error": "access_denied"}

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("mnemo_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret123"

            mock_client = AsyncMock()
            mock_client.post.side_effect = [device_response, denied_response]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await setup_google_auth()

        assert result is False

    async def test_expired_token_error(self):
        """Returns False on expired_token error."""
        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev_code",
            "user_code": "CODE",
            "verification_url": "https://google.com/device",
            "interval": 1,
            "expires_in": 30,
        }

        expired_response = MagicMock()
        expired_response.status_code = 400
        expired_response.json.return_value = {"error": "expired_token"}

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("mnemo_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret123"

            mock_client = AsyncMock()
            mock_client.post.side_effect = [device_response, expired_response]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await setup_google_auth()

        assert result is False

    async def test_unexpected_error_during_poll(self):
        """Returns False on unexpected error during token poll."""
        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev_code",
            "user_code": "CODE",
            "verification_url": "https://google.com/device",
            "interval": 1,
            "expires_in": 30,
        }

        unexpected_response = MagicMock()
        unexpected_response.status_code = 500
        unexpected_response.json.return_value = {"error": "server_error"}

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("mnemo_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret123"

            mock_client = AsyncMock()
            mock_client.post.side_effect = [device_response, unexpected_response]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await setup_google_auth()

        assert result is False

    async def test_token_poll_exception(self):
        """Returns False when token poll raises an exception."""
        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev_code",
            "user_code": "CODE",
            "verification_url": "https://google.com/device",
            "interval": 1,
            "expires_in": 30,
        }

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("mnemo_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret123"

            mock_client = AsyncMock()
            # First call succeeds (device code), second raises
            mock_client.post.side_effect = [
                device_response,
                Exception("Connection reset"),
            ]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await setup_google_auth()

        assert result is False

    async def test_relay_message_send_fails_silently(self):
        """Relay message failure doesn't prevent auth flow."""
        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev_code",
            "user_code": "CODE",
            "verification_url": "https://google.com/device",
            "interval": 1,
            "expires_in": 10,
        }

        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "test_relay_fail_token",
            "expires_in": 3600,
        }

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("mnemo_mcp.sync._save_token"),
            patch("mnemo_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret123"

            mock_client = AsyncMock()
            mock_client.post.side_effect = [
                device_response,
                Exception("Relay down"),  # relay message fails
                token_response,  # token poll succeeds
            ]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await setup_google_auth(
                relay_url="https://relay.test",
                session_id="sess-fail",
            )

        assert result is True

    async def test_device_code_expired(self):
        """Returns False when device code expires (loop times out)."""
        device_response = MagicMock()
        device_response.status_code = 200
        device_response.json.return_value = {
            "device_code": "dev_code",
            "user_code": "CODE",
            "verification_url": "https://google.com/device",
            "interval": 1,
            "expires_in": 1,  # Very short expiry
        }

        pending_response = MagicMock()
        pending_response.status_code = 428
        pending_response.json.return_value = {"error": "authorization_pending"}

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("mnemo_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
            patch("mnemo_mcp.sync.time") as mock_time,
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_settings.google_drive_client_secret = "secret123"

            mock_client = AsyncMock()
            mock_client.post.side_effect = [device_response, pending_response]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            # First time.time() is for deadline, second is for loop check (past deadline)
            mock_time.time.side_effect = [1000, 1000, 1002]

            result = await setup_google_auth()

        assert result is False


# ---------------------------------------------------------------------------
# _auto_sync_loop error during loop iteration
# ---------------------------------------------------------------------------


class TestAutoSyncLoopError:
    async def test_loop_error_continues_then_cancels(self):
        """Loop handles non-fatal error in loop body and continues."""
        call_count = 0

        async def mock_sync_full(db):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"status": "ok"}  # Initial sync OK
            if call_count == 2:
                raise RuntimeError("Temporary error")
            raise asyncio.CancelledError

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync.sync_full", side_effect=mock_sync_full),
            patch("mnemo_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.sync_interval = 60
            await _auto_sync_loop(MagicMock())
            assert call_count >= 3


# ---------------------------------------------------------------------------
# sync_full with successful merge
# ---------------------------------------------------------------------------


class TestSyncFullMergeSuccess:
    async def test_full_sync_pull_merge_push(self, tmp_db, tmp_path):
        """Full sync: pull remote -> merge -> push."""
        from pathlib import Path

        temp_db = tmp_path / "sync_temp" / "remote_db.sqlite"
        temp_db.parent.mkdir(parents=True)
        temp_db.write_bytes(b"fake db")

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync._has_token_available", return_value=True),
            patch(
                "mnemo_mcp.sync._get_valid_token",
                new_callable=AsyncMock,
                return_value={"access_token": "valid"},
            ),
            patch(
                "mnemo_mcp.sync.sync_pull",
                new_callable=AsyncMock,
                return_value=temp_db,
            ),
            patch(
                "mnemo_mcp.sync.sync_push",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "mnemo_mcp.sync.asyncio.to_thread",
                new_callable=AsyncMock,
                return_value={"imported": 5, "skipped": 2},
            ),
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = "client123"
            mock_settings.get_db_path.return_value = Path("/fake/db.sqlite")
            mock_settings.sync_folder = "test-folder"

            result = await sync_full(tmp_db)

        assert result["status"] == "ok"
        assert result["pull"]["imported"] == 5
        assert result["push"]["success"] is True
