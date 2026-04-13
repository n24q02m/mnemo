"""Coverage tests for vec-enabled code paths that work on runners WITHOUT
sqlite3 enable_load_extension support.

These tests set `_vec_enabled=True` on a MemoryDB instance after construction
and stub out the underlying sqlite3 operations that would otherwise require
the sqlite-vec virtual table. The goal is to execute the `if self._vec_enabled`
branches in db.py so CI coverage on macOS hosted runners (which build Python
without --enable-loadable-sqlite-extensions) still reaches the 95% threshold.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mnemo_mcp.db import MemoryDB


@pytest.fixture
def _forced_vec_db(tmp_path: Path):
    """MemoryDB with _vec_enabled forcibly True and a *regular* memories_vec
    table standing in for the virtual vec0 table. Only the schema columns the
    code touches (id, embedding, plus a fake distance column for SELECTs) are
    needed for the non-MATCH paths to execute without errors.

    The MATCH-based semantic search path is exercised separately by stubbing
    _conn.execute results.
    """
    db = MemoryDB(tmp_path / "forced_vec.db", embedding_dims=3)
    db._vec_enabled = True
    # Create a plain table with the same columns for INSERT/DELETE to work.
    # The CREATE VIRTUAL TABLE line in _init_schema already ran (or was
    # skipped on macOS); either way, make sure a usable table exists.
    try:
        db._conn.execute("DROP TABLE IF EXISTS memories_vec")
    except Exception:
        pass
    db._conn.execute("CREATE TABLE memories_vec (id TEXT PRIMARY KEY, embedding BLOB)")
    db._conn.commit()
    yield db
    db.close()


class TestAddWithForcedVec:
    def test_add_with_embedding_executes_vec_insert(self, _forced_vec_db):
        """add() with embedding + vec_enabled inserts into memories_vec."""
        mid = _forced_vec_db.add("hello", embedding=[0.1, 0.2, 0.3])
        row = _forced_vec_db._conn.execute(
            "SELECT id FROM memories_vec WHERE id = ?", (mid,)
        ).fetchone()
        assert row is not None


class TestUpdateWithForcedVec:
    def test_update_embedding_replaces_vec_row(self, _forced_vec_db):
        mid = _forced_vec_db.add("hello", embedding=[0.1, 0.2, 0.3])
        ok = _forced_vec_db.update(mid, embedding=[0.9, 0.8, 0.7])
        assert ok is True
        row = _forced_vec_db._conn.execute(
            "SELECT COUNT(*) AS c FROM memories_vec WHERE id = ?", (mid,)
        ).fetchone()
        assert row["c"] == 1


class TestDeleteWithForcedVec:
    def test_delete_removes_vec_row(self, _forced_vec_db):
        mid = _forced_vec_db.add("hello", embedding=[0.1, 0.2, 0.3])
        _forced_vec_db.delete(mid)
        row = _forced_vec_db._conn.execute(
            "SELECT COUNT(*) AS c FROM memories_vec WHERE id = ?", (mid,)
        ).fetchone()
        assert row["c"] == 0


class TestImportReplaceWithForcedVec:
    def test_import_replace_wipes_vec_table(self, _forced_vec_db):
        _forced_vec_db.add("hello", embedding=[0.1, 0.2, 0.3])
        _forced_vec_db.add("world", embedding=[0.4, 0.5, 0.6])
        # import_jsonl(mode="replace") executes DELETE FROM memories_vec
        result = _forced_vec_db.import_jsonl("", mode="replace")
        assert result is not None
        row = _forced_vec_db._conn.execute(
            "SELECT COUNT(*) AS c FROM memories_vec"
        ).fetchone()
        assert row["c"] == 0


class TestStatsWithForcedVec:
    def test_stats_reports_vec_enabled(self, _forced_vec_db):
        stats = _forced_vec_db.stats()
        assert stats["vec_enabled"] is True
