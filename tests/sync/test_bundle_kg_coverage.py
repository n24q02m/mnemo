"""Coverage tests for bundle KG sections — error paths + edge cases."""

from __future__ import annotations

import json
from pathlib import Path

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.sync.bundle import encode_bundle
from mnemo_mcp.sync.delta import (
    _apply_kg_sections,
    _build_payload,
    _query_kg_since,
    apply_bundle,
)

_PASS = "covered-pass-phrase"


def test_query_kg_since_empty_db(tmp_path: Path):
    db = MemoryDB(tmp_path / "empty.db", embedding_dims=0)
    result = _query_kg_since(db, since=None)
    assert result == {"entities": [], "edges": [], "links": []}


def test_build_payload_phase3_keys_present():
    payload = _build_payload(
        rows=[],
        since=None,
        entities=[{"id": "1", "name": "X", "entity_type": "concept"}],
        edges=[],
        links=[],
    )
    assert "memories_entities.jsonl" in payload
    assert "memories_edges.jsonl" in payload
    assert "memories_entity_links.jsonl" in payload
    manifest = json.loads(payload["manifest.json"])
    assert manifest["entity_count"] == 1
    assert manifest["edge_count"] == 0
    assert manifest["link_count"] == 0


def test_build_payload_with_none_kg_sections():
    """When entities/edges/links are None, sections are empty bytes."""
    payload = _build_payload(rows=[], since=None)
    assert payload["memories_entities.jsonl"] == b""
    assert payload["memories_edges.jsonl"] == b""
    assert payload["memories_entity_links.jsonl"] == b""


def test_apply_kg_sections_skips_malformed_jsonl(tmp_path: Path):
    db = MemoryDB(tmp_path / "tgt.db", embedding_dims=0)
    payload = {
        "memories_entities.jsonl": (
            b'{"id": "1", "name": "Valid", "entity_type": "concept", "created_at": "2026-01-01", "updated_at": "2026-01-01"}\n'
            b"NOT JSON\n"
            b'{"id": "2", "name": "Also Valid", "entity_type": "tool", "created_at": "2026-01-01", "updated_at": "2026-01-01"}\n'
        ),
        "memories_edges.jsonl": b"",
        "memories_entity_links.jsonl": b"",
    }
    counts = _apply_kg_sections(db, payload)
    assert counts["entities_applied"] == 2  # malformed line skipped


def test_apply_bundle_legacy_phase2_bundle_no_kg(tmp_path: Path):
    """Apply a Phase 2-style bundle (empty KG sections) without errors."""
    db = MemoryDB(tmp_path / "legacy_apply.db", embedding_dims=0)
    payload = {
        "manifest.json": json.dumps(
            {"row_count": 0, "schema_version": "mem_002_compression"}
        ).encode("utf-8"),
        "memories.jsonl": b"",
        "memories_entities.jsonl": b"",
        "memories_edges.jsonl": b"",
    }
    bundle = encode_bundle(payload, _PASS)
    import asyncio

    counts = asyncio.run(apply_bundle(db, bundle, _PASS))
    assert counts["entities_applied"] == 0
    assert counts["edges_applied"] == 0
    assert counts["links_applied"] == 0


def test_apply_kg_sections_handles_db_exception_per_row(tmp_path: Path):
    """Each row insert is wrapped in try/except — an error on one row is
    logged + skipped, the rest proceed."""
    db = MemoryDB(tmp_path / "err.db", embedding_dims=0)
    # Edge referencing nonexistent entity ids — FK violation when foreign
    # keys are on. Rest of the batch should still be processed.
    payload = {
        "memories_entities.jsonl": b"",
        # Edge with FK violation (entity ids 'nope1', 'nope2' don't exist).
        "memories_edges.jsonl": (
            b'{"id": "ed1", "source_id": "nope1", "target_id": "nope2", '
            b'"relation_type": "uses", "created_at": "2026-01-01"}\n'
        ),
        "memories_entity_links.jsonl": (
            b'{"memory_id": "no_mem", "entity_id": "no_ent"}\n'
        ),
    }
    counts = _apply_kg_sections(db, payload)
    # FK violations -> skipped silently; counts may be 0 per side.
    assert "edges_applied" in counts
    assert "links_applied" in counts


def test_apply_kg_sections_with_invalid_jsonl_in_each_section(tmp_path: Path):
    """All three sections handle malformed JSONL lines gracefully."""
    db = MemoryDB(tmp_path / "bad.db", embedding_dims=0)
    payload = {
        "memories_entities.jsonl": b"NOT JSON\n",
        "memories_edges.jsonl": b"ALSO NOT JSON\n",
        "memories_entity_links.jsonl": b"NEITHER\n",
    }
    counts = _apply_kg_sections(db, payload)
    assert counts == {
        "entities_applied": 0,
        "edges_applied": 0,
        "links_applied": 0,
    }
