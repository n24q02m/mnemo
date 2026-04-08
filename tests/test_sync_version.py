"""Tests for mnemo_mcp.sync -- Google Drive OAuth token refresh."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_token_refresh_preserves_refresh_token():
    """Test that _refresh_token keeps existing refresh_token if not returned."""
    from mnemo_mcp.sync import _refresh_token

    token = {
        "access_token": "old_access",
        "refresh_token": "original_refresh",
        "client_id": "client123",
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "new_access",
        "expires_in": 3600,
        "token_type": "Bearer",
        # Note: no refresh_token in response
    }

    with (
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("mnemo_mcp.sync._save_token") as mock_save,
        patch("mnemo_mcp.sync.settings") as mock_settings,
    ):
        mock_settings.google_drive_client_secret = "secret123"
        mock_settings.google_drive_client_id = "client123"
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await _refresh_token(token)

    assert result is not None
    assert result["access_token"] == "new_access"
    # Should keep original refresh_token
    assert result["refresh_token"] == "original_refresh"
    assert result["client_id"] == "client123"
    mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_token_refresh_updates_refresh_token():
    """Test that _refresh_token updates refresh_token when returned."""
    from mnemo_mcp.sync import _refresh_token

    token = {
        "access_token": "old_access",
        "refresh_token": "original_refresh",
        "client_id": "client123",
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
        "expires_in": 3600,
        "token_type": "Bearer",
    }

    with (
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("mnemo_mcp.sync._save_token"),
        patch("mnemo_mcp.sync.settings") as mock_settings,
    ):
        mock_settings.google_drive_client_secret = "secret123"
        mock_settings.google_drive_client_id = "client123"
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await _refresh_token(token)

    assert result is not None
    assert result["refresh_token"] == "new_refresh"


@pytest.mark.asyncio
async def test_token_refresh_uses_settings_client_id():
    """Test that _refresh_token falls back to settings.google_drive_client_id."""
    from mnemo_mcp.sync import _refresh_token

    token = {
        "access_token": "old",
        "refresh_token": "refresh123",
        # No client_id in token
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "new",
        "expires_in": 3600,
    }

    with (
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("mnemo_mcp.sync._save_token"),
        patch("mnemo_mcp.sync.settings") as mock_settings,
    ):
        mock_settings.google_drive_client_id = "settings_client_id"
        mock_settings.google_drive_client_secret = "secret123"
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await _refresh_token(token)

    assert result is not None
    assert result["client_id"] == "settings_client_id"
