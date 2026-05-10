"""Phase 3: temporal KG columns + entity table rename + audit + entity-vec.

Implements ``mem_003_temporal`` from the Phase 3 plan
(``2026-05-09-phase-3-plan.md`` Task 1) and spec
``2026-04-19-mnemo-v2-design.md`` §6.

Adds:

* ``memories.commit_sha TEXT`` -- per-row commit hash (sha256 of content)
  for provenance + audit chain. Backfilled to sha256(content) for legacy
  rows.
* ``memories.valid_from DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP`` --
  bitemporal lower bound. Backfilled to ``created_at`` for legacy rows.
* ``memories.valid_to DATETIME`` -- bitemporal upper bound (NULL = currently
  valid). New default behaviour for ``memory.get`` filters ``valid_to IS
  NULL``.
* ``memories.superseded_by INTEGER`` -- forward pointer to the new memory
  that replaced this one (set during supersession). Self-FK column kept
  TEXT-compatible since memories.id is a TEXT uuid in this codebase.

Renames (idempotent):

* ``entities`` -> ``memory_entities`` (canonical spec §5.2 name)
* ``memory_entities`` (current join table) -> ``memory_entity_links``
  (Phase 1 used the same name for the join; spec name collides so rename
  the join first then the entity table).
* ``relations`` -> ``memory_edges`` + ADD ``valid_from`` / ``valid_to``
  bitemporal columns + ``memory_id`` link column.

New tables:

* ``memory_audit`` -- mutation log (operation, prev_state_hash,
  new_state_hash, commit_sha, occurred_at). Index on
  ``(memory_id, occurred_at DESC)``.
* ``memory_entities_vec`` -- sqlite-vec virtual table for entity-name
  embeddings (used by entity resolution).

The migration is idempotent: each RENAME / ALTER inspects sqlite_master /
PRAGMA table_info before mutating, so re-running the migration on an
already-upgraded DB is a no-op.

SQLite cannot drop columns without a table rebuild. ``downgrade`` reverses
the renames + drops the new tables but leaves the additive columns on
``memories`` in place (Phase 1 / Phase 2 precedent).

Revision ID: mem_003_temporal
Revises: mem_002_compression
Create Date: 2026-05-10
"""

from __future__ import annotations

import logging

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision = "mem_003_temporal"
down_revision = "mem_002_compression"
branch_labels = None
depends_on = None


logger = logging.getLogger("alembic.runtime.migration")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    rows = bind.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    row = bind.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _has_index(name: str) -> bool:
    bind = op.get_bind()
    row = bind.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Apply Phase 3 schema additions idempotently."""
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Bitemporal columns on memories
    # ------------------------------------------------------------------
    columns = _existing_columns("memories")

    if "commit_sha" not in columns:
        op.execute("ALTER TABLE memories ADD COLUMN commit_sha TEXT")
    else:
        logger.info("mem_003: commit_sha already present, skipping")

    if "valid_from" not in columns:
        # SQLite ALTER TABLE ADD COLUMN cannot use a non-constant default,
        # so add the column nullable first then backfill.
        op.execute("ALTER TABLE memories ADD COLUMN valid_from DATETIME")
    else:
        logger.info("mem_003: valid_from already present, skipping")

    if "valid_to" not in columns:
        op.execute("ALTER TABLE memories ADD COLUMN valid_to DATETIME")
    else:
        logger.info("mem_003: valid_to already present, skipping")

    if "superseded_by" not in columns:
        # memories.id is a TEXT uuid in this codebase; the FK target type
        # must match. Keep nullable so existing rows are unaffected.
        op.execute("ALTER TABLE memories ADD COLUMN superseded_by TEXT")
    else:
        logger.info("mem_003: superseded_by already present, skipping")

    # Backfill bitemporal columns + commit_sha for legacy rows happens in
    # ``MemoryDB._backfill_phase3_temporal`` (called from
    # ``_run_migrations`` AFTER ``command.upgrade`` returns). The Python
    # post-migration backfill avoids running UPDATEs through Alembic's
    # connection while FTS5 triggers are wired -- updates from a separate
    # SQLAlchemy connection during migration confuse SQLite's WAL on
    # Windows ("database disk image is malformed").

    # ------------------------------------------------------------------
    # 2. Rename current join table memory_entities -> memory_entity_links
    #    (must run BEFORE renaming `entities` -> `memory_entities` to avoid
    #    name collision).
    # ------------------------------------------------------------------
    if _table_exists("memory_entities") and not _table_exists("memory_entity_links"):
        # Detect which table currently named `memory_entities` actually IS
        # the join table (memory_id + entity_id columns) vs the entity
        # table itself. The join table has columns memory_id + entity_id;
        # the entity table has id + name + entity_type.
        cols = _existing_columns("memory_entities")
        if {"memory_id", "entity_id"}.issubset(cols):
            op.execute("ALTER TABLE memory_entities RENAME TO memory_entity_links")
            # Rename associated index if it exists.
            if _has_index("idx_memory_entities_entity_id"):
                op.execute("DROP INDEX idx_memory_entities_entity_id")
            op.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_entity_links_entity_id "
                "ON memory_entity_links(entity_id)"
            )
        else:
            logger.info(
                "mem_003: memory_entities exists but is not join shape; skipping rename"
            )
    elif _table_exists("memory_entity_links"):
        logger.info(
            "mem_003: memory_entity_links already present, skipping join rename"
        )

    # ------------------------------------------------------------------
    # 3. Rename entity table entities -> memory_entities (spec §5.2).
    # ------------------------------------------------------------------
    if _table_exists("entities") and not _table_exists("memory_entities"):
        op.execute("ALTER TABLE entities RENAME TO memory_entities")
        # Recreate unique index under canonical name.
        if _has_index("idx_entities_name_type"):
            op.execute("DROP INDEX idx_entities_name_type")
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_entities_name_type "
            "ON memory_entities(name, entity_type)"
        )
    elif _table_exists("memory_entities") and not _table_exists("entities"):
        logger.info("mem_003: memory_entities already present, skipping entity rename")

    # ------------------------------------------------------------------
    # 4. Rename relations -> memory_edges + ADD bitemporal + memory_id.
    # ------------------------------------------------------------------
    if _table_exists("relations") and not _table_exists("memory_edges"):
        op.execute("ALTER TABLE relations RENAME TO memory_edges")
        # Drop / recreate associated indexes under new names.
        if _has_index("idx_relations_source"):
            op.execute("DROP INDEX idx_relations_source")
        if _has_index("idx_relations_target"):
            op.execute("DROP INDEX idx_relations_target")
        if _has_index("idx_relations_unique"):
            op.execute("DROP INDEX idx_relations_unique")
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_edges_source ON memory_edges(source_id)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_edges_target ON memory_edges(target_id)"
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_edges_unique "
            "ON memory_edges(source_id, target_id, relation_type)"
        )
    elif _table_exists("memory_edges"):
        logger.info("mem_003: memory_edges already present, skipping relations rename")

    # Add bitemporal + memory_id columns (idempotent).
    if _table_exists("memory_edges"):
        edge_cols = _existing_columns("memory_edges")
        if "memory_id" not in edge_cols:
            op.execute("ALTER TABLE memory_edges ADD COLUMN memory_id TEXT")
        if "valid_from" not in edge_cols:
            op.execute("ALTER TABLE memory_edges ADD COLUMN valid_from DATETIME")
            # Backfill valid_from = created_at for existing edges.
            op.execute(
                "UPDATE memory_edges SET valid_from = created_at WHERE valid_from IS NULL"
            )
        if "valid_to" not in edge_cols:
            op.execute("ALTER TABLE memory_edges ADD COLUMN valid_to DATETIME")

    # ------------------------------------------------------------------
    # 5. memory_audit table -- mutation log.
    # ------------------------------------------------------------------
    if not _table_exists("memory_audit"):
        op.create_table(
            "memory_audit",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("memory_id", sa.Text(), nullable=False),
            sa.Column("prev_state_hash", sa.Text(), nullable=True),
            sa.Column("new_state_hash", sa.Text(), nullable=False),
            sa.Column("operation", sa.Text(), nullable=False),
            sa.Column("commit_sha", sa.Text(), nullable=False),
            sa.Column(
                "occurred_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
        )
        op.create_index(
            "idx_memory_audit_memory_time",
            "memory_audit",
            ["memory_id", "occurred_at"],
        )
    else:
        logger.info("mem_003: memory_audit already present, skipping")

    # ------------------------------------------------------------------
    # 6. memory_entities_vec virtual table (sqlite-vec).
    # ------------------------------------------------------------------
    # Best-effort: load extension on raw connection then create. If the
    # extension is unavailable (e.g. test harness without sqlite-vec) we
    # silently skip -- entity resolution falls back to name-only match.
    if not _table_exists("memory_entities_vec"):
        try:
            raw = bind.connection.connection  # underlying sqlite3.Connection
            try:
                raw.enable_load_extension(True)
                import sqlite_vec

                sqlite_vec.load(raw)
                raw.enable_load_extension(False)
            except Exception as load_err:  # pragma: no cover - env-dependent
                logger.info(
                    f"mem_003: sqlite-vec not loadable in migration runner ({load_err}); "
                    "skipping memory_entities_vec creation. Server runtime will "
                    "create it on first use."
                )
            else:
                op.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_entities_vec "
                    "USING vec0(embedding float[768])"
                )
        except Exception as e:  # pragma: no cover - runtime guard
            logger.warning(f"mem_003: memory_entities_vec creation failed: {e}")


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    """Reverse renames + drop new tables. Additive columns retained.

    SQLite cannot drop columns without rebuilding the parent table; we
    deliberately leave commit_sha / valid_from / valid_to / superseded_by
    on memories (and memory_id / valid_from / valid_to on memory_edges)
    in place to avoid data-loss risk in production downgrades.
    """
    if _table_exists("memory_entities_vec"):
        op.execute("DROP TABLE IF EXISTS memory_entities_vec")

    if _table_exists("memory_audit"):
        op.drop_table("memory_audit")

    if _table_exists("memory_edges") and not _table_exists("relations"):
        if _has_index("idx_memory_edges_source"):
            op.execute("DROP INDEX idx_memory_edges_source")
        if _has_index("idx_memory_edges_target"):
            op.execute("DROP INDEX idx_memory_edges_target")
        if _has_index("idx_memory_edges_unique"):
            op.execute("DROP INDEX idx_memory_edges_unique")
        op.execute("ALTER TABLE memory_edges RENAME TO relations")
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id)"
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_relations_unique "
            "ON relations(source_id, target_id, relation_type)"
        )

    if _table_exists("memory_entities") and not _table_exists("entities"):
        # Detect entity-table shape (vs join shape).
        cols = _existing_columns("memory_entities")
        if {"id", "name", "entity_type"}.issubset(cols):
            if _has_index("idx_memory_entities_name_type"):
                op.execute("DROP INDEX idx_memory_entities_name_type")
            op.execute("ALTER TABLE memory_entities RENAME TO entities")
            op.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_name_type "
                "ON entities(name, entity_type)"
            )

    if _table_exists("memory_entity_links") and not _table_exists("memory_entities"):
        if _has_index("idx_memory_entity_links_entity_id"):
            op.execute("DROP INDEX idx_memory_entity_links_entity_id")
        op.execute("ALTER TABLE memory_entity_links RENAME TO memory_entities")
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_entities_entity_id "
            "ON memory_entities(entity_id)"
        )

    logger.warning(
        "mem_003 downgrade is partial: SQLite drop-column requires manual "
        "table rebuild. Columns commit_sha / valid_from / valid_to / "
        "superseded_by on memories and memory_id / valid_from / valid_to "
        "on memory_edges left in place."
    )
