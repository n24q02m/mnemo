"""Mnemo MCP Server - Persistent AI memory with embedded sync."""

from importlib.metadata import version

from mnemo_mcp.server import main, mcp

__version__ = version("mnemo-mcp")
__all__ = ["mcp", "main", "__version__"]
