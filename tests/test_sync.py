"""Tests for mnemo_mcp.sync -- Google Drive sync operations."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import mnemo_mcp.sync
from mnemo_mcp.sync import (
    _download_file,
    _find_file_in_folder,
    _find_or_create_folder,
    _has_token_available,
    _upload_file,
    check_health,
    setup_sync,
    start_auto_sync,
    sync_full,
    sync_pull,
    sync_push,
)


class TestTokenManagement:
    def test_has_token_false_when_no_token(self):
        with patch("mnemo_mcp.sync._load_token", return_value=None):
            assert _has_token_available() is False

    def test_has_token_true_when_token_exists(self):
        with patch(
            "mnemo_mcp.sync._load_token",
            return_value={"access_token": "ya29.abc"},
        ):
            assert _has_token_available() is True

    async def test_refresh_token_success(self):
        from mnemo_mcp.sync import _refresh_token

        token = {
            "access_token": "old",
            "refresh_token": "refresh123",
            "client_id": "client123",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch("mnemo_mcp.sync._save_token") as mock_save,
            patch("mnemo_mcp.sync.settings") as mock_settings,
        ):
            mock_settings.google_drive_client_secret = "secret123"
            mock_settings.google_drive_client_id = "client123"
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await _refresh_token(token)

        assert result is not None
        assert result["access_token"] == "new_access"
        assert result["refresh_token"] == "refresh123"
        mock_save.assert_called_once()

    async def test_refresh_token_failure(self):
        from mnemo_mcp.sync import _refresh_token

        token = {
            "access_token": "old",
            "refresh_token": "refresh123",
            "client_id": "client123",
        }

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "invalid_grant"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await _refresh_token(token)

        assert result is None

    async def test_refresh_token_missing_refresh_token(self):
        from mnemo_mcp.sync import _refresh_token

        token = {"access_token": "old", "client_id": "client123"}
        result = await _refresh_token(token)
        assert result is None

    async def test_get_valid_token_no_token(self):
        from mnemo_mcp.sync import _get_valid_token

        with patch("mnemo_mcp.sync._load_token", return_value=None):
            result = await _get_valid_token()
        assert result is None

    async def test_get_valid_token_not_expired(self):
        import time

        from mnemo_mcp.sync import _get_valid_token

        token = {
            "access_token": "valid",
            "expiry": time.time() + 3600,
        }
        with patch("mnemo_mcp.sync._load_token", return_value=token):
            result = await _get_valid_token()
        assert result == token

    async def test_get_valid_token_expired_refreshes(self):
        import time

        from mnemo_mcp.sync import _get_valid_token

        token = {
            "access_token": "expired",
            "refresh_token": "refresh123",
            "expiry": time.time() - 100,
        }
        refreshed = {"access_token": "new", "expiry": time.time() + 3600}
        with (
            patch("mnemo_mcp.sync._load_token", return_value=token),
            patch(
                "mnemo_mcp.sync._refresh_token",
                new_callable=AsyncMock,
                return_value=refreshed,
            ),
        ):
            result = await _get_valid_token()
        assert result == refreshed


class TestDriveHelpers:
    def setup_method(self):
        """Clear folder ID cache between tests."""
        import mnemo_mcp.sync as sync_mod

        sync_mod._folder_id_cache.clear()

    async def test_find_or_create_folder_found(self):
        token = {"access_token": "test"}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"files": [{"id": "folder123"}]}

        with (
            patch(
                "mnemo_mcp.sync._drive_request",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
            patch("mnemo_mcp.sync._load_folder_id", return_value=None),
            patch("mnemo_mcp.sync._save_folder_id"),
        ):
            result = await _find_or_create_folder(token, "test-folder")
        assert result == "folder123"

    async def test_find_or_create_folder_creates(self):
        token = {"access_token": "test"}
        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.json.return_value = {"files": []}

        create_resp = MagicMock()
        create_resp.status_code = 200
        create_resp.json.return_value = {"id": "new_folder"}

        with (
            patch(
                "mnemo_mcp.sync._drive_request",
                new_callable=AsyncMock,
                side_effect=[search_resp, search_resp, search_resp, create_resp],
            ),
            patch("mnemo_mcp.sync._load_folder_id", return_value=None),
            patch("mnemo_mcp.sync._save_folder_id"),
            patch("asyncio.sleep", return_value=None),
        ):
            result = await _find_or_create_folder(token, "new-folder")
        assert result == "new_folder"

    async def test_find_file_in_folder_found(self):
        token = {"access_token": "test"}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "files": [
                {"id": "file123", "name": "db.sqlite", "modifiedTime": "2026-01-01"}
            ]
        }

        with patch(
            "mnemo_mcp.sync._drive_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await _find_file_in_folder(token, "folder1", "db.sqlite")
        assert result is not None
        assert result["id"] == "file123"

    async def test_find_file_in_folder_not_found(self):
        token = {"access_token": "test"}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"files": []}

        with patch(
            "mnemo_mcp.sync._drive_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await _find_file_in_folder(token, "folder1", "db.sqlite")
        assert result is None

    async def test_upload_file_new(self, tmp_path):
        token = {"access_token": "test"}
        db_file = tmp_path / "test.db"
        db_file.write_bytes(b"test data")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "new_file"}

        with patch(
            "mnemo_mcp.sync._drive_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await _upload_file(token, db_file, "folder1")
        assert result is True

    async def test_upload_file_update(self, tmp_path):
        token = {"access_token": "test"}
        db_file = tmp_path / "test.db"
        db_file.write_bytes(b"updated data")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch(
            "mnemo_mcp.sync._drive_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await _upload_file(token, db_file, "folder1", "existing123")
        assert result is True

    async def test_upload_file_failure(self, tmp_path):
        token = {"access_token": "test"}
        db_file = tmp_path / "test.db"
        db_file.write_bytes(b"data")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch(
            "mnemo_mcp.sync._drive_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await _upload_file(token, db_file, "folder1")
        assert result is False

    async def test_download_file(self, tmp_path):
        token = {"access_token": "test"}
        dest = tmp_path / "downloaded.db"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"file contents"

        with patch(
            "mnemo_mcp.sync._drive_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await _download_file(token, "file123", dest)
        assert result is True
        assert dest.read_bytes() == b"file contents"

    async def test_download_file_failure(self, tmp_path):
        token = {"access_token": "test"}
        dest = tmp_path / "downloaded.db"

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        with patch(
            "mnemo_mcp.sync._drive_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await _download_file(token, "file123", dest)
        assert result is False


class TestSyncPush:
    async def test_no_token(self, tmp_path):
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"data")
        with patch(
            "mnemo_mcp.sync._get_valid_token",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await sync_push(db_path, "folder")
        assert result is False

    async def test_success(self, tmp_path):
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"data")
        token = {"access_token": "valid"}

        with (
            patch(
                "mnemo_mcp.sync._get_valid_token",
                new_callable=AsyncMock,
                return_value=token,
            ),
            patch(
                "mnemo_mcp.sync._find_or_create_folder",
                new_callable=AsyncMock,
                return_value="folder_id",
            ),
            patch(
                "mnemo_mcp.sync._find_file_in_folder",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "mnemo_mcp.sync._upload_file",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await sync_push(db_path, "folder")
        assert result is True


class TestSyncPull:
    async def test_no_token(self, tmp_path):
        db_path = tmp_path / "test.db"
        with patch(
            "mnemo_mcp.sync._get_valid_token",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await sync_pull(db_path, "folder")
        assert result is None

    async def test_no_remote_file(self, tmp_path):
        db_path = tmp_path / "test.db"
        token = {"access_token": "valid"}

        with (
            patch(
                "mnemo_mcp.sync._get_valid_token",
                new_callable=AsyncMock,
                return_value=token,
            ),
            patch(
                "mnemo_mcp.sync._find_or_create_folder",
                new_callable=AsyncMock,
                return_value="folder_id",
            ),
            patch(
                "mnemo_mcp.sync._find_file_in_folder",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await sync_pull(db_path, "folder")
        assert result is None


class TestSyncFull:
    async def test_disabled(self, tmp_db):
        """Sync returns disabled when not configured."""
        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.sync_enabled = False
            result = await sync_full(tmp_db)
            assert result["status"] == "disabled"

    async def test_no_client_id(self, tmp_db):
        """Sync errors when client ID is not set."""
        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = ""
            result = await sync_full(tmp_db)
            assert result["status"] == "error"
            assert "GOOGLE_DRIVE_CLIENT_ID" in result["message"]

    async def test_no_token(self, tmp_db):
        """Sync errors when no token is available."""
        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync._has_token_available", return_value=False),
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = "client123"
            result = await sync_full(tmp_db)
            assert result["status"] == "error"
            assert "token" in result["message"].lower()

    async def test_token_expired_refresh_failed(self, tmp_db):
        """Sync errors when token refresh fails."""
        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync._has_token_available", return_value=True),
            patch(
                "mnemo_mcp.sync._get_valid_token",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = "client123"
            result = await sync_full(tmp_db)
            assert result["status"] == "error"
            assert "expired" in result["message"].lower()


class TestCheckHealth:
    async def test_no_token(self):
        with patch(
            "mnemo_mcp.sync._get_valid_token",
            new_callable=AsyncMock,
            return_value=None,
        ):
            assert await check_health() is False

    async def test_success(self):
        token = {"access_token": "valid"}
        mock_response = MagicMock()
        mock_response.status_code = 200

        with (
            patch(
                "mnemo_mcp.sync._get_valid_token",
                new_callable=AsyncMock,
                return_value=token,
            ),
            patch(
                "mnemo_mcp.sync._drive_request",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
        ):
            assert await check_health() is True

    async def test_failure(self):
        token = {"access_token": "valid"}
        mock_response = MagicMock()
        mock_response.status_code = 403

        with (
            patch(
                "mnemo_mcp.sync._get_valid_token",
                new_callable=AsyncMock,
                return_value=token,
            ),
            patch(
                "mnemo_mcp.sync._drive_request",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
        ):
            assert await check_health() is False


class TestSetupSync:
    def test_no_client_id(self, capsys):
        """setup_sync exits when GOOGLE_DRIVE_CLIENT_ID is not set."""
        import pytest

        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.google_drive_client_id = ""
            with pytest.raises(SystemExit, match="1"):
                setup_sync()

    def test_success(self, capsys):
        """setup_sync prints success on successful auth."""
        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync.asyncio.run", return_value=True),
        ):
            mock_settings.google_drive_client_id = "client123"
            setup_sync()
            captured = capsys.readouterr()
            assert "SUCCESS" in captured.out
            assert "SYNC_ENABLED" in captured.out

    def test_failure(self, capsys):
        """setup_sync exits on auth failure."""
        import pytest

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync.asyncio.run", return_value=False),
        ):
            mock_settings.google_drive_client_id = "client123"
            with pytest.raises(SystemExit, match="1"):
                setup_sync()


class TestStartAutoSync:
    def teardown_method(self):
        """Ensure _sync_task is reset after each test."""
        if mnemo_mcp.sync._sync_task and not mnemo_mcp.sync._sync_task.done():
            mnemo_mcp.sync._sync_task.cancel()
        mnemo_mcp.sync._sync_task = None

    def test_sync_disabled(self, tmp_db):
        """Task is not started if sync is disabled."""
        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync.asyncio.create_task") as mock_create_task,
        ):
            mock_settings.sync_enabled = False
            start_auto_sync(tmp_db)
            mock_create_task.assert_not_called()

    def test_invalid_interval(self, tmp_db):
        """Task is not started if interval is <= 0."""
        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync.asyncio.create_task") as mock_create_task,
        ):
            mock_settings.sync_enabled = True
            mock_settings.sync_interval = 0
            start_auto_sync(tmp_db)
            mock_create_task.assert_not_called()

    def test_already_running(self, tmp_db):
        """Task is not started if already running."""
        # Simulate running task
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mnemo_mcp.sync._sync_task = mock_task

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync.asyncio.create_task") as mock_create_task,
        ):
            mock_settings.sync_enabled = True
            mock_settings.sync_interval = 60

            start_auto_sync(tmp_db)
            mock_create_task.assert_not_called()

    def test_starts_task(self, tmp_db):
        """Task is started correctly when conditions are met."""
        mnemo_mcp.sync._sync_task = None

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync.asyncio.create_task") as mock_create_task,
            patch("mnemo_mcp.sync._auto_sync_loop") as mock_loop,
        ):
            mock_settings.sync_enabled = True
            mock_settings.sync_interval = 60

            # Setup create_task to return a dummy task
            dummy_task = MagicMock()
            mock_create_task.return_value = dummy_task

            start_auto_sync(tmp_db)

            mock_create_task.assert_called_once()
            # Verify the global var was set
            assert mnemo_mcp.sync._sync_task == dummy_task
            mock_loop.assert_called_once_with(tmp_db)


class TestDriveRequest:
    async def test_authenticated_request(self):
        from mnemo_mcp.sync import _drive_request

        token = {"access_token": "test_token"}
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.request.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await _drive_request("GET", "https://example.com", token)

        assert result.status_code == 200
        # Verify auth header was set
        call_kwargs = mock_client.request.call_args
        assert "Authorization" in call_kwargs.kwargs.get(
            "headers", {}
        ) or "Authorization" in call_kwargs[1].get("headers", {})
