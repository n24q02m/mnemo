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
    try:
        memory_id = store.add(
            content=content,
            category=category,
            tags=tags,
            source=source,
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
        rows = store.search(query, limit=k)
    except sqlite3.Error as exc:
        return results.err(results.STORAGE, f"recall failed: {exc}")
    except Exception as exc:  # noqa: BLE001 - taxonomy boundary
        return results.err(results.INTERNAL, f"unexpected failure: {exc}")
    return results.ok({"subject": subject, "query": query, "matches": rows})


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
    return results.ok({"subject": subject, "memory": row})
