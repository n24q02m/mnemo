"""Tests for mnemo.cli -- HTTP MCP server entry point.

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
        from mnemo import cli

        with (
            patch.object(sys, "argv", ["n24q02m-mnemo"]),
            patch("mnemo.server.main") as mock_server_main,
        ):
            rc = cli.main()

        mock_server_main.assert_called_once()
        assert rc == 0

    def test_unknown_flag_is_rejected_by_argparse(self):
        """There is no --http spawn mode anymore: unknown flags exit rc 2."""
        from mnemo import cli

        with (
            patch.object(sys, "argv", ["n24q02m-mnemo", "--http"]),
            patch("mnemo.server.main") as mock_server_main,
            pytest.raises(SystemExit) as excinfo,
        ):
            cli.main()

        assert excinfo.value.code == 2
        mock_server_main.assert_not_called()


class TestUnknownSubcommand:
    """argparse rejects unrecognized subcommands -- rc 2, no server start."""

    def test_unknown_subcommand_returns_rc_2(self, capsys):
        from mnemo import cli

        with (
            patch.object(sys, "argv", ["n24q02m-mnemo", "bogus"]),
            patch("mnemo.server.main") as mock_server_main,
            pytest.raises(SystemExit) as excinfo,
        ):
            cli.main()

        mock_server_main.assert_not_called()
        assert excinfo.value.code == 2
        assert "invalid choice" in capsys.readouterr().err


class TestWarmupSubcommand:
    """`n24q02m-mnemo warmup` -- run_warmup, no argument-taking configure."""

    def test_happy_path(self, capsys):
        from mnemo import cli

        result = {"status": "ok", "mode": "local", "steps": []}
        with (
            patch.object(sys, "argv", ["n24q02m-mnemo", "warmup"]),
            patch(
                "mnemo.setup_tool.run_warmup", new=AsyncMock(return_value=result)
            ) as mock_warmup,
        ):
            rc = cli.main()

        mock_warmup.assert_awaited_once_with()
        assert rc == 0
        assert '"mode": "local"' in capsys.readouterr().out

    def test_error_status_returns_nonzero(self):
        from mnemo import cli

        result = {"status": "error", "steps": []}
        with (
            patch.object(sys, "argv", ["n24q02m-mnemo", "warmup"]),
            patch("mnemo.setup_tool.run_warmup", new=AsyncMock(return_value=result)),
        ):
            rc = cli.main()

        assert rc == 1


class TestConfigSubcommands:
    """`mnemo config set|get|path|show` edits the file in place, like hull."""

    @staticmethod
    def _config(tmp_path, monkeypatch):
        path = tmp_path / "config.toml"
        path.write_text(
            '[server]\nhost = "127.0.0.1"\nport = 8000\n# auth = "token"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr("mnemo.runtime.mnemo_config_path", lambda: path)
        return path

    def test_set_keeps_comments_and_get_reads_it_back(self, tmp_path, monkeypatch, capsys):
        from mnemo import cli

        path = self._config(tmp_path, monkeypatch)
        with patch.object(sys, "argv", ["n24q02m-mnemo", "config", "set", "server.port", "8771"]):
            assert cli.main() == 0
        body = path.read_text(encoding="utf-8")
        assert "port = 8771" in body
        assert '# auth = "token"' in body

        with patch.object(sys, "argv", ["n24q02m-mnemo", "config", "get", "server.port"]):
            assert cli.main() == 0
        assert capsys.readouterr().out.strip().splitlines()[-1] == "8771"

    def test_a_token_is_masked_and_a_hash_is_not(self, tmp_path, monkeypatch, capsys):
        from mnemo import cli

        self._config(tmp_path, monkeypatch)
        with patch.object(
            sys, "argv", ["n24q02m-mnemo", "config", "set", "server.token_hash", "scrypt$abc"]
        ):
            assert cli.main() == 0
        assert "scrypt$abc" in capsys.readouterr().out

        with patch.object(sys, "argv", ["n24q02m-mnemo", "config", "set", "server.token", "s3cr3t"]):
            assert cli.main() == 0
        out = capsys.readouterr().out
        assert "s3cr3t" not in out and "*** (value not echoed)" in out

    def test_set_on_a_missing_section_fails_with_a_reason(self, tmp_path, monkeypatch, capsys):
        from mnemo import cli

        self._config(tmp_path, monkeypatch)
        with patch.object(
            sys, "argv", ["n24q02m-mnemo", "config", "set", "nope.key", "1"]
        ):
            assert cli.main() == 2
        assert "section [nope] not found" in capsys.readouterr().err

    def test_path_prints_the_config_location(self, tmp_path, monkeypatch, capsys):
        from mnemo import cli

        path = self._config(tmp_path, monkeypatch)
        with patch.object(sys, "argv", ["n24q02m-mnemo", "config", "path"]):
            assert cli.main() == 0
        assert capsys.readouterr().out.strip() == str(path)
