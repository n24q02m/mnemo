"""Tests for Alembic migration runner inside ``MemoryDB.__init__``.

Covers:
- ``baseline_001 -> mem_001`` adds ``context_type`` and ``archived_at`` columns.
- Existing pre-migration rows survive and pick up the default ``context_type``.
- Re-running the migration twice is a no-op (idempotent path).
- A backup file is produced before forward migrations are applied.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mnemo_mcp.db import MemoryDB


@pytest.fixture
def isolated_db_path(tmp_path: Path) -> Path:
    """Yield a clean temporary DB path with no existing file."""
    return tmp_path / "memories.db"


def _table_columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {row[1] for row in rows}
    finally:
        conn.close()


def _alembic_version(db_path: Path) -> str | None:
    conn = sqlite3.connect(str(db_path))
    try:
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.OperationalError:
            return None
        return row[0] if row else None
    finally:
        conn.close()


def test_migration_baseline_to_mem_001_adds_columns(isolated_db_path: Path) -> None:
    """Fresh DB lands at head with the new columns present."""
    db = MemoryDB(isolated_db_path, embedding_dims=0)
    db.close()

    cols = _table_columns(isolated_db_path, "memories")
    assert "context_type" in cols, f"expected context_type column, got: {cols}"
    assert "archived_at" in cols, f"expected archived_at column, got: {cols}"
    # Importance was added pre-Alembic but should still be present.
    assert "importance" in cols

    assert _alembic_version(isolated_db_path) == "mem_002_compression"


def test_existing_data_preserved_with_default_context_type(
    isolated_db_path: Path,
) -> None:
    """Rows inserted before mem_001 keep their data and get the default value."""
    # Phase 1: simulate a pre-Alembic install — create the legacy schema and
    # insert a row without context_type, without invoking the runner.
    conn = sqlite3.connect(str(isolated_db_path))
    conn.executescript(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY NOT NULL,
            content TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            tags TEXT NOT NULL DEFAULT '[]',
            source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            access_count INTEGER NOT NULL DEFAULT 0,
            last_accessed TEXT NOT NULL,
            importance REAL NOT NULL DEFAULT 0.5
        );
        """
    )
    conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('legacy-1', 'legacy content', '2026-01-01', '2026-01-01', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    # Phase 2: open through MemoryDB — runner stamps baseline_001 then applies
    # mem_001.
    db = MemoryDB(isolated_db_path, embedding_dims=0)
    db.close()

    conn = sqlite3.connect(str(isolated_db_path))
    try:
        row = conn.execute(
            "SELECT id, content, context_type, archived_at FROM memories "
            "WHERE id = 'legacy-1'"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "legacy row was lost during migration"
    assert row[0] == "legacy-1"
    assert row[1] == "legacy content"
    assert row[2] == "conversation", "expected default context_type"
    assert row[3] is None, "archived_at should be NULL by default"
    assert _alembic_version(isolated_db_path) == "mem_002_compression"


def test_idempotent_rerun_does_not_error(isolated_db_path: Path) -> None:
    """Opening the DB a second time must not re-add columns or raise."""
    db1 = MemoryDB(isolated_db_path, embedding_dims=0)
    db1.close()

    # Second open at head — runner should detect current==head and return.
    db2 = MemoryDB(isolated_db_path, embedding_dims=0)
    db2.close()

    cols = _table_columns(isolated_db_path, "memories")
    # Columns appear exactly once each
    assert sum(1 for c in cols if c == "context_type") == 1
    assert sum(1 for c in cols if c == "archived_at") == 1
    assert _alembic_version(isolated_db_path) == "mem_002_compression"


def _table_exists(db_path: Path, table: str) -> bool:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def test_mem_002_adds_compression_columns(isolated_db_path: Path) -> None:
    """``mem_002_compression`` adds text_raw / compressed / compression_provider."""
    # Seed pre-mem_002 schema with 5 rows.
    conn = sqlite3.connect(str(isolated_db_path))
    conn.executescript(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY NOT NULL,
            content TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            tags TEXT NOT NULL DEFAULT '[]',
            source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            access_count INTEGER NOT NULL DEFAULT 0,
            last_accessed TEXT NOT NULL,
            importance REAL NOT NULL DEFAULT 0.5
        );
        """
    )
    for i in range(5):
        conn.execute(
            "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
            "VALUES (?, ?, '2026-01-01', '2026-01-01', '2026-01-01')",
            (f"seed-{i}", f"seed content {i}"),
        )
    conn.commit()
    conn.close()

    db = MemoryDB(isolated_db_path, embedding_dims=0)
    db.close()

    cols = _table_columns(isolated_db_path, "memories")
    assert "text_raw" in cols, f"expected text_raw column, got: {cols}"
    assert "compressed" in cols, f"expected compressed column, got: {cols}"
    assert "compression_provider" in cols, (
        f"expected compression_provider column, got: {cols}"
    )

    # Pre-existing rows have NULL text_raw, compressed=0, NULL provider.
    conn = sqlite3.connect(str(isolated_db_path))
    try:
        rows = conn.execute(
            "SELECT id, text_raw, compressed, compression_provider FROM memories "
            "ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 5
    for row in rows:
        assert row[1] is None, f"expected NULL text_raw on legacy row, got {row[1]}"
        assert row[2] == 0, f"expected compressed=0 on legacy row, got {row[2]}"
        assert row[3] is None, (
            f"expected NULL compression_provider on legacy row, got {row[3]}"
        )

    assert _alembic_version(isolated_db_path) == "mem_002_compression"


def test_mem_002_creates_sync_state_table(isolated_db_path: Path) -> None:
    """``sync_state`` table exists with the documented schema after mem_002."""
    db = MemoryDB(isolated_db_path, embedding_dims=0)
    db.close()

    assert _table_exists(isolated_db_path, "sync_state")

    cols = _table_columns(isolated_db_path, "sync_state")
    assert "backend" in cols
    assert "last_sync_at" in cols
    assert "last_commit_sha" in cols
    assert "upload_cursor" in cols


def test_mem_002_idempotent(isolated_db_path: Path) -> None:
    """Running the migration twice is a no-op."""
    db1 = MemoryDB(isolated_db_path, embedding_dims=0)
    db1.close()
    db2 = MemoryDB(isolated_db_path, embedding_dims=0)
    db2.close()

    cols = _table_columns(isolated_db_path, "memories")
    # Each compression column appears exactly once.
    for col in ("text_raw", "compressed", "compression_provider"):
        assert sum(1 for c in cols if c == col) == 1, (
            f"{col} appeared more than once in {cols}"
        )

    assert _alembic_version(isolated_db_path) == "mem_002_compression"


def test_mem_002_sync_state_helpers_round_trip(isolated_db_path: Path) -> None:
    """``MemoryDB.get/upsert_sync_state`` round-trip cleanly across backends."""
    db = MemoryDB(isolated_db_path, embedding_dims=0)
    try:
        assert db.get_sync_state("s3") is None

        db.upsert_sync_state(
            "s3", last_sync_at=12345.0, last_commit_sha="abc123", upload_cursor=7
        )
        state = db.get_sync_state("s3")
        assert state == {
            "backend": "s3",
            "last_sync_at": 12345.0,
            "last_commit_sha": "abc123",
            "upload_cursor": 7,
        }

        # Partial update preserves untouched fields.
        db.upsert_sync_state("s3", upload_cursor=8)
        state = db.get_sync_state("s3")
        assert state is not None
        assert state["upload_cursor"] == 8
        assert state["last_sync_at"] == 12345.0
        assert state["last_commit_sha"] == "abc123"

        # Independent backends do not collide.
        db.upsert_sync_state("gdrive", upload_cursor=1)
        gdrive_state = db.get_sync_state("gdrive")
        s3_state = db.get_sync_state("s3")
        assert gdrive_state is not None and gdrive_state["upload_cursor"] == 1
        assert s3_state is not None and s3_state["upload_cursor"] == 8
    finally:
        db.close()


def test_mem_002_add_with_context_type_compression_columns(
    isolated_db_path: Path,
) -> None:
    """``add_with_context_type`` writes compression columns when supplied."""
    db = MemoryDB(isolated_db_path, embedding_dims=0)
    try:
        mid = db.add_with_context_type(
            content="compressed text",
            context_type="fact",
            text_raw="original much longer raw text",
            compressed=True,
            compression_provider="gemini",
        )
    finally:
        db.close()

    conn = sqlite3.connect(str(isolated_db_path))
    try:
        row = conn.execute(
            "SELECT content, text_raw, compressed, compression_provider "
            "FROM memories WHERE id = ?",
            (mid,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "compressed text"
    assert row[1] == "original much longer raw text"
    assert row[2] == 1
    assert row[3] == "gemini"


def test_backup_file_created_for_pre_alembic_db(isolated_db_path: Path) -> None:
    """A pre-Alembic DB triggers a forward upgrade, which must back up first."""
    # Seed legacy schema (no alembic_version table).
    conn = sqlite3.connect(str(isolated_db_path))
    conn.executescript(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY NOT NULL,
            content TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            tags TEXT NOT NULL DEFAULT '[]',
            source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            access_count INTEGER NOT NULL DEFAULT 0,
            last_accessed TEXT NOT NULL,
            importance REAL NOT NULL DEFAULT 0.5
        );
        """
    )
    conn.commit()
    conn.close()

    db = MemoryDB(isolated_db_path, embedding_dims=0)
    db.close()

    backups = list(isolated_db_path.parent.glob("memories.db.bak.*"))
    assert backups, (
        "expected at least one .bak.<ts> file alongside DB after migration; "
        f"found: {list(isolated_db_path.parent.iterdir())}"
    )
