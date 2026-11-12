"""Mnemo MCP Server - Persistent AI memory with hybrid search."""

from importlib.metadata import version

from mnemo.server import main

try:
    __version__ = version("n24q02m-mnemo")
except Exception:
    __version__ = version("mnemo-mcp")
__all__ = ["main", "__version__"]
