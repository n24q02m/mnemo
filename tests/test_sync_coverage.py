"""Additional tests for mnemo_mcp.sync — covering uncovered lines.

Targets: _get_rclone_path, _extract_zip_sync, _download_rclone,
ensure_rclone, _run_rclone, check_remote_configured, sync_push,
sync_pull, sync_full (pull+merge+push flow), _auto_sync_loop,
stop_auto_sync, setup_sync (win32 branch).
"""

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import mnemo_mcp.sync
from mnemo_mcp.sync import (
    _auto_sync_loop,
    _extract_zip_sync,
    _get_rclone_path,
    _run_rclone,
    check_remote_configured,
    ensure_rclone,
    stop_auto_sync,
    sync_full,
    sync_pull,
    sync_push,
)

# ---------------------------------------------------------------------------
# _get_rclone_path
# ---------------------------------------------------------------------------


class TestGetRclonePath:
    def test_system_rclone_found(self, tmp_path):
        """Returns system rclone if found in PATH."""
        rclone_bin = tmp_path / "rclone"
        rclone_bin.touch()
        with patch("mnemo_mcp.sync.shutil.which", return_value=str(rclone_bin)):
            result = _get_rclone_path()
            assert result == Path(str(rclone_bin))

    def test_system_rclone_not_found_bundled_exists(self, tmp_path):
        """Falls back to bundled binary when system rclone is absent."""
        bundled = tmp_path / "bin" / "rclone"
        bundled.parent.mkdir(parents=True)
        bundled.touch()
        with (
            patch("mnemo_mcp.sync.shutil.which", return_value=None),
            patch("mnemo_mcp.sync._get_rclone_dir", return_value=tmp_path / "bin"),
            patch("mnemo_mcp.sync.sys.platform", "linux"),
        ):
            result = _get_rclone_path()
            assert result == bundled

    def test_no_rclone_anywhere(self, tmp_path):
        """Returns None when no rclone is available."""
        with (
            patch("mnemo_mcp.sync.shutil.which", return_value=None),
            patch("mnemo_mcp.sync._get_rclone_dir", return_value=tmp_path / "bin"),
        ):
            result = _get_rclone_path()
            assert result is None

    def test_bundled_windows_extension(self, tmp_path):
        """On Windows, checks for rclone.exe bundled binary."""
        bundled = tmp_path / "bin" / "rclone.exe"
        bundled.parent.mkdir(parents=True)
        bundled.touch()
        with (
            patch("mnemo_mcp.sync.shutil.which", return_value=None),
            patch("mnemo_mcp.sync._get_rclone_dir", return_value=tmp_path / "bin"),
            patch("mnemo_mcp.sync.sys.platform", "win32"),
        ):
            result = _get_rclone_path()
            assert result == bundled


# ---------------------------------------------------------------------------
# _extract_zip_sync
# ---------------------------------------------------------------------------


class TestExtractZipSync:
    def test_extract_success(self, tmp_path):
        """Extracts binary from zip and writes to target."""
        import zipfile

        zip_path = tmp_path / "test.zip"
        target_path = tmp_path / "rclone"

        # Create a real zip with a rclone binary inside
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("rclone-v1/rclone", b"binary_content")

        result = _extract_zip_sync(zip_path, target_path, "rclone")
        assert result is True
        assert target_path.exists()
        assert target_path.read_bytes() == b"binary_content"

    def test_binary_not_found_in_zip(self, tmp_path):
        """Returns False when binary is not in the zip."""
        import zipfile

        zip_path = tmp_path / "test.zip"
        target_path = tmp_path / "rclone"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("some_other_file.txt", b"not rclone")

        result = _extract_zip_sync(zip_path, target_path, "rclone")
        assert result is False
        assert not target_path.exists()

    def test_skips_directories(self, tmp_path):
        """Skips directory entries even if name matches."""
        import zipfile

        zip_path = tmp_path / "test.zip"
        target_path = tmp_path / "rclone"

        with zipfile.ZipFile(zip_path, "w") as zf:
            # Add a directory ending with "rclone"
            zf.mkdir("rclone")
            zf.writestr("subdir/rclone", b"real_binary")

        result = _extract_zip_sync(zip_path, target_path, "rclone")
        assert result is True


# ---------------------------------------------------------------------------
# _download_rclone
# ---------------------------------------------------------------------------


class TestDownloadRclone:
    async def test_already_exists_returns_early(self, tmp_path):
        """Returns existing binary without downloading."""
        from mnemo_mcp.sync import _download_rclone

        bundled = tmp_path / "bin" / "rclone"
        bundled.parent.mkdir(parents=True)
        bundled.touch()

        with (
            patch(
                "mnemo_mcp.sync._get_platform_info", return_value=("linux", "amd64", "")
            ),
            patch("mnemo_mcp.sync._get_rclone_dir", return_value=tmp_path / "bin"),
            patch("mnemo_mcp.sync.settings") as mock_settings,
        ):
            mock_settings.rclone_version = "v1.68.2"
            result = await _download_rclone()
            assert result == bundled

    async def test_no_checksum_warning(self, tmp_path):
        """Logs warning when no checksum found for platform."""

        from mnemo_mcp.sync import _download_rclone

        dummy_content = b"fake zip content"

        mock_response = MagicMock()
        mock_response.content = dummy_content
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response

        install_dir = tmp_path / "bin"

        with (
            patch("mnemo_mcp.sync.httpx.AsyncClient", return_value=mock_client),
            patch(
                "mnemo_mcp.sync._get_platform_info",
                return_value=("freebsd", "amd64", ""),
            ),
            patch("mnemo_mcp.sync._get_rclone_dir", return_value=install_dir),
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync.tempfile.NamedTemporaryFile") as mock_temp,
            patch("builtins.open", new_callable=MagicMock),
            patch.dict("mnemo_mcp.sync._RCLONE_CHECKSUMS", {}, clear=True),
            patch(
                "mnemo_mcp.sync._extract_zip_sync", return_value=True
            ) as mock_extract,
            patch(
                "mnemo_mcp.sync.asyncio.to_thread", side_effect=lambda fn, *a: fn(*a)
            ),
        ):
            mock_settings.rclone_version = "v1.68.2"
            mock_temp_file = MagicMock()
            mock_temp.return_value.__enter__.return_value = mock_temp_file
            mock_temp_file.name = str(tmp_path / "fake.zip")

            await _download_rclone()
            # Should continue and try to extract (no checksum check)
            mock_extract.assert_called_once()

    async def test_binary_not_found_in_archive(self, tmp_path):
        """Returns None when binary not found in downloaded archive."""
        import hashlib

        from mnemo_mcp.sync import _download_rclone

        dummy_content = b"fake zip content"
        dummy_hash = hashlib.sha256(dummy_content).hexdigest()

        mock_response = MagicMock()
        mock_response.content = dummy_content
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response

        install_dir = tmp_path / "bin"

        with (
            patch("mnemo_mcp.sync.httpx.AsyncClient", return_value=mock_client),
            patch(
                "mnemo_mcp.sync._get_platform_info", return_value=("linux", "amd64", "")
            ),
            patch("mnemo_mcp.sync._get_rclone_dir", return_value=install_dir),
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync.tempfile.NamedTemporaryFile") as mock_temp,
            patch("builtins.open", new_callable=MagicMock) as mock_open,
            patch.dict("mnemo_mcp.sync._RCLONE_CHECKSUMS", {"linux-amd64": dummy_hash}),
            patch("mnemo_mcp.sync._extract_zip_sync", return_value=False),
            patch(
                "mnemo_mcp.sync.asyncio.to_thread", side_effect=lambda fn, *a: fn(*a)
            ),
        ):
            mock_settings.rclone_version = "v1.68.2"
            mock_temp_file = MagicMock()
            mock_temp.return_value.__enter__.return_value = mock_temp_file
            mock_temp_file.name = str(tmp_path / "fake.zip")

            mock_file_handle = MagicMock()
            mock_file_handle.read.side_effect = [dummy_content, b""]
            mock_open.return_value.__enter__.return_value = mock_file_handle

            result = await _download_rclone()
            assert result is None


# ---------------------------------------------------------------------------
# ensure_rclone
# ---------------------------------------------------------------------------


class TestEnsureRclone:
    async def test_returns_existing_path(self, tmp_path):
        """Returns path if rclone already available."""
        rclone_path = tmp_path / "rclone"
        rclone_path.touch()

        with patch(
            "mnemo_mcp.sync.asyncio.to_thread",
            return_value=rclone_path,
        ):
            result = await ensure_rclone()
            assert result == rclone_path

    async def test_downloads_when_not_found(self, tmp_path):
        """Downloads rclone when not found locally."""
        rclone_path = tmp_path / "rclone"
        rclone_path.touch()

        with (
            patch("mnemo_mcp.sync.asyncio.to_thread", return_value=None),
            patch(
                "mnemo_mcp.sync._download_rclone",
                new_callable=AsyncMock,
                return_value=rclone_path,
            ) as mock_download,
        ):
            result = await ensure_rclone()
            assert result == rclone_path
            mock_download.assert_called_once()

    async def test_download_fails_returns_none(self):
        """Returns None when download also fails."""
        with (
            patch("mnemo_mcp.sync.asyncio.to_thread", return_value=None),
            patch(
                "mnemo_mcp.sync._download_rclone",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await ensure_rclone()
            assert result is None


# ---------------------------------------------------------------------------
# _run_rclone
# ---------------------------------------------------------------------------


class TestRunRclone:
    def test_runs_command(self, tmp_path):
        """Runs rclone command and returns CompletedProcess."""
        rclone = tmp_path / "rclone"
        rclone.touch()

        mock_result = subprocess.CompletedProcess(
            args=["rclone", "version"],
            returncode=0,
            stdout="rclone v1.68.2",
            stderr="",
        )
        with patch(
            "mnemo_mcp.sync.subprocess.run", return_value=mock_result
        ) as mock_run:
            result = _run_rclone(rclone, ["version"])
            assert result.returncode == 0
            assert result.stdout == "rclone v1.68.2"
            mock_run.assert_called_once()

    def test_passes_args_and_env(self, tmp_path):
        """Passes correct args and environment."""
        rclone = tmp_path / "rclone"

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with (
            patch(
                "mnemo_mcp.sync.subprocess.run", return_value=mock_result
            ) as mock_run,
            patch(
                "mnemo_mcp.sync._prepare_rclone_env", return_value={"PATH": "/usr/bin"}
            ),
        ):
            _run_rclone(rclone, ["copy", "src", "dst"], timeout=60)
            args = mock_run.call_args
            assert args[0][0] == [str(rclone), "copy", "src", "dst"]
            assert args[1]["timeout"] == 60


# ---------------------------------------------------------------------------
# check_remote_configured
# ---------------------------------------------------------------------------


class TestCheckRemoteConfigured:
    async def test_remote_present(self, tmp_path):
        """Returns True when remote is in the list."""
        rclone = tmp_path / "rclone"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "gdrive:\nremote2:\n"

        with patch(
            "mnemo_mcp.sync.asyncio.to_thread",
            return_value=mock_result,
        ):
            result = await check_remote_configured(rclone, "gdrive")
            assert result is True

    async def test_remote_absent(self, tmp_path):
        """Returns False when remote is not listed."""
        rclone = tmp_path / "rclone"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "other:\n"

        with patch(
            "mnemo_mcp.sync.asyncio.to_thread",
            return_value=mock_result,
        ):
            result = await check_remote_configured(rclone, "gdrive")
            assert result is False

    async def test_command_failure(self, tmp_path):
        """Returns False when rclone command fails."""
        rclone = tmp_path / "rclone"
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch(
            "mnemo_mcp.sync.asyncio.to_thread",
            return_value=mock_result,
        ):
            result = await check_remote_configured(rclone, "gdrive")
            assert result is False


# ---------------------------------------------------------------------------
# sync_push
# ---------------------------------------------------------------------------


class TestSyncPush:
    async def test_push_success(self, tmp_path):
        """Returns True on successful push."""
        rclone = tmp_path / "rclone"
        db_path = tmp_path / "memories.db"
        db_path.touch()

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("mnemo_mcp.sync.asyncio.to_thread", return_value=mock_result):
            result = await sync_push(rclone, db_path, "gdrive", "mnemo-mcp")
            assert result is True

    async def test_push_failure(self, tmp_path):
        """Returns False on push failure."""
        rclone = tmp_path / "rclone"
        db_path = tmp_path / "memories.db"
        db_path.touch()

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error: permission denied"

        with patch("mnemo_mcp.sync.asyncio.to_thread", return_value=mock_result):
            result = await sync_push(rclone, db_path, "gdrive", "mnemo-mcp")
            assert result is False


# ---------------------------------------------------------------------------
# sync_pull
# ---------------------------------------------------------------------------


class TestSyncPull:
    async def test_pull_success(self, tmp_path):
        """Returns temp path on successful pull."""
        rclone = tmp_path / "rclone"
        db_path = tmp_path / "memories.db"

        mock_result = MagicMock()
        mock_result.returncode = 0

        async def mock_to_thread(fn, *args, **kwargs):
            # Simulate rclone creating the file
            temp_dir = db_path.parent / "sync_temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_db = temp_dir / f"remote_{db_path.name}"
            temp_db.touch()
            return mock_result

        with patch("mnemo_mcp.sync.asyncio.to_thread", side_effect=mock_to_thread):
            result = await sync_pull(rclone, db_path, "gdrive", "mnemo-mcp")
            assert result is not None
            assert "remote_memories.db" in str(result)

    async def test_pull_failure(self, tmp_path):
        """Returns None on pull failure."""
        rclone = tmp_path / "rclone"
        db_path = tmp_path / "memories.db"

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "file not found"

        with patch("mnemo_mcp.sync.asyncio.to_thread", return_value=mock_result):
            result = await sync_pull(rclone, db_path, "gdrive", "mnemo-mcp")
            assert result is None


# ---------------------------------------------------------------------------
# sync_full (pull + merge + push flow)
# ---------------------------------------------------------------------------


class TestSyncFullFlow:
    async def test_full_cycle_with_remote_db(self, tmp_db, tmp_path):
        """Full sync cycle: pull remote DB, merge, push."""
        from mnemo_mcp.db import MemoryDB

        # Add data to local DB
        tmp_db.add("local memory", category="local")

        # Create a remote DB with different data
        remote_db_path = tmp_path / "sync_temp" / "remote_memories.db"
        remote_db_path.parent.mkdir(parents=True, exist_ok=True)
        remote_db = MemoryDB(remote_db_path, embedding_dims=0)
        remote_db.add("remote memory", category="remote")
        remote_db.close()

        rclone_path = tmp_path / "rclone"
        rclone_path.touch()

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch(
                "mnemo_mcp.sync.ensure_rclone",
                new_callable=AsyncMock,
                return_value=rclone_path,
            ),
            patch(
                "mnemo_mcp.sync.check_remote_configured",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "mnemo_mcp.sync.sync_pull",
                new_callable=AsyncMock,
                return_value=remote_db_path,
            ),
            patch(
                "mnemo_mcp.sync.sync_push", new_callable=AsyncMock, return_value=True
            ),
        ):
            mock_settings.sync_enabled = True
            mock_settings.sync_remote = "gdrive"
            mock_settings.sync_folder = "mnemo-mcp"
            mock_settings.get_db_path.return_value = tmp_path / "test.db"

            result = await sync_full(tmp_db)

            assert result["status"] == "ok"
            assert result["pull"] is not None
            assert result["pull"]["imported"] >= 0
            assert result["push"]["success"] is True

    async def test_full_cycle_no_remote_db(self, tmp_db, tmp_path):
        """Sync with no remote DB found (pull returns None)."""
        rclone_path = tmp_path / "rclone"
        rclone_path.touch()

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch(
                "mnemo_mcp.sync.ensure_rclone",
                new_callable=AsyncMock,
                return_value=rclone_path,
            ),
            patch(
                "mnemo_mcp.sync.check_remote_configured",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "mnemo_mcp.sync.sync_pull", new_callable=AsyncMock, return_value=None
            ),
            patch(
                "mnemo_mcp.sync.sync_push", new_callable=AsyncMock, return_value=True
            ),
        ):
            mock_settings.sync_enabled = True
            mock_settings.sync_remote = "gdrive"
            mock_settings.sync_folder = "mnemo-mcp"
            mock_settings.get_db_path.return_value = tmp_path / "test.db"

            result = await sync_full(tmp_db)

            assert result["status"] == "ok"
            assert result["pull"]["note"] == "No remote DB found"
            assert result["push"]["success"] is True

    async def test_full_cycle_merge_error(self, tmp_db, tmp_path):
        """Handles merge errors gracefully during sync."""
        rclone_path = tmp_path / "rclone"
        rclone_path.touch()

        # Create a fake "remote DB" that will cause an error when opened
        bad_remote = tmp_path / "sync_temp" / "remote_memories.db"
        bad_remote.parent.mkdir(parents=True, exist_ok=True)
        bad_remote.write_text("not a sqlite db")

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch(
                "mnemo_mcp.sync.ensure_rclone",
                new_callable=AsyncMock,
                return_value=rclone_path,
            ),
            patch(
                "mnemo_mcp.sync.check_remote_configured",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "mnemo_mcp.sync.sync_pull",
                new_callable=AsyncMock,
                return_value=bad_remote,
            ),
            patch(
                "mnemo_mcp.sync.sync_push", new_callable=AsyncMock, return_value=True
            ),
        ):
            mock_settings.sync_enabled = True
            mock_settings.sync_remote = "gdrive"
            mock_settings.sync_folder = "mnemo-mcp"
            mock_settings.get_db_path.return_value = tmp_path / "test.db"

            result = await sync_full(tmp_db)

            assert result["status"] == "ok"
            assert "error" in result["pull"]

    async def test_full_cycle_empty_remote_jsonl(self, tmp_db, tmp_path):
        """Handles empty remote JSONL (no data to merge)."""
        from mnemo_mcp.db import MemoryDB

        rclone_path = tmp_path / "rclone"
        rclone_path.touch()

        # Create an empty remote DB
        remote_db_path = tmp_path / "sync_temp" / "remote_memories.db"
        remote_db_path.parent.mkdir(parents=True, exist_ok=True)
        remote_db = MemoryDB(remote_db_path, embedding_dims=0)
        remote_db.close()

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch(
                "mnemo_mcp.sync.ensure_rclone",
                new_callable=AsyncMock,
                return_value=rclone_path,
            ),
            patch(
                "mnemo_mcp.sync.check_remote_configured",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "mnemo_mcp.sync.sync_pull",
                new_callable=AsyncMock,
                return_value=remote_db_path,
            ),
            patch(
                "mnemo_mcp.sync.sync_push", new_callable=AsyncMock, return_value=True
            ),
        ):
            mock_settings.sync_enabled = True
            mock_settings.sync_remote = "gdrive"
            mock_settings.sync_folder = "mnemo-mcp"
            mock_settings.get_db_path.return_value = tmp_path / "test.db"

            result = await sync_full(tmp_db)

            assert result["status"] == "ok"
            assert result["pull"]["imported"] == 0
            assert result["pull"]["skipped"] == 0


# ---------------------------------------------------------------------------
# _auto_sync_loop
# ---------------------------------------------------------------------------


class TestAutoSyncLoop:
    async def test_zero_interval_returns(self, tmp_db):
        """Loop exits immediately if interval <= 0."""
        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.sync_interval = 0
            await _auto_sync_loop(tmp_db)
            # Should return without doing anything

    async def test_cancelled_error_stops_loop(self, tmp_db):
        """CancelledError stops the auto-sync loop."""
        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_settings.sync_interval = 10
            mock_sleep.side_effect = asyncio.CancelledError()

            await _auto_sync_loop(tmp_db)
            # Should exit cleanly

    async def test_sync_error_continues_loop(self, tmp_db):
        """Non-fatal errors during sync don't stop the loop."""
        call_count = 0

        async def mock_sleep(interval):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch("mnemo_mcp.sync.asyncio.sleep", side_effect=mock_sleep),
            patch(
                "mnemo_mcp.sync.sync_full",
                new_callable=AsyncMock,
                side_effect=RuntimeError("test"),
            ),
        ):
            mock_settings.sync_interval = 1
            await _auto_sync_loop(tmp_db)
            assert call_count >= 2


# ---------------------------------------------------------------------------
# stop_auto_sync
# ---------------------------------------------------------------------------


class TestStopAutoSync:
    def test_stops_running_task(self):
        """Cancels and clears running sync task."""
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mnemo_mcp.sync._sync_task = mock_task

        stop_auto_sync()

        mock_task.cancel.assert_called_once()
        assert mnemo_mcp.sync._sync_task is None

    def test_noop_when_no_task(self):
        """Does nothing when no task is running."""
        mnemo_mcp.sync._sync_task = None
        stop_auto_sync()  # Should not raise

    def test_noop_when_task_done(self):
        """Does nothing when task is already done."""
        mock_task = MagicMock()
        mock_task.done.return_value = True
        mnemo_mcp.sync._sync_task = mock_task

        stop_auto_sync()
        mock_task.cancel.assert_not_called()

    def teardown_method(self):
        mnemo_mcp.sync._sync_task = None


# ---------------------------------------------------------------------------
# setup_sync (win32 branch)
# ---------------------------------------------------------------------------


class TestSetupSyncWin32:
    def test_fallback_instructions_win32(self, tmp_path, capsys):
        """Win32 fallback instructions use python instead of python3."""
        from mnemo_mcp.sync import setup_sync

        rclone_path = tmp_path / "rclone"
        rclone_path.touch()

        with (
            patch("mnemo_mcp.sync._get_rclone_path", return_value=rclone_path),
            patch(
                "mnemo_mcp.sync.subprocess.run",
                return_value=MagicMock(returncode=0, stdout="no token here"),
            ),
            patch("mnemo_mcp.sync.sys.platform", "win32"),
        ):
            setup_sync("drive")
            captured = capsys.readouterr()
            assert "MANUAL SETUP" in captured.out
            assert "python -c" in captured.out
