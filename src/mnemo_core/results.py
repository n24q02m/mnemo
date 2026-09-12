"""Result envelopes shared by every mnemo pilot surface (CLI, MCP).

Both surfaces serialize these plain dicts identically, which is what the
P0 equivalence harness asserts: same operation + same args => byte-equal
envelope regardless of surface.
"""

from __future__ import annotations

from typing import Any

# Error taxonomy (spec section 2, rule 2). Values are stable wire codes.
VALIDATION = "VALIDATION"
NOT_FOUND = "NOT_FOUND"
AUTH_DENIED = "AUTH_DENIED"
STORAGE = "STORAGE"
CAP = "CAP"
INTERNAL = "INTERNAL"

_EXIT_CODES: dict[str, int] = {
    VALIDATION: 2,
    NOT_FOUND: 3,
    AUTH_DENIED: 4,
    STORAGE: 5,
    CAP: 6,
    INTERNAL: 1,
}


def ok(data: dict[str, Any]) -> dict[str, Any]:
    """Successful envelope."""
    return {"ok": True, "data": data}


def err(code: str, message: str) -> dict[str, Any]:
    """Failure envelope with a taxonomy code."""
    return {"ok": False, "error": {"code": code, "message": message}}


def exit_code(envelope: dict[str, Any]) -> int:
    """CLI exit code mapped from the envelope (0 on success)."""
    if envelope.get("ok"):
        return 0
    return _EXIT_CODES.get(envelope["error"]["code"], 1)
