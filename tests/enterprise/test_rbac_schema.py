"""Wave B RBAC schema: tenants/orgs/teams + memories tenant columns (spec §4.2).

mem_006 adds the RBAC tables idempotently and backfills legacy memory rows to
``('local', NULL, 'private')`` so local-mode semantics survive the migration.
"""

from __future__ import annotations

import hashlib
import sqlite3

from alembic import command
from alembic.config import Config

from mnemo_mcp.db import _ALEMBIC_INI_PATH, _ALEMBIC_SCRIPT_LOCATION, MemoryDB

_EXPECTED_TABLES = ("tenants", "org_members", "teams", "team_members")
_EXPECTED_INDEXES = ("idx_memories_tenant_vis", "idx_memories_owner")


def _cfg(db_path) -> Config:
    cfg = Config(str(_ALEMBIC_INI_PATH))
    cfg.set_main_option("script_location", str(_ALEMBIC_SCRIPT_LOCATION))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.resolve().as_posix()}")
    return cfg


def _schema_hash(conn: sqlite3.Connection) -> str:
    dump = "\n".join(
        "|".join("" if v is None else str(v) for v in row)
        for row in conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
    )
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def test_rbac_tables_exist(tmp_path):
    db = MemoryDB(tmp_path / "memories.db", embedding_dims=0)
    try:
        tables = _tables(db._conn)
        for name in _EXPECTED_TABLES:
            assert name in tables, f"missing RBAC table: {name}"
        indexes = {
            r[0]
            for r in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        for name in _EXPECTED_INDEXES:
            assert name in indexes, f"missing RBAC index: {name}"
        cols = {r[1] for r in db._conn.execute("PRAGMA table_info(memories)")}
        assert {"tenant_id", "owner_sub", "visibility"} <= cols
    finally:
        db.close()


def test_legacy_rows_backfill_and_upgrade_idempotent(tmp_path):
    """Legacy rows land on ('local', NULL, 'private'); re-upgrade is a no-op."""
    path = tmp_path / "memories.db"
    db = MemoryDB(path, embedding_dims=0)
    db.close()

    cfg = _cfg(path)
    command.downgrade(cfg, "mem_005_enterprise_audit")

    raw = sqlite3.connect(str(path))
    try:
        cols = {r[1] for r in raw.execute("PRAGMA table_info(memories)")}
        assert {"tenant_id", "owner_sub", "visibility"} - cols, (
            "downgrade must remove the RBAC columns for a true legacy simulation"
        )
        raw.execute(
            "INSERT INTO memories (id, content, category, tags, source,"
            " created_at, updated_at, access_count, last_accessed)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-001",
                "legacy content",
                "general",
                "[]",
                None,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
                0,
                "2026-01-01T00:00:00Z",
            ),
        )
        raw.commit()
    finally:
        raw.close()

    command.upgrade(cfg, "head")
    check = sqlite3.connect(str(path))
    try:
        row = check.execute(
            "SELECT tenant_id, owner_sub, visibility FROM memories WHERE id = ?",
            ("legacy-001",),
        ).fetchone()
        assert tuple(row) == ("local", None, "private")
        before = _schema_hash(check)
    finally:
        check.close()

    command.upgrade(cfg, "head")
    check = sqlite3.connect(str(path))
    try:
        assert _schema_hash(check) == before
        row = check.execute(
            "SELECT tenant_id, owner_sub, visibility FROM memories WHERE id = ?",
            ("legacy-001",),
        ).fetchone()
        assert tuple(row) == ("local", None, "private")
    finally:
        check.close()
