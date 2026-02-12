"""Mnemo MCP Server - Persistent AI memory with embedded sync."""

from importlib.metadata import version

from mnemo_mcp.__main__ import _cli as main
from mnemo_mcp.server import mcp

__version__ = version("mnemo-mcp")
__all__ = ["mcp", "main", "__version__"]
