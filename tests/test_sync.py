"""Tests for mnemo_mcp.sync — rclone management and sync operations."""

from unittest.mock import AsyncMock, MagicMock, patch

from mnemo_mcp.sync import _get_platform_info, setup_sync, sync_full


class TestPlatformInfo:
    @patch("mnemo_mcp.sync.platform")
    def test_linux_amd64(self, mock_plat):
        mock_plat.system.return_value = "Linux"
        mock_plat.machine.return_value = "x86_64"
        os_name, arch, ext = _get_platform_info()
        assert os_name == "linux"
        assert arch == "amd64"
        assert ext == ""

    @patch("mnemo_mcp.sync.platform")
    def test_darwin_arm64(self, mock_plat):
        mock_plat.system.return_value = "Darwin"
        mock_plat.machine.return_value = "arm64"
        os_name, arch, ext = _get_platform_info()
        assert os_name == "osx"
        assert arch == "arm64"
        assert ext == ""

    @patch("mnemo_mcp.sync.platform")
    def test_windows(self, mock_plat):
        mock_plat.system.return_value = "Windows"
        mock_plat.machine.return_value = "AMD64"
        os_name, arch, ext = _get_platform_info()
        assert os_name == "windows"
        assert arch == "amd64"
        assert ext == ".exe"

    @patch("mnemo_mcp.sync.platform")
    def test_linux_arm64(self, mock_plat):
        mock_plat.system.return_value = "Linux"
        mock_plat.machine.return_value = "aarch64"
        os_name, arch, ext = _get_platform_info()
        assert os_name == "linux"
        assert arch == "arm64"

    @patch("mnemo_mcp.sync.platform")
    def test_unknown_arch_fallback(self, mock_plat):
        mock_plat.system.return_value = "Linux"
        mock_plat.machine.return_value = "riscv64"
        _, arch, _ = _get_platform_info()
        assert arch == "amd64"  # Fallback

    @patch("mnemo_mcp.sync.platform")
    def test_i686_maps_to_386(self, mock_plat):
        mock_plat.system.return_value = "Linux"
        mock_plat.machine.return_value = "i686"
        _, arch, _ = _get_platform_info()
        assert arch == "386"


class TestSyncFull:
    async def test_disabled(self, tmp_db):
        """Sync returns disabled when not configured."""
        with patch("mnemo_mcp.sync.settings") as mock_settings:
            mock_settings.sync_enabled = False
            mock_settings.sync_remote = ""
            result = await sync_full(tmp_db)
            assert result["status"] == "disabled"

    async def test_no_rclone(self, tmp_db):
        """Sync errors when rclone is not available."""
        with (
            patch("mnemo_mcp.sync.settings") as mock_settings,
            patch(
                "mnemo_mcp.sync.ensure_rclone",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mock_settings.sync_enabled = True
            mock_settings.sync_remote = "test-remote"
            result = await sync_full(tmp_db)
            assert result["status"] == "error"
            assert "rclone" in result["message"].lower()

    async def test_remote_not_configured(self, tmp_db, tmp_path):
        """Sync errors when rclone remote is not set up."""
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
                return_value=False,
            ),
        ):
            mock_settings.sync_enabled = True
            mock_settings.sync_remote = "gdrive"
            result = await sync_full(tmp_db)
            assert result["status"] == "error"
            assert "gdrive" in result["message"]
            assert "RCLONE_CONFIG_GDRIVE_TYPE" in result["message"]


class TestSetupSync:
    def test_rclone_found(self, tmp_path, capsys):
        """setup_sync uses existing rclone and runs authorize."""
        rclone_path = tmp_path / "rclone"
        rclone_path.touch()
        mock_result = MagicMock(returncode=0)
        with (
            patch("mnemo_mcp.sync._get_rclone_path", return_value=rclone_path),
            patch(
                "mnemo_mcp.sync.subprocess.run", return_value=mock_result
            ) as mock_run,
        ):
            setup_sync("drive")
            # Verify rclone authorize was called
            mock_run.assert_called_once()
            args = mock_run.call_args
            assert args[0][0] == [str(rclone_path), "authorize", "drive"]

    def test_rclone_downloaded(self, tmp_path, capsys):
        """setup_sync downloads rclone when not found."""
        rclone_path = tmp_path / "rclone"
        mock_result = MagicMock(returncode=0)
        with (
            patch("mnemo_mcp.sync._get_rclone_path", return_value=None),
            patch(
                "mnemo_mcp.sync.asyncio.run",
                return_value=rclone_path,
            ),
            patch("mnemo_mcp.sync.subprocess.run", return_value=mock_result),
        ):
            setup_sync("drive")
            captured = capsys.readouterr()
            assert "Downloading rclone" in captured.out

    def test_download_fails(self, capsys):
        """setup_sync exits when rclone download fails."""
        with (
            patch("mnemo_mcp.sync._get_rclone_path", return_value=None),
            patch("mnemo_mcp.sync.asyncio.run", return_value=None),
        ):
            import pytest

            with pytest.raises(SystemExit, match="1"):
                setup_sync("drive")

    def test_authorize_fails(self, tmp_path):
        """setup_sync exits when rclone authorize fails."""
        rclone_path = tmp_path / "rclone"
        rclone_path.touch()
        mock_result = MagicMock(returncode=1)
        with (
            patch("mnemo_mcp.sync._get_rclone_path", return_value=rclone_path),
            patch("mnemo_mcp.sync.subprocess.run", return_value=mock_result),
        ):
            import pytest

            with pytest.raises(SystemExit, match="1"):
                setup_sync("drive")

    def test_prints_env_var_instructions(self, tmp_path, capsys):
        """setup_sync prints correct env var names for the remote type."""
        rclone_path = tmp_path / "rclone"
        rclone_path.touch()
        mock_result = MagicMock(returncode=0)
        with (
            patch("mnemo_mcp.sync._get_rclone_path", return_value=rclone_path),
            patch("mnemo_mcp.sync.subprocess.run", return_value=mock_result),
        ):
            setup_sync("s3")
            captured = capsys.readouterr()
            assert "RCLONE_CONFIG_S3_TYPE" in captured.out
            assert "RCLONE_CONFIG_S3_TOKEN" in captured.out
