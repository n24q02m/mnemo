"""Tests for mnemo_mcp.cli -- HTTP MCP server entry point.

De-host rework: the auth/logout subcommands (Google BYO pairing, Drive token
store) pinned removed sync machinery and were deleted; unknown flags and
subcommands now fail through argparse with exit code 2. Live subcommands:
token-hash, token-verify, warmup, config-init; bare invocation serves HTTP.
"""

import sys
from unittest.mock import AsyncMock, patch

import pytest


class TestServeDispatch:
    """Bare argv routes to the server; unknown flags die in argparse."""

    def test_bare_invocation_starts_server(self):
        from mnemo_mcp import cli

        with (
            patch.object(sys, "argv", ["mnemo-mcp"]),
            patch("mnemo_mcp.server.main") as mock_server_main,
        ):
            rc = cli.main()

        mock_server_main.assert_called_once()
        assert rc == 0

    def test_unknown_flag_is_rejected_by_argparse(self):
        """There is no --http spawn mode anymore: unknown flags exit rc 2."""
        from mnemo_mcp import cli

        with (
            patch.object(sys, "argv", ["mnemo-mcp", "--http"]),
            patch("mnemo_mcp.server.main") as mock_server_main,
            pytest.raises(SystemExit) as excinfo,
        ):
            cli.main()

        assert excinfo.value.code == 2
        mock_server_main.assert_not_called()


class TestUnknownSubcommand:
    """argparse rejects unrecognized subcommands -- rc 2, no server start."""

    def test_unknown_subcommand_returns_rc_2(self, capsys):
        from mnemo_mcp import cli

        with (
            patch.object(sys, "argv", ["mnemo-mcp", "bogus"]),
            patch("mnemo_mcp.server.main") as mock_server_main,
            pytest.raises(SystemExit) as excinfo,
        ):
            cli.main()

        mock_server_main.assert_not_called()
        assert excinfo.value.code == 2
        assert "invalid choice" in capsys.readouterr().err


class TestWarmupSubcommand:
    """`mnemo-mcp warmup` -- run_warmup, no argument-taking configure."""

    def test_happy_path(self, capsys):
        from mnemo_mcp import cli

        result = {"status": "ok", "mode": "local", "steps": []}
        with (
            patch.object(sys, "argv", ["mnemo-mcp", "warmup"]),
            patch(
                "mnemo_mcp.setup_tool.run_warmup", new=AsyncMock(return_value=result)
            ) as mock_warmup,
        ):
            rc = cli.main()

        mock_warmup.assert_awaited_once_with()
        assert rc == 0
        assert '"mode": "local"' in capsys.readouterr().out

    def test_error_status_returns_nonzero(self):
        from mnemo_mcp import cli

        result = {"status": "error", "steps": []}
        with (
            patch.object(sys, "argv", ["mnemo-mcp", "warmup"]),
            patch(
                "mnemo_mcp.setup_tool.run_warmup", new=AsyncMock(return_value=result)
            ),
        ):
            rc = cli.main()

        assert rc == 1
