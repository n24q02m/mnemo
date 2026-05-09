"""Mnemo MCP Server - Persistent AI memory with embedded sync."""

from importlib.metadata import version

from mnemo_mcp.server import main

__version__ = version("mnemo-mcp")
__all__ = ["main", "__version__"]
