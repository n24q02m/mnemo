from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.sync import _download_rclone


@pytest.mark.asyncio
async def test_download_rclone_uses_configured_version(tmp_path):
    """Test that _download_rclone uses the version from settings."""
    # Mock settings
    with patch("mnemo_mcp.sync.settings") as mock_settings:
        mock_settings.rclone_version = "v1.99.9"

        # Mock platform info to get predictable URL
        with patch(
            "mnemo_mcp.sync._get_platform_info", return_value=("linux", "amd64", "")
        ):
            # Mock get_rclone_dir to return a temp dir
            with patch("mnemo_mcp.sync._get_rclone_dir", return_value=tmp_path):
                # Mock httpx.AsyncClient
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.content = b"fake-zip-content"
                mock_client.get.return_value = mock_response
                mock_client.__aenter__.return_value = mock_client

                with patch(
                    "mnemo_mcp.sync.httpx.AsyncClient", return_value=mock_client
                ):
                    # Mock zipfile to prevent errors
                    with patch("mnemo_mcp.sync.zipfile.ZipFile"):
                        # Mock tempfile to avoid writing
                        with patch(
                            "mnemo_mcp.sync.tempfile.NamedTemporaryFile"
                        ) as mock_temp:
                            mock_temp.return_value.__enter__.return_value.name = str(
                                tmp_path / "temp.zip"
                            )

                            await _download_rclone()

                            # Verify URL
                            expected_url = "https://github.com/rclone/rclone/releases/download/v1.99.9/rclone-v1.99.9-linux-amd64.zip"
                            mock_client.get.assert_called_with(
                                expected_url, timeout=120.0
                            )
