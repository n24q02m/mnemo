"""F9: skip GDrive device-code on Cloudflare.

On CF the memory DB is D1 + Vectorize (durable), so the Google Drive delta-sync
is redundant; the relay must not trigger a non-functional GDrive setup there.
"""

from __future__ import annotations

from unittest.mock import patch

from mnemo_mcp.credential_state import _sync_redundant_on_cf, _trigger_gdrive_flow


def test_sync_redundant_on_cf(monkeypatch):
    monkeypatch.delenv("DOCS_DB_BACKEND", raising=False)
    assert _sync_redundant_on_cf() is False
    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    assert _sync_redundant_on_cf() is True
    monkeypatch.setenv("DOCS_DB_BACKEND", "sqlite")
    assert _sync_redundant_on_cf() is False


def test_gdrive_flow_skipped_on_cf(monkeypatch):
    """With GDrive creds present, the device-code flow is still skipped on CF."""
    monkeypatch.setenv("DOCS_DB_BACKEND", "cf-d1")
    monkeypatch.delenv("SYNC_S3_BUCKET", raising=False)

    from mnemo_mcp.config import settings

    monkeypatch.setattr(settings, "google_drive_client_id", "cid", raising=False)
    monkeypatch.setattr(
        settings, "google_drive_client_secret", "csecret", raising=False
    )

    with patch("httpx.post") as mock_post:
        result = _trigger_gdrive_flow(auto_open=True)

    assert result is None
    assert mock_post.call_count == 0
