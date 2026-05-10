"""Phase 3 Task 10: bundle codec KG-section round-trip.

Verifies:
- ``build_delta_bundle`` populates memories_entities.jsonl /
  memories_edges.jsonl / memories_entity_links.jsonl with current KG.
- ``apply_bundle`` applies KG sections via INSERT OR IGNORE.
- Manifest schema_version = ``mem_003_temporal``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.graph import (
    create_relations,
    link_memory_entities,
    upsert_entities,
)
from mnemo_mcp.sync.bundle import decode_bundle
from mnemo_mcp.sync.delta import (
    apply_bundle,
    build_full_bundle,
)

_PASS = "test-pass-phrase-123!"


@pytest.fixture
def db_with_kg(tmp_path: Path) -> MemoryDB:
    """DB seeded with memories + entities + edges + links."""
    db = MemoryDB(tmp_path / "src.db", embedding_dims=0)
    mid = db.add("Alice works on Project X using Python")
    eids = upsert_entities(
        db._conn,
        [
            {"name": "Alice", "type": "person"},
            {"name": "Project X", "type": "project"},
            {"name": "Python", "type": "tool"},
        ],
    )
    name_to_id = {
        "Alice": eids[0],
        "Project X": eids[1],
        "Python": eids[2],
    }
    create_relations(
        db._conn,
        [
            {"source": "Alice", "target": "Project X", "type": "works_on"},
            {"source": "Project X", "target": "Python", "type": "uses"},
        ],
        name_to_id,
    )
    link_memory_entities(db._conn, mid, eids)
    db._conn.commit()
    return db


async def test_bundle_includes_kg_sections(db_with_kg: MemoryDB):
    bundle = await build_full_bundle(db_with_kg, _PASS)
    payload = decode_bundle(bundle, _PASS)
    assert "memories_entities.jsonl" in payload
    assert "memories_edges.jsonl" in payload
    assert "memories_entity_links.jsonl" in payload
    assert payload["memories_entities.jsonl"] != b""
    assert payload["memories_edges.jsonl"] != b""
    assert payload["memories_entity_links.jsonl"] != b""


async def test_manifest_schema_version_mem_003(db_with_kg: MemoryDB):
    bundle = await build_full_bundle(db_with_kg, _PASS)
    payload = decode_bundle(bundle, _PASS)
    manifest = json.loads(payload["manifest.json"])
    assert manifest["schema_version"] == "mem_003_temporal"
    assert manifest["entity_count"] == 3
    assert manifest["edge_count"] == 2
    assert manifest["link_count"] == 3


async def test_apply_bundle_replicates_kg(db_with_kg: MemoryDB, tmp_path: Path):
    # Source bundle.
    bundle = await build_full_bundle(db_with_kg, _PASS)

    # Receiver: fresh DB.
    receiver = MemoryDB(tmp_path / "receiver.db", embedding_dims=0)

    counts = await apply_bundle(receiver, bundle, _PASS)
    assert counts["entities_applied"] == 3
    assert counts["edges_applied"] == 2
    assert counts["links_applied"] == 3

    # Verify KG copied across.
    ent_count = receiver._conn.execute(
        "SELECT COUNT(*) FROM memory_entities"
    ).fetchone()[0]
    assert ent_count == 3
    edge_count = receiver._conn.execute("SELECT COUNT(*) FROM memory_edges").fetchone()[
        0
    ]
    assert edge_count == 2
    link_count = receiver._conn.execute(
        "SELECT COUNT(*) FROM memory_entity_links"
    ).fetchone()[0]
    assert link_count == 3


async def test_apply_bundle_idempotent_kg(db_with_kg: MemoryDB, tmp_path: Path):
    """Replaying the same bundle is a no-op (INSERT OR IGNORE)."""
    bundle = await build_full_bundle(db_with_kg, _PASS)
    receiver = MemoryDB(tmp_path / "receiver.db", embedding_dims=0)
    await apply_bundle(receiver, bundle, _PASS)
    counts2 = await apply_bundle(receiver, bundle, _PASS)
    assert counts2["entities_applied"] == 0
    assert counts2["edges_applied"] == 0
    assert counts2["links_applied"] == 0
