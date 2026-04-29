"""Smoke test: ``config__open_relay`` MCP tool is registered.

Verifies Wave 3 (Transparent Bridge v2) wiring — the
``register_open_relay_tool`` helper from ``n24q02m-mcp-core>=1.11.0`` is
called at module import time and the resulting tool appears in the
FastMCP server's tool list.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_config_open_relay_tool_registered():
    """`config__open_relay` is registered alongside the existing tools."""
    from mnemo_mcp.server import mcp

    tools = await mcp.list_tools()
    tool_names = {tool.name for tool in tools}

    assert "config__open_relay" in tool_names, (
        f"config__open_relay missing from registered tools: {sorted(tool_names)}"
    )
    # Sanity: pre-existing tools still present (no accidental clobber).
    assert {"memory", "config", "help"}.issubset(tool_names)
