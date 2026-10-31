"""Mnemo MCP Server - Persistent AI memory with embedded sync."""

from importlib.metadata import version

from mnemo.server import main

try:
    __version__ = version("n24q02m-mnemo")
except Exception:
    __version__ = version("mnemo-mcp")
__all__ = ["main", "__version__"]
