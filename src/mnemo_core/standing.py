"""Standing questions / knowledge pages (MN-5 / P5, dry).

A standing page materializes a reflect answer together with the exact
source versions it was built from, so a later read is cheap (no search,
no recompute) and can verdict staleness deterministically.

Storage mapping (no schema migration): a page is a memory row with
``category="_standing"`` whose content is a JSON document. The pilot
tier has no update/delete, so pages follow the corpus-wide
newest-wins supersede semantics: the page with the highest id for
(subject, key) is the live one; refresh materializes a new page,
invalidation materializes a tombstone page. Staleness is computed on
read by re-fetching the pinned source ids and comparing content
hashes.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from mnemo_core import results
from mnemo_core.operations import reflect
from mnemo_core.ports import StoragePort

STANDING_CATEGORY = "_standing"


def _page_json(
    key: str,
    question: str,
    answer: str | None,
    sources: list[dict[str, Any]],
    *,
    tombstone: bool = False,
) -> str:
    return json.dumps(
        {
            "page": 1,
            "key": key,
            "question": question,
            "answer": answer,
            "tombstone": tombstone,
            "sources": sources,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def _content_sha(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _write_page(
    store: StoragePort,
    subject: str | None,
    content: str,
) -> dict[str, Any]:
    try:
        page_id = store.add(
            content=content,
            category=STANDING_CATEGORY,
            tags=None,
            source=None,
            subject=subject,
        )
    except ValueError as exc:
        return results.err(results.VALIDATION, str(exc))
    except sqlite3.Error as exc:
        return results.err(results.STORAGE, f"standing write failed: {exc}")
    except Exception as exc:  # noqa: BLE001 - taxonomy boundary
        return results.err(results.INTERNAL, f"unexpected failure: {exc}")
    return results.ok(
        {"id": page_id, "subject": subject, "category": STANDING_CATEGORY}
    )


def _newest_page(
    store: StoragePort, subject: str | None, key: str
) -> dict[str, Any] | None:
    """Newest-wins page lookup: latest created_at among matching rows."""
    try:
        rows = store.search(
            f'"{key}"', category=STANDING_CATEGORY, limit=25, subject=subject
        )
    except sqlite3.Error:
        return None
    best: dict[str, Any] | None = None
    best_order: tuple[str, str] = ("", "")
    for row in rows:
        if not isinstance(row, dict) or row.get("category") != STANDING_CATEGORY:
            continue
        try:
            doc = json.loads(row.get("content") or "")
        except (TypeError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("key") == key:
            order = (str(row.get("created_at") or ""), str(row.get("id") or ""))
            if order >= best_order:
                best_order = order
                best = row
    return best


def standing_refresh(
    store: StoragePort,
    subject: str | None,
    key: str,
    question: str,
    k: int = 5,
) -> dict[str, Any]:
    """Explicitly (re)materialize the page for (subject, key) via reflect."""
    if not key or not key.strip():
        return results.err(results.VALIDATION, "key is required")
    if not question or not question.strip():
        return results.err(results.VALIDATION, "question is required")
    reflected = reflect(store, subject, question.strip(), k=k)
    if not reflected.get("ok"):
        return reflected
    data = reflected["data"]
    sources = [
        {"id": c.get("id"), "sha": _content_sha(c.get("content"))}
        for c in data["citations"]
    ]
    content = _page_json(key.strip(), question.strip(), data["answer"], sources)
    written = _write_page(store, subject, content)
    if not written.get("ok"):
        return written
    return results.ok(
        {
            "id": written["data"]["id"],
            "subject": subject,
            "key": key.strip(),
            "answer": data["answer"],
            "abstained": data["abstained"],
            "sources": sources,
            "cost": data["cost"],
        }
    )


def standing_invalidate(
    store: StoragePort,
    subject: str | None,
    key: str,
    question: str = "",
) -> dict[str, Any]:
    """Materialize a tombstone page; the newest-wins read reports it."""
    if not key or not key.strip():
        return results.err(results.VALIDATION, "key is required")
    content = _page_json(key.strip(), question, None, [], tombstone=True)
    written = _write_page(store, subject, content)
    if not written.get("ok"):
        return written
    return results.ok(
        {
            "id": written["data"]["id"],
            "subject": subject,
            "key": key.strip(),
            "tombstone": True,
        }
    )


def standing_read(store: StoragePort, subject: str | None, key: str) -> dict[str, Any]:
    """Cheap read: newest page + staleness verdict, no recompute."""
    if not key or not key.strip():
        return results.err(results.VALIDATION, "key is required")
    row = _newest_page(store, subject, key.strip())
    if row is None:
        return results.err(
            results.NOT_FOUND, f"standing page {key.strip()!r} not found"
        )
    try:
        doc = json.loads(row.get("content") or "")
    except (TypeError, ValueError):
        return results.err(results.STORAGE, "standing page content is not valid JSON")
    if doc.get("tombstone"):
        return results.ok(
            {
                "id": row.get("id"),
                "subject": subject,
                "key": key.strip(),
                "tombstone": True,
                "answer": None,
                "staleness": "invalidated",
                "sources": [],
                "cost": {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0},
            }
        )
    staleness = "fresh"
    sources: list[dict[str, Any]] = []
    for src in doc.get("sources", []):
        try:
            live = store.get(src["id"], subject=subject)
        except sqlite3.Error as exc:
            return results.err(results.STORAGE, f"standing read failed: {exc}")
        except Exception as exc:  # noqa: BLE001 - taxonomy boundary
            return results.err(results.INTERNAL, f"unexpected failure: {exc}")
        if live is None:
            state = "missing"
            staleness = "stale:source_missing"
        else:
            changed = _content_sha(live.get("content")) != src.get("sha")
            state = "changed" if changed else "fresh"
            if changed:
                staleness = "stale:content_changed"
        sources.append({"id": src.get("id"), "state": state})
    return results.ok(
        {
            "id": row.get("id"),
            "subject": subject,
            "key": key.strip(),
            "tombstone": False,
            "answer": doc.get("answer"),
            "staleness": staleness,
            "sources": sources,
            "cost": {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0},
        }
    )
