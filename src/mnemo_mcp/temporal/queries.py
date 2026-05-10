"""Phase 3 KG-aware queries: entity_search / entity_graph / history / as_of.

Spec § 4.3 Phase 3 actions. These are read-only helpers consumed by
``memory(action="entity_search"|"entity_graph"|"history")`` in
:mod:`mnemo_mcp.server`. They live outside ``db.py`` so the temporal-KG
surface stays modular and swappable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mnemo_mcp.db import MemoryDB


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
    entities = db._conn.execute(ent_sql, params).fetchall()

    if not entities:
        # Fallback: fuzzy substring match.
        like_sql = (
            "SELECT id, name, entity_type FROM memory_entities "
            "WHERE name LIKE ? COLLATE NOCASE LIMIT 5"
        )
        entities = db._conn.execute(like_sql, (f"%{name.strip()}%",)).fetchall()
    if not entities:
        return []

    entity_ids = [e[0] if not hasattr(e, "keys") else e["id"] for e in entities]
    placeholders = ",".join("?" * len(entity_ids))

    mem_sql = (
        "SELECT m.*, mel.entity_id FROM memories m "
        "JOIN memory_entity_links mel ON mel.memory_id = m.id "
        f"WHERE mel.entity_id IN ({placeholders}) "
        "  AND m.archived_at IS NULL "
        "  AND (m.valid_to IS NULL) "
        "ORDER BY m.updated_at DESC LIMIT ?"
    )
    rows = db._conn.execute(mem_sql, (*entity_ids, limit)).fetchall()

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
    if entity_id is None and name:
        row = db._conn.execute(
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
    rows = db._conn.execute(cte, (entity_id, depth, depth, limit)).fetchall()
    node_ids = [r[0] if not hasattr(r, "keys") else r["entity_id"] for r in rows]

    if not node_ids:
        return {"nodes": [], "edges": [], "depth": depth, "anchor": entity_id}

    placeholders = ",".join("?" * len(node_ids))
    nodes = db._conn.execute(
        f"SELECT id, name, entity_type FROM memory_entities WHERE id IN ({placeholders})",
        node_ids,
    ).fetchall()
    edges = db._conn.execute(
        "SELECT id, source_id, target_id, relation_type, memory_id, valid_from, valid_to "
        f"FROM memory_edges WHERE source_id IN ({placeholders}) "
        f"  AND target_id IN ({placeholders})",
        (*node_ids, *node_ids),
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
    rows = db._conn.execute(sql, (entity_id,)).fetchall()
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

    rows = db._conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
