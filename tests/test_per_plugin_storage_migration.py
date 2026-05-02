"""Verify migration to PerPluginStore + cred persistence works."""

from __future__ import annotations

import sys


def _reload_credential_state():
    """Reload credential_state module to pick up monkeypatched home."""
    for mod_name in list(sys.modules.keys()):
        if "mnemo_mcp.credential_state" in mod_name or "per_plugin_store" in mod_name:
            del sys.modules[mod_name]


def test_loads_from_new_path(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    # PerPluginStore is only loaded in HTTP mode (spec §4.1: stdio = env vars
    # only). Set MCP_TRANSPORT=http to exercise the legitimate persistence path.
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    _reload_credential_state()

    from mcp_core.storage.per_plugin_store import PerPluginStore

    PerPluginStore("mnemo").save({"GEMINI_API_KEY": "fake-key"})

    from mnemo_mcp.credential_state import CredentialState, resolve_credential_state

    # Clear env so it falls through to config file check
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)

    # Should read the PerPluginStore-saved cred and return CONFIGURED
    state = resolve_credential_state()
    assert state == CredentialState.CONFIGURED


def test_save_writes_to_new_path(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _reload_credential_state()

    # Simulate calling save_credentials from the local OAuth form
    import mnemo_mcp.credential_state as cs

    cs.save_credentials({"GEMINI_API_KEY": "saved-key"}, {})

    from mcp_core.storage.per_plugin_store import PerPluginStore

    stored = PerPluginStore("mnemo").load()
    assert stored is not None
    assert stored.get("GEMINI_API_KEY") == "saved-key"


def test_clear_removes_new_path(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _reload_credential_state()

    from mcp_core.storage.per_plugin_store import PerPluginStore

    import mnemo_mcp.credential_state as cs

    # Write then clear
    PerPluginStore("mnemo").save({"x": "y"})
    cs.reset_state()

    stored = PerPluginStore("mnemo").load()
    assert stored is None
