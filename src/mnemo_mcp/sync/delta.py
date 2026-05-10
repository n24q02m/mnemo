"""Delta-sync orchestrator with last-write-wins conflict resolution.

Phase 2 Task 8 + spec ``2026-04-19-mnemo-v2-design.md`` section 4.4.

Each sync cycle is one of:

* **Delta push** (common case): collect rows whose ``updated_at >
  last_sync_at`` -> encrypted bundle -> push at ``cursor + 1``.
* **Full pull + merge + full push** (sequence-gap fallback): when the
  remote sequence advanced beyond ``local_cursor + 1`` (another machine
  pushed in the meantime), pull the latest full passport, merge with LWW
  per row, then upload a new full bundle.

Last-write-wins (LWW) conflict resolution: row-level. For each incoming
row we compare ``remote.updated_at`` against ``local.updated_at``:

* ``local >= remote`` -> keep local; record an audit row in
  ``sync_overrides`` so the user can inspect divergence.
* ``local < remote`` -> upsert the remote row (compressed text + raw +
  context_type + importance + archived_at all preserved).
* ``local missing`` -> insert the remote row.

The orchestrator never blocks on conflict; LWW is automatic per row so
two machines syncing concurrently both converge after the next round.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

from loguru import logger

from mnemo_mcp.sync.bundle import decode_bundle, encode_bundle

if TYPE_CHECKING:
    from mnemo_mcp.db import MemoryDB
    from mnemo_mcp.sync.base import SyncBackend


# ---------------------------------------------------------------------------
# Bundle build / apply
# ---------------------------------------------------------------------------


def _query_rows_since(db: MemoryDB, since: float | None) -> list[dict]:
    """Return memory rows whose ``updated_at`` is more recent than ``since``.

    ``updated_at`` is stored as ISO 8601 UTC text; we filter via ISO
    string comparison which is monotonic for ISO timestamps. ``since``
    is passed as a Unix timestamp; we convert to ISO once at the call
    site.
    """
    cursor = db._conn.cursor()
    if since is None or since <= 0:
        rows = cursor.execute("SELECT * FROM memories ORDER BY updated_at").fetchall()
    else:
        from datetime import UTC, datetime

        since_iso = datetime.fromtimestamp(since, tz=UTC).isoformat()
        rows = cursor.execute(
            "SELECT * FROM memories WHERE updated_at > ? ORDER BY updated_at",
            (since_iso,),
        ).fetchall()
    return [dict(r) for r in rows]


def _build_payload(
    rows: list[dict],
    since: float | None,
    *,
    entities: list[dict] | None = None,
    edges: list[dict] | None = None,
    links: list[dict] | None = None,
) -> dict[str, bytes]:
    """Assemble the bundle payload sections from ``rows``.

    Phase 3 populates the previously-empty ``memories_entities.jsonl`` /
    ``memories_edges.jsonl`` reservations with the temporal KG fragment
    captured since the last sync. ``schema_version`` bumps to
    ``mem_003_temporal`` so older receivers know to refuse the bundle
    (see ``apply_bundle`` schema-version check).
    """
    manifest = {
        "row_count": len(rows),
        "since": since,
        "created_at": time.time(),
        "schema_version": "mem_003_temporal",
        "entity_count": len(entities) if entities is not None else 0,
        "edge_count": len(edges) if edges is not None else 0,
        "link_count": len(links) if links is not None else 0,
    }
    memories_jsonl = "\n".join(json.dumps(r, default=str) for r in rows).encode("utf-8")
    entities_jsonl = (
        "\n".join(json.dumps(e, default=str) for e in (entities or [])).encode("utf-8")
        if entities
        else b""
    )
    edges_jsonl = (
        "\n".join(json.dumps(e, default=str) for e in (edges or [])).encode("utf-8")
        if edges
        else b""
    )
    links_jsonl = (
        "\n".join(json.dumps(le, default=str) for le in (links or [])).encode("utf-8")
        if links
        else b""
    )
    return {
        "manifest.json": json.dumps(manifest).encode("utf-8"),
        "memories.jsonl": memories_jsonl,
        # Phase 3: now populated with the renamed graph tables.
        "memories_entities.jsonl": entities_jsonl,
        "memories_edges.jsonl": edges_jsonl,
        "memories_entity_links.jsonl": links_jsonl,
    }


def _query_kg_since(db: MemoryDB, since: float | None) -> dict:
    """Snapshot ``memory_entities`` / ``memory_edges`` / ``memory_entity_links``.

    Phase 3 always sends the FULL KG snapshot (not delta) since the KG
    tables are small relative to memories.jsonl and per-row updated_at
    tracking on entities is not yet implemented. Receivers re-apply via
    INSERT OR IGNORE so duplicates are harmless.
    """
    cursor = db._conn.cursor()
    try:
        ents = cursor.execute(
            "SELECT id, name, entity_type, created_at, updated_at "
            "FROM memory_entities ORDER BY created_at"
        ).fetchall()
        edges = cursor.execute(
            "SELECT id, source_id, target_id, relation_type, created_at, "
            "  memory_id, valid_from, valid_to FROM memory_edges ORDER BY created_at"
        ).fetchall()
        links = cursor.execute(
            "SELECT memory_id, entity_id FROM memory_entity_links"
        ).fetchall()
    except Exception:
        # Fallback for legacy schemas or transient errors.
        return {"entities": [], "edges": [], "links": []}
    return {
        "entities": [dict(r) for r in ents],
        "edges": [dict(r) for r in edges],
        "links": [dict(r) for r in links],
    }


async def build_delta_bundle(
    db: MemoryDB, since: float | None, passphrase: str
) -> bytes:
    """Encrypt all memories newer than ``since`` into a passport bundle."""
    rows = await asyncio.to_thread(_query_rows_since, db, since)
    kg = await asyncio.to_thread(_query_kg_since, db, since)
    payload = _build_payload(
        rows,
        since,
        entities=kg["entities"],
        edges=kg["edges"],
        links=kg["links"],
    )
    return encode_bundle(payload, passphrase)


async def build_full_bundle(db: MemoryDB, passphrase: str) -> bytes:
    """Encrypt the full memory store (used after sequence-gap merge)."""
    return await build_delta_bundle(db, since=None, passphrase=passphrase)


# ---------------------------------------------------------------------------
# Apply (LWW per row)
# ---------------------------------------------------------------------------


_INSERT_COLS = (
    "id",
    "content",
    "category",
    "tags",
    "source",
    "created_at",
    "updated_at",
    "access_count",
    "last_accessed",
    "importance",
    "context_type",
    "archived_at",
    "text_raw",
    "compressed",
    "compression_provider",
)


def _ensure_overrides_table(db: MemoryDB) -> None:
    """Create ``sync_overrides`` audit table on first use (idempotent)."""
    db._conn.execute(
        """CREATE TABLE IF NOT EXISTS sync_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL,
            local_updated_at TEXT,
            remote_updated_at TEXT,
            local_content TEXT,
            remote_content TEXT,
            recorded_at REAL NOT NULL
        )"""
    )


def _upsert_row_lww(db: MemoryDB, remote: dict) -> str:
    """Insert / update / skip per LWW. Returns 'inserted', 'updated', 'skipped'.

    'inserted' = no local row, INSERT OR REPLACE applied.
    'updated' = remote.updated_at > local.updated_at, REPLACE applied.
    'skipped' = local.updated_at >= remote.updated_at, audit row written.
    """
    cursor = db._conn.cursor()
    existing = cursor.execute(
        "SELECT updated_at, content FROM memories WHERE id = ?",
        (remote["id"],),
    ).fetchone()

    if existing is None:
        outcome = "inserted"
    else:
        local_updated = existing["updated_at"]
        remote_updated = remote.get("updated_at", "")
        if local_updated >= remote_updated:
            _ensure_overrides_table(db)
            cursor.execute(
                "INSERT INTO sync_overrides "
                "(memory_id, local_updated_at, remote_updated_at, "
                "local_content, remote_content, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    remote["id"],
                    local_updated,
                    remote_updated,
                    existing["content"],
                    remote.get("content"),
                    time.time(),
                ),
            )
            db._conn.commit()
            return "skipped"
        outcome = "updated"

    placeholders = ", ".join("?" for _ in _INSERT_COLS)
    cols_csv = ", ".join(_INSERT_COLS)
    cursor.execute(
        f"INSERT OR REPLACE INTO memories ({cols_csv}) VALUES ({placeholders})",
        tuple(remote.get(c) for c in _INSERT_COLS),
    )
    db._conn.commit()
    return outcome


def _apply_kg_sections(db: MemoryDB, payload: dict[str, bytes]) -> dict:
    """Apply Phase 3 KG sections (entities + edges + links) via INSERT OR IGNORE.

    Idempotent: replaying the same bundle is safe because the unique
    indexes on ``memory_entities(name, entity_type)`` and
    ``memory_edges(source_id, target_id, relation_type)`` collapse
    duplicates. Returns counts dict.
    """
    counts = {"entities_applied": 0, "edges_applied": 0, "links_applied": 0}
    cursor = db._conn.cursor()

    ents_raw = payload.get("memories_entities.jsonl", b"").decode("utf-8")
    for line in ents_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ent = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO memory_entities "
                "(id, name, entity_type, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    ent.get("id"),
                    ent.get("name"),
                    ent.get("entity_type"),
                    ent.get("created_at"),
                    ent.get("updated_at"),
                ),
            )
            counts["entities_applied"] += cursor.rowcount or 0
        except Exception as e:
            logger.debug(f"apply_bundle: entity skipped ({e})")

    edges_raw = payload.get("memories_edges.jsonl", b"").decode("utf-8")
    for line in edges_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            edge = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO memory_edges "
                "(id, source_id, target_id, relation_type, created_at, "
                " memory_id, valid_from, valid_to) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    edge.get("id"),
                    edge.get("source_id"),
                    edge.get("target_id"),
                    edge.get("relation_type"),
                    edge.get("created_at"),
                    edge.get("memory_id"),
                    edge.get("valid_from"),
                    edge.get("valid_to"),
                ),
            )
            counts["edges_applied"] += cursor.rowcount or 0
        except Exception as e:
            logger.debug(f"apply_bundle: edge skipped ({e})")

    links_raw = payload.get("memories_entity_links.jsonl", b"").decode("utf-8")
    for line in links_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            link = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO memory_entity_links "
                "(memory_id, entity_id) VALUES (?, ?)",
                (link.get("memory_id"), link.get("entity_id")),
            )
            counts["links_applied"] += cursor.rowcount or 0
        except Exception as e:
            logger.debug(f"apply_bundle: link skipped ({e})")

    db._conn.commit()
    return counts


async def apply_bundle(db: MemoryDB, bundle: bytes, passphrase: str) -> dict:
    """Decrypt ``bundle`` and apply each memory row via LWW per row.

    Phase 3 also applies the ``memories_entities.jsonl`` /
    ``memories_edges.jsonl`` / ``memories_entity_links.jsonl`` sections
    via INSERT OR IGNORE so the receiver KG converges with the sender.

    Returns counts dict::

        {
            "inserted": <int>, "updated": <int>, "skipped": <int>,
            "row_count": <int>, "manifest": <decoded manifest dict>,
            "entities_applied": <int>, "edges_applied": <int>,
            "links_applied": <int>,
        }
    """
    payload = decode_bundle(bundle, passphrase)
    manifest = json.loads(payload.get("manifest.json", b"{}").decode("utf-8"))
    memories_jsonl = payload.get("memories.jsonl", b"").decode("utf-8")

    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    rows: list[dict] = []
    for line in memories_jsonl.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("apply_bundle: skipping malformed JSONL line")
            continue

    for row in rows:
        outcome = await asyncio.to_thread(_upsert_row_lww, db, row)
        counts[outcome] += 1

    # Phase 3 KG sections.
    kg_counts = await asyncio.to_thread(_apply_kg_sections, db, payload)

    return {**counts, **kg_counts, "row_count": len(rows), "manifest": manifest}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def sync_now(db: MemoryDB, backend_name: str, passphrase: str) -> dict:
    """Push delta (or full on sequence gap) via the named backend.

    Workflow:

    1. Read local cursor + last sync timestamp from sync_state.
    2. Query backend's last_remote_sequence.
    3. If remote_seq > local_cursor + 1 (another machine pushed) ->
       full pull + merge + full push at remote_seq + 1.
    4. Else delta push at local_cursor + 1.
    5. Persist new cursor + timestamp to sync_state.

    Returns a result dict with ``mode`` ('delta' | 'full-pull-push'),
    ``cursor``, ``rows`` counts, and (when applicable) the merge counts
    from :func:`apply_bundle`.
    """
    from mnemo_mcp.sync import get as get_backend

    backend: SyncBackend = get_backend(backend_name)

    state = await asyncio.to_thread(db.get_sync_state, backend_name) or {}
    local_cursor = int(state.get("upload_cursor") or 0)
    last_sync_at = float(state.get("last_sync_at") or 0.0)

    remote_seq = await backend.last_remote_sequence()

    if remote_seq > local_cursor + 1:
        # Sequence gap -> another machine pushed. Pull full passport,
        # merge LWW, then push consolidated bundle.
        full_bundle = await backend.pull(sequence=None)
        merge_counts = (
            await apply_bundle(db, full_bundle, passphrase)
            if full_bundle
            else {"inserted": 0, "updated": 0, "skipped": 0, "row_count": 0}
        )
        new_full = await build_full_bundle(db, passphrase)
        new_cursor = remote_seq + 1
        await backend.push(new_full, sequence=new_cursor)
        await asyncio.to_thread(
            db.upsert_sync_state,
            backend_name,
            time.time(),
            None,
            new_cursor,
        )
        return {
            "mode": "full-pull-push",
            "cursor": new_cursor,
            "remote_seq_before": remote_seq,
            "merge": merge_counts,
        }

    # Common case: push delta of local changes since last_sync_at.
    delta = await build_delta_bundle(db, since=last_sync_at, passphrase=passphrase)
    new_cursor = local_cursor + 1
    await backend.push(delta, sequence=new_cursor)
    rows = await asyncio.to_thread(_query_rows_since, db, last_sync_at)
    await asyncio.to_thread(
        db.upsert_sync_state, backend_name, time.time(), None, new_cursor
    )
    return {
        "mode": "delta",
        "cursor": new_cursor,
        "rows": len(rows),
    }
