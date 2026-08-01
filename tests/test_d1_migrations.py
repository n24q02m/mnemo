"""Tests for the Cloudflare D1 migrations in ``migrations/``.

``migrations/0001_init.sql`` is the initial schema for the D1 backend. Unlike
the SQLite path -- where ``MemoryDB._init_schema`` creates base tables and the
Alembic revisions grow them with ``ALTER TABLE ADD COLUMN`` -- a D1 database is
created in one shot, so the migration has to encode the *end state* of that
lineage. These tests load the file into a blank SQLite database and assert the
objects it produces, then diff the result against a real ``MemoryDB`` so the
migration cannot silently drift when someone adds a column to ``db.py``.

They also pin the two D1-specific constraints that are invisible when you only
read the SQL: no ``memories_vec`` (D1 cannot load the ``sqlite-vec``
extension), and no explicit transaction (wrangler scans the raw file and
refuses one).
"""

from __future__ import annotations

import pathlib
import re
import sqlite3

import pytest

from mnemo_mcp.db import MemoryDB

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_MIGRATION = _REPO_ROOT / "migrations" / "0001_init.sql"

# Every object migrations/0001_init.sql is expected to create. Written out in
# full rather than derived, so that adding or dropping DDL forces a deliberate
# edit here.
EXPECTED_TABLES = {
    "archived_memories",
    "memories",
    "memories_fts",
    "memory_edges",
    "memory_entities",
    "memory_entity_links",
    "store_meta",
}
EXPECTED_INDEXES = {
    "idx_archived_memories_archived_at",
    "idx_memories_accessed",
    "idx_memories_category",
    "idx_memories_category_updated",
    "idx_memories_updated",
    "idx_memory_edges_source",
    "idx_memory_edges_target",
    "idx_memory_edges_unique",
    "idx_memory_entities_name_type",
    "idx_memory_entity_links_entity_id",
}
EXPECTED_TRIGGERS = {"memories_ai", "memories_ad", "memories_au"}

# Tables the SQLite lineage has that this migration deliberately omits. The
# first two are plain tables that D1 would accept and are simply out of scope
# for the initial migration; the vec ones need the sqlite-vec extension, which
# D1 cannot load at all.
KNOWN_OMITTED_PREFIXES = (
    "alembic_version",
    "sync_state",
    "memory_audit",
    "memory_entities_vec",
)


def _strip_sql_comments(sql: str) -> str:
    """Return ``sql`` with ``--`` line comments removed.

    The migration's header comment discusses the very tokens these tests grep
    for (``memories_vec``, ``PRAGMA``), so assertions must look at executable
    SQL only.
    """
    return "\n".join(re.sub(r"--.*$", "", line) for line in sql.splitlines())


@pytest.fixture(scope="module")
def migration_sql() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def migrated_conn(migration_sql: str) -> sqlite3.Connection:
    """A blank in-memory SQLite database with the migration applied."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(migration_sql)
    return conn


@pytest.fixture(scope="module")
def sqlite_conn(tmp_path_factory) -> sqlite3.Connection:
    """A real ``MemoryDB``: ``_init_schema`` plus Alembic walked to head."""
    path = tmp_path_factory.mktemp("parity") / "memories.db"
    # embedding_dims=0 skips the sqlite-vec table, which D1 cannot have.
    return MemoryDB(path, embedding_dims=0)._conn


def _objects(conn: sqlite3.Connection, kind: str) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%'",
        (kind,),
    ).fetchall()
    return {r[0] for r in rows}


class TestMigrationApplies:
    def test_migration_file_exists(self):
        assert _MIGRATION.is_file(), f"missing migration: {_MIGRATION}"

    def test_creates_expected_tables(self, migrated_conn: sqlite3.Connection):
        # FTS5 also creates memories_fts_{data,idx,docsize,config} shadow
        # tables; those are an implementation detail of the virtual table.
        tables = {
            t
            for t in _objects(migrated_conn, "table")
            if not t.startswith("memories_fts_")
        }
        assert tables == EXPECTED_TABLES

    def test_creates_expected_indexes(self, migrated_conn: sqlite3.Connection):
        assert _objects(migrated_conn, "index") == EXPECTED_INDEXES

    def test_creates_expected_triggers(self, migrated_conn: sqlite3.Connection):
        assert _objects(migrated_conn, "trigger") == EXPECTED_TRIGGERS


class TestD1Constraints:
    def test_no_vec0_virtual_table(self, migration_sql: str):
        """D1 cannot load the sqlite-vec extension, so vec0 must not appear.

        Vector search on the D1 backend is served by Vectorize instead.
        """
        body = _strip_sql_comments(migration_sql)
        assert "vec0" not in body
        assert "memories_vec" not in body

    def test_no_pragma_statements(self, migration_sql: str):
        """db.py sets WAL / synchronous / busy_timeout / foreign_keys.

        None of those belong in a D1 migration: D1 owns its storage engine, and
        foreign keys are already enforced and cannot be toggled from a query.
        """
        assert "PRAGMA" not in _strip_sql_comments(migration_sql).upper()

    def test_no_explicit_transaction(self, migration_sql: str):
        """wrangler greps the RAW file -- comments included -- for a
        transaction opener and aborts with "contains several transactions".

        D1 already wraps the migration in one. Asserted against the whole file,
        not the comment-stripped body, because that is what wrangler reads.
        """
        assert "BEGIN " + "TRANSACTION" not in migration_sql.upper()

    def test_memories_is_a_rowid_table(self, migrated_conn: sqlite3.Connection):
        """memories_fts is external-content keyed on content_rowid=rowid.

        A WITHOUT ROWID `memories` would break the index and its triggers.
        """
        row = migrated_conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='memories'"
        ).fetchone()
        assert "WITHOUT ROWID" not in row[0].upper()

    def test_fts_is_external_content_over_memories(
        self, migrated_conn: sqlite3.Connection
    ):
        row = migrated_conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='memories_fts'"
        ).fetchone()
        assert "content=memories" in row[0]


class TestFtsTriggersKeepIndexInSync:
    """The external-content index stores no text of its own, so the triggers
    are what make search work at all. Exercise all three."""

    @pytest.fixture
    def conn(self, migration_sql: str) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.executescript(migration_sql)
        return conn

    def _add(self, conn: sqlite3.Connection, mid: str, content: str) -> None:
        conn.execute(
            "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
            "VALUES (?, ?, 't', 't', 't')",
            (mid, content),
        )

    def _match(self, conn: sqlite3.Connection, term: str) -> int:
        return conn.execute(
            "SELECT count(*) FROM memories_fts WHERE memories_fts MATCH ?", (term,)
        ).fetchone()[0]

    def test_insert_trigger_indexes_row(self, conn: sqlite3.Connection):
        self._add(conn, "m1", "the quick brown fox")
        assert self._match(conn, "fox") == 1

    def test_update_trigger_drops_stale_terms(self, conn: sqlite3.Connection):
        self._add(conn, "m1", "the quick brown fox")
        conn.execute("UPDATE memories SET content = 'lazy dog' WHERE id = 'm1'")
        assert self._match(conn, "fox") == 0
        assert self._match(conn, "dog") == 1

    def test_delete_trigger_removes_row(self, conn: sqlite3.Connection):
        self._add(conn, "m1", "the quick brown fox")
        conn.execute("DELETE FROM memories WHERE id = 'm1'")
        assert self._match(conn, "fox") == 0

    def test_index_survives_integrity_check(self, conn: sqlite3.Connection):
        """External-content indexes corrupt silently if a delete trigger
        replays values that differ from what was indexed."""
        self._add(conn, "m1", "alpha beta")
        self._add(conn, "m2", "gamma delta")
        conn.execute("UPDATE memories SET content = 'epsilon' WHERE id = 'm1'")
        conn.execute("DELETE FROM memories WHERE id = 'm2'")
        conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('integrity-check')")


class TestParityWithSqliteSchema:
    """The migration must encode the end state of db.py + the Alembic lineage.

    Building a real ``MemoryDB`` runs ``_init_schema`` and then walks Alembic to
    head, which is exactly the schema a D1 database has to match.
    """

    @pytest.mark.parametrize("table", sorted(EXPECTED_TABLES - {"memories_fts"}))
    def test_columns_match_sqlite_schema(
        self,
        table: str,
        sqlite_conn: sqlite3.Connection,
        migrated_conn: sqlite3.Connection,
    ):
        def cols(conn: sqlite3.Connection) -> list[tuple]:
            # (name, type, notnull, default, pk) -- ignore cid ordering noise.
            return [tuple(r[1:6]) for r in conn.execute(f"PRAGMA table_info({table})")]

        assert cols(migrated_conn) == cols(sqlite_conn), (
            f"{table} drifted from db.py / Alembic; update migrations/0001_init.sql"
        )

    def test_migration_adds_nothing_sqlite_lacks(
        self, sqlite_conn: sqlite3.Connection, migrated_conn: sqlite3.Connection
    ):
        assert not _objects(migrated_conn, "table") - _objects(sqlite_conn, "table")

    def test_omitted_tables_are_only_the_known_ones(
        self, sqlite_conn: sqlite3.Connection, migrated_conn: sqlite3.Connection
    ):
        """Anything the SQLite schema grows that D1 does not get must be a
        conscious decision recorded in KNOWN_OMITTED_PREFIXES."""
        missing = _objects(sqlite_conn, "table") - _objects(migrated_conn, "table")
        unexplained = {t for t in missing if not t.startswith(KNOWN_OMITTED_PREFIXES)}
        assert not unexplained, (
            f"tables present in SQLite but absent from the D1 migration: {unexplained}"
        )


def test_wrangler_config_points_at_migrations_dir():
    """The D1 binding must declare migrations_dir, or wrangler never finds
    this file."""
    import json

    raw = (_REPO_ROOT / "wrangler.jsonc").read_text(encoding="utf-8")
    stripped = "\n".join(re.sub(r"^\s*//.*$", "", line) for line in raw.splitlines())
    cfg = json.loads(stripped)
    d1 = cfg["d1_databases"][0]
    assert d1["migrations_dir"] == "migrations"
    assert (_REPO_ROOT / d1["migrations_dir"]).is_dir()
