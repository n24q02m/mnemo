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

    assert _alembic_version(isolated_db_path) == "mem_001"


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
    assert _alembic_version(isolated_db_path) == "mem_001"


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
    assert _alembic_version(isolated_db_path) == "mem_001"


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
