"""Tests for the mnemo.__main__ entry point."""

from __future__ import annotations

import runpy
from unittest.mock import patch


def test_main_module_calls_server_main():
    """'python -m mnemo' must dispatch to 'server.main'."""
    with patch("mnemo.server.main") as mock_main:
        # We use run_module on the package mnemo which will execute its __main__.py
        runpy.run_module("mnemo", run_name="__main__")
        mock_main.assert_called_once()


def test_main_explicit_call():
    """Directly calling main from mnemo.__main__ also works."""
    with patch("mnemo.server.main") as mock_main:
        from mnemo.__main__ import main as entry_main

        entry_main()
        mock_main.assert_called_once()


def test_main_runs_http_server_with_env_binding(monkeypatch):
    """MNEMO_HOST / MNEMO_PORT override the bind address for the HTTP server."""
    monkeypatch.setenv("MNEMO_HOST", "0.0.0.0")
    monkeypatch.setenv("MNEMO_PORT", "8123")

    with patch("mnemo.server.run_server_blocking") as mock_run:
        from mnemo.server import main

        main()

    mock_run.assert_called_once_with(host="0.0.0.0", port=8123)


def test_main_default_binding(monkeypatch):
    """No env overrides -> run_server_blocking gets None host/port."""
    monkeypatch.delenv("MNEMO_HOST", raising=False)
    monkeypatch.delenv("MNEMO_PORT", raising=False)

    with patch("mnemo.server.run_server_blocking") as mock_run:
        from mnemo.server import main

        main()

    mock_run.assert_called_once_with(host=None, port=None)
