"""Tests for sync.py folder ID caching and _find_or_create_folder cache paths.

Covers: _load_folder_id, _save_folder_id, _verify_folder_exists,
_find_or_create_folder memory cache hit, disk cache hit, disk cache invalid,
sync_full merge success path with actual data.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import mnemo_mcp.sync
from mnemo_mcp.sync import (
    _find_or_create_folder,
    _load_folder_id,
    _save_folder_id,
    _verify_folder_exists,
    sync_full,
)

# ---------------------------------------------------------------------------
# _load_folder_id
# ---------------------------------------------------------------------------


class TestLoadFolderId:
    def test_returns_none_when_file_missing(self, tmp_path):
        """Returns None when sync_folder_ids.json doesn't exist."""
        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.get_data_dir.return_value = tmp_path
            result = _load_folder_id("test-folder")
        assert result is None

    def test_returns_id_when_present(self, tmp_path):
        """Returns folder ID from saved file."""
        path = tmp_path / "sync_folder_ids.json"
        path.write_text(json.dumps({"my-folder": "folder-123"}), encoding="utf-8")

        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.get_data_dir.return_value = tmp_path
            result = _load_folder_id("my-folder")

        assert result == "folder-123"

    def test_returns_none_for_unknown_folder(self, tmp_path):
        """Returns None when folder name not in saved file."""
        path = tmp_path / "sync_folder_ids.json"
        path.write_text(json.dumps({"other-folder": "id-456"}), encoding="utf-8")

        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.get_data_dir.return_value = tmp_path
            result = _load_folder_id("my-folder")

        assert result is None

    def test_handles_json_decode_error(self, tmp_path):
        """Returns None when file contains invalid JSON."""
        path = tmp_path / "sync_folder_ids.json"
        path.write_text("not-valid-json", encoding="utf-8")

        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.get_data_dir.return_value = tmp_path
            result = _load_folder_id("my-folder")

        assert result is None


# ---------------------------------------------------------------------------
# _save_folder_id
# ---------------------------------------------------------------------------


class TestSaveFolderId:
    def test_creates_new_file(self, tmp_path):
        """Creates sync_folder_ids.json with folder ID."""
        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.get_data_dir.return_value = tmp_path
            _save_folder_id("my-folder", "folder-123")

        path = tmp_path / "sync_folder_ids.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["my-folder"] == "folder-123"

    def test_appends_to_existing_file(self, tmp_path):
        """Adds new folder ID to existing file."""
        path = tmp_path / "sync_folder_ids.json"
        path.write_text(json.dumps({"existing": "id-1"}), encoding="utf-8")

        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.get_data_dir.return_value = tmp_path
            _save_folder_id("new-folder", "id-2")

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["existing"] == "id-1"
        assert data["new-folder"] == "id-2"

    def test_handles_corrupt_existing_file(self, tmp_path):
        """Overwrites corrupt existing file."""
        path = tmp_path / "sync_folder_ids.json"
        path.write_text("corrupt-json", encoding="utf-8")

        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.get_data_dir.return_value = tmp_path
            _save_folder_id("folder", "id-1")

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["folder"] == "id-1"


# ---------------------------------------------------------------------------
# _verify_folder_exists
# ---------------------------------------------------------------------------


class TestVerifyFolderExists:
    async def test_folder_exists_not_trashed(self):
        """Returns True when folder exists and is not trashed."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "fid", "trashed": False}

        with patch(
            "mnemo_mcp.sync._drive_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await _verify_folder_exists({"access_token": "t"}, "fid")

        assert result is True

    async def test_folder_trashed(self):
        """Returns False when folder is trashed."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "fid", "trashed": True}

        with patch(
            "mnemo_mcp.sync._drive_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await _verify_folder_exists({"access_token": "t"}, "fid")

        assert result is False

    async def test_folder_not_found(self):
        """Returns False when API returns non-200."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch(
            "mnemo_mcp.sync._drive_request",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await _verify_folder_exists({"access_token": "t"}, "fid")

        assert result is False


# ---------------------------------------------------------------------------
# _find_or_create_folder cache paths
# ---------------------------------------------------------------------------


class TestFindOrCreateFolderCache:
    async def test_memory_cache_hit(self):
        """Returns folder ID from memory cache when valid."""
        # Pre-populate memory cache
        old_cache = mnemo_mcp.sync._folder_id_cache.copy()
        mnemo_mcp.sync._folder_id_cache["test-folder"] = "cached-id"

        try:
            mock_verify_resp = MagicMock()
            mock_verify_resp.status_code = 200
            mock_verify_resp.json.return_value = {"id": "cached-id", "trashed": False}

            with patch(
                "mnemo_mcp.sync._drive_request",
                new_callable=AsyncMock,
                return_value=mock_verify_resp,
            ):
                result = await _find_or_create_folder(
                    {"access_token": "t"}, "test-folder"
                )

            assert result == "cached-id"
        finally:
            mnemo_mcp.sync._folder_id_cache.clear()
            mnemo_mcp.sync._folder_id_cache.update(old_cache)

    async def test_memory_cache_invalid_falls_through(self):
        """When memory cache entry is trashed, falls through to disk cache."""
        old_cache = mnemo_mcp.sync._folder_id_cache.copy()
        mnemo_mcp.sync._folder_id_cache["test-folder"] = "stale-id"

        try:
            verify_stale = MagicMock()
            verify_stale.status_code = 404

            search_resp = MagicMock()
            search_resp.status_code = 200
            search_resp.json.return_value = {"files": [{"id": "found-id"}]}

            with (
                patch(
                    "mnemo_mcp.sync._drive_request",
                    new_callable=AsyncMock,
                    side_effect=[verify_stale, search_resp],
                ),
                patch("mnemo_mcp.sync._load_folder_id", return_value=None),
                patch("mnemo_mcp.sync._save_folder_id"),
            ):
                result = await _find_or_create_folder(
                    {"access_token": "t"}, "test-folder"
                )

            assert result == "found-id"
        finally:
            mnemo_mcp.sync._folder_id_cache.clear()
            mnemo_mcp.sync._folder_id_cache.update(old_cache)

    async def test_disk_cache_hit(self):
        """Returns folder ID from disk cache when valid."""
        old_cache = mnemo_mcp.sync._folder_id_cache.copy()
        mnemo_mcp.sync._folder_id_cache.clear()

        try:
            verify_resp = MagicMock()
            verify_resp.status_code = 200
            verify_resp.json.return_value = {"id": "disk-id", "trashed": False}

            with (
                patch("mnemo_mcp.sync._load_folder_id", return_value="disk-id"),
                patch(
                    "mnemo_mcp.sync._drive_request",
                    new_callable=AsyncMock,
                    return_value=verify_resp,
                ),
            ):
                result = await _find_or_create_folder(
                    {"access_token": "t"}, "test-folder"
                )

            assert result == "disk-id"
            # Should be cached in memory now
            assert mnemo_mcp.sync._folder_id_cache.get("test-folder") == "disk-id"
        finally:
            mnemo_mcp.sync._folder_id_cache.clear()
            mnemo_mcp.sync._folder_id_cache.update(old_cache)

    async def test_search_finds_folder(self):
        """Search API finds existing folder."""
        old_cache = mnemo_mcp.sync._folder_id_cache.copy()
        mnemo_mcp.sync._folder_id_cache.clear()

        try:
            search_resp = MagicMock()
            search_resp.status_code = 200
            search_resp.json.return_value = {"files": [{"id": "search-id"}]}

            with (
                patch("mnemo_mcp.sync._load_folder_id", return_value=None),
                patch(
                    "mnemo_mcp.sync._drive_request",
                    new_callable=AsyncMock,
                    return_value=search_resp,
                ),
                patch("mnemo_mcp.sync._save_folder_id") as mock_save,
            ):
                result = await _find_or_create_folder(
                    {"access_token": "t"}, "test-folder"
                )

            assert result == "search-id"
            mock_save.assert_called_once_with("test-folder", "search-id")
        finally:
            mnemo_mcp.sync._folder_id_cache.clear()
            mnemo_mcp.sync._folder_id_cache.update(old_cache)

    async def test_create_new_folder(self):
        """Creates new folder when not found anywhere."""
        old_cache = mnemo_mcp.sync._folder_id_cache.copy()
        mnemo_mcp.sync._folder_id_cache.clear()

        try:
            search_resp = MagicMock()
            search_resp.status_code = 200
            search_resp.json.return_value = {"files": []}

            create_resp = MagicMock()
            create_resp.status_code = 200
            create_resp.json.return_value = {"id": "new-id"}

            with (
                patch("mnemo_mcp.sync._load_folder_id", return_value=None),
                patch(
                    "mnemo_mcp.sync._drive_request",
                    new_callable=AsyncMock,
                    side_effect=[search_resp, create_resp],
                ),
                patch("mnemo_mcp.sync._save_folder_id") as mock_save,
            ):
                result = await _find_or_create_folder(
                    {"access_token": "t"}, "test-folder"
                )

            assert result == "new-id"
            mock_save.assert_called_once_with("test-folder", "new-id")
        finally:
            mnemo_mcp.sync._folder_id_cache.clear()
            mnemo_mcp.sync._folder_id_cache.update(old_cache)


# ---------------------------------------------------------------------------
# sync_full merge success path
# ---------------------------------------------------------------------------


class TestSyncFullMergeSuccess:
    async def test_merge_success_with_imports(self, tmp_db):
        """Full sync with actual data imports from remote DB."""
        from mnemo_mcp.db import MemoryDB

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync._has_token_available", return_value=True),
            patch(
                "mnemo_mcp.sync._get_valid_token",
                new_callable=AsyncMock,
                return_value={"access_token": "valid"},
            ),
            patch(
                "mnemo_mcp.sync.sync_push",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = "client123"
            mock_settings.sync_folder = "test-folder"

            # Create a real remote DB with data
            import tempfile

            with tempfile.TemporaryDirectory() as td:
                remote_path = Path(td) / "sync_temp" / "remote_test.db"
                remote_path.parent.mkdir(parents=True)
                remote_db = MemoryDB(remote_path, embedding_dims=0)
                remote_db.add("Remote memory 1", category="test", tags=["remote"])
                remote_db.close()

                mock_settings.get_db_path.return_value = Path(td) / "local.db"

                with patch(
                    "mnemo_mcp.sync.sync_pull",
                    new_callable=AsyncMock,
                    return_value=remote_path,
                ):
                    result = await sync_full(tmp_db)

        assert result["status"] == "ok"
        assert result["pull"]["imported"] >= 1
        assert result["push"]["success"] is True

    async def test_merge_empty_remote_jsonl(self, tmp_db):
        """Full sync with empty remote JSONL data."""
        from mnemo_mcp.db import MemoryDB

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync._has_token_available", return_value=True),
            patch(
                "mnemo_mcp.sync._get_valid_token",
                new_callable=AsyncMock,
                return_value={"access_token": "valid"},
            ),
            patch(
                "mnemo_mcp.sync.sync_push",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = "client123"
            mock_settings.sync_folder = "test-folder"

            import tempfile

            with tempfile.TemporaryDirectory() as td:
                remote_path = Path(td) / "sync_temp" / "remote_test.db"
                remote_path.parent.mkdir(parents=True)
                # Create empty DB
                remote_db = MemoryDB(remote_path, embedding_dims=0)
                remote_db.close()

                mock_settings.get_db_path.return_value = Path(td) / "local.db"

                with patch(
                    "mnemo_mcp.sync.sync_pull",
                    new_callable=AsyncMock,
                    return_value=remote_path,
                ):
                    result = await sync_full(tmp_db)

        assert result["status"] == "ok"
        assert result["pull"]["imported"] == 0

    async def test_sync_disabled(self, tmp_db):
        """sync_full returns disabled when sync is off."""
        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.sync_enabled = False
            result = await sync_full(tmp_db)

        assert result["status"] == "disabled"

    async def test_no_client_id(self, tmp_db):
        """sync_full returns error when client ID is missing."""
        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.sync_enabled = True
            mock_settings.google_drive_client_id = ""
            result = await sync_full(tmp_db)

        assert result["status"] == "error"
        assert "GOOGLE_DRIVE_CLIENT_ID" in result["message"]

    async def test_no_token_available(self, tmp_db):
        """sync_full returns error when no token is available."""
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
        """sync_full returns error when token refresh fails."""
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
        assert "refresh" in result["message"].lower()
