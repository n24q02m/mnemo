"""Lightweight knowledge graph: entity extraction + relation management."""

import json
import uuid
from datetime import UTC, datetime

from loguru import logger


async def extract_entities(content: str) -> dict | None:
    """Extract entities and relations from text via LLM.

    Returns {"entities": [...], "relations": [...]} or None if LLM unavailable.
    """
    from mnemo_mcp.config import settings

    mode = settings.resolve_litellm_mode()
    if mode == "local":
        return None

    try:
        from litellm import acompletion

        llm_kwargs: dict = {}
        if settings.litellm_proxy_url:
            llm_kwargs["api_base"] = settings.litellm_proxy_url
            if settings.litellm_proxy_key:
                llm_kwargs["api_key"] = settings.litellm_proxy_key

        models = [m.strip() for m in settings.llm_models.split(",") if m.strip()]
        model = models[0] if models else "gemini/gemini-3-flash-preview"

        response = await acompletion(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Extract entities and relations from this text. Return ONLY valid JSON:\n"
                        '{"entities": [{"name": "...", "type": "person|project|tool|concept|org|location|event"}], '
                        '"relations": [{"source": "entity_name", "target": "entity_name", '
                        '"type": "uses|works_on|related_to|depends_on|created_by|part_of"}]}\n\n'
                        f"<content>\n{content[:3000]}\n</content>"
                    ),
                }
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=500,
            **llm_kwargs,
        )

        text = response.choices[0].message.content
        data = json.loads(text)
        return data if "entities" in data else None
    except Exception as e:
        logger.debug(f"Entity extraction failed: {e}")
        return None


async def score_importance(content: str) -> float:
    """Score memory importance 0.0-1.0 via LLM. Returns 0.5 if unavailable."""
    from mnemo_mcp.config import settings

    mode = settings.resolve_litellm_mode()
    if mode == "local":
        return 0.5

    try:
        from litellm import acompletion

        llm_kwargs: dict = {}
        if settings.litellm_proxy_url:
            llm_kwargs["api_base"] = settings.litellm_proxy_url
            if settings.litellm_proxy_key:
                llm_kwargs["api_key"] = settings.litellm_proxy_key

        models = [m.strip() for m in settings.llm_models.split(",") if m.strip()]
        model = models[0] if models else "gemini/gemini-3-flash-preview"

        response = await acompletion(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Rate the importance of this memory for future recall. "
                        "Return ONLY a number between 0.0 (trivial) and 1.0 (critical).\n\n"
                        f"{content[:1000]}"
                    ),
                }
            ],
            temperature=0,
            max_tokens=10,
            **llm_kwargs,
        )

        text = response.choices[0].message.content.strip()
        score = float(text)
        return max(0.0, min(1.0, score))
    except Exception as e:
        logger.debug(f"Importance scoring failed: {e}")
        return 0.5


def upsert_entities(conn, entities: list[dict]) -> list[str]:
    """Insert or update entities. Returns list of entity IDs."""
    now = datetime.now(UTC).isoformat()
    ids = []
    for ent in entities:
        name = ent.get("name", "").strip()
        etype = ent.get("type", "concept").strip().lower()
        if not name:
            continue
        row = conn.execute(
            "SELECT id FROM entities WHERE name = ? AND entity_type = ?",
            (name, etype),
        ).fetchone()
        if row:
            eid = row[0]
            conn.execute("UPDATE entities SET updated_at = ? WHERE id = ?", (now, eid))
        else:
            eid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO entities (id, name, entity_type, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (eid, name, etype, now, now),
            )
        ids.append(eid)
    return ids


def create_relations(
    conn, relations: list[dict], entity_name_to_id: dict[str, str]
) -> None:
    """Create relations between entities."""
    now = datetime.now(UTC).isoformat()
    for rel in relations:
        src_name = rel.get("source", "").strip()
        tgt_name = rel.get("target", "").strip()
        rtype = rel.get("type", "related_to").strip().lower()
        src_id = entity_name_to_id.get(src_name)
        tgt_id = entity_name_to_id.get(tgt_name)
        if not src_id or not tgt_id or src_id == tgt_id:
            continue
        existing = conn.execute(
            "SELECT id FROM relations WHERE source_id = ? AND target_id = ? AND relation_type = ?",
            (src_id, tgt_id, rtype),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO relations (id, source_id, target_id, relation_type, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), src_id, tgt_id, rtype, now),
            )


def link_memory_entities(conn, memory_id: str, entity_ids: list[str]) -> None:
    """Link a memory to entities."""
    for eid in entity_ids:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO memory_entities (memory_id, entity_id) VALUES (?, ?)",
                (memory_id, eid),
            )
        except Exception:
            pass


def find_related_memory_ids(conn, memory_id: str, max_depth: int = 2) -> list[str]:
    """Find memory IDs related via shared entities (up to max_depth hops)."""
    entity_ids = [
        r[0]
        for r in conn.execute(
            "SELECT entity_id FROM memory_entities WHERE memory_id = ?",
            (memory_id,),
        ).fetchall()
    ]

    if not entity_ids:
        return []

    visited_entities = set(entity_ids)
    all_entity_ids = list(entity_ids)

    # Walk relations up to max_depth hops
    for _depth in range(max_depth - 1):
        if not all_entity_ids:
            break
        placeholders = ",".join("?" * len(all_entity_ids))
        neighbor_rows = conn.execute(
            f"SELECT target_id FROM relations WHERE source_id IN ({placeholders}) "
            f"UNION SELECT source_id FROM relations WHERE target_id IN ({placeholders})",
            (*all_entity_ids, *all_entity_ids),
        ).fetchall()
        new_ids = [r[0] for r in neighbor_rows if r[0] not in visited_entities]
        if not new_ids:
            break
        visited_entities.update(new_ids)
        all_entity_ids = new_ids

    # Find memories sharing any of the discovered entities
    all_eids = list(visited_entities)
    placeholders = ",".join("?" * len(all_eids))
    rows = conn.execute(
        f"SELECT DISTINCT memory_id FROM memory_entities "
        f"WHERE entity_id IN ({placeholders}) AND memory_id != ?",
        (*all_eids, memory_id),
    ).fetchall()

    return [r[0] for r in rows]
