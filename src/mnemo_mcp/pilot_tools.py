"""Pilot MCP-shaped handlers over mnemo_core (TOOL-1, P0).

These are the functions a FastMCP ``@mcp.tool`` registration will wrap in
P0.1 (thin: parse the tool-args dict, call the core, return the envelope).
They exist as plain functions so the equivalence harness can exercise the
exact MCP call path in-process without a running server. The existing rich
tools in ``mnemo_mcp.server`` are untouched.
"""

from __future__ import annotations

from typing import Any

from mnemo_core import operations
from mnemo_mcp.db import MemoryDB


def pilot_capture(db: MemoryDB, subject: str | None, args: dict[str, Any]) -> dict:
    """MCP tool ``pilot_capture``: args dict in, envelope out."""
    return operations.capture(
        db,
        subject,
        args.get("content", ""),
        tags=args.get("tags"),
        category=args.get("category", "general"),
        source=args.get("source"),
    )


def pilot_recall(db: MemoryDB, subject: str | None, args: dict[str, Any]) -> dict:
    """MCP tool ``pilot_recall``: args dict in, envelope out."""
    return operations.recall(db, subject, args.get("query", ""), k=args.get("k", 5))


def pilot_fetch(db: MemoryDB, subject: str | None, args: dict[str, Any]) -> dict:
    """MCP tool ``pilot_fetch``: args dict in, envelope out."""
    return operations.fetch(db, subject, args.get("memory_id", ""))
