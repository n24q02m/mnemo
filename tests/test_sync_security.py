"""Tests for mnemo_mcp.sync -- Google Drive API security and edge cases."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.config import Settings


def test_google_drive_client_id_default(monkeypatch):
    """Google Drive client ID and secret are empty by default."""
    monkeypatch.delenv("GOOGLE_DRIVE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_DRIVE_CLIENT_SECRET", raising=False)
    s = Settings(api_keys=None)
    assert s.google_drive_client_id == ""
    assert s.google_drive_client_secret == ""


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


# ---------------------------------------------------------------------------
# Error-log redaction: error responses from the OAuth token / device-code
# endpoints can echo back token material (refresh tokens, authorization codes,
# client secrets). We must never log the raw response body on these paths.
# ---------------------------------------------------------------------------

# A body that simulates an error response leaking sensitive material.
_SENSITIVE_BODY = (
    '{"error":"invalid_grant",'
    '"refresh_token":"1//LEAKED-REFRESH-TOKEN",'
    '"client_secret":"GOCSPX-LEAKED-SECRET"}'
)
_SECRET_MARKERS = ("LEAKED-REFRESH-TOKEN", "GOCSPX-LEAKED-SECRET", "refresh_token")


def _mock_async_client(response):
    """Build a patchable httpx.AsyncClient whose post() returns ``response``."""
    mock_client = AsyncMock()
    mock_client.post.return_value = response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


@pytest.mark.asyncio
async def test_refresh_token_error_does_not_log_response_body():
    """_refresh_token must log only the status code, never the raw body."""
    from mnemo_mcp.sync import _refresh_token

    response = MagicMock()
    response.status_code = 400
    response.text = _SENSITIVE_BODY

    token = {"refresh_token": "1//USER-REFRESH", "client_id": "client123"}

    with (
        patch("mnemo_mcp.sync.gdrive.httpx.AsyncClient") as mock_client_cls,
        patch("mnemo_mcp.sync.gdrive.settings") as mock_settings,
        patch("mnemo_mcp.sync.gdrive.logger") as mock_logger,
    ):
        mock_settings.google_drive_client_id = "client123"
        mock_settings.google_drive_client_secret = "GOCSPX-USER-SECRET"
        mock_client_cls.return_value = _mock_async_client(response)

        result = await _refresh_token(token)

    assert result is None
    logged = " ".join(str(c.args[0]) for c in mock_logger.error.call_args_list)
    for marker in _SECRET_MARKERS:
        assert marker not in logged, f"leaked '{marker}' in error log: {logged!r}"
    assert "400" in logged


@pytest.mark.asyncio
async def test_request_device_code_error_does_not_log_response_body():
    """_request_device_code must log only the status code, never the raw body."""
    from mnemo_mcp.sync import _request_device_code

    response = MagicMock()
    response.status_code = 403
    response.text = _SENSITIVE_BODY

    with (
        patch("mnemo_mcp.sync.gdrive.httpx.AsyncClient") as mock_client_cls,
        patch("mnemo_mcp.sync.gdrive.logger") as mock_logger,
    ):
        mock_client_cls.return_value = _mock_async_client(response)

        result = await _request_device_code("client123")

    assert result is None
    logged = " ".join(str(c.args[0]) for c in mock_logger.error.call_args_list)
    for marker in _SECRET_MARKERS:
        assert marker not in logged, f"leaked '{marker}' in error log: {logged!r}"
    assert "403" in logged


@pytest.mark.asyncio
async def test_upload_file_error_truncates_response_body():
    """_upload_file must truncate the logged response body to 100 chars."""
    from mnemo_mcp.sync import _upload_file

    long_body = "X" * 500
    response = MagicMock()
    response.status_code = 500
    response.text = long_body

    token = {"access_token": "test"}
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        f.write(b"test data")
        f.flush()
        file_path = Path(f.name)

    with (
        patch(
            "mnemo_mcp.sync._drive_request",
            new_callable=AsyncMock,
            return_value=response,
        ),
        patch("mnemo_mcp.sync.gdrive.logger") as mock_logger,
    ):
        result = await _upload_file(token, file_path, "folder_id")

    file_path.unlink(missing_ok=True)
    assert result is False
    logged = " ".join(str(c.args[0]) for c in mock_logger.error.call_args_list)
    assert long_body not in logged
    assert "X" * 100 in logged
    assert "X" * 101 not in logged
