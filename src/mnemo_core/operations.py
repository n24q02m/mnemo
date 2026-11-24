"""Domain operations for the mnemo pilot (TOOL-1 / P0).

Rules (spec `2026-09-10-mnemo-pilot-mn1-6-tool1-design.md` section 2):

1. This module NEVER imports a surface module (mnemo server, mnemo_cli)
   and NEVER reads ``os.environ`` — subject context arrives explicitly.
2. Every operation returns the shared envelope from ``mnemo_core.results``;
   surfaces only parse input and serialize the envelope.
3. Errors are mapped to the shared taxonomy here, in exactly one place.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from mnemo_core import results
from mnemo_core.defense import evaluate_poison_risk, redact
from mnemo_core.ports import CapExceeded, ReflectPort, StoragePort
from mnemo_core.rewrite import rewrite_query

logger = logging.getLogger(__name__)

# Mirrors mnemo.db.MAX_CONTENT_LENGTH (validated at the DB layer too);
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
    blocked, confidence, poison_findings = evaluate_poison_risk(content, source=source)
    if blocked:
        kinds_str = ", ".join(f["kind"] for f in poison_findings)
        return results.err(
            results.VALIDATION, f"blocked prompt injection ({kinds_str})"
        )
    persisted, kinds = redact(content)
    contradictions: list[dict[str, Any]] = []
    detect_fn = getattr(store, "detect_contradictions", None)
    if callable(detect_fn):
        try:
            contradictions = list(detect_fn(persisted, subject=subject) or [])
        except Exception:
            contradictions = []
    try:
        memory_id = store.add(
            content=persisted,
            category=category,
            tags=tags,
            source=source,
            subject=subject,
        )
        if confidence < 1.0:
            set_conf = getattr(store, "set_confidence", None)
            if callable(set_conf):
                set_conf(memory_id, confidence)
    except ValueError as exc:
        return results.err(results.VALIDATION, str(exc))
    except sqlite3.Error:
        logger.exception("capture failed")
        return results.err(results.STORAGE, "capture failed")
    except Exception:  # noqa: BLE001 - taxonomy boundary
        logger.exception("unexpected failure")
        return results.err(results.INTERNAL, "unexpected failure")
    payload: dict[str, Any] = {
        "id": memory_id,
        "subject": subject,
        "category": category,
        "tags": tags or [],
        "redactions": kinds,
        "confidence": confidence,
    }
    if contradictions:
        payload["contradictions"] = contradictions
    return results.ok(payload)


def recall(
    store: StoragePort,
    subject: str | None,
    query: str,
    k: int = 5,
    include_standing: bool = False,
    *,
    context: list[str] | None = None,
    compact: bool = False,
    rewrite: bool = True,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Search a subject's memories. Returns the recall envelope.

    MN-5: standing pages (``category="_standing"``) are excluded by
    default — they are materialized reflect answers consumed via
    ``standing_read``, not ordinary recall hits. Pass
    ``include_standing=True`` to restore the legacy mixed behavior.
    """
    if query is None or not query.strip():
        return results.err(results.VALIDATION, "query is required")
    if k < 1:
        return results.err(results.VALIDATION, "k must be >= 1")
    rw = (
        rewrite_query(query, context=context)
        if rewrite
        else {
            "original": query,
            "resolved": query,
            "bilingual_alternatives": [],
            "resolved_pronouns": [],
            "temporal": {
                "since": None,
                "until": None,
                "prefer_recent": False,
                "matched": None,
            },
        }
    )
    effective_query = rw["resolved"]
    try:
        rows = list(store.search(effective_query, limit=k, subject=subject))
        seen_ids = {r.get("id") for r in rows if r.get("id") is not None}
        if len(rows) < k and rw["bilingual_alternatives"]:
            for alt in rw["bilingual_alternatives"][:2]:
                for hit in store.search(alt, limit=k, subject=subject):
                    hid = hit.get("id")
                    if hid not in seen_ids:
                        seen_ids.add(hid)
                        rows.append(hit)
                if len(rows) >= k:
                    break
        if not include_standing:
            rows = [row for row in rows if row.get("category") != "_standing"]
    except sqlite3.Error:
        logger.exception("recall failed")
        return results.err(results.STORAGE, "recall failed")
    except Exception:  # noqa: BLE001 - taxonomy boundary
        logger.exception("unexpected failure")
        return results.err(results.INTERNAL, "unexpected failure")

    # Apply explicit temporal bounds if requested, or boost matches in inferred window.
    win_since = since or rw["temporal"]["since"]
    win_until = until or rw["temporal"]["until"]
    if since or until:
        filtered = []
        for row in rows:
            ts = str(row.get("valid_from") or row.get("created_at") or "")
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            filtered.append(row)
        rows = filtered
    elif win_since or win_until or rw["temporal"]["prefer_recent"]:

        def _temporal_key(row: dict[str, Any]) -> tuple[int, str, float]:
            ts = str(row.get("valid_from") or row.get("created_at") or "")
            in_win = 1
            if win_since and ts < win_since:
                in_win = 0
            if win_until and ts > win_until:
                in_win = 0
            return (in_win, ts, float(row.get("score") or 0.0))

        rows = sorted(rows, key=_temporal_key, reverse=True)

    rows = rows[:k]
    matches, egress_kinds = _redact_rows(rows)
    if compact:
        matches = [
            {
                "id": m.get("id"),
                "snippet": str(m.get("content") or "")[:120],
                "category": m.get("category"),
                "score": m.get("score"),
                "updated_at": m.get("updated_at"),
                "valid_from": m.get("valid_from"),
            }
            for m in matches
        ]
    return results.ok(
        {
            "subject": subject,
            "query": query,
            "resolved_query": effective_query,
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
    except sqlite3.Error:
        logger.exception("fetch failed")
        return results.err(results.STORAGE, "fetch failed")
    except Exception:  # noqa: BLE001 - taxonomy boundary
        logger.exception("unexpected failure")
        return results.err(results.INTERNAL, "unexpected failure")
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
    except sqlite3.Error:
        logger.exception("reflect retrieval failed")
        return results.err(results.STORAGE, "reflect retrieval failed")
    except Exception:  # noqa: BLE001 - taxonomy boundary
        logger.exception("unexpected failure")
        return results.err(results.INTERNAL, "unexpected failure")
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
    except Exception:  # noqa: BLE001 - taxonomy boundary
        logger.exception("provider failed")
        return results.err(results.INTERNAL, "provider failed")
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


def forget(
    store: StoragePort,
    subject: str | None,
    memory_id: str,
    *,
    hard: bool = False,
) -> dict[str, Any]:
    """Forget a memory (soft-archive by default, or hard delete if ``hard=True``)."""
    if not memory_id or not memory_id.strip():
        return results.err(results.VALIDATION, "memory_id is required")
    mid = memory_id.strip()
    try:
        if hard:
            ok = bool(store.delete(mid, subject=subject))
            mode = "hard"
        else:
            soft_fn = getattr(store, "soft_archive", None)
            if callable(soft_fn):
                ok = bool(soft_fn(mid, subject=subject))
                mode = "soft_archive"
            else:
                ok = bool(store.delete(mid, subject=subject))
                mode = "hard"
    except sqlite3.Error:
        logger.exception("forget failed")
        return results.err(results.STORAGE, "forget failed")
    except Exception:  # noqa: BLE001 - taxonomy boundary
        logger.exception("unexpected failure")
        return results.err(results.INTERNAL, "unexpected failure")
    if not ok:
        return results.err(results.NOT_FOUND, f"memory not found: {mid}")
    return results.ok(
        {
            "id": mid,
            "subject": subject,
            "forgotten": True,
            "mode": mode,
        }
    )


def timeline(
    store: Any,
    subject: str | None,
    *,
    entity: str | None = None,
    since: str | None = None,
    until: str | None = None,
    include_superseded: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """Return a chronological memory timeline, optionally filtered by entity and time."""
    if limit < 1:
        return results.err(results.VALIDATION, "limit must be >= 1")
    try:
        from mnemo.temporal.queries import build_timeline

        entries = build_timeline(
            store,
            subject=subject,
            entity=entity,
            since=since,
            until=until,
            include_superseded=include_superseded,
            limit=limit,
        )
    except sqlite3.Error:
        logger.exception("timeline failed")
        return results.err(results.STORAGE, "timeline failed")
    except Exception:  # noqa: BLE001 - taxonomy boundary
        logger.exception("unexpected failure")
        return results.err(results.INTERNAL, "unexpected failure")
    redacted_entries, egress_kinds = _redact_rows(entries)
    return results.ok(
        {
            "subject": subject,
            "entity": entity,
            "count": len(redacted_entries),
            "entries": redacted_entries,
            "redactions": egress_kinds,
        }
    )


def entity_graph(
    store: Any,
    subject: str | None,
    entity_query: str,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    """Return matched entities, relations, and chronological evolution timeline."""
    if not entity_query or not entity_query.strip():
        return results.err(results.VALIDATION, "entity_query is required")
    if limit < 1:
        return results.err(results.VALIDATION, "limit must be >= 1")
    try:
        from mnemo.temporal.resolve import entity_evolution

        if hasattr(store, "connection"):
            with store.connection() as conn:
                evo = entity_evolution(
                    conn, entity_query.strip(), subject=subject, limit=limit
                )
        else:
            return results.err(
                results.VALIDATION, "store does not support graph queries"
            )
    except sqlite3.Error:
        logger.exception("entity_graph failed")
        return results.err(results.STORAGE, "entity_graph failed")
    except Exception:  # noqa: BLE001 - taxonomy boundary
        logger.exception("unexpected failure")
        return results.err(results.INTERNAL, "unexpected failure")
    timeline_rows, egress_kinds = _redact_rows(list(evo.get("timeline") or []))
    evo["timeline"] = timeline_rows
    evo["subject"] = subject
    evo["redactions"] = egress_kinds
    return results.ok(evo)
