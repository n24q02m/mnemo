"""Tests for mnemo_mcp.cli -- shared mcp_core CLI builder mount.

Bare invocation and any leading-dash argv start the server unchanged;
subcommands (auth/warmup) run one-shot operator actions. No network or
model calls -- run_setup_sync/run_warmup/setup_google_auth are mocked.
"""

import sys
from unittest.mock import AsyncMock, patch


class TestServeDispatch:
    """Bare/flag argv route to the server unchanged."""

    def test_bare_invocation_starts_server(self):
        from mnemo_mcp import cli

        with (
            patch.object(sys, "argv", ["mnemo-mcp"]),
            patch("mnemo_mcp.server.main") as mock_server_main,
        ):
            rc = cli.main()

        mock_server_main.assert_called_once()
        assert rc == 0

    def test_http_flag_passes_through_argv_unchanged(self):
        from mnemo_mcp import cli

        with (
            patch.object(sys, "argv", ["mnemo-mcp", "--http"]),
            patch("mnemo_mcp.server.main") as mock_server_main,
        ):
            rc = cli.main()

        mock_server_main.assert_called_once()
        assert rc == 0


class TestAuthSubcommand:
    """`mnemo-mcp auth google` -- BYO client resolution + run_setup_sync."""

    def test_half_pair_flags_returns_clean_error(self, capsys):
        from mnemo_mcp import cli

        with patch.object(
            sys, "argv", ["mnemo-mcp", "auth", "google", "--client-secret", "shh"]
        ):
            rc = cli.main()

        assert rc == 2
        err = capsys.readouterr().err
        assert "set both together" in err
        assert "shh" not in err  # never print the secret value

    def test_happy_path_threads_byo_pair_to_setup_google_auth(self, capsys):
        """auth google --client-id/--client-secret must reach setup_google_auth.

        mnemo_mcp.config.settings is a module-level singleton resolved at
        import time, so a prior regression wrote the BYO pair to os.environ
        (a no-op -- the singleton was already frozen) instead of threading
        it through run_setup_sync's params. This does NOT blanket-mock
        run_setup_sync: it lets the real function run (including its
        missing-credentials check) and only mocks the network-touching
        setup_google_auth, so the assertion below proves the pair actually
        reaches that call rather than being silently dropped.
        """
        from mnemo_mcp import cli

        with (
            patch.object(
                sys,
                "argv",
                [
                    "mnemo-mcp",
                    "auth",
                    "google",
                    "--client-id",
                    "my-id",
                    "--client-secret",
                    "my-secret",
                ],
            ),
            patch(
                "mnemo_mcp.sync.setup_google_auth",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_setup_google_auth,
        ):
            rc = cli.main()

        mock_setup_google_auth.assert_awaited_once_with(
            client_id="my-id", client_secret="my-secret"
        )
        assert rc == 0
        assert '"status": "authenticated"' in capsys.readouterr().out

    def test_no_flags_skips_byo_resolution(self, capsys):
        from mnemo_mcp import cli

        result = {"status": "error", "error": "boom"}
        with (
            patch.object(sys, "argv", ["mnemo-mcp", "auth", "google"]),
            patch(
                "mnemo_mcp.setup_tool.run_setup_sync",
                new=AsyncMock(return_value=result),
            ) as mock_setup,
        ):
            rc = cli.main()

        mock_setup.assert_awaited_once_with()
        assert rc == 1


class TestUnknownSubcommand:
    """build_cli's own unrecognized-subcommand handling -- rc 2, no server start."""

    def test_unknown_subcommand_returns_rc_2(self, capsys):
        from mnemo_mcp import cli

        with (
            patch.object(sys, "argv", ["mnemo-mcp", "bogus"]),
            patch("mnemo_mcp.server.main") as mock_server_main,
        ):
            rc = cli.main()

        mock_server_main.assert_not_called()
        assert rc == 2
        assert "unknown subcommand" in capsys.readouterr().err


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
