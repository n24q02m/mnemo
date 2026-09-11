"""Domain operations for the mnemo pilot (TOOL-1 / P0).

Rules (spec `2026-09-10-mnemo-pilot-mn1-6-tool1-design.md` section 2):

1. This module NEVER imports a surface module (mnemo_mcp server, mnemo_cli)
   and NEVER reads ``os.environ`` — subject context arrives explicitly.
2. Every operation returns the shared envelope from ``mnemo_core.results``;
   surfaces only parse input and serialize the envelope.
3. Errors are mapped to the shared taxonomy here, in exactly one place.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from mnemo_core import results
from mnemo_core.defense import redact
from mnemo_core.ports import StoragePort

# Mirrors mnemo_mcp.db.MAX_CONTENT_LENGTH (validated at the DB layer too);
# re-declared here so VALIDATION mapping does not depend on the adapter.
_MAX_CONTENT_LENGTH = 20_000


def capture(
    store: StoragePort,
    subject: str | None,
    content: str,
    tags: list[str] | None = None,
    category: str = "general",
    source: str | None = None,
) -> dict[str, Any]:
    """Store one memory for a subject. Returns the capture envelope."""
    if content is None or not content.strip():
        return results.err(results.VALIDATION, "content is required")
    persisted, kinds = redact(content)
    try:
        memory_id = store.add(
            content=persisted,
            category=category,
            tags=tags,
            source=source,
            subject=subject,
        )
    except ValueError as exc:
        return results.err(results.VALIDATION, str(exc))
    except sqlite3.Error as exc:
        return results.err(results.STORAGE, f"capture failed: {exc}")
    except Exception as exc:  # noqa: BLE001 - taxonomy boundary
        return results.err(results.INTERNAL, f"unexpected failure: {exc}")
    return results.ok(
        {
            "id": memory_id,
            "subject": subject,
            "category": category,
            "tags": tags or [],
            "redactions": kinds,
        }
    )


def recall(
    store: StoragePort,
    subject: str | None,
    query: str,
    k: int = 5,
) -> dict[str, Any]:
    """Search a subject's memories. Returns the recall envelope."""
    if query is None or not query.strip():
        return results.err(results.VALIDATION, "query is required")
    if k < 1:
        return results.err(results.VALIDATION, "k must be >= 1")
    try:
        rows = store.search(query, limit=k, subject=subject)
    except sqlite3.Error as exc:
        return results.err(results.STORAGE, f"recall failed: {exc}")
    except Exception as exc:  # noqa: BLE001 - taxonomy boundary
        return results.err(results.INTERNAL, f"unexpected failure: {exc}")
    matches, egress_kinds = _redact_rows(rows)
    return results.ok(
        {
            "subject": subject,
            "query": query,
            "matches": matches,
            "redactions": egress_kinds,
        }
    )


def fetch(
    store: StoragePort,
    subject: str | None,
    memory_id: str,
) -> dict[str, Any]:
    """Fetch one memory by id. Returns the fetch envelope."""
    if not memory_id:
        return results.err(results.VALIDATION, "memory_id is required")
    try:
        row = store.get(memory_id)
    except sqlite3.Error as exc:
        return results.err(results.STORAGE, f"fetch failed: {exc}")
    except Exception as exc:  # noqa: BLE001 - taxonomy boundary
        return results.err(results.INTERNAL, f"unexpected failure: {exc}")
    if row is None:
        return results.err(results.NOT_FOUND, f"memory {memory_id!r} not found")
    memory, kinds = _redact_row(row)
    return results.ok({"subject": subject, "memory": memory, "redactions": kinds})


def _redact_row(row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Egress defense: redact stored content before it leaves the core."""
    content = row.get("content") if isinstance(row, dict) else None
    if not isinstance(content, str):
        return row, []
    persisted, kinds = redact(content)
    if kinds:
        row = dict(row)
        row["content"] = persisted
    return row, kinds


def _redact_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    out: list[dict[str, Any]] = []
    all_kinds: list[str] = []
    for row in rows:
        redacted, kinds = _redact_row(row)
        out.append(redacted)
        all_kinds.extend(kinds)
    return out, all_kinds
