"""Additional tests for mnemo_mcp.sync -- covering Google Drive sync operations.

Targets: sync_push, sync_pull, sync_full (pull+merge+push flow),
_auto_sync_loop, stop_auto_sync, setup_sync, setup_google_auth,
_find_or_create_folder (error paths), _upload_file (multipart).
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import mnemo_mcp.sync
from mnemo_mcp.sync import (
    _auto_sync_loop,
    _find_or_create_folder,
    stop_auto_sync,
    sync_full,
    sync_pull,
    sync_push,
)

# ---------------------------------------------------------------------------
# sync_push
# ---------------------------------------------------------------------------


class TestSyncPushCoverage:
    async def test_folder_creation_fails(self, tmp_path):
        """Push fails when folder creation fails."""
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"data")

        with (
            patch(
                "mnemo_mcp.sync._get_valid_token",
                new_callable=AsyncMock,
                return_value={"access_token": "valid"},
            ),
            patch(
                "mnemo_mcp.sync._find_or_create_folder",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await sync_push(db_path, "folder")
        assert result is False

    async def test_upload_fails(self, tmp_path):
        """Push fails when upload fails."""
        db_path = tmp_path / "test.db"
        db_path.write_bytes(b"data")

        with (
            patch(
                "mnemo_mcp.sync._get_valid_token",
                new_callable=AsyncMock,
                return_value={"access_token": "valid"},
            ),
            patch(
                "mnemo_mcp.sync._find_or_create_folder",
                new_callable=AsyncMock,
                return_value="folder_id",
            ),
            patch(
                "mnemo_mcp.sync._find_file_in_folder",
                new_callable=AsyncMock,
                return_value={"id": "existing_id"},
            ),
            patch(
                "mnemo_mcp.sync._upload_file",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await sync_push(db_path, "folder")
        assert result is False


# ---------------------------------------------------------------------------
# sync_pull
# ---------------------------------------------------------------------------


class TestSyncPullCoverage:
    async def test_folder_not_found(self, tmp_path):
        """Pull returns None when folder creation fails."""
        db_path = tmp_path / "test.db"

        with (
            patch(
                "mnemo_mcp.sync._get_valid_token",
                new_callable=AsyncMock,
                return_value={"access_token": "valid"},
            ),
            patch(
                "mnemo_mcp.sync._find_or_create_folder",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await sync_pull(db_path, "folder")
        assert result is None

    async def test_download_fails(self, tmp_path):
        """Pull returns None when download fails."""
        db_path = tmp_path / "test.db"

        with (
            patch(
                "mnemo_mcp.sync._get_valid_token",
                new_callable=AsyncMock,
                return_value={"access_token": "valid"},
            ),
            patch(
                "mnemo_mcp.sync._find_or_create_folder",
                new_callable=AsyncMock,
                return_value="folder_id",
            ),
            patch(
                "mnemo_mcp.sync._find_file_in_folder",
                new_callable=AsyncMock,
                return_value={"id": "file_id"},
            ),
            patch(
                "mnemo_mcp.sync._download_file",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await sync_pull(db_path, "folder")
        assert result is None

    async def test_download_success(self, tmp_path):
        """Pull returns path when download succeeds."""
        db_path = tmp_path / "test.db"

        # Pre-create the expected temp file
        sync_temp = db_path.parent / "sync_temp"
        sync_temp.mkdir(parents=True, exist_ok=True)
        temp_db = sync_temp / f"remote_{db_path.name}"
        temp_db.write_bytes(b"remote data")

        with (
            patch(
                "mnemo_mcp.sync._get_valid_token",
                new_callable=AsyncMock,
                return_value={"access_token": "valid"},
            ),
            patch(
                "mnemo_mcp.sync._find_or_create_folder",
                new_callable=AsyncMock,
                return_value="folder_id",
            ),
            patch(
                "mnemo_mcp.sync._find_file_in_folder",
                new_callable=AsyncMock,
                return_value={"id": "file_id"},
            ),
            patch(
                "mnemo_mcp.sync._download_file",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await sync_pull(db_path, "folder")
        assert result is not None
        assert result.name == f"remote_{db_path.name}"


# ---------------------------------------------------------------------------
# sync_full (pull+merge+push flow)
# ---------------------------------------------------------------------------


class TestSyncFullCoverage:
    async def test_full_sync_pull_no_remote_db(self, tmp_db):
        """Full sync handles case where no remote DB exists."""
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
                return_value=None,
            ),
            patch(
                "mnemo_mcp.sync.sync_push",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = "client123"
            mock_settings.get_db_path.return_value = Path("/fake/db.sqlite")
            mock_settings.sync_folder = "test-folder"

            result = await sync_full(tmp_db)

        assert result["status"] == "ok"
        assert result["pull"]["imported"] == 0
        assert result["push"]["success"] is True

    async def test_full_sync_merge_exception(self, tmp_db, tmp_path):
        """Full sync handles merge errors gracefully."""
        temp_db = tmp_path / "sync_temp" / "remote_test.db"
        temp_db.parent.mkdir(parents=True)
        temp_db.write_bytes(b"invalid db content")

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
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = "client123"
            mock_settings.get_db_path.return_value = Path("/fake/db.sqlite")
            mock_settings.sync_folder = "test-folder"

            # The merge will fail because temp_db contains invalid data
            # We mock the thread to raise
            with patch(
                "mnemo_mcp.sync.asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=Exception("merge error"),
            ):
                result = await sync_full(tmp_db)

        assert result["status"] == "ok"
        assert "error" in result["pull"]


# ---------------------------------------------------------------------------
# _auto_sync_loop
# ---------------------------------------------------------------------------


class TestAutoSyncLoopCoverage:
    async def test_loop_zero_interval(self):
        """Loop exits immediately when interval is <= 0."""
        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.sync_interval = 0
            await _auto_sync_loop(MagicMock())

    async def test_loop_cancelled(self):
        """Loop handles cancellation gracefully."""
        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch(
                "mnemo_mcp.sync.sync_full",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError,
            ),
        ):
            mock_settings.sync_interval = 60
            await _auto_sync_loop(MagicMock())

    async def test_loop_initial_error_continues(self):
        """Loop continues after initial sync error."""
        call_count = 0

        async def mock_sync_full(db):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("initial error")
            raise asyncio.CancelledError

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync.sync_full", side_effect=mock_sync_full),
            patch("mnemo_mcp.sync.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.sync_interval = 60
            await _auto_sync_loop(MagicMock())
            assert call_count >= 2


# ---------------------------------------------------------------------------
# stop_auto_sync
# ---------------------------------------------------------------------------


class TestStopAutoSync:
    def test_stops_running_task(self):
        """Cancels a running sync task."""
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mnemo_mcp.sync._sync_task = mock_task

        stop_auto_sync()

        mock_task.cancel.assert_called_once()
        assert mnemo_mcp.sync._sync_task is None

    def test_noop_when_no_task(self):
        """No error when task is None."""
        mnemo_mcp.sync._sync_task = None
        stop_auto_sync()  # Should not raise

    def test_noop_when_task_done(self):
        """No cancellation when task is already done."""
        mock_task = MagicMock()
        mock_task.done.return_value = True
        mnemo_mcp.sync._sync_task = mock_task

        stop_auto_sync()
        mock_task.cancel.assert_not_called()


# ---------------------------------------------------------------------------
# _find_or_create_folder error paths
# ---------------------------------------------------------------------------


class TestFindOrCreateFolderCoverage:
    async def test_create_folder_fails(self):
        """Returns None when folder creation request fails."""
        token = {"access_token": "test"}
        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.json.return_value = {"files": []}

        create_resp = MagicMock()
        create_resp.status_code = 500
        create_resp.text = "Server error"

        with (
            patch(
                "mnemo_mcp.sync._drive_request",
                new_callable=AsyncMock,
                side_effect=[search_resp, search_resp, search_resp, create_resp],
            ),
            patch("asyncio.sleep", return_value=None),
        ):
            result = await _find_or_create_folder(token, "folder")
        assert result is None


# ---------------------------------------------------------------------------
# setup_google_auth
# ---------------------------------------------------------------------------


class TestSetupGoogleAuthCoverage:
    async def test_no_client_id(self):
        """Returns False when client_id is not set."""
        from mnemo_mcp.sync import setup_google_auth

        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.google_drive_client_id = ""
            result = await setup_google_auth()
        assert result is False

    async def test_device_code_request_fails(self):
        """Returns False when device code request fails."""
        from mnemo_mcp.sync import setup_google_auth

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await setup_google_auth()
        assert result is False

    async def test_device_code_request_exception(self):
        """Returns False when device code request raises exception."""
        from mnemo_mcp.sync import setup_google_auth

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.google_drive_client_id = "client123"
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("network error")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await setup_google_auth()
        assert result is False
