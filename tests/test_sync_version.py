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
async def test_token_refresh_clears_token_missing_client_id():
    """A token with no client_id key is treated as a client mismatch.

    token_client_mismatch() flags a missing client_id the same as a
    different one -- a token that never recorded which client minted it
    cannot be trusted, so the old "fall back to
    settings.google_drive_client_id" refresh behavior is unreachable for
    this token; it is cleared and None is returned instead of refreshed.
    """
    from mnemo_mcp.sync import _refresh_token

    token = {
        "access_token": "old",
        "refresh_token": "refresh123",
        # No client_id in token
    }

    with (
        patch("mnemo_mcp.sync._clear_token") as mock_clear,
        patch("mnemo_mcp.sync.httpx.AsyncClient") as mock_client_cls,
        patch("mnemo_mcp.sync.settings") as mock_settings,
    ):
        mock_settings.google_drive_client_id = "settings_client_id"
        mock_settings.google_drive_client_secret = "secret123"

        result = await _refresh_token(token)

    assert result is None
    mock_clear.assert_called_once()
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_clears_token_on_client_mismatch():
    """A token minted by a different client_id is cleared, not refreshed."""
    from mnemo_mcp.sync import _refresh_token

    token = {
        "access_token": "old",
        "refresh_token": "refresh123",
        "client_id": "other-client",
    }

    with (
        patch("mnemo_mcp.sync._clear_token") as mock_clear,
        patch("mnemo_mcp.sync.logger.warning") as mock_warn,
        patch("mnemo_mcp.sync.httpx.AsyncClient") as mock_client_cls,
        patch("mnemo_mcp.sync.settings") as mock_settings,
    ):
        mock_settings.google_drive_client_id = "current-client"
        mock_settings.google_drive_client_secret = "secret123"

        result = await _refresh_token(token)

    assert result is None
    mock_clear.assert_called_once()
    mock_warn.assert_called_once()
    mock_client_cls.assert_not_called()
