import hashlib
import zipfile
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from mnemo_mcp.sync import _download_rclone
from mnemo_mcp.config import Settings


@pytest.mark.asyncio
async def test_rclone_download_checksum_success():
    """Test successful rclone download with valid checksum."""
    # We need to construct bytes that hash to expected_hash, or mock the checksum dict
    # Let's mock the checksum dict so we can use arbitrary bytes.

    # Create a valid zip file content so zipfile extraction works
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("rclone", b"executable bytes")
    zip_content = zip_buffer.getvalue()
    zip_hash = hashlib.sha256(zip_content).hexdigest()

    mock_response = AsyncMock()
    mock_response.content = zip_content
    mock_response.raise_for_status = MagicMock()

    mock_client_instance = AsyncMock()
    mock_client_instance.get.return_value = mock_response

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client_instance

    with (
        patch("mnemo_mcp.sync.httpx.AsyncClient", mock_client_cls),
        patch("mnemo_mcp.sync._get_platform_info", return_value=("linux", "amd64", "")),
        patch("mnemo_mcp.sync._RCLONE_CHECKSUMS", {"linux-amd64": zip_hash}),
        patch("mnemo_mcp.sync.Path.mkdir"),
        patch("mnemo_mcp.sync.Path.chmod"),
        patch("mnemo_mcp.sync.Path.exists", return_value=False),
        patch("mnemo_mcp.sync.Path.stat"),
        patch("mnemo_mcp.sync.Path.write_bytes") as mock_write_bytes,
    ):
        path = await _download_rclone()
        assert path is not None
        mock_write_bytes.assert_called_once()


@pytest.mark.asyncio
async def test_rclone_download_checksum_mismatch():
    """Test failed rclone download with invalid checksum."""

    mock_response = AsyncMock()
    mock_response.content = b"malicious content"
    mock_response.raise_for_status = MagicMock()

    mock_client_instance = AsyncMock()
    mock_client_instance.get.return_value = mock_response

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client_instance

    with (
        patch("mnemo_mcp.sync.httpx.AsyncClient", mock_client_cls),
        patch("mnemo_mcp.sync._get_platform_info", return_value=("linux", "amd64", "")),
        patch("mnemo_mcp.sync.Path.mkdir"),
        patch("mnemo_mcp.sync.Path.exists", return_value=False),
    ):
        path = await _download_rclone()
        # The function catches exceptions and logs error, returns None on failure
        assert path is None

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
