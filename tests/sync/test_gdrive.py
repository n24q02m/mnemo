from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import mnemo_mcp.sync.gdrive
from mnemo_mcp.sync.gdrive import (
    GDriveBackend,
    _download_file,
    _drive_request,
    _ensure_bundle_folder,
    _find_file_in_folder,
    _find_or_create_folder,
    _load_folder_id,
    _refresh_token,
    _save_folder_id,
    _upload_file,
    _verify_folder_exists,
    setup_sync,
    start_auto_sync,
    sync_full,
    sync_pull,
    sync_push,
)


@pytest.fixture
def fake_token():
    return {
        "access_token": "fake_access",
        "refresh_token": "fake_refresh",
        "expiry": 0,
        "client_id": "fake_client",
        "client_secret": "fake_secret",
    }


# --- Token management ---


async def test_refresh_token_success():
    token = {"refresh_token": "ref", "client_id": "cid", "client_secret": "sec"}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "new_acc", "expires_in": 3600}

    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp),
        patch("mnemo_mcp.sync.gdrive.settings") as mock_settings,
    ):
        mock_settings.google_drive_client_id = "cid"
        mock_settings.google_drive_client_secret = "sec"
        new_token = await _refresh_token(token)
        assert new_token is not None
        assert new_token["access_token"] == "new_acc"
        assert "expiry" in new_token


async def test_refresh_token_missing_params():
    # Trigger line 91
    token = {"refresh_token": ""}
    with patch("mnemo_mcp.sync.gdrive.settings") as mock_settings:
        mock_settings.google_drive_client_id = ""
        new_token = await _refresh_token(token)
        assert new_token is None


async def test_refresh_token_failure():
    token = {"refresh_token": "ref"}
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "invalid grant"

    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp),
        patch("mnemo_mcp.sync.gdrive.settings") as mock_settings,
    ):
        mock_settings.google_drive_client_id = "cid"
        mock_settings.google_drive_client_secret = "sec"
        new_token = await _refresh_token(token)
        assert new_token is None


async def test_refresh_token_exception():
    token = {"refresh_token": "ref"}
    with (
        patch("httpx.AsyncClient.post", side_effect=Exception("net error")),
        patch("mnemo_mcp.sync.gdrive.settings") as mock_settings,
    ):
        mock_settings.google_drive_client_id = "cid"
        mock_settings.google_drive_client_secret = "sec"
        new_token = await _refresh_token(token)
        assert new_token is None


async def test_get_valid_token_expired():
    token = {"access_token": "old", "expiry": 0}
    with (
        patch(
            "mnemo_mcp.sync.gdrive._load_token",
            new_callable=AsyncMock,
            return_value=token,
        ),
        patch(
            "mnemo_mcp.sync.gdrive._refresh_token",
            new_callable=AsyncMock,
            return_value={"access_token": "new"},
        ),
        patch("mnemo_mcp.sync.gdrive._save_token", new_callable=AsyncMock),
    ):
        from mnemo_mcp.sync.gdrive import _get_valid_token

        valid = await _get_valid_token()
        assert valid is not None
        assert valid["access_token"] == "new"


async def test_get_valid_token_not_expired():
    token = {"access_token": "live", "expiry": time.time() + 1000}
    with patch(
        "mnemo_mcp.sync.gdrive._load_token", new_callable=AsyncMock, return_value=token
    ):
        from mnemo_mcp.sync.gdrive import _get_valid_token

        valid = await _get_valid_token()
        assert valid is not None
        assert valid["access_token"] == "live"


async def test_get_valid_token_none():
    with patch(
        "mnemo_mcp.sync.gdrive._load_token", new_callable=AsyncMock, return_value=None
    ):
        from mnemo_mcp.sync.gdrive import _get_valid_token

        valid = await _get_valid_token()
        assert valid is None


# --- _drive_request ---


async def test_drive_request_direct():
    token = {"access_token": "abc"}
    resp200 = MagicMock()
    resp200.status_code = 200

    mock_client = AsyncMock()
    mock_client.request.return_value = resp200
    mock_client.__aenter__.return_value = mock_client

    with patch("httpx.AsyncClient", return_value=mock_client):
        resp = await _drive_request("GET", "https://api", token)
        assert resp.status_code == 200


# --- Folder caching ---


async def test_folder_id_disk_cache(tmp_path):
    with patch("mnemo_mcp.sync.gdrive.settings") as mock_settings:
        mock_settings.get_data_dir.return_value = tmp_path
        await _save_folder_id("test", "id123")
        loaded = await _load_folder_id("test")
        assert loaded == "id123"

        # Test corruption
        path = tmp_path / "sync_folder_ids.json"
        path.write_text("invalid json")
        assert await _load_folder_id("test") is None

        await _save_folder_id("test2", "id456")
        assert await _load_folder_id("test2") == "id456"


# --- _verify_folder_exists ---


async def test_verify_folder_exists_ok():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "123", "trashed": False}
    with patch(
        "mnemo_mcp.sync.gdrive._drive_request",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        assert await _verify_folder_exists({}, "123") is True


async def test_verify_folder_exists_trashed():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "123", "trashed": True}
    with patch(
        "mnemo_mcp.sync.gdrive._drive_request",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        assert await _verify_folder_exists({}, "123") is False


async def test_verify_folder_exists_404():
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch(
        "mnemo_mcp.sync.gdrive._drive_request",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        assert await _verify_folder_exists({}, "123") is False


# --- _find_or_create_folder ---


async def test_find_or_create_folder_mem_cache():
    mnemo_mcp.sync.gdrive._folder_id_cache["cached"] = "id123"
    with patch(
        "mnemo_mcp.sync.gdrive._verify_folder_exists",
        new_callable=AsyncMock,
        return_value=True,
    ):
        assert await _find_or_create_folder({}, "cached") == "id123"


async def test_find_or_create_folder_mem_cache_invalid():
    mnemo_mcp.sync.gdrive._folder_id_cache["cached_invalid"] = "id_old"
    with (
        patch(
            "mnemo_mcp.sync.gdrive._verify_folder_exists",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "mnemo_mcp.sync.gdrive._load_folder_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new_callable=AsyncMock,
            side_effect=Exception("stop"),
        ),
    ):
        try:
            await _find_or_create_folder({}, "cached_invalid")
        except Exception:
            pass
        assert "cached_invalid" not in mnemo_mcp.sync.gdrive._folder_id_cache


async def test_find_or_create_folder_disk_cache():
    with (
        patch(
            "mnemo_mcp.sync.gdrive._load_folder_id",
            new_callable=AsyncMock,
            return_value="disk123",
        ),
        patch(
            "mnemo_mcp.sync.gdrive._verify_folder_exists",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        assert await _find_or_create_folder({}, "disk") == "disk123"


async def test_find_or_create_folder_disk_cache_invalid():
    with (
        patch(
            "mnemo_mcp.sync.gdrive._load_folder_id",
            new_callable=AsyncMock,
            return_value="disk_invalid",
        ),
        patch(
            "mnemo_mcp.sync.gdrive._verify_folder_exists",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new_callable=AsyncMock,
            side_effect=Exception("stop"),
        ),
    ):
        try:
            await _find_or_create_folder({}, "disk")
        except Exception:
            pass


async def test_find_or_create_folder_search_found():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"files": [{"id": "found123"}]}
    with (
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ),
        patch(
            "mnemo_mcp.sync.gdrive._load_folder_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("mnemo_mcp.sync.gdrive._save_folder_id", new_callable=AsyncMock),
    ):
        assert await _find_or_create_folder({}, "search") == "found123"


async def test_find_or_create_folder_create_new():
    mock_search = MagicMock()
    mock_search.status_code = 200
    mock_search.json.return_value = {"files": []}

    mock_create = MagicMock()
    mock_create.status_code = 200
    mock_create.json.return_value = {"id": "new123"}

    # We need 3 search responses (for 3 attempts) + 1 create response
    with (
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new_callable=AsyncMock,
            side_effect=[mock_search, mock_search, mock_search, mock_create],
        ),
        patch(
            "mnemo_mcp.sync.gdrive._load_folder_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("mnemo_mcp.sync.gdrive._save_folder_id", new_callable=AsyncMock),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        assert await _find_or_create_folder({}, "new") == "new123"


async def test_find_or_create_folder_create_no_id():
    mock_search = MagicMock()
    mock_search.status_code = 200
    mock_search.json.return_value = {"files": []}

    mock_create = MagicMock()
    mock_create.status_code = 200
    mock_create.json.return_value = {}  # No ID

    with (
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new_callable=AsyncMock,
            side_effect=[mock_search, mock_search, mock_search, mock_create],
        ),
        patch(
            "mnemo_mcp.sync.gdrive._load_folder_id",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("mnemo_mcp.sync.gdrive._save_folder_id", new_callable=AsyncMock),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        assert await _find_or_create_folder({}, "new_no_id") is None


# --- _find_file_in_folder ---


async def test_find_file_in_folder_not_found():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"files": []}
    with patch(
        "mnemo_mcp.sync.gdrive._drive_request",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        assert await _find_file_in_folder({}, "fid", "fname") is None


async def test_find_file_in_folder_found():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"files": [{"id": "fileid"}]}
    with patch(
        "mnemo_mcp.sync.gdrive._drive_request",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        res = await _find_file_in_folder({}, "fid", "fname")
        assert res is not None
        assert res["id"] == "fileid"


# --- _upload_file / _download_file ---


async def test_upload_file_new(tmp_path):
    p = tmp_path / "test.db"
    p.write_bytes(b"data")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch(
        "mnemo_mcp.sync.gdrive._drive_request",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        assert await _upload_file({}, p, "fid") is True


async def test_upload_file_patch(tmp_path):
    p = tmp_path / "test.db"
    p.write_bytes(b"data")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch(
        "mnemo_mcp.sync.gdrive._drive_request",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        assert await _upload_file({}, p, "fid", existing_file_id="eid") is True


async def test_upload_file_fail(tmp_path):
    p = tmp_path / "test.db"
    p.write_bytes(b"data")
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "err"
    with patch(
        "mnemo_mcp.sync.gdrive._drive_request",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        assert await _upload_file({}, p, "fid") is False


async def test_download_file_success(tmp_path):
    p = tmp_path / "test.db"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"downloaded"
    with patch(
        "mnemo_mcp.sync.gdrive._drive_request",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        assert await _download_file({}, "fid", p) is True
        assert p.read_bytes() == b"downloaded"


async def test_download_file_fail(tmp_path):
    p = tmp_path / "test.db"
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "not found"
    with patch(
        "mnemo_mcp.sync.gdrive._drive_request",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        assert await _download_file({}, "fid", p) is False


# --- sync_push / sync_pull ---


async def test_sync_push_no_token():
    with patch(
        "mnemo_mcp.sync.gdrive._get_valid_token",
        new_callable=AsyncMock,
        return_value=None,
    ):
        assert await sync_push(Path("db"), "folder") is False


async def test_sync_push_success(tmp_path):
    p = tmp_path / "test.db"
    p.write_bytes(b"")
    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new_callable=AsyncMock,
            return_value={"acc": "1"},
        ),
        patch(
            "mnemo_mcp.sync.gdrive._find_or_create_folder",
            new_callable=AsyncMock,
            return_value="fid",
        ),
        patch(
            "mnemo_mcp.sync.gdrive._find_file_in_folder",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "mnemo_mcp.sync.gdrive._upload_file",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        assert await sync_push(p, "folder") is True


async def test_sync_pull_no_token():
    with patch(
        "mnemo_mcp.sync.gdrive._get_valid_token",
        new_callable=AsyncMock,
        return_value=None,
    ):
        assert await sync_pull(Path("db"), "folder") is None


async def test_sync_pull_no_remote_file():
    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new_callable=AsyncMock,
            return_value={"acc": "1"},
        ),
        patch(
            "mnemo_mcp.sync.gdrive._find_or_create_folder",
            new_callable=AsyncMock,
            return_value="fid",
        ),
        patch(
            "mnemo_mcp.sync.gdrive._find_file_in_folder",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        assert await sync_pull(Path("db"), "folder") is None


# --- sync_full coverage ---


async def test_sync_full_disabled():
    from mnemo_mcp.config import settings

    with patch.object(settings, "sync_enabled", False):
        res = await sync_full(MagicMock())
        assert res["status"] == "disabled"


async def test_sync_full_no_client_id():
    from mnemo_mcp.config import settings

    with (
        patch.object(settings, "sync_enabled", True),
        patch.object(settings, "google_drive_client_id", ""),
    ):
        res = await sync_full(MagicMock())
        assert res["status"] == "error"
        assert "CLIENT_ID" in res["message"]


async def test_sync_full_no_token():
    from mnemo_mcp.config import settings

    with (
        patch.object(settings, "sync_enabled", True),
        patch.object(settings, "google_drive_client_id", "cid"),
        patch(
            "mnemo_mcp.sync.gdrive._has_token_available",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        res = await sync_full(MagicMock())
        assert res["status"] == "error"
        assert "token available" in res["message"]


async def test_sync_full_token_expired():
    from mnemo_mcp.config import settings

    with (
        patch.object(settings, "sync_enabled", True),
        patch.object(settings, "google_drive_client_id", "cid"),
        patch(
            "mnemo_mcp.sync.gdrive._has_token_available",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        res = await sync_full(MagicMock())
        assert res["status"] == "error"
        assert "refresh failed" in res["message"]


async def test_sync_full_merge_logic(tmp_path):
    remote_db_path = tmp_path / "remote.db"
    remote_db_path.write_bytes(b"remote_data")

    mock_db = MagicMock()
    mock_db.import_jsonl.return_value = {"imported": 5, "skipped": 0}

    # Mock MemoryDB inside the thread
    with (
        patch(
            "mnemo_mcp.sync.gdrive.sync_pull",
            new_callable=AsyncMock,
            return_value=remote_db_path,
        ),
        patch(
            "mnemo_mcp.sync.gdrive.sync_push", new_callable=AsyncMock, return_value=True
        ),
        patch("mnemo_mcp.sync.gdrive.settings") as mock_settings,
        patch(
            "mnemo_mcp.sync.gdrive._has_token_available",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new_callable=AsyncMock,
            return_value={"acc": "1"},
        ),
    ):
        mock_settings.sync_enabled = True
        mock_settings.google_drive_client_id = "cid"
        mock_settings.get_db_path.return_value = Path("local.db")
        mock_settings.sync_folder = "folder"

        # Mocking the inner MemoryDB constructor and export_jsonl
        class FakeRemoteDB:
            def __init__(self, *args, **kwargs):
                pass

            def export_jsonl(self):
                return ("data\n", {})

            def close(self):
                pass

        with patch("mnemo_mcp.db.MemoryDB", FakeRemoteDB):
            res = await sync_full(mock_db)
            assert res["status"] == "ok"
            assert res["pull"]["imported"] == 5


async def test_sync_full_merge_empty_remote(tmp_path):
    remote_db_path = tmp_path / "remote.db"
    remote_db_path.write_bytes(b"")

    mock_db = MagicMock()

    with (
        patch(
            "mnemo_mcp.sync.gdrive.sync_pull",
            new_callable=AsyncMock,
            return_value=remote_db_path,
        ),
        patch(
            "mnemo_mcp.sync.gdrive.sync_push", new_callable=AsyncMock, return_value=True
        ),
        patch("mnemo_mcp.sync.gdrive.settings") as mock_settings,
        patch(
            "mnemo_mcp.sync.gdrive._has_token_available",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new_callable=AsyncMock,
            return_value={"acc": "1"},
        ),
    ):
        mock_settings.sync_enabled = True
        mock_settings.google_drive_client_id = "cid"
        mock_settings.get_db_path.return_value = Path("local.db")
        mock_settings.sync_folder = "folder"

        class FakeRemoteDB:
            def __init__(self, *args, **kwargs):
                pass

            def export_jsonl(self):
                return ("", {})

            def close(self):
                pass

        with patch("mnemo_mcp.db.MemoryDB", FakeRemoteDB):
            res = await sync_full(mock_db)
            assert res["status"] == "ok"
            assert res["pull"]["imported"] == 0


async def test_sync_full_cleanup_oserror(tmp_path):
    remote_db_path = tmp_path / "remote.db"
    remote_db_path.write_bytes(b"data")

    mock_db = MagicMock()

    with (
        patch(
            "mnemo_mcp.sync.gdrive.sync_pull",
            new_callable=AsyncMock,
            return_value=remote_db_path,
        ),
        patch(
            "mnemo_mcp.sync.gdrive.sync_push", new_callable=AsyncMock, return_value=True
        ),
        patch("mnemo_mcp.sync.gdrive.settings") as mock_settings,
        patch(
            "mnemo_mcp.sync.gdrive._has_token_available",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new_callable=AsyncMock,
            return_value={"acc": "1"},
        ),
    ):
        mock_settings.sync_enabled = True
        mock_settings.google_drive_client_id = "cid"
        mock_settings.get_db_path.return_value = Path("local.db")
        mock_settings.sync_folder = "folder"

        class FakeRemoteDB:
            def __init__(self, *args, **kwargs):
                pass

            def export_jsonl(self):
                return ("data\n", {})

            def close(self):
                pass

        with (
            patch("mnemo_mcp.db.MemoryDB", FakeRemoteDB),
            patch.object(Path, "rmdir", side_effect=OSError("busy")),
        ):
            res = await sync_full(mock_db)
            assert res["status"] == "ok"


# --- start_auto_sync / stop_auto_sync ---


def test_start_auto_sync_already_running():
    mock_db = MagicMock()
    with patch("mnemo_mcp.sync.gdrive.settings") as mock_settings:
        mock_settings.sync_enabled = True
        mock_settings.google_drive_client_id = "cid"
        mock_settings.sync_interval = 60

        mock_task = MagicMock()
        mock_task.done.return_value = False

        with patch("mnemo_mcp.sync.gdrive._sync_task", mock_task):
            start_auto_sync(mock_db)
            # Should return without creating new task (already running)


def test_start_auto_sync_disabled():
    mock_db = MagicMock()
    with patch("mnemo_mcp.sync.gdrive.settings") as mock_settings:
        mock_settings.sync_enabled = False
        start_auto_sync(mock_db)
        # Should return immediately


def test_start_auto_sync_missing_config():
    mock_db = MagicMock()
    with patch("mnemo_mcp.sync.gdrive.settings") as mock_settings:
        mock_settings.sync_enabled = True
        mock_settings.google_drive_client_id = ""  # Missing
        start_auto_sync(mock_db)


def test_start_auto_sync_trigger():
    mock_db = MagicMock()
    with (
        patch("mnemo_mcp.sync.gdrive.settings") as mock_settings,
        patch("asyncio.create_task") as mock_create_task,
    ):
        mock_settings.sync_enabled = True
        mock_settings.google_drive_client_id = "cid"
        mock_settings.sync_interval = 60

        with patch("mnemo_mcp.sync.gdrive._sync_task", None):
            start_auto_sync(mock_db)
            mock_create_task.assert_called_once()


# --- setup_sync ---


def test_setup_sync_no_client_id():
    with (
        patch("mnemo_mcp.sync.gdrive.settings") as mock_settings,
        patch("sys.exit") as mock_exit,
    ):
        mock_settings.google_drive_client_id = ""
        setup_sync()
        mock_exit.assert_called_with(1)


def test_setup_sync_success():
    with (
        patch("mnemo_mcp.sync.gdrive.settings") as mock_settings,
        patch(
            "mnemo_mcp.sync.gdrive.setup_google_auth",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("builtins.print"),
    ):
        mock_settings.google_drive_client_id = "cid"
        setup_sync()


def test_setup_sync_fail():
    with (
        patch("mnemo_mcp.sync.gdrive.settings") as mock_settings,
        patch(
            "mnemo_mcp.sync.gdrive.setup_google_auth",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("sys.exit") as mock_exit,
        patch("builtins.print"),
    ):
        mock_settings.google_drive_client_id = "cid"
        setup_sync()
        mock_exit.assert_called_with(1)


# --- Phase 2 GDriveBackend ---


async def test_ensure_bundle_folder_search_found():
    mock_search = MagicMock()
    mock_search.status_code = 200
    mock_search.json.return_value = {"files": [{"id": "bundle_id"}]}

    with (
        patch(
            "mnemo_mcp.sync.gdrive._find_or_create_folder",
            new_callable=AsyncMock,
            return_value="base_id",
        ),
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new_callable=AsyncMock,
            return_value=mock_search,
        ),
    ):
        assert await _ensure_bundle_folder({}, "folder") == "bundle_id"


async def test_ensure_bundle_folder_create():
    mock_search = MagicMock()
    mock_search.status_code = 200
    mock_search.json.return_value = {"files": []}

    mock_create = MagicMock()
    mock_create.status_code = 200
    mock_create.json.return_value = {"id": "bundle_id"}

    with (
        patch(
            "mnemo_mcp.sync.gdrive._find_or_create_folder",
            new_callable=AsyncMock,
            return_value="base_id",
        ),
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new_callable=AsyncMock,
            side_effect=[mock_search, mock_create],
        ),
    ):
        assert await _ensure_bundle_folder({}, "folder") == "bundle_id"


async def test_ensure_bundle_folder_fail():
    with patch(
        "mnemo_mcp.sync.gdrive._find_or_create_folder",
        new_callable=AsyncMock,
        return_value=None,
    ):
        assert await _ensure_bundle_folder({}, "folder") is None


async def test_backend_pull_no_token():
    backend = GDriveBackend("folder")
    with patch(
        "mnemo_mcp.sync.gdrive._get_valid_token",
        new_callable=AsyncMock,
        return_value=None,
    ):
        assert await backend.pull() is None


async def test_backend_pull_no_bundle_folder():
    backend = GDriveBackend("folder")
    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new_callable=AsyncMock,
            return_value={"acc": "1"},
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        assert await backend.pull() is None


async def test_backend_pull_no_files():
    backend = GDriveBackend("folder")
    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new_callable=AsyncMock,
            return_value={"acc": "1"},
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new_callable=AsyncMock,
            return_value="bid",
        ),
        patch.object(
            GDriveBackend, "_max_sequence", new_callable=AsyncMock, return_value=0
        ),
    ):
        assert await backend.pull() is None


async def test_backend_pull_max_sequence_fail():
    backend = GDriveBackend("folder")
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new_callable=AsyncMock,
            return_value={"acc": "1"},
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new_callable=AsyncMock,
            return_value="bid",
        ),
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ),
    ):
        assert await backend.pull() is None
