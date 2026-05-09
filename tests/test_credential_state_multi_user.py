"""Unit tests for the multi-user remote helpers in credential_state.

Mirrors ``tests/integration/test_multi_user_remote.py`` but without the
``integration`` marker so the per-subject file IO and PUBLIC_URL branch
counts toward the default coverage gate.
"""

from __future__ import annotations

import hashlib

import pytest


def _read_for_sub(sub: str) -> dict[str, str]:
    from mnemo_mcp.credential_state import _current_sub, credentials_for_current_request

    token = _current_sub.set(sub)
    try:
        return credentials_for_current_request()
    finally:
        _current_sub.reset(token)


def test_sub_data_dir_creates_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import _sub_data_dir

    d = _sub_data_dir("sub_xyz")
    expected_hash = hashlib.sha256(b"sub_xyz").hexdigest()
    assert d == tmp_path / "subs" / expected_hash
    assert d.exists() and d.is_dir()


def test_store_and_read_for_sub_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import (
        store_for_sub,
    )

    store_for_sub("alice", {"JINA_AI_API_KEY": "key_a"})
    store_for_sub("bob", {"JINA_AI_API_KEY": "key_b"})

    assert _read_for_sub("alice") == {"JINA_AI_API_KEY": "key_a"}
    assert _read_for_sub("bob") == {"JINA_AI_API_KEY": "key_b"}


def test_read_for_sub_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))

    assert _read_for_sub("never_seen") == {}


def test_save_credentials_multi_user_branch(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_URL", "https://mnemo.example.com")
    # Force GDrive trigger off so this test stays purely about per-sub
    # config storage. The GDrive multi-user trigger has its own coverage.
    from mnemo_mcp.config import settings as s

    monkeypatch.setattr(s, "google_drive_client_id", "", raising=False)
    monkeypatch.setattr(s, "google_drive_client_secret", "", raising=False)

    from mnemo_mcp.credential_state import (
        save_credentials,
    )

    result = save_credentials({"JINA_AI_API_KEY": "k1"}, {"sub": "alice"})

    assert result is None
    assert _read_for_sub("alice")["JINA_AI_API_KEY"] == "k1"


def test_save_credentials_multi_user_requires_sub(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_URL", "https://mnemo.example.com")
    from mnemo_mcp.credential_state import save_credentials

    with pytest.raises(RuntimeError, match="sub required"):
        save_credentials({"JINA_AI_API_KEY": "k1"}, {})


def test_save_credentials_multi_user_triggers_gdrive_per_sub(tmp_path, monkeypatch):
    """Multi-user branch starts the device-code flow when a Google client
    is configured, returning ``oauth_device_code`` for the relay form."""
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_URL", "https://mnemo.example.com")
    from mnemo_mcp.config import settings as s

    monkeypatch.setattr(s, "google_drive_client_id", "test-client-id", raising=False)
    monkeypatch.setattr(
        s, "google_drive_client_secret", "test-client-secret", raising=False
    )

    fake_device_response = {
        "device_code": "dc-abc",
        "user_code": "ABC-123",
        "verification_url": "https://www.google.com/device",
        "interval": 5,
        "expires_in": 600,
    }

    class _FakeResponse:
        status_code = 200

        def json(self):
            return fake_device_response

    def _fake_post(url, data, timeout):  # noqa: ARG001
        return _FakeResponse()

    monkeypatch.setattr("httpx.post", _fake_post)

    from mnemo_mcp.credential_state import save_credentials

    result = save_credentials({"JINA_AI_API_KEY": "k1"}, {"sub": "bob"})

    assert result == {
        "type": "oauth_device_code",
        "verification_url": "https://www.google.com/device",
        "user_code": "ABC-123",
    }
