"""Phase 3 KG-store helper: wire extract output into memory_edges with memory_id.

Phase 1 ``server._enrich_memory`` calls ``graph.upsert_entities`` +
``graph.create_relations`` + ``graph.link_memory_entities`` to persist the
LLM-extracted KG fragment, but the ``memory_edges`` rows it writes do NOT
record which capture they came from. Phase 3 adds bitemporal columns
(``memory_id`` / ``valid_from`` / ``valid_to``) to ``memory_edges`` so
edges can be traced back to a specific capture and aged out via
supersession.

This module provides :func:`store_kg_with_memory_id` which extends the
Phase 1 wiring with three Phase 3 enhancements:

1. Backfills ``memory_edges.memory_id`` to the originating capture id so
   the audit / supersession path can target relation rows by source.
2. Initialises ``memory_edges.valid_from`` to capture time and leaves
   ``valid_to`` NULL (currently valid).
3. Returns counts ``{"entities": N, "edges": M, "links": L}`` so the
   caller (server enrichment + future ``knowledge-audit`` action) can
   report the KG growth without a follow-up query.

The legacy ``graph`` helpers stay untouched so existing tests keep
passing; this module composes them then patches the extra columns
in-place via a single UPDATE.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

from mnemo_mcp.graph import (
    create_relations,
    link_memory_entities,
    upsert_entities,
)

if TYPE_CHECKING:
    pass


def store_kg_with_memory_id(
    conn,
    memory_id: str,
    extracted: dict | None,
) -> dict:
    """Persist ``extracted`` KG fragment with Phase 3 bitemporal bookkeeping.

    Args:
        conn: Live ``sqlite3.Connection`` from :class:`MemoryDB`.
        memory_id: Capture row id the extracted KG belongs to.
        extracted: Output from :func:`mnemo_mcp.temporal.extract.extract_entities`
            with shape ``{"entities": [...], "relations": [...], ...}``.

    Returns:
        ``{"entities": int, "edges": int, "links": int}`` counts.
    """
    if not extracted or not extracted.get("entities"):
        return {"entities": 0, "edges": 0, "links": 0}

    entities = extracted["entities"]
    relations = extracted.get("relations") or []

    entity_ids = upsert_entities(conn, entities)
    name_to_id: dict[str, str] = {}
    for ent, eid in zip(entities, entity_ids, strict=False):
        name = ent.get("name", "").strip()
        if name and eid:
            name_to_id[name] = eid

    if relations:
        create_relations(conn, relations, name_to_id)

    link_memory_entities(conn, memory_id, entity_ids)

    # Phase 3: backfill memory_id + valid_from on the freshly inserted edges.
    # We target rows that match (source, target, type) for this batch and
    # have NULL memory_id / NULL valid_from -- so an edge already attached
    # to an earlier capture is left alone.
    edge_count = 0
    params = []
    if relations:
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
        for rel in relations:
            src_name = rel.get("source", "").strip()
            tgt_name = rel.get("target", "").strip()
            rtype = rel.get("type", "").strip().lower()
            src_id = name_to_id.get(src_name)
            tgt_id = name_to_id.get(tgt_name)
            if not (src_id and tgt_id and rtype):
                continue
            params.append((memory_id, now_iso, src_id, tgt_id, rtype))

    if params:
        cursor = conn.executemany(
            "UPDATE memory_edges SET "
            "  memory_id = COALESCE(memory_id, ?), "
            "  valid_from = COALESCE(valid_from, ?) "
            "WHERE source_id = ? AND target_id = ? AND relation_type = ?",
            params,
        )
        # For UPDATE, executemany's rowcount is the sum of all affected rows.
        # Bolt Performance Note: Using executemany eliminates N+1 updates.
        edge_count = cursor.rowcount if cursor.rowcount != -1 else len(params)
        conn.commit()

    logger.debug(
        f"temporal.store: memory_id={memory_id} "
        f"entities={len(entity_ids)} edges={edge_count}"
    )

    return {
        "entities": len(entity_ids),
        "edges": edge_count,
        "links": len(entity_ids),
    }
