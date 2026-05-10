"""Phase 3 entity resolution: cross-memory dedup via embedding + name match.

When the LLM extracts the same real-world entity twice (e.g. "FastAPI" and
"Fast API", "K8s" and "Kubernetes") under different name strings, the
naive ``upsert_entities`` path stores both as distinct rows because the
unique index keys on ``(name, entity_type)``. Entity resolution closes
this gap by:

1. Looking up an embedding for the candidate name (via the configured
   embedding backend; gracefully skips when the backend is not ready).
2. Querying ``memory_entities_vec`` for an existing entity within the
   ``TEMPORAL_ENTITY_RESOLUTION_THRESHOLD`` cosine band (default 0.85).
3. If a match exists -> return its id (no new row); else INSERT the new
   entity AND its embedding into ``memory_entities`` + ``memory_entities_vec``.

When ``memory_entities_vec`` is unavailable (sqlite-vec extension absent
in the migration runner or embedding backend not initialised) the function
falls back to plain name + entity_type lookup so callers remain
deterministic.
"""

from __future__ import annotations

import os
import struct
import uuid
from datetime import UTC, datetime

from loguru import logger

_DEFAULT_THRESHOLD: float = 0.85
_EMBEDDING_DIMS: int = 768  # matches memories_vec / memory_entities_vec schema


def _resolve_threshold() -> float:
    raw = os.environ.get("TEMPORAL_ENTITY_RESOLUTION_THRESHOLD", "")
    if not raw.strip():
        return _DEFAULT_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            f"temporal.resolve: TEMPORAL_ENTITY_RESOLUTION_THRESHOLD={raw!r} "
            f"is not a float; using {_DEFAULT_THRESHOLD}"
        )
        return _DEFAULT_THRESHOLD
    return max(0.0, min(1.0, value))


def _serialize(vec: list[float]) -> bytes:
    n = min(len(vec), _EMBEDDING_DIMS)
    if n < _EMBEDDING_DIMS:
        vec = vec + [0.0] * (_EMBEDDING_DIMS - n)
    else:
        vec = vec[:_EMBEDDING_DIMS]
    return struct.Struct(f"{_EMBEDDING_DIMS}f").pack(*vec)


def _vec_table_exists(conn) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_entities_vec'"
    ).fetchone()
    return row is not None


def find_similar_entity(
    conn,
    name: str,
    entity_type: str,
    embedding: list[float] | None,
    threshold: float | None = None,
) -> str | None:
    """Return the id of an existing entity that matches ``name`` semantically.

    Two-stage match:

    1. **Exact name + type** -- the canonical Phase 1 lookup. This covers
       100% of replays of the same string and is cheap.
    2. **Embedding cosine** -- when ``embedding`` is provided AND
       ``memory_entities_vec`` exists, query the top-1 nearest neighbour
       and accept it when ``cosine_similarity >= threshold``.
       Cosine similarity is computed as ``1 - (vec_distance / 2)`` since
       sqlite-vec returns squared L2 on normalised vectors.

    Returns ``None`` when no acceptable match exists (caller should
    INSERT a new row).
    """
    threshold = threshold if threshold is not None else _resolve_threshold()

    # Stage 1: exact name + type (cheap, deterministic).
    row = conn.execute(
        "SELECT id FROM memory_entities WHERE name = ? AND entity_type = ?",
        (name, entity_type),
    ).fetchone()
    if row is not None:
        return row[0] if not hasattr(row, "keys") else row["id"]

    # Stage 2: embedding KNN.
    if embedding is None or not _vec_table_exists(conn):
        return None

    try:  # pragma: no cover - requires sqlite-vec; macOS sqlite3 lacks loadable ext
        rows = conn.execute(
            "SELECT v.rowid, v.distance FROM memory_entities_vec v "
            "WHERE v.embedding MATCH ? AND k = 1 "
            "ORDER BY v.distance",
            (_serialize(embedding),),
        ).fetchall()
    except Exception as e:  # pragma: no cover
        logger.debug(f"temporal.resolve: vec KNN failed (non-blocking): {e}")
        return None

    if not rows:  # pragma: no cover
        return None
    rowid = (
        rows[0][0] if not hasattr(rows[0], "keys") else rows[0]["rowid"]
    )  # pragma: no cover
    distance = (
        rows[0][1] if not hasattr(rows[0], "keys") else rows[0]["distance"]
    )  # pragma: no cover
    similarity = max(0.0, 1.0 - float(distance) / 2.0)  # pragma: no cover
    if similarity < threshold:  # pragma: no cover
        return None

    ent_row = conn.execute(  # pragma: no cover
        "SELECT id FROM memory_entities WHERE rowid = ?", (rowid,)
    ).fetchone()
    if ent_row is None:  # pragma: no cover
        return None
    return (
        ent_row[0] if not hasattr(ent_row, "keys") else ent_row["id"]
    )  # pragma: no cover


def insert_entity_with_embedding(
    conn,
    name: str,
    entity_type: str,
    embedding: list[float] | None,
) -> str:
    """INSERT a new entity row + parallel embedding row.

    Returns the new entity id.
    """
    new_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO memory_entities (id, name, entity_type, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(name, entity_type) DO UPDATE SET updated_at = excluded.updated_at",
        (new_id, name, entity_type, now, now),
    )
    # Re-fetch in case ON CONFLICT picked the existing row's id.
    actual = conn.execute(
        "SELECT id FROM memory_entities WHERE name = ? AND entity_type = ?",
        (name, entity_type),
    ).fetchone()
    actual_id = actual[0] if actual and not hasattr(actual, "keys") else actual["id"]

    # Parallel embedding row when vec table is present.
    if embedding is not None and _vec_table_exists(conn):  # pragma: no cover - vec ext
        try:
            ent_rowid = conn.execute(
                "SELECT rowid FROM memory_entities WHERE id = ?",
                (actual_id,),
            ).fetchone()
            if ent_rowid is not None:
                row_pk = (
                    ent_rowid[0]
                    if not hasattr(ent_rowid, "keys")
                    else ent_rowid["rowid"]
                )
                conn.execute(
                    "DELETE FROM memory_entities_vec WHERE rowid = ?", (row_pk,)
                )
                conn.execute(
                    "INSERT INTO memory_entities_vec (rowid, embedding) VALUES (?, ?)",
                    (row_pk, _serialize(embedding)),
                )
        except Exception as e:
            logger.debug(
                f"temporal.resolve: embedding insert failed (non-blocking): {e}"
            )

    conn.commit()
    return actual_id


def resolve_entity(
    conn,
    name: str,
    entity_type: str,
    embedding: list[float] | None = None,
    threshold: float | None = None,
) -> str:
    """Return id of canonical entity for (name, type, embedding).

    Two-stage flow: try :func:`find_similar_entity`; on miss, INSERT via
    :func:`insert_entity_with_embedding`. The function is idempotent for
    repeated identical inputs (Stage 1 hits exact name on every replay).
    """
    existing = find_similar_entity(conn, name, entity_type, embedding, threshold)
    if existing is not None:
        return existing
    return insert_entity_with_embedding(conn, name, entity_type, embedding)
