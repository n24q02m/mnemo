"""Unit tests for the multi-user remote helpers in credential_state.

Mirrors ``tests/integration/test_multi_user_remote.py`` but without the
``integration`` marker so the per-subject file IO and PUBLIC_URL branch
counts toward the default coverage gate.
"""

from __future__ import annotations

import pytest


def test_sub_data_dir_creates_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import _sub_data_dir

    d = _sub_data_dir("sub_xyz")
    assert d == tmp_path / "subs" / "sub_xyz"
    assert d.exists() and d.is_dir()


def test_store_and_read_for_sub_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import read_for_sub, store_for_sub

    store_for_sub("alice", {"JINA_AI_API_KEY": "key_a"})
    store_for_sub("bob", {"JINA_AI_API_KEY": "key_b"})

    assert read_for_sub("alice") == {"JINA_AI_API_KEY": "key_a"}
    assert read_for_sub("bob") == {"JINA_AI_API_KEY": "key_b"}


def test_read_for_sub_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import read_for_sub

    assert read_for_sub("never_seen") == {}


def test_save_credentials_multi_user_branch(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_URL", "https://mnemo.example.com")
    from mnemo_mcp.credential_state import read_for_sub, save_credentials

    result = save_credentials({"JINA_AI_API_KEY": "k1"}, {"sub": "alice"})

    assert result is None
    assert read_for_sub("alice")["JINA_AI_API_KEY"] == "k1"


def test_save_credentials_multi_user_requires_sub(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_URL", "https://mnemo.example.com")
    from mnemo_mcp.credential_state import save_credentials

    with pytest.raises(RuntimeError, match="sub required"):
        save_credentials({"JINA_AI_API_KEY": "k1"}, {})
