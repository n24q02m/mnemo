"""Tests for Phase 1 archive policy: importance x recency + restore.

Covers:
- ``archive_by_score`` flips ``archived_at`` when
  ``recency_factor * (1 - importance) > score_threshold``.
- High-importance rows survive longer than equally-aged low-importance rows.
- Recently-updated rows are kept regardless of importance.
- ``restore_memory`` clears ``archived_at`` on the soft-archived row.
- ``search`` excludes soft-archived rows by default; ``include_archived=True``
  re-includes them.
- Boundary behaviour around ``score_threshold = 1.0``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mnemo_mcp.db import MemoryDB


def _set_age(db: MemoryDB, memory_id: str, days_old: int) -> None:
    aged_ts = (datetime.now(UTC) - timedelta(days=days_old)).isoformat()
    db._conn.execute(
        "UPDATE memories SET updated_at = ?, last_accessed = ? WHERE id = ?",
        (aged_ts, aged_ts, memory_id),
    )
    db._conn.commit()


def _archived_at(db: MemoryDB, memory_id: str) -> str | None:
    row = db._conn.execute(
        "SELECT archived_at FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# archive_by_score: scoring formula
# ---------------------------------------------------------------------------


def test_archive_old_low_importance_memory_archived(tmp_db: MemoryDB):
    """Old + low importance -> recency_factor*(1-importance) > 1 -> archive."""
    mid = tmp_db.add("legacy todo nobody opens")
    tmp_db.update_importance(mid, 0.1)
    _set_age(tmp_db, mid, days_old=200)  # ~2.2x archive_after_days

    count = tmp_db.archive_by_score(archive_after_days=90)

    assert count == 1
    assert _archived_at(tmp_db, mid) is not None


def test_archive_high_importance_kept(tmp_db: MemoryDB):
    """Equally aged but high importance -> below threshold -> kept."""
    mid = tmp_db.add("critical infrastructure decision")
    tmp_db.update_importance(mid, 0.95)
    _set_age(tmp_db, mid, days_old=200)

    count = tmp_db.archive_by_score(archive_after_days=90)

    assert count == 0
    assert _archived_at(tmp_db, mid) is None


def test_archive_recent_kept_regardless_of_importance(tmp_db: MemoryDB):
    """recency_factor < 1 -> score < 1 even with importance=0 -> kept."""
    mid = tmp_db.add("fresh capture from this morning")
    tmp_db.update_importance(mid, 0.0)
    _set_age(tmp_db, mid, days_old=10)  # 10/90 = 0.11 < 1.0

    count = tmp_db.archive_by_score(archive_after_days=90)

    assert count == 0
    assert _archived_at(tmp_db, mid) is None


def test_archive_score_boundary_just_above_one(tmp_db: MemoryDB):
    """Score just above the threshold (1.0) flips to archived."""
    mid = tmp_db.add("boundary candidate")
    tmp_db.update_importance(mid, 0.0)  # multiplier = 1.0
    _set_age(tmp_db, mid, days_old=110)  # 110/100 = 1.10 > 1.0

    count = tmp_db.archive_by_score(archive_after_days=100)

    assert count == 1
    assert _archived_at(tmp_db, mid) is not None


def test_archive_score_boundary_just_below_one(tmp_db: MemoryDB):
    """Score just below the threshold (1.0) stays active."""
    mid = tmp_db.add("under-threshold candidate")
    tmp_db.update_importance(mid, 0.0)
    _set_age(tmp_db, mid, days_old=90)  # 90/100 = 0.9 < 1.0

    count = tmp_db.archive_by_score(archive_after_days=100)

    assert count == 0
    assert _archived_at(tmp_db, mid) is None


def test_archive_skips_already_archived(tmp_db: MemoryDB):
    """Re-running archive_by_score is idempotent for archived rows."""
    mid = tmp_db.add("already archived")
    tmp_db.update_importance(mid, 0.0)
    _set_age(tmp_db, mid, days_old=300)

    first = tmp_db.archive_by_score(archive_after_days=90)
    second = tmp_db.archive_by_score(archive_after_days=90)

    assert first == 1
    assert second == 0


def test_archive_by_score_default_after_days_uses_settings(tmp_db: MemoryDB):
    """Falls back to settings.archive_after_days (90) when arg omitted."""
    mid = tmp_db.add("default after_days candidate")
    tmp_db.update_importance(mid, 0.0)
    _set_age(tmp_db, mid, days_old=200)  # 200/90 ~ 2.2 > 1.0

    count = tmp_db.archive_by_score()

    assert count == 1
    assert _archived_at(tmp_db, mid) is not None


# ---------------------------------------------------------------------------
# Restore action
# ---------------------------------------------------------------------------


def test_restore_action_unsets_archived_at(tmp_db: MemoryDB):
    mid = tmp_db.add("paused initiative")
    tmp_db.update_importance(mid, 0.0)
    _set_age(tmp_db, mid, days_old=200)
    tmp_db.archive_by_score(archive_after_days=90)
    assert _archived_at(tmp_db, mid) is not None

    ok = tmp_db.restore_memory(mid)

    assert ok is True
    assert _archived_at(tmp_db, mid) is None


def test_restore_nonexistent_returns_false(tmp_db: MemoryDB):
    assert tmp_db.restore_memory("does-not-exist") is False


# ---------------------------------------------------------------------------
# search default exclusion + include_archived flag
# ---------------------------------------------------------------------------


def test_search_excludes_archived_default(tmp_db: MemoryDB):
    keep_id = tmp_db.add("python script for backup")
    archive_id = tmp_db.add("python script for legacy export")
    tmp_db.update_importance(archive_id, 0.0)
    _set_age(tmp_db, archive_id, days_old=300)
    tmp_db.archive_by_score(archive_after_days=90)

    results = tmp_db.search("python script", limit=10)
    found = {r["id"] for r in results}

    assert keep_id in found
    assert archive_id not in found


def test_search_includes_archived_when_flag_true(tmp_db: MemoryDB):
    keep_id = tmp_db.add("redis caching strategy")
    archive_id = tmp_db.add("redis caching strategy old")
    tmp_db.update_importance(archive_id, 0.0)
    _set_age(tmp_db, archive_id, days_old=300)
    tmp_db.archive_by_score(archive_after_days=90)

    results = tmp_db.search("redis caching", include_archived=True, limit=10)
    found = {r["id"] for r in results}

    assert keep_id in found
    assert archive_id in found


# ---------------------------------------------------------------------------
# list_archived after soft-archive
# ---------------------------------------------------------------------------


def test_list_archived_returns_soft_archived_rows(tmp_db: MemoryDB):
    mid1 = tmp_db.add("alpha kept")  # not archived
    mid2 = tmp_db.add("beta archived")
    tmp_db.update_importance(mid2, 0.0)
    _set_age(tmp_db, mid2, days_old=200)
    tmp_db.archive_by_score(archive_after_days=90)

    archived = tmp_db.list_archived()
    archived_ids = {a["id"] for a in archived}

    assert mid2 in archived_ids
    assert mid1 not in archived_ids


# ---------------------------------------------------------------------------
# Server-level capture trigger: capture passthrough should not reset archive
# ---------------------------------------------------------------------------


async def test_capture_does_not_unset_archived_at(tmp_db: MemoryDB):
    """Capture inserts a NEW row; existing archived rows are untouched."""
    from mnemo_mcp.capture import capture

    archived_id = tmp_db.add("archived row stays archived")
    tmp_db.update_importance(archived_id, 0.0)
    _set_age(tmp_db, archived_id, days_old=200)
    tmp_db.archive_by_score(archive_after_days=90)
    assert _archived_at(tmp_db, archived_id) is not None

    await capture(tmp_db, "wholly new captured fact", context_type="fact")

    # Existing archived row remains archived; new row is active.
    assert _archived_at(tmp_db, archived_id) is not None


# ---------------------------------------------------------------------------
# memory(action="archive_now") server dispatcher
# ---------------------------------------------------------------------------


async def test_handle_archive_now_runs_archive_by_score(mock_ctx):
    import json

    from mnemo_mcp.server import _handle_archive_now

    ctx, db = mock_ctx
    mid = db.add("a stale row")
    db.update_importance(mid, 0.0)
    _set_age(db, mid, days_old=200)

    raw = await _handle_archive_now(ctx)
    payload = json.loads(raw)

    assert payload["status"] == "archived"
    assert payload["count"] >= 1
    assert _archived_at(db, mid) is not None


async def test_archive_now_via_memory_dispatcher(mock_ctx):
    import json

    from mnemo_mcp.server import memory

    ctx, db = mock_ctx
    mid = db.add("dispatcher target")
    db.update_importance(mid, 0.0)
    _set_age(db, mid, days_old=300)

    raw = await memory(action="archive_now", ctx=ctx)
    payload = json.loads(raw)

    assert payload["status"] == "archived"
    assert payload["count"] >= 1
    assert _archived_at(db, mid) is not None


# ---------------------------------------------------------------------------
# Auto-trigger via capture counter
# ---------------------------------------------------------------------------


async def test_capture_triggers_archive_at_interval(mock_ctx, monkeypatch):
    """ARCHIVE_TRIGGER_EVERY=1 -> every capture schedules an archive sweep."""
    import json

    from mnemo_mcp.server import _CAPTURE_COUNTER, memory

    ctx, db = mock_ctx
    monkeypatch.setenv("ARCHIVE_TRIGGER_EVERY", "1")
    _CAPTURE_COUNTER["calls"] = 0

    archive_id = db.add("legacy reminder")
    db.update_importance(archive_id, 0.0)
    _set_age(db, archive_id, days_old=300)

    raw = await memory(
        action="capture", text="brand new note", context_type="fact", ctx=ctx
    )
    payload = json.loads(raw)
    assert payload["status"] == "captured"

    # Background task may need a tick to land; await any scheduled tasks.
    import asyncio

    pending = [
        t
        for t in asyncio.all_tasks()
        if not t.done() and t is not asyncio.current_task()
    ]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    assert _archived_at(db, archive_id) is not None
    assert _CAPTURE_COUNTER["calls"] >= 1


# ---------------------------------------------------------------------------
# Edge-case coverage for archive_by_score
# ---------------------------------------------------------------------------


def test_archive_by_score_skips_invalid_timestamp(tmp_db: MemoryDB):
    """A row whose updated_at cannot be parsed is silently skipped."""
    mid = tmp_db.add("corrupt timestamp candidate")
    tmp_db.update_importance(mid, 0.0)
    tmp_db._conn.execute(
        "UPDATE memories SET updated_at = ? WHERE id = ?",
        ("not-a-real-iso-timestamp", mid),
    )
    tmp_db._conn.commit()

    count = tmp_db.archive_by_score(archive_after_days=90)
    assert count == 0
    assert _archived_at(tmp_db, mid) is None


def test_archive_by_score_returns_zero_on_empty_db(tmp_db: MemoryDB):
    assert tmp_db.archive_by_score(archive_after_days=90) == 0


# ---------------------------------------------------------------------------
# Legacy-path coverage for restore + list_archived
# ---------------------------------------------------------------------------


def test_restore_legacy_archived_memories_table_path(tmp_db: MemoryDB):
    """Pre-mem_001 hard-archived rows can still be restored."""
    legacy_id = "legacy-restore-id"
    tmp_db._conn.execute(
        """INSERT INTO archived_memories
           (id, content, category, tags, source, importance,
            created_at, updated_at, access_count, last_accessed, archived_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            legacy_id,
            "legacy content",
            "general",
            "[]",
            None,
            0.5,
            "2026-01-01",
            "2026-01-01",
            0,
            "2026-01-01",
            "2026-01-02",
        ),
    )
    tmp_db._conn.commit()

    assert tmp_db.get(legacy_id) is None

    ok = tmp_db.restore_memory(legacy_id)
    assert ok is True

    restored = tmp_db.get(legacy_id)
    assert restored is not None
    assert restored["content"] == "legacy content"

    legacy_rows = tmp_db._conn.execute(
        "SELECT id FROM archived_memories WHERE id = ?", (legacy_id,)
    ).fetchall()
    assert legacy_rows == []


def test_list_archived_merges_legacy_and_soft(tmp_db: MemoryDB):
    soft_id = tmp_db.add("soft archived item")
    tmp_db.update_importance(soft_id, 0.0)
    _set_age(tmp_db, soft_id, days_old=200)
    tmp_db.archive_by_score(archive_after_days=90)

    tmp_db._conn.execute(
        """INSERT INTO archived_memories
           (id, content, category, tags, source, importance,
            created_at, updated_at, access_count, last_accessed, archived_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "legacy-list-id",
            "legacy listing item",
            "general",
            "[]",
            None,
            0.5,
            "2026-01-01",
            "2026-01-01",
            0,
            "2026-01-01",
            "2026-01-02",
        ),
    )
    tmp_db._conn.commit()

    archived = tmp_db.list_archived()
    archived_ids = {a["id"] for a in archived}

    assert soft_id in archived_ids
    assert "legacy-list-id" in archived_ids


def test_list_memories_excludes_archived_default(tmp_db: MemoryDB):
    keep_id = tmp_db.add("active list item")
    archive_id = tmp_db.add("soon to archive")
    tmp_db.update_importance(archive_id, 0.0)
    _set_age(tmp_db, archive_id, days_old=300)
    tmp_db.archive_by_score(archive_after_days=90)

    listed = tmp_db.list_memories(limit=20)
    listed_ids = {m["id"] for m in listed}

    assert keep_id in listed_ids
    assert archive_id not in listed_ids


def test_list_memories_include_archived_returns_all(tmp_db: MemoryDB):
    keep_id = tmp_db.add("first row")
    archive_id = tmp_db.add("second row about to archive")
    tmp_db.update_importance(archive_id, 0.0)
    _set_age(tmp_db, archive_id, days_old=300)
    tmp_db.archive_by_score(archive_after_days=90)

    listed = tmp_db.list_memories(include_archived=True, limit=20)
    listed_ids = {m["id"] for m in listed}

    assert keep_id in listed_ids
    assert archive_id in listed_ids


def test_list_memories_with_category_excludes_archived(tmp_db: MemoryDB):
    keep_id = tmp_db.add("active in cat", category="work")
    archive_id = tmp_db.add("archived in cat", category="work")
    tmp_db.update_importance(archive_id, 0.0)
    _set_age(tmp_db, archive_id, days_old=300)
    tmp_db.archive_by_score(archive_after_days=90)

    listed = tmp_db.list_memories(category="work", limit=20)
    listed_ids = {m["id"] for m in listed}

    assert keep_id in listed_ids
    assert archive_id not in listed_ids
