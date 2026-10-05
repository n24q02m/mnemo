"""Verify mnemo runs as a real HTTP MCP server (de-host entry).

Spawns ``python -m mnemo`` on an ephemeral loopback port and exercises the
initialize handshake plus ``tools/list`` over the streamable-HTTP MCP
transport, proving the FastMCP HTTP app is wired directly (no bridge layer in
front of it). There is no stdio mode post-de-host.

Marked ``live`` because it spawns a real subprocess and speaks the MCP
protocol; excluded from the default ``pytest`` invocation but runs under
``uv run pytest -m live``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from live_http import mcp_client_session, mnemo_http_server

pytestmark = [pytest.mark.live, pytest.mark.timeout(120)]


def _server_env(tmp_path: Path) -> dict[str, str]:
    """Parent env + an isolated ``~/.mnemo`` instance home under tmp_path."""
    home = tmp_path / "home"
    return {
        **os.environ,
        "LOG_LEVEL": "WARNING",
        "HOME": str(home),
        "USERPROFILE": str(home),
    }


async def test_http_direct_init_responds(tmp_path):
    """Spawn the HTTP server; verify the initialize response shape."""
    async with mnemo_http_server(
        _server_env(tmp_path), tmp_path / "server.log"
    ) as port:
        async with mcp_client_session(port) as session:
            result = await session.initialize()
            # FastMCP negotiates protocol version; just assert it returned one.
            assert result.protocolVersion
            # Server name is "Mnemo" per FastMCP("Mnemo", ...) in server.py.
            assert result.serverInfo.name == "Mnemo"


async def test_http_direct_tools_list_returns_expected_tools(tmp_path):
    """Verify tools/list returns the full de-hosted mnemo tool set."""
    async with mnemo_http_server(
        _server_env(tmp_path), tmp_path / "server.log"
    ) as port:
        async with mcp_client_session(port) as session:
            await session.initialize()
            result = await session.list_tools()
            tool_names = {t.name for t in result.tools}
            expected = {
                "add_memory",
                "search_memory",
                "list_memories",
                "update_memory",
                "delete_memory",
                "export_memories",
                "import_memories",
                "memory_stats",
                "restore_memory",
                "archived_memories",
                "consolidate_memories",
                "memory",
                "config",
            }
            assert expected == tool_names, (
                f"missing={expected - tool_names} unexpected={tool_names - expected}"
            )
