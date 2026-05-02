"""Regression: stdio mode must NOT read PerPluginStore.

Per spec ``2026-05-01-stdio-pure-http-multiuser.md`` §4.1 + OQ3, stdio mode
treats env vars as the ONLY credential source. Reading
``~/.mnemo-mcp/config.json`` (or any peer plugin store) as a fallback would
violate the stdio-pure architecture: the stdio entry point is supposed to
exit-1 with a clear error if required env vars are missing, NOT silently
re-hydrate from a previous HTTP-mode config persisted on disk.

mnemo-mcp specifically has no required cred (it works zero-config with local
SQLite + Qwen3 ONNX) so the stdio-no-fallback path returns ``AWAITING_SETUP``
instead of exiting -- but the *invariant* (no PerPluginStore read in stdio
mode) is identical to wet-mcp.

These tests guard against the silent fallback regression.
"""

from __future__ import annotations

from unittest.mock import patch

from mnemo_mcp.credential_state import (
    CLOUD_KEYS,
    CredentialState,
    _is_http_mode,
    resolve_credential_state,
    set_state,
)


class TestStdioSkipsPerPluginStore:
    """Stdio mode (default after 2026-05-01 flip) does NOT read PerPluginStore."""

    def test_stdio_skips_per_plugin_store(self, monkeypatch):
        """Empty env + stdio mode -> PerPluginStore.load() never called.

        Even if the user had a previously-persisted ``~/.mnemo-mcp/config.json``
        from a past HTTP-mode session, stdio mode must IGNORE it. Otherwise
        a stdio process inherits creds it never received via env -- breaking
        the spec §4.1 OQ3 contract that stdio = env vars ONLY.
        """
        # Clear all cloud keys + force stdio mode
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.delenv("TRANSPORT_MODE", raising=False)
        # Ensure no --http arg in argv
        monkeypatch.setattr("sys.argv", ["mnemo-mcp"])

        # Sanity check: we are in stdio mode
        assert not _is_http_mode()

        set_state(CredentialState.AWAITING_SETUP)

        with (
            patch("mcp_core.storage.per_plugin_store.PerPluginStore.load") as mock_load,
            patch("mcp_core.get_mode", return_value=None),
        ):
            result = resolve_credential_state()

        # PerPluginStore.load() must NEVER be called in stdio mode
        assert mock_load.call_count == 0, (
            f"PerPluginStore.load() called {mock_load.call_count} times in stdio mode "
            "-- spec §4.1 violation. stdio = env vars ONLY."
        )
        # mnemo has no required cred, so no env -> AWAITING_SETUP (benign)
        assert result == CredentialState.AWAITING_SETUP

    def test_stdio_skips_store_even_if_store_has_creds(self, monkeypatch):
        """Even if PerPluginStore is populated, stdio must not load it.

        Prevents the silent re-hydration regression where a prior HTTP setup
        leaks creds into a subsequent stdio process.
        """
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.delenv("TRANSPORT_MODE", raising=False)
        monkeypatch.setattr("sys.argv", ["mnemo-mcp"])

        # PerPluginStore would return real creds if asked -- but stdio must not ask.
        populated = {"JINA_AI_API_KEY": "leaked_from_disk"}
        set_state(CredentialState.AWAITING_SETUP)

        with (
            patch(
                "mcp_core.storage.per_plugin_store.PerPluginStore.load",
                return_value=populated,
            ) as mock_load,
            patch("mcp_core.get_mode", return_value=None),
        ):
            result = resolve_credential_state()

        # The store must not be touched
        assert mock_load.call_count == 0
        # State must NOT be CONFIGURED -- we got no env, store ignored
        assert result == CredentialState.AWAITING_SETUP
        # And the fake disk value must NOT have leaked into env
        import os as _os

        assert _os.environ.get("JINA_AI_API_KEY") != "leaked_from_disk"


class TestHttpModeUsesPerPluginStore:
    """HTTP mode reads PerPluginStore as the legitimate persistence path."""

    def test_http_mode_uses_per_plugin_store(self, monkeypatch):
        """Empty env + MCP_TRANSPORT=http -> PerPluginStore.load() called -> CONFIGURED.

        HTTP mode is where the browser-form / paste-cred flow lives. After
        the user submits creds, ``save_credentials`` writes them to
        ``~/.mnemo-mcp/config.json`` (PerPluginStore). On the next startup
        ``resolve_credential_state`` must re-hydrate so HTTP doesn't lose
        creds across restarts.
        """
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("MCP_TRANSPORT", "http")

        # Sanity check: we are in HTTP mode
        assert _is_http_mode()

        set_state(CredentialState.AWAITING_SETUP)

        saved = {"JINA_AI_API_KEY": "from_http_form", "GEMINI_API_KEY": "gem_key"}
        with patch(
            "mcp_core.storage.per_plugin_store.PerPluginStore.load",
            return_value=saved,
        ) as mock_load:
            result = resolve_credential_state()

        # In HTTP mode, the store IS read
        assert mock_load.call_count >= 1
        assert result == CredentialState.CONFIGURED

        # Cleanup -- env was applied
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def test_http_mode_via_transport_mode_env(self, monkeypatch):
        """``TRANSPORT_MODE=http`` (Docker convention) also enables HTTP mode."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.setenv("TRANSPORT_MODE", "http")

        assert _is_http_mode()

        set_state(CredentialState.AWAITING_SETUP)

        with patch(
            "mcp_core.storage.per_plugin_store.PerPluginStore.load",
            return_value={"JINA_AI_API_KEY": "k"},
        ) as mock_load:
            result = resolve_credential_state()

        assert mock_load.call_count >= 1
        assert result == CredentialState.CONFIGURED
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)

    def test_http_mode_via_argv_flag(self, monkeypatch):
        """``--http`` CLI flag also enables HTTP mode (Python ``__main__`` path)."""
        for k in CLOUD_KEYS:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.delenv("TRANSPORT_MODE", raising=False)
        monkeypatch.setattr("sys.argv", ["mnemo-mcp", "--http"])

        assert _is_http_mode()

        set_state(CredentialState.AWAITING_SETUP)

        with patch(
            "mcp_core.storage.per_plugin_store.PerPluginStore.load",
            return_value={"JINA_AI_API_KEY": "k"},
        ) as mock_load:
            result = resolve_credential_state()

        assert mock_load.call_count >= 1
        assert result == CredentialState.CONFIGURED
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)


class TestIsHttpModeDetection:
    """Direct tests for the ``_is_http_mode`` helper."""

    def test_default_is_stdio(self, monkeypatch):
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.delenv("TRANSPORT_MODE", raising=False)
        monkeypatch.setattr("sys.argv", ["mnemo-mcp"])
        assert _is_http_mode() is False

    def test_mcp_transport_stdio_is_stdio(self, monkeypatch):
        """Explicit MCP_TRANSPORT=stdio is stdio (not http)."""
        monkeypatch.setenv("MCP_TRANSPORT", "stdio")
        monkeypatch.delenv("TRANSPORT_MODE", raising=False)
        monkeypatch.setattr("sys.argv", ["mnemo-mcp"])
        assert _is_http_mode() is False

    def test_mcp_transport_http(self, monkeypatch):
        monkeypatch.setenv("MCP_TRANSPORT", "http")
        monkeypatch.setattr("sys.argv", ["mnemo-mcp"])
        assert _is_http_mode() is True

    def test_transport_mode_http(self, monkeypatch):
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.setenv("TRANSPORT_MODE", "http")
        monkeypatch.setattr("sys.argv", ["mnemo-mcp"])
        assert _is_http_mode() is True

    def test_argv_http(self, monkeypatch):
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.delenv("TRANSPORT_MODE", raising=False)
        monkeypatch.setattr("sys.argv", ["mnemo-mcp", "--http"])
        assert _is_http_mode() is True
