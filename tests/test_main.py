"""Tests for the mnemo_mcp.__main__ entry point."""

from __future__ import annotations

import runpy
import sys
from unittest.mock import AsyncMock, patch


def test_main_module_calls_server_main():
    """'python -m mnemo_mcp' must dispatch to 'server.main'."""
    with patch("mnemo_mcp.server.main") as mock_main:
        # We use run_module on the package mnemo_mcp which will execute its __main__.py
        runpy.run_module("mnemo_mcp", run_name="__main__")
        mock_main.assert_called_once()


def test_main_explicit_call():
    """Directly calling main from mnemo_mcp.__main__ also works."""
    with patch("mnemo_mcp.server.main") as mock_main:
        from mnemo_mcp.__main__ import main as entry_main

        entry_main()
        mock_main.assert_called_once()


def test_cli_http_flag_triggers_run_http():
    """Passing --http flag should trigger run_http instead of mcp.run."""
    from mnemo_mcp import server as server_mod

    with (
        patch.object(sys, "argv", ["mnemo-mcp", "--http"]),
        patch("mnemo_mcp.server.run_http", new_callable=AsyncMock) as mock_run_http,
        patch.object(server_mod.mcp, "run") as mock_run_stdio,
        patch("mnemo_mcp.server.logger"),
        patch("mnemo_mcp.server.settings") as mock_settings,
    ):
        mock_settings.log_level = "INFO"
        from mnemo_mcp.server import main

        main()

        mock_run_http.assert_called_once()
        mock_run_stdio.assert_not_called()


def test_cli_default_stdio():
    """No flags should trigger mcp.run(transport='stdio')."""
    from mnemo_mcp import server as server_mod

    with (
        patch.object(sys, "argv", ["mnemo-mcp"]),
        patch("mnemo_mcp.server.run_http", new_callable=AsyncMock) as mock_run_http,
        patch.object(server_mod.mcp, "run") as mock_run_stdio,
        patch("mnemo_mcp.server.logger"),
        patch("mnemo_mcp.server.settings") as mock_settings,
    ):
        mock_settings.log_level = "INFO"
        from mnemo_mcp.server import main

        main()

        mock_run_http.assert_not_called()
        mock_run_stdio.assert_called_once_with(transport="stdio")
