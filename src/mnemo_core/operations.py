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
from mnemo_core.ports import CapExceeded, ReflectPort, StoragePort

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
        row = store.get(memory_id, subject=subject)
    except sqlite3.Error as exc:
        return results.err(results.STORAGE, f"fetch failed: {exc}")
    except Exception as exc:  # noqa: BLE001 - taxonomy boundary
        return results.err(results.INTERNAL, f"unexpected failure: {exc}")
    if row is None:
        return results.err(results.NOT_FOUND, f"memory {memory_id!r} not found")
    memory, kinds = _redact_row(row)
    return results.ok({"subject": subject, "memory": memory, "redactions": kinds})


_MAX_REFLECT_K = 10


def reflect(
    store: StoragePort,
    subject: str | None,
    query: str,
    k: int = 5,
    provider: ReflectPort | None = None,
) -> dict[str, Any]:
    """Bounded cited reflect (P4).

    Dry path (``provider is None``, default): the answer is composed ONLY
    from retrieval results (extractive: the best match's redacted content is
    returned verbatim as ``answer``). Zero model calls.

    Paid path (``provider`` given): the redacted citations and the query are
    handed to the provider and its completion becomes ``answer``. The provider
    is invoked ONLY when retrieval has support — an abstention makes no call.
    Citations never carry unredacted content across the boundary in either
    path. Reflect never writes back. The cost receipt is always present so
    the caller can audit boundedness.
    """
    if not query or not query.strip():
        return results.err(results.VALIDATION, "query is required")
    if k < 1:
        return results.err(results.VALIDATION, "k must be >= 1")
    try:
        rows = store.search(
            query.strip(), limit=min(k, _MAX_REFLECT_K), subject=subject
        )
    except sqlite3.Error as exc:
        return results.err(results.STORAGE, f"reflect retrieval failed: {exc}")
    except Exception as exc:  # noqa: BLE001 - taxonomy boundary
        return results.err(results.INTERNAL, f"unexpected failure: {exc}")
    citations, redactions = _redact_rows(
        [
            {
                "id": row.get("id"),
                "subject": row.get("subject"),
                "content": row.get("content"),
                "score": row.get("score"),
            }
            for row in rows
        ]
    )
    receipt: dict[str, Any] = {
        "model_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    if not citations:
        return results.ok(
            {
                "subject": subject,
                "answer": None,
                "abstained": True,
                "reason": "no_retrieval_support",
                "citations": [],
                "redactions": [],
                "cost": receipt,
            }
        )
    if provider is None:
        return results.ok(
            {
                "subject": subject,
                "answer": citations[0]["content"],
                "abstained": False,
                "citations": citations,
                "redactions": redactions,
                "cost": receipt,
            }
        )
    try:
        answer = provider.synthesize(query.strip(), citations)
    except CapExceeded as exc:
        return results.err(results.CAP, str(exc))
    except Exception as exc:  # noqa: BLE001 - taxonomy boundary
        return results.err(results.INTERNAL, f"provider failed: {exc}")
    receipt.update(
        {
            "model_calls": 1,
            "prompt_tokens": answer["prompt_tokens"],
            "completion_tokens": answer["completion_tokens"],
            "model": answer["model"],
            "est_cost_usd": round(
                provider.estimate_cost(
                    answer["prompt_tokens"], answer["completion_tokens"]
                ),
                6,
            ),
            "session_spent_usd": round(provider.spent_usd, 6),
        }
    )
    return results.ok(
        {
            "subject": subject,
            "answer": answer["text"],
            "abstained": False,
            "citations": citations,
            "redactions": redactions,
            "cost": receipt,
        }
    )


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
