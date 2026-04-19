"""Tests for mnemo_mcp.sync -- Google Drive API security and edge cases."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.config import Settings


def test_google_drive_client_id_default(monkeypatch):
    """Default ships Google Desktop OAuth client (PUBLIC per Google docs).

    Parity with wet-mcp (both are "http local relay" category MCP servers).
    Desktop/Installed OAuth client_secret is explicitly PUBLIC per
    https://developers.google.com/identity/protocols/oauth2#installed.
    """
    monkeypatch.delenv("GOOGLE_DRIVE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_CLIENT_SECRET", raising=False)
    s = Settings(api_keys=None)
    assert s.google_drive_client_id.endswith(".apps.googleusercontent.com")
    assert s.google_drive_client_secret.startswith("GOCSPX-")


def test_google_drive_credentials_from_env(monkeypatch):
    """google_drive credentials should be settable via env."""
    monkeypatch.setenv("GOOGLE_DRIVE_CLIENT_ID", "test.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_DRIVE_CLIENT_SECRET", "test-secret")
    s = Settings(api_keys=None)
    assert s.google_drive_client_id == "test.apps.googleusercontent.com"
    assert s.google_drive_client_secret == "test-secret"


@pytest.mark.asyncio
async def test_sync_full_requires_token():
    """sync_full should fail when no token is available."""
    from mnemo_mcp.sync import sync_full

    mock_db = MagicMock()

    with (
        patch("mnemo_mcp.sync.settings") as mock_settings,
        patch("mnemo_mcp.sync._has_token_available", return_value=False),
    ):
        mock_settings.sync_enabled = True
        mock_settings.google_drive_client_id = "client123"

        result = await sync_full(mock_db)

    assert result["status"] == "error"
    assert "token" in result["message"].lower()


@pytest.mark.asyncio
async def test_sync_full_requires_client_id():
    """sync_full should fail when client ID is missing."""
    from mnemo_mcp.sync import sync_full

    mock_db = MagicMock()

    with patch("mnemo_mcp.sync.settings") as mock_settings:
        mock_settings.sync_enabled = True
        mock_settings.google_drive_client_id = ""

        result = await sync_full(mock_db)

    assert result["status"] == "error"
    assert "GOOGLE_DRIVE_CLIENT_ID" in result["message"]


@pytest.mark.asyncio
async def test_drive_request_adds_auth_header():
    """_drive_request should add Authorization header."""
    from mnemo_mcp.sync import _drive_request

    token = {"access_token": "secret_token"}

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await _drive_request("GET", "https://api.example.com", token)

        # Verify the auth header was passed
        call_kwargs = mock_client.request.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers["Authorization"] == "Bearer secret_token"


@pytest.mark.asyncio
async def test_upload_boundary_uses_app_name():
    """Multipart upload boundary should use mnemo_mcp prefix."""
    from mnemo_mcp.sync import _upload_file

    token = {"access_token": "test"}
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        f.write(b"test data")
        f.flush()
        file_path = Path(f.name)

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch(
        "mnemo_mcp.sync._drive_request",
        new_callable=AsyncMock,
        return_value=mock_response,
    ) as mock_request:
        await _upload_file(token, file_path, "folder_id")

        # Verify the boundary in content type uses mnemo_mcp prefix
        call_kwargs = mock_request.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert "mnemo_mcp_upload_boundary" in headers.get("Content-Type", "")

    file_path.unlink(missing_ok=True)
