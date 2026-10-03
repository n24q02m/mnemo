"""Edge paths in mnemo.runtime (config/users/auth assembly) and the CLI."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hull_core.auth.middleware import Authenticator
from hull_core.auth.tokens import hash_token, verify_token
from hull_core.config.settings import HullSettings, ServerSettings

from mnemo import cli
from mnemo.runtime import (
    cell_configured,
    load_users_for,
    mnemo_config_dir,
    mnemo_config_path,
    write_default_config,
)

# ---------------------------------------------------------------------------
# runtime: config paths
# ---------------------------------------------------------------------------


def test_config_paths_follow_home(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert mnemo_config_dir() == tmp_path / ".mnemo"
    assert mnemo_config_path() == tmp_path / ".mnemo" / "config.toml"


# ---------------------------------------------------------------------------
# runtime: load_users_for
# ---------------------------------------------------------------------------


def _settings(auth: str, users_file: Path | None = None) -> HullSettings:
    return HullSettings(
        config_dir=Path("/unused"),
        server=ServerSettings(auth=auth, users_file=users_file),
    )


def test_load_users_for_non_multi_returns_none():
    assert load_users_for(_settings("no-auth")) is None
    assert load_users_for(_settings("token")) is None


def test_load_users_for_multi_requires_users_file():
    with pytest.raises(RuntimeError, match="users_file"):
        load_users_for(_settings("multi", users_file=None))


def test_load_users_for_multi_parses_users(tmp_path: Path):
    users_file = tmp_path / "users.toml"
    users_file.write_text(
        "\n".join(
            [
                "[users.alice]",
                f'token_hash = "{hash_token("alice-secret")}"',
                "enabled = true",
                'namespace = "alice"',
                "[users.alice.limits]",
                "rpm = 60",
            ]
        ),
        encoding="utf-8",
    )
    users = load_users_for(_settings("multi", users_file=users_file))
    assert users is not None, "load_users_for must return the user table"
    assert set(users) == {"alice"}
    assert users["alice"].namespace == "alice"
    assert users["alice"].limits is not None


# ---------------------------------------------------------------------------
# runtime: build_authenticator / cell_configured
# ---------------------------------------------------------------------------


def test_build_authenticator_no_auth_default_limiter():
    from mnemo.runtime import build_authenticator

    authenticator = build_authenticator(_settings("no-auth"))
    assert isinstance(authenticator, Authenticator)
    assert authenticator.mode == "no-auth"
    assert authenticator.limiter is not None


def test_build_authenticator_passes_limiter_through():
    from mnemo.runtime import build_authenticator

    limiter = MagicMock()
    authenticator = build_authenticator(_settings("no-auth"), limiter=limiter)
    assert authenticator.limiter is limiter


def test_cell_configured_reflects_model_cell(monkeypatch):
    cell = MagicMock()
    cell.configured = True
    monkeypatch.setattr("mnemo.runtime.model_cell", lambda task, s=None: cell)
    assert cell_configured("embed") is True
    cell.configured = False
    assert cell_configured("embed") is False


# ---------------------------------------------------------------------------
# runtime: write_default_config
# ---------------------------------------------------------------------------


def test_write_default_config_creates_then_refuses_then_forces(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    from mnemo.runtime import CONFIG_TEMPLATE

    path = write_default_config()
    assert path == tmp_path / ".mnemo" / "config.toml"
    assert path.read_text(encoding="utf-8") == CONFIG_TEMPLATE

    with pytest.raises(FileExistsError, match="use --force"):
        write_default_config()

    path.write_text("# overwritten", encoding="utf-8")
    forced = write_default_config(force=True)
    assert forced.read_text(encoding="utf-8") == CONFIG_TEMPLATE


# ---------------------------------------------------------------------------
# cli: token hash / verify / config-init / bare dispatch
# ---------------------------------------------------------------------------


class TestTokenHash:
    def test_hashes_token_from_env(self, monkeypatch, capsys):
        monkeypatch.setenv("MNEMO_AUTH_TOKEN", "s3cret")
        rc = cli._handle_token_hash(MagicMock())
        out = capsys.readouterr().out.strip()
        assert rc == 0
        # The printed encoding is a fresh random-salt hash that verifies.
        assert out.startswith("scrypt$")
        assert verify_token("s3cret", out)

    def test_empty_token_is_rejected(self, monkeypatch, capsys):
        monkeypatch.delenv("MNEMO_AUTH_TOKEN", raising=False)
        monkeypatch.setattr("getpass.getpass", lambda _prompt: "")
        rc = cli._handle_token_hash(MagicMock())
        captured = capsys.readouterr()
        assert rc == 2
        assert "empty token" in captured.err


class TestTokenVerify:
    def test_valid_token_prints_ok(self, capsys):
        encoded = hash_token("s3cret")
        rc = cli._handle_token_verify(argparse_ns(token="s3cret", encoded=encoded))
        assert rc == 0
        assert "OK" in capsys.readouterr().out

    def test_wrong_token_fails(self, capsys):
        encoded = hash_token("s3cret")
        rc = cli._handle_token_verify(argparse_ns(token="other", encoded=encoded))
        assert rc == 1
        assert "FAIL" in capsys.readouterr().out

    def test_malformed_encoding_returns_2(self, capsys):
        rc = cli._handle_token_verify(
            argparse_ns(token="s3cret", encoded="not-a-scrypt-hash")
        )
        assert rc == 2
        assert "mnemo-mcp:" in capsys.readouterr().out


def argparse_ns(**kw):
    import argparse

    return argparse.Namespace(**kw)


class TestConfigInit:
    def test_writes_default_config(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        rc = cli._handle_config_init(argparse_ns(force=False))
        out = capsys.readouterr().out
        assert rc == 0
        assert "Wrote" in out
        assert (tmp_path / ".mnemo" / "config.toml").is_file()

    def test_force_overwrites_existing(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        config_path = tmp_path / ".mnemo" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("# stale", encoding="utf-8")
        rc = cli._handle_config_init(argparse_ns(force=True))
        assert rc == 0
        assert "# stale" not in config_path.read_text(encoding="utf-8")


def test_main_bare_invocation_serves(monkeypatch):
    """Bare argv falls through to the serve path."""
    monkeypatch.setattr(sys, "argv", ["mnemo-mcp"])
    with patch("mnemo.cli._serve", return_value=None) as serve:
        assert cli.main() == 0
    serve.assert_called_once_with([])


def test_main_dispatches_subcommand(monkeypatch):
    monkeypatch.setenv("MNEMO_AUTH_TOKEN", "s3cret")
    monkeypatch.setattr(sys, "argv", ["mnemo-mcp", "token-hash"])
    assert cli.main() == 0
