import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from mnemo_mcp.config import Settings
from mnemo_mcp.sync import _download_rclone


@pytest.mark.asyncio
async def test_download_verification_fails_on_checksum_mismatch():
    """Verify that _download_rclone fails when SHA256 checksum mismatches."""
    # Mock content
    dummy_content = b"fake zip content"
    # The real code expects a specific hash for linux-amd64.
    # We guarantee mismatch by using random content.

    # Mock httpx response
    mock_response = MagicMock()
    mock_response.content = dummy_content
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get.return_value = mock_response

    # Mock temp file context manager
    mock_temp = MagicMock()
    mock_temp_file = MagicMock()
    mock_temp.return_value.__enter__.return_value = mock_temp_file
    mock_temp_file.name = "/tmp/fake_rclone.zip"

    with (
        patch("mnemo_mcp.sync.httpx.AsyncClient", return_value=mock_client),
        patch("mnemo_mcp.sync._get_platform_info", return_value=("linux", "amd64", "")),
        patch("mnemo_mcp.sync.tempfile.NamedTemporaryFile", mock_temp),
        patch("builtins.open", new_callable=MagicMock) as mock_open,
        patch("pathlib.Path.unlink"),
        patch("pathlib.Path.exists", return_value=False),
        patch("pathlib.Path.mkdir"),
    ):
        # Mock reading the file for checksum calculation
        # The code does open(tmp_path, "rb")
        mock_file_handle = MagicMock()
        mock_file_handle.read.side_effect = [
            dummy_content,
            b"",
        ]  # Return content then EOF
        mock_open.return_value.__enter__.return_value = mock_file_handle

        # Call the function - checksum mismatch raises ValueError,
        # which is caught by the except block and returns None
        result = await _download_rclone()

        # Assertions
        assert result is None, "Should fail (return None) on checksum mismatch"


@pytest.mark.asyncio
async def test_download_verification_succeeds_with_correct_checksum():
    """Verify that _download_rclone succeeds when SHA256 checksum matches."""
    # Mock content
    dummy_content = b"valid zip content"
    dummy_hash = hashlib.sha256(dummy_content).hexdigest()

    # Mock httpx response
    mock_response = MagicMock()
    mock_response.content = dummy_content
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.get.return_value = mock_response

    # Mock ZipFile
    mock_zip_instance = MagicMock()
    mock_info = MagicMock()
    mock_info.filename = "rclone"
    mock_info.is_dir.return_value = False
    mock_zip_instance.infolist.return_value = [mock_info]

    mock_read_handle = MagicMock()
    mock_read_handle.read.return_value = b"binary data"
    mock_zip_instance.open.return_value.__enter__.return_value = mock_read_handle

    mock_zip_cls = MagicMock()
    mock_zip_cls.return_value.__enter__.return_value = mock_zip_instance

    # Mock _RCLONE_CHECKSUMS to match our dummy content
    # We patch the dictionary in the module
    with (
        patch("mnemo_mcp.sync.httpx.AsyncClient", return_value=mock_client),
        patch("mnemo_mcp.sync._get_platform_info", return_value=("linux", "amd64", "")),
        patch("mnemo_mcp.sync.zipfile.ZipFile", mock_zip_cls),
        patch("mnemo_mcp.sync.tempfile.NamedTemporaryFile") as mock_temp,
        patch("builtins.open", new_callable=MagicMock) as mock_open,
        patch.dict("mnemo_mcp.sync._RCLONE_CHECKSUMS", {"linux-amd64": dummy_hash}),
        patch("pathlib.Path.mkdir"),
        patch("pathlib.Path.chmod"),
        patch("pathlib.Path.exists", return_value=False),
        patch("pathlib.Path.write_bytes"),
        patch("pathlib.Path.stat"),
    ):
        # Mock temp file
        mock_temp_file = MagicMock()
        mock_temp.return_value.__enter__.return_value = mock_temp_file
        mock_temp_file.name = "/tmp/fake_rclone.zip"

        # Mock reading file for checksum
        mock_file_handle = MagicMock()
        mock_file_handle.read.side_effect = [dummy_content, b""]
        mock_open.return_value.__enter__.return_value = mock_file_handle

        # Call function
        result = await _download_rclone()

        assert result is not None
        assert result.name == "rclone"


def test_sync_remote_valid():
    """Valid sync_remote values should be accepted."""
    s = Settings(sync_remote="my-gdrive_1.2")
    assert s.sync_remote == "my-gdrive_1.2"

    s = Settings(sync_remote="")
    assert s.sync_remote == ""

    s.sync_remote = "another.valid-remote_name"
    assert s.sync_remote == "another.valid-remote_name"


def test_sync_remote_invalid_characters():
    """Invalid characters should be rejected to prevent injection."""
    invalid_remotes = [
        "my gdrive",
        "my;gdrive",
        "my&gdrive",
        "my|gdrive",
        "my`gdrive",
        "my$gdrive",
        "my(gdrive",
        "my)gdrive",
        "my<gdrive",
        "my>gdrive",
    ]
    for remote in invalid_remotes:
        with pytest.raises(ValidationError, match="can only contain alphanumeric"):
            Settings(sync_remote=remote)

        s = Settings()
        with pytest.raises(ValidationError, match="can only contain alphanumeric"):
            s.sync_remote = remote


def test_sync_remote_starts_with_hyphen():
    """sync_remote starting with hyphen should be rejected to prevent argument injection."""
    with pytest.raises(ValidationError, match="must not start with a hyphen"):
        Settings(sync_remote="-my-gdrive")

    with pytest.raises(ValidationError, match="must not start with a hyphen"):
        Settings(sync_remote="--config")

    s = Settings()
    with pytest.raises(ValidationError, match="must not start with a hyphen"):
        s.sync_remote = "-my-gdrive"

    with pytest.raises(ValidationError, match="must not start with a hyphen"):
        s.sync_remote = "--config"


@pytest.mark.asyncio
async def test_interactive_auth_invalid_provider():
    """Verify that _interactive_auth fails when an invalid provider is provided."""
    from mnemo_mcp.sync import _interactive_auth

    result = await _interactive_auth(MagicMock(), "invalid_provider")
    assert result is None
