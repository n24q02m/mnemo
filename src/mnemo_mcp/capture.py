"""Smart capture pipeline for ``memory(action="capture")``.

Phase 1 v0 wires the typed capture API on top of the existing dedup primitives
in :mod:`mnemo_mcp.db`. The pipeline:

1. Validate ``context_type`` is one of the six canonical kinds
   (conversation/fact/preference/skill/task/decision) — invalid values raise
   ``ValueError`` so callers can surface a structured error to the LLM.
2. Run a dedup probe via :meth:`MemoryDB.check_duplicate`. When the similarity
   score is at or above ``DEDUP_THRESHOLD`` (env-driven, default 0.92), return
   the existing memory id instead of inserting a duplicate row.
3. Otherwise call :meth:`MemoryDB.add_with_context_type`, which writes the
   ``context_type`` column added by the ``mem_001_context_types`` Alembic
   migration.

The ``auto`` flag is captured for forward-compat with the Phase 2 hook-based
auto-capture path. In Phase 1 v0 it is stored in the response payload so
clients (and tests) can confirm round-trip behaviour, but execution is
identical to ``auto=False``.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Final

from loguru import logger

if TYPE_CHECKING:
    from mnemo_mcp.db import MemoryDB


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Canonical context_type values per spec §4.1 / §6 (mem_001_context_types).
# Tests parametrize over this exact set; do not extend without bumping spec.
CONTEXT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "conversation",
        "fact",
        "preference",
        "skill",
        "task",
        "decision",
    }
)


_DEFAULT_DEDUP_THRESHOLD: Final[float] = 0.92


def _resolve_dedup_threshold() -> float:
    """Read ``DEDUP_THRESHOLD`` env var with a Phase 1 default of 0.92.

    The legacy ``MemoryDB.check_duplicate`` baseline lives at 0.9 so that
    add() retains permissive dedup; capture tightens to 0.92 so accidental
    paraphrases of the same fact reuse the existing row.
    """
    raw = os.environ.get("DEDUP_THRESHOLD")
    if not raw:
        return _DEFAULT_DEDUP_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            f"capture: DEDUP_THRESHOLD={raw!r} is not a float; "
            f"falling back to {_DEFAULT_DEDUP_THRESHOLD}"
        )
        return _DEFAULT_DEDUP_THRESHOLD
    return max(0.0, min(1.0, value))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def capture(
    db: MemoryDB,
    text: str,
    context_type: str = "conversation",
    *,
    category: str = "general",
    tags: list[str] | None = None,
    source: str | None = None,
    embedding: list[float] | None = None,
    importance: float | None = None,
    auto: bool = False,
) -> dict:
    """Capture ``text`` as a typed memory with embedding-aware dedup.

    Args:
        db: Live :class:`MemoryDB` instance from the lifespan context.
        text: Raw text to capture.
        context_type: One of :data:`CONTEXT_TYPES`. Raises ``ValueError`` when
            the value is unknown so the caller can return a structured tool
            error instead of writing an invalid row.
        category: Free-form bucket (defaults to "general", matches add()).
        tags: Optional tag list.
        source: Optional provenance marker.
        embedding: Optional dense vector — caller (server.py) embeds the text
            because the embedding backend lives in the lifespan context.
        importance: Optional importance score in [0.0, 1.0]. ``None`` defers
            to the schema default (0.5) so background importance scoring can
            update it later.
        auto: Forward-compat flag for hook-driven auto-capture (Phase 2).
            Stored in the response payload but does not change execution.

    Returns:
        A dict with at least ``memory_id``, ``deduplicated``, and ``auto``
        keys. When deduplication fires the response also contains
        ``similarity`` and ``existing_content`` from
        :meth:`MemoryDB.check_duplicate`.

    Raises:
        ValueError: If ``context_type`` is not in :data:`CONTEXT_TYPES`, or
            if ``text`` exceeds :data:`mnemo_mcp.db.MAX_CONTENT_LENGTH` (the
            underlying ``add_with_context_type`` raises).
    """
    if context_type not in CONTEXT_TYPES:
        raise ValueError(
            f"Unknown context_type {context_type!r}; "
            f"expected one of {sorted(CONTEXT_TYPES)}"
        )

    threshold = _resolve_dedup_threshold()

    # Dedup probe — runs FTS-backed similarity, never blocks on embedding.
    # Use to_thread because check_duplicate itself runs sync SQLite + search.
    dedup: dict | None = None
    try:
        dedup = await asyncio.to_thread(db.check_duplicate, text, threshold)
    except Exception as e:
        logger.warning(f"capture: dedup probe failed (non-blocking): {e}")
        dedup = None

    if dedup and dedup.get("duplicate") and dedup.get("similarity", 0.0) >= threshold:
        existing_id = dedup.get("existing_id", "")
        return {
            "memory_id": existing_id,
            "deduplicated": True,
            "similarity": dedup.get("similarity"),
            "existing_content": dedup.get("existing_content"),
            "context_type": context_type,
            "auto": auto,
        }

    memory_id = await asyncio.to_thread(
        db.add_with_context_type,
        content=text,
        context_type=context_type,
        category=category,
        tags=tags,
        source=source,
        embedding=embedding,
        importance=importance,
    )

    return {
        "memory_id": memory_id,
        "deduplicated": False,
        "context_type": context_type,
        "auto": auto,
    }
