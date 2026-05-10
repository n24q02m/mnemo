"""Tests for the Phase 2 GDriveBackend adapter.

The Phase 1 sync_full / sync_push helpers are covered by the existing
test_sync*.py suite. This module focuses on the new class-based bundle
push / pull / last_remote_sequence / health_check paths so the Phase 2
coverage gate stays >=95%.

All tests mock _get_valid_token / _drive_request so we never touch a
real Google account.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.sync.gdrive import (
    GDriveBackend,
    _bundle_filename,
    _ensure_bundle_folder,
)


@pytest.fixture
def fake_token() -> dict:
    return {"access_token": "fake-access-token"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_bundle_filename_format() -> None:
    assert _bundle_filename(1) == "seq-000001.bin"
    assert _bundle_filename(123456) == "seq-123456.bin"


# ---------------------------------------------------------------------------
# _ensure_bundle_folder
# ---------------------------------------------------------------------------


async def test_ensure_bundle_folder_returns_existing(fake_token: dict) -> None:
    """Existing passport/ subfolder is returned without create call."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"files": [{"id": "passport-folder-id"}]}

    with (
        patch(
            "mnemo_mcp.sync.gdrive._find_or_create_folder",
            new=AsyncMock(return_value="parent-id"),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new=AsyncMock(return_value=mock_response),
        ),
    ):
        result = await _ensure_bundle_folder(fake_token, "mnemo-mcp")

    assert result == "passport-folder-id"


async def test_ensure_bundle_folder_creates_when_missing(fake_token: dict) -> None:
    """Empty list response -> POST create + return new id."""
    list_resp = MagicMock(status_code=200)
    list_resp.json.return_value = {"files": []}
    create_resp = MagicMock(status_code=200)
    create_resp.json.return_value = {"id": "new-folder-id"}

    drive_mock = AsyncMock(side_effect=[list_resp, create_resp])
    with (
        patch(
            "mnemo_mcp.sync.gdrive._find_or_create_folder",
            new=AsyncMock(return_value="parent-id"),
        ),
        patch("mnemo_mcp.sync.gdrive._drive_request", new=drive_mock),
    ):
        result = await _ensure_bundle_folder(fake_token, "mnemo-mcp")

    assert result == "new-folder-id"
    assert drive_mock.call_count == 2


async def test_ensure_bundle_folder_returns_none_when_parent_missing(
    fake_token: dict,
) -> None:
    with patch(
        "mnemo_mcp.sync.gdrive._find_or_create_folder",
        new=AsyncMock(return_value=None),
    ):
        assert await _ensure_bundle_folder(fake_token, "mnemo-mcp") is None


async def test_ensure_bundle_folder_returns_none_on_create_failure(
    fake_token: dict,
) -> None:
    list_resp = MagicMock(status_code=200)
    list_resp.json.return_value = {"files": []}
    create_resp = MagicMock(status_code=500, text="server error")

    drive_mock = AsyncMock(side_effect=[list_resp, create_resp])
    with (
        patch(
            "mnemo_mcp.sync.gdrive._find_or_create_folder",
            new=AsyncMock(return_value="parent-id"),
        ),
        patch("mnemo_mcp.sync.gdrive._drive_request", new=drive_mock),
    ):
        assert await _ensure_bundle_folder(fake_token, "mnemo-mcp") is None


# ---------------------------------------------------------------------------
# GDriveBackend.push
# ---------------------------------------------------------------------------


async def test_push_raises_without_token() -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    with patch(
        "mnemo_mcp.sync.gdrive._get_valid_token", new=AsyncMock(return_value=None)
    ):
        with pytest.raises(RuntimeError, match="no valid token"):
            await backend.push(b"x", sequence=1)


async def test_push_raises_when_folder_unavailable(fake_token: dict) -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new=AsyncMock(return_value=fake_token),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new=AsyncMock(return_value=None),
        ),
    ):
        with pytest.raises(RuntimeError, match="bundle folder"):
            await backend.push(b"x", sequence=1)


async def test_push_creates_new_bundle(fake_token: dict) -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    upload_resp = MagicMock(status_code=200)

    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new=AsyncMock(return_value=fake_token),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new=AsyncMock(return_value="folder-id"),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._find_file_in_folder",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new=AsyncMock(return_value=upload_resp),
        ) as drive_mock,
    ):
        await backend.push(b"new-bundle", sequence=1)

    # POST upload called.
    assert drive_mock.call_count == 1


async def test_push_overwrites_existing_bundle(fake_token: dict) -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    upload_resp = MagicMock(status_code=200)

    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new=AsyncMock(return_value=fake_token),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new=AsyncMock(return_value="folder-id"),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._find_file_in_folder",
            new=AsyncMock(return_value={"id": "existing-id"}),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new=AsyncMock(return_value=upload_resp),
        ) as drive_mock,
    ):
        await backend.push(b"updated", sequence=1)

    # PATCH on existing-id called.
    args = drive_mock.call_args.args
    assert args[0] == "PATCH"
    assert "existing-id" in args[1]


async def test_push_raises_on_upload_failure(fake_token: dict) -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    bad_resp = MagicMock(status_code=500, text="server-error")

    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new=AsyncMock(return_value=fake_token),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new=AsyncMock(return_value="folder-id"),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._find_file_in_folder",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new=AsyncMock(return_value=bad_resp),
        ),
    ):
        with pytest.raises(RuntimeError, match="upload failed"):
            await backend.push(b"x", sequence=1)


# ---------------------------------------------------------------------------
# GDriveBackend.pull
# ---------------------------------------------------------------------------


async def test_pull_returns_none_without_token() -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    with patch(
        "mnemo_mcp.sync.gdrive._get_valid_token", new=AsyncMock(return_value=None)
    ):
        assert await backend.pull(sequence=1) is None


async def test_pull_returns_none_when_folder_unavailable(fake_token: dict) -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new=AsyncMock(return_value=fake_token),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new=AsyncMock(return_value=None),
        ),
    ):
        assert await backend.pull(sequence=1) is None


async def test_pull_returns_none_when_bundle_missing(fake_token: dict) -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new=AsyncMock(return_value=fake_token),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new=AsyncMock(return_value="folder-id"),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._find_file_in_folder",
            new=AsyncMock(return_value=None),
        ),
    ):
        assert await backend.pull(sequence=99) is None


async def test_pull_returns_bundle_bytes(fake_token: dict) -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    download_resp = MagicMock(status_code=200, content=b"the-bundle")

    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new=AsyncMock(return_value=fake_token),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new=AsyncMock(return_value="folder-id"),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._find_file_in_folder",
            new=AsyncMock(return_value={"id": "file-id"}),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new=AsyncMock(return_value=download_resp),
        ),
    ):
        result = await backend.pull(sequence=1)

    assert result == b"the-bundle"


async def test_pull_returns_none_on_404(fake_token: dict) -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    bad_resp = MagicMock(status_code=404)

    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new=AsyncMock(return_value=fake_token),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new=AsyncMock(return_value="folder-id"),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._find_file_in_folder",
            new=AsyncMock(return_value={"id": "file-id"}),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new=AsyncMock(return_value=bad_resp),
        ),
    ):
        assert await backend.pull(sequence=1) is None


async def test_pull_latest_returns_none_when_empty(fake_token: dict) -> None:
    """sequence=None + max_sequence=0 -> None."""
    backend = GDriveBackend(folder_name="mnemo-mcp")
    list_resp = MagicMock(status_code=200)
    list_resp.json.return_value = {"files": []}

    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new=AsyncMock(return_value=fake_token),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new=AsyncMock(return_value="folder-id"),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new=AsyncMock(return_value=list_resp),
        ),
    ):
        assert await backend.pull(sequence=None) is None


# ---------------------------------------------------------------------------
# GDriveBackend.last_remote_sequence
# ---------------------------------------------------------------------------


async def test_last_remote_sequence_returns_zero_without_token() -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    with patch(
        "mnemo_mcp.sync.gdrive._get_valid_token", new=AsyncMock(return_value=None)
    ):
        assert await backend.last_remote_sequence() == 0


async def test_last_remote_sequence_returns_zero_when_folder_missing(
    fake_token: dict,
) -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new=AsyncMock(return_value=fake_token),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new=AsyncMock(return_value=None),
        ),
    ):
        assert await backend.last_remote_sequence() == 0


async def test_last_remote_sequence_returns_max(fake_token: dict) -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    list_resp = MagicMock(status_code=200)
    list_resp.json.return_value = {
        "files": [
            {"name": "seq-000001.bin"},
            {"name": "seq-000012.bin"},
            {"name": "seq-000005.bin"},
            {"name": "junk.txt"},
            {"name": "seq-bad.bin"},
        ]
    }

    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new=AsyncMock(return_value=fake_token),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new=AsyncMock(return_value="folder-id"),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new=AsyncMock(return_value=list_resp),
        ),
    ):
        assert await backend.last_remote_sequence() == 12


async def test_last_remote_sequence_returns_zero_on_list_failure(
    fake_token: dict,
) -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    bad_resp = MagicMock(status_code=500)

    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new=AsyncMock(return_value=fake_token),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._ensure_bundle_folder",
            new=AsyncMock(return_value="folder-id"),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._drive_request",
            new=AsyncMock(return_value=bad_resp),
        ),
    ):
        assert await backend.last_remote_sequence() == 0


# ---------------------------------------------------------------------------
# GDriveBackend.health_check
# ---------------------------------------------------------------------------


async def test_health_check_false_without_token() -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    with patch(
        "mnemo_mcp.sync.gdrive._get_valid_token", new=AsyncMock(return_value=None)
    ):
        assert await backend.health_check() is False


async def test_health_check_true_when_folder_resolves(fake_token: dict) -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new=AsyncMock(return_value=fake_token),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._find_or_create_folder",
            new=AsyncMock(return_value="folder-id"),
        ),
    ):
        assert await backend.health_check() is True


async def test_health_check_false_when_find_folder_raises(
    fake_token: dict,
) -> None:
    backend = GDriveBackend(folder_name="mnemo-mcp")
    with (
        patch(
            "mnemo_mcp.sync.gdrive._get_valid_token",
            new=AsyncMock(return_value=fake_token),
        ),
        patch(
            "mnemo_mcp.sync.gdrive._find_or_create_folder",
            new=AsyncMock(side_effect=RuntimeError("network down")),
        ),
    ):
        assert await backend.health_check() is False


# ---------------------------------------------------------------------------
# Default folder fallback
# ---------------------------------------------------------------------------


def test_default_folder_falls_back_to_settings(monkeypatch) -> None:
    from mnemo_mcp.config import settings

    backend = GDriveBackend()
    assert backend._folder_name == settings.sync_folder
