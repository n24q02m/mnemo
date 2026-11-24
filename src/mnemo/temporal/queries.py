"""Phase 3 KG-aware queries: entity_search / entity_graph / history / as_of.

Spec § 4.3 Phase 3 actions. These are read-only helpers consumed by
``memory(action="entity_search"|"entity_graph"|"history")`` in
:mod:`mnemo.server`. They live outside ``db.py`` so the temporal-KG
surface stays modular and swappable.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mnemo.db import MemoryDB


def entity_search(
    db: MemoryDB,
    name: str | None = None,
    entity_type: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Find memories that mention an entity by name (and optional type).

    Returns memory rows ordered by ``updated_at DESC`` (most-recent first)
    plus a ``matched_entity`` annotation per row. Falls back to fuzzy
    LIKE-match when an exact name is not found.

    Args:
        db: Live :class:`MemoryDB`.
        name: Entity name to look up (case-insensitive).
        entity_type: Optional entity_type filter
            (person/project/tool/concept/org/location/event).
        limit: Maximum memory rows returned.

    Returns:
        List of memory dicts with ``matched_entity`` field appended.
    """
    if not name or not name.strip():
        return []

    if isinstance(limit, int):
        limit = max(1, min(limit, 100))

    where = ["name = ? COLLATE NOCASE"]
    params: list = [name.strip()]
    if entity_type:
        where.append("entity_type = ?")
        params.append(entity_type)

    ent_sql = (
        "SELECT id, name, entity_type FROM memory_entities "
        f"WHERE {' AND '.join(where)} LIMIT 5"
    )
    with db.connection() as conn:
        entities = conn.execute(ent_sql, params).fetchall()

        if not entities:
            # Fallback: fuzzy substring match.
            # Escape LIKE wildcards to prevent injection/broad matching.
            escaped_name = (
                name.strip()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            like_sql = (
                "SELECT id, name, entity_type FROM memory_entities "
                "WHERE name LIKE ? ESCAPE '\\' COLLATE NOCASE LIMIT 5"
            )
            entities = conn.execute(like_sql, (f"%{escaped_name}%",)).fetchall()
        if not entities:
            return []

        entity_ids = [e[0] if not hasattr(e, "keys") else e["id"] for e in entities]

        mem_sql = (
            "SELECT m.*, mel.entity_id FROM memories m "
            "JOIN memory_entity_links mel ON mel.memory_id = m.id "
            "WHERE mel.entity_id IN (SELECT value FROM json_each(?)) "
            "  AND m.archived_at IS NULL "
            "  AND (m.valid_to IS NULL) "
            "ORDER BY m.updated_at DESC LIMIT ?"
        )
        rows = conn.execute(mem_sql, (json.dumps(entity_ids), limit)).fetchall()

    # Map entity_id back to name for the response annotation.
    name_by_id = {
        (e[0] if not hasattr(e, "keys") else e["id"]): (
            e[1] if not hasattr(e, "keys") else e["name"]
        )
        for e in entities
    }

    out: list[dict] = []
    for row in rows:
        d = dict(row)
        ent_id = d.pop("entity_id", None)
        d["matched_entity"] = name_by_id.get(ent_id, name)
        out.append(d)
    return out


def entity_graph(
    db: MemoryDB,
    entity_id: str | None = None,
    name: str | None = None,
    depth: int = 2,
    limit: int = 50,
) -> dict:
    """Return KG neighbourhood subgraph anchored at one entity.

    Args:
        db: Live :class:`MemoryDB`.
        entity_id: Anchor entity id. Resolved via ``name`` when omitted.
        name: Anchor entity name (used when ``entity_id`` not given).
        depth: BFS depth (1 or 2 only — prevents runaway traversal).
        limit: Maximum nodes returned (centre + neighbours).

    Returns:
        ``{"nodes": [...], "edges": [...], "depth": int, "anchor": str}``.
    """
    with db.connection() as conn:
        if entity_id is None and name:
            row = conn.execute(
                "SELECT id FROM memory_entities WHERE name = ? COLLATE NOCASE LIMIT 1",
                (name.strip(),),
            ).fetchone()
            if row is not None:
                entity_id = row[0] if not hasattr(row, "keys") else row["id"]
        if not entity_id:
            return {"nodes": [], "edges": [], "depth": depth, "anchor": name or ""}

        depth = max(1, min(int(depth), 2))
        limit = max(1, min(int(limit), 500))

        # BFS via recursive CTE, bounded by depth.
        cte = """
            WITH RECURSIVE traverse(entity_id, depth) AS (
                SELECT ?, 0
                UNION
                SELECT e.target_id, t.depth + 1
                  FROM memory_edges e
                  JOIN traverse t ON e.source_id = t.entity_id
                 WHERE t.depth < ?
                UNION
                SELECT e.source_id, t.depth + 1
                  FROM memory_edges e
                  JOIN traverse t ON e.target_id = t.entity_id
                 WHERE t.depth < ?
            )
            SELECT DISTINCT entity_id FROM traverse LIMIT ?
        """
        rows = conn.execute(cte, (entity_id, depth, depth, limit)).fetchall()
        node_ids = [r[0] if not hasattr(r, "keys") else r["entity_id"] for r in rows]

        if not node_ids:
            return {"nodes": [], "edges": [], "depth": depth, "anchor": entity_id}

        node_ids_json = json.dumps(node_ids)
        nodes = conn.execute(
            "SELECT id, name, entity_type FROM memory_entities WHERE id IN (SELECT value FROM json_each(?))",
            (node_ids_json,),
        ).fetchall()
        edges = conn.execute(
            "SELECT id, source_id, target_id, relation_type, memory_id, valid_from, valid_to "
            "FROM memory_edges WHERE source_id IN (SELECT value FROM json_each(?)) "
            "  AND target_id IN (SELECT value FROM json_each(?))",
            (node_ids_json, node_ids_json),
        ).fetchall()

    return {
        "anchor": entity_id,
        "depth": depth,
        "nodes": [dict(r) for r in nodes],
        "edges": [dict(r) for r in edges],
    }


def history_for_entity(db: MemoryDB, entity_id: str) -> list[dict]:
    """Return all memory versions that ever linked to ``entity_id``.

    Includes superseded rows (``valid_to IS NOT NULL``) so callers can see
    the full timeline. Ordered by ``valid_from`` ascending.
    """
    sql = (
        "SELECT m.*, mel.entity_id FROM memories m "
        "JOIN memory_entity_links mel ON mel.memory_id = m.id "
        "WHERE mel.entity_id = ? "
        "ORDER BY COALESCE(m.valid_from, m.created_at) ASC"
    )
    with db.connection() as conn:
        rows = conn.execute(sql, (entity_id,)).fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d.pop("entity_id", None)
        out.append(d)
    return out


def memories_as_of(
    db: MemoryDB,
    as_of: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Return memories valid at ``as_of`` (ISO timestamp).

    When ``as_of`` is None, returns rows where ``valid_to IS NULL``
    (current state — Phase 3 default). Otherwise returns rows where
    ``valid_from <= as_of AND (valid_to IS NULL OR valid_to > as_of)``.
    """
    if isinstance(limit, int):
        limit = max(1, min(limit, 100))

    if as_of is None:
        sql = (
            "SELECT * FROM memories "
            "WHERE valid_to IS NULL AND archived_at IS NULL "
            "ORDER BY COALESCE(valid_from, created_at) DESC LIMIT ?"
        )
        params: tuple = (limit,)
    else:
        sql = (
            "SELECT * FROM memories "
            "WHERE COALESCE(valid_from, created_at) <= ? "
            "  AND (valid_to IS NULL OR valid_to > ?) "
            "  AND archived_at IS NULL "
            "ORDER BY COALESCE(valid_from, created_at) DESC LIMIT ?"
        )
        params = (as_of, as_of, limit)

    with db.connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def build_timeline(
    db: MemoryDB,
    *,
    subject: str | None = None,
    entity: str | None = None,
    since: str | None = None,
    until: str | None = None,
    include_superseded: bool = True,
    limit: int = 50,
) -> list[dict]:
    """Return chronological timeline of memories ordered oldest-to-newest.

    Supports filtering by ``subject``, optional ``entity`` substring/name,
    ISO bounds ``since``/``until``, and flags each item as ``active`` vs
    ``superseded`` vs ``archived``.
    """
    limit = max(1, min(limit, 200))
    clauses = ["1=1"]
    params: list[object] = []

    if subject is not None:
        clauses.append("m.subject = ?")
        params.append(subject)
    if not include_superseded:
        clauses.append("m.valid_to IS NULL AND m.archived_at IS NULL")
    if since:
        clauses.append("COALESCE(m.valid_from, m.created_at) >= ?")
        params.append(since)
    if until:
        clauses.append("COALESCE(m.valid_from, m.created_at) <= ?")
        params.append(until)
    if entity:
        ent_pat = f"%{entity.strip()}%"
        clauses.append(
            "(m.content LIKE ? OR EXISTS ("
            "SELECT 1 FROM memory_entity_links l "
            "JOIN memory_entities e ON l.entity_id = e.id "
            "WHERE l.memory_id = m.id AND e.name LIKE ?))"
        )
        params.extend([ent_pat, ent_pat])

    sql = (
        "SELECT m.* FROM memories m "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY COALESCE(m.valid_from, m.created_at) ASC, m.created_at ASC "
        "LIMIT ?"
    )
    params.append(limit)
    with db.connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    timeline: list[dict] = []
    for r in rows:
        item = dict(r)
        if item.get("archived_at"):
            state = "archived"
        elif item.get("valid_to") or item.get("superseded_by"):
            state = "superseded"
        else:
            state = "active"
        item["timeline_state"] = state
        item["timestamp"] = item.get("valid_from") or item.get("created_at")
        timeline.append(item)
    return timeline
