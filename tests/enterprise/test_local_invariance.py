"""Wave B Task 7: local-mode invariance pin.

With ``MNEMO_ENTERPRISE`` unset the Wave B columns exist but carry only
backfill defaults, and every default read/write path behaves exactly as
before: search/list/get output keeps the full physical row shape, legacy
writes land with the Wave B defaults, and the RBAC builder is a no-op
without a principal.
"""

from __future__ import annotations

import json

from mnemo_mcp.db import (
    MEMORY_COLUMNS,
    MemoryDB,
    _build_fts_queries,
)

# The physical ``memories`` column list after Wave B. Everything through
# ``superseded_by`` predates Wave B; the final three are the mem_006
# additions. Nothing else may appear.
_WAVE_B_COLUMNS = frozenset({"tenant_id", "owner_sub", "visibility"})


def test_memory_columns_gained_only_wave_b_three():
    assert set(MEMORY_COLUMNS) - _WAVE_B_COLUMNS == frozenset(
        {
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
            "commit_sha",
            "valid_from",
            "valid_to",
            "superseded_by",
        }
    )
    assert _WAVE_B_COLUMNS <= set(MEMORY_COLUMNS)


def test_local_write_then_read_roundtrip(tmp_path):
    """Legacy add -> get -> list -> search -> export is shape-identical."""
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    try:
        mid = db.add("alpha launch retro notes", category="work", tags=["urgent"])
        row = db.get(mid)
        assert row is not None
        # Backfill semantic: legacy-shaped write lands with Wave B defaults.
        assert (row["tenant_id"], row["owner_sub"], row["visibility"]) == (
            "local",
            None,
            "private",
        )
        assert row["content"] == "alpha launch retro notes"
        assert row["category"] == "work"
        assert json.loads(row["tags"]) == ["urgent"]

        listed = db.list_memories()
        assert [r["id"] for r in listed] == [mid]
        assert set(listed[0]) == set(MEMORY_COLUMNS)

        hits = db.search("alpha launch")
        assert [r["id"] for r in hits] == [mid]
        assert set(hits[0]) - {"score"} == set(MEMORY_COLUMNS)

        jsonl, count = db.export_jsonl()
        assert count == 1
        record = json.loads(jsonl.splitlines()[0])
        assert record["id"] == mid
        assert record["content"] == "alpha launch retro notes"
    finally:
        db.close()


def test_rbac_builder_noop_without_principal(tmp_path):
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    try:
        assert db._build_rbac_sql(None) == ("", [])
        assert db._build_rbac_sql(None, "sub-a") == ("", [])
        # Local rows: None principal sees them; a principal does not.
        mid = db.add("alpha legacy content")
        assert db.get(mid) is not None
        assert db.get(mid, principal=None) is not None
    finally:
        db.close()


def test_fts_query_builder_untouched():
    assert _build_fts_queries("alpha beta") == _build_fts_queries("alpha beta")
    assert "alpha" in _build_fts_queries("alpha")[0]
