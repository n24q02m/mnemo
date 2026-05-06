"""Verify migration to PerPluginStore + cred persistence works.

The conftest ``_isolate_per_plugin_home`` autouse fixture already redirects
``HOME`` / ``USERPROFILE`` per test so ``Path.home()`` resolves to an isolated
tmp dir. ``PerPluginStore`` and ``credential_state`` both call ``Path.home()``
inside functions (not at module-load time) so no module reload is needed --
the redirect alone suffices.

Earlier revisions of this file deleted ``mnemo_mcp.credential_state`` from
``sys.modules`` to "pick up monkeypatched home". That was both unnecessary
(no module-level caching) and harmful: a subsequent ``import`` rebuilt the
module and its ``CredentialState`` enum / ``set_state`` / ``get_state``
function objects, leaving prior callers (other test files imported during
collection, autouse fixtures with cached references) bound to the old
module instance. Cross-instance enum equality (``OLD.CONFIGURED ==
NEW.CONFIGURED``) is ``False``, so any state mutation in one instance was
invisible to the other -- silently breaking 6 unrelated tests in
``test_server_setup_actions.py`` whenever this file ran first.
"""

from __future__ import annotations


def test_loads_from_new_path(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    # PerPluginStore is only loaded in HTTP mode (spec §4.1: stdio = env vars
    # only). Set MCP_TRANSPORT=http to exercise the legitimate persistence path.
    monkeypatch.setenv("MCP_TRANSPORT", "http")

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

    # Simulate calling save_credentials from the local OAuth form
    import mnemo_mcp.credential_state as cs

    cs.save_credentials({"GEMINI_API_KEY": "saved-key"}, {})

    from mcp_core.storage.per_plugin_store import PerPluginStore

    stored = PerPluginStore("mnemo").load()
    assert stored is not None
    assert stored.get("GEMINI_API_KEY") == "saved-key"


def test_clear_removes_new_path(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    from mcp_core.storage.per_plugin_store import PerPluginStore

    import mnemo_mcp.credential_state as cs

    # Write then clear
    PerPluginStore("mnemo").save({"x": "y"})
    cs.reset_state()

    stored = PerPluginStore("mnemo").load()
    assert stored is None
