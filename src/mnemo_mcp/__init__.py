"""Mnemo MCP Server - Persistent AI memory with embedded sync."""

from mnemo_mcp.__main__ import _cli as main
from mnemo_mcp.server import mcp

__version__ = "0.1.0-beta.1"
__all__ = ["mcp", "main", "__version__"]
