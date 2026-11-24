"""Tests for mnemo MCP stdio transport, canonical ~/.n24q02m/mnemo storage, profiles, and default-DB CLI."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

from mnemo import cli, runtime
from mnemo.config import Settings
from mnemo_cli.__main__ import main as mnemo_cli_main


def test_default_dirs_use_n24q02m_mnemo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert runtime.mnemo_config_dir() == tmp_path / ".n24q02m" / "mnemo"
    assert Settings(db_path="").get_data_dir() == tmp_path / ".n24q02m" / "mnemo"


def test_n24q02m_home_and_xdg_overrides(tmp_path: Path, monkeypatch) -> None:
    custom_home = tmp_path / "custom-home"
    monkeypatch.setenv("N24Q02M_HOME", str(custom_home))
    assert runtime.mnemo_config_dir() == custom_home / "mnemo"

    monkeypatch.delenv("N24Q02M_HOME")
    xdg_cfg = tmp_path / "xdg-cfg"
    monkeypatch.setenv("N24Q02M_USE_XDG", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_cfg))
    monkeypatch.setenv("APPDATA", str(xdg_cfg))
    assert runtime.mnemo_config_dir() == xdg_cfg / "n24q02m" / "mnemo"


def test_legacy_mnemo_dir_migrates_non_destructively(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    legacy = tmp_path / ".mnemo"
    legacy.mkdir()
    (legacy / "config.toml").write_text("[server]\nport = 9123\n", encoding="utf-8")

    migrated = runtime.mnemo_config_dir()
    assert migrated == tmp_path / ".n24q02m" / "mnemo"
    assert (migrated / "config.toml").read_text(encoding="utf-8") == (
        "[server]\nport = 9123\n"
    )
    assert (legacy / "config.toml").is_file()


def test_profile_routes_config_path(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert cli.main(["--profile", "work", "config", "path"]) == 0
    out_work = Path(capsys.readouterr().out.strip())
    assert (
        out_work
        == tmp_path / ".n24q02m" / "mnemo" / "profiles" / "work" / "config.toml"
    )

    assert cli.main(["config", "path", "--profile", "staging"]) == 0
    out_staging = Path(capsys.readouterr().out.strip())
    assert (
        out_staging
        == tmp_path / ".n24q02m" / "mnemo" / "profiles" / "staging" / "config.toml"
    )


def test_mcp_cli_dispatches_stdio_and_http() -> None:
    with patch("mnemo.server.run_stdio") as mock_stdio:
        assert cli.main(["mcp"]) == 0
    mock_stdio.assert_called_once_with()

    with patch("mnemo.server.run_server_blocking") as mock_http:
        assert cli.main(["mcp", "--http", "--host", "127.0.0.1", "--port", "9099"]) == 0
    mock_http.assert_called_once_with(host="127.0.0.1", port=9099)


def test_run_stdio_calls_mcp_run_stdio() -> None:
    from mnemo import server

    with patch.object(server.mcp, "run") as mock_run:
        server.run_stdio()
    mock_run.assert_called_once_with(transport="stdio")


@pytest.mark.timeout(60)
async def test_stdio_wire_initialize_and_list_tools(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["USERPROFILE"] = str(tmp_path)
    env["DISABLE_LOCAL_EMBED"] = "true"
    env["DISABLE_LOCAL_RERANK"] = "true"
    for k in ("N24Q02M_HOME", "N24Q02M_USE_XDG", "MNEMO_PROFILE", "HULL_PROFILE"):
        env.pop(k, None)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mnemo.cli", "mcp"],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            info = getattr(init, "server_info", None) or init.serverInfo
            assert info.name == "Mnemo"

            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            assert {"add_memory", "search_memory", "list_memories", "config"}.issubset(
                names
            )


def test_mnemo_cli_default_db_and_profile(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    rc_cap = mnemo_cli_main(
        ["capture", "--profile", "team", "--subject", "dev", "remember alpha token"]
    )
    assert rc_cap == 0
    cap_out = json.loads(capsys.readouterr().out)
    assert cap_out["ok"] is True
    assert (
        tmp_path / ".n24q02m" / "mnemo" / "profiles" / "team" / "memories.db"
    ).is_file()

    rc_rec = mnemo_cli_main(
        ["recall", "--profile", "team", "--subject", "dev", "alpha"]
    )
    assert rc_rec == 0
    rec_out = json.loads(capsys.readouterr().out)
    assert rec_out["ok"] is True
    assert len(rec_out["data"]["matches"]) >= 1
