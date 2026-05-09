"""Per-sub credential isolation in mnemo-mcp remote multi-user mode."""

from __future__ import annotations

import pytest


def _read_for_sub(sub: str) -> dict[str, str]:
    from mnemo_mcp.credential_state import _current_sub, credentials_for_current_request

    token = _current_sub.set(sub)
    try:
        return credentials_for_current_request()
    finally:
        _current_sub.reset(token)


@pytest.mark.integration
def test_two_subs_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import (
        store_for_sub,
    )

    store_for_sub("user_a", {"JINA_AI_API_KEY": "key_a"})
    store_for_sub("user_b", {"JINA_AI_API_KEY": "key_b"})

    assert _read_for_sub("user_a") == {"JINA_AI_API_KEY": "key_a"}
    assert _read_for_sub("user_b") == {"JINA_AI_API_KEY": "key_b"}
    assert _read_for_sub("user_a") != _read_for_sub("user_b")


@pytest.mark.integration
def test_save_credentials_uses_sub_when_public_url_set(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_URL", "https://mnemo.example.com")
    from mnemo_mcp.credential_state import (
        save_credentials,
    )

    save_credentials({"JINA_AI_API_KEY": "k1"}, {"sub": "user_a"})
    save_credentials({"JINA_AI_API_KEY": "k2"}, {"sub": "user_b"})

    assert _read_for_sub("user_a")["JINA_AI_API_KEY"] == "k1"
    assert _read_for_sub("user_b")["JINA_AI_API_KEY"] == "k2"
