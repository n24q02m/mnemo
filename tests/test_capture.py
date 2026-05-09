"""Tests for ``memory(action="capture")`` and the underlying capture pipeline.

Covers:
- Insertion writes the new ``context_type`` column.
- All six canonical context types round-trip.
- Invalid context_type raises ``ValueError``.
- Dedup short-circuits to the existing memory id (no duplicate row).
- ``auto=True`` is preserved end-to-end.
- Server-level ``memory(action="capture")`` dispatcher returns expected JSON.
"""

from __future__ import annotations

import json

import pytest

from mnemo_mcp.capture import CONTEXT_TYPES, capture
from mnemo_mcp.db import MemoryDB
from mnemo_mcp.server import _handle_capture


def _row_count(db: MemoryDB) -> int:
    return db._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]


def _context_type_for(db: MemoryDB, memory_id: str) -> str | None:
    row = db._conn.execute(
        "SELECT context_type FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Pipeline-level tests
# ---------------------------------------------------------------------------


async def test_capture_with_context_type_conversation(tmp_db: MemoryDB):
    result = await capture(tmp_db, "User said hi", context_type="conversation")

    assert result["deduplicated"] is False
    assert result["context_type"] == "conversation"
    assert _row_count(tmp_db) == 1
    assert _context_type_for(tmp_db, result["memory_id"]) == "conversation"


@pytest.mark.parametrize(
    "ctype",
    sorted(CONTEXT_TYPES),
)
async def test_capture_all_6_context_types(tmp_db: MemoryDB, ctype: str):
    result = await capture(tmp_db, f"sample {ctype} content", context_type=ctype)

    assert result["deduplicated"] is False
    assert result["context_type"] == ctype
    assert _context_type_for(tmp_db, result["memory_id"]) == ctype


async def test_capture_invalid_context_type_raises(tmp_db: MemoryDB):
    with pytest.raises(ValueError, match="Unknown context_type"):
        await capture(tmp_db, "some text", context_type="not-a-valid-type")

    # And no row was written.
    assert _row_count(tmp_db) == 0


async def test_capture_dedup_returns_existing_id(tmp_db: MemoryDB):
    text = "User prefers the dark theme for the dashboard"

    first = await capture(tmp_db, text, context_type="preference")
    second = await capture(tmp_db, text, context_type="preference")

    assert first["deduplicated"] is False
    assert second["deduplicated"] is True
    assert second["memory_id"] == first["memory_id"]
    assert second.get("similarity") is not None
    # Only one row total — dedup did not insert a duplicate.
    assert _row_count(tmp_db) == 1


async def test_capture_below_dedup_threshold_inserts_new(tmp_db: MemoryDB, monkeypatch):
    # Force a high threshold so even identical-keyword text inserts new rows.
    monkeypatch.setenv("DEDUP_THRESHOLD", "0.999")

    first = await capture(tmp_db, "completely unique sentence one", context_type="fact")
    second = await capture(
        tmp_db,
        "another wholly different statement with no overlap",
        context_type="fact",
    )

    assert first["deduplicated"] is False
    assert second["deduplicated"] is False
    assert first["memory_id"] != second["memory_id"]
    assert _row_count(tmp_db) == 2


async def test_capture_auto_flag_stored(tmp_db: MemoryDB):
    result = await capture(tmp_db, "auto captured fact", context_type="fact", auto=True)

    assert result["auto"] is True
    assert result["deduplicated"] is False


async def test_capture_passes_category_tags_source(tmp_db: MemoryDB):
    result = await capture(
        tmp_db,
        "User prefers Vim over Emacs",
        context_type="preference",
        category="editor",
        tags=["vim", "preference"],
        source="user-message",
    )

    row = tmp_db.get(result["memory_id"])
    assert row is not None
    assert row["category"] == "editor"
    assert json.loads(row["tags"]) == ["vim", "preference"]
    assert row["source"] == "user-message"


# ---------------------------------------------------------------------------
# Server-dispatcher tests
# ---------------------------------------------------------------------------


async def test_handle_capture_missing_text_returns_error(mock_ctx):
    ctx, _db = mock_ctx
    raw = await _handle_capture(ctx, text=None, context_type="fact")
    payload = json.loads(raw)

    assert "error" in payload
    assert "text" in payload["error"]


async def test_handle_capture_invalid_context_type_returns_error(mock_ctx):
    ctx, _db = mock_ctx
    raw = await _handle_capture(ctx, text="something", context_type="not-real")
    payload = json.loads(raw)

    assert "error" in payload
    assert "valid_context_types" in payload
    assert "conversation" in payload["valid_context_types"]


async def test_handle_capture_inserts_and_returns_id(mock_ctx):
    ctx, db = mock_ctx
    raw = await _handle_capture(
        ctx,
        text="User picked PostgreSQL for the orders DB",
        context_type="decision",
        category="architecture",
    )
    payload = json.loads(raw)

    assert payload["status"] == "captured"
    assert payload["context_type"] == "decision"
    assert payload["deduplicated"] is False
    assert payload["auto"] is False
    assert "id" in payload

    assert _context_type_for(db, payload["id"]) == "decision"


async def test_handle_capture_dedup_returns_status_deduplicated(mock_ctx):
    ctx, _db = mock_ctx

    text = "All API errors return JSON with code, message, and request_id"
    first = json.loads(await _handle_capture(ctx, text=text, context_type="decision"))
    second = json.loads(await _handle_capture(ctx, text=text, context_type="decision"))

    assert first["status"] == "captured"
    assert second["status"] == "deduplicated"
    assert second["id"] == first["id"]
    assert second["deduplicated"] is True
    assert "similarity" in second
