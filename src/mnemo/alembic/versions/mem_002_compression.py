"""Add compression columns and sync_state table.

Implements ``mem_002_compression`` from the Phase 2 design (spec
``2026-04-19-mnemo-v2-design.md`` §6). Adds:

* ``memories.text_raw TEXT`` - original uncompressed text retained for audit /
  recovery when compression rewrites ``memories.content``.
* ``memories.compressed BOOLEAN NOT NULL DEFAULT 0`` - flag indicating the row
  was rewritten by the LLM compression pipeline.
* ``memories.compression_provider TEXT`` - records which LLM provider performed
  the compression (gemini/openai/anthropic/xai) so downstream re-compression /
  audit can trace lineage. NULL when ``compressed = 0``.
* ``sync_state`` table - per-backend (s3 / gdrive) sync cursor for the Phase 2
  passport delta-sync orchestrator. Holds last successful sync timestamp,
  optional commit SHA, and the monotonic upload cursor used to detect
  sequence-gap conflicts.

The migration is *idempotent*: it inspects ``PRAGMA table_info(memories)`` and
``PRAGMA table_list`` before mutating. SQLite cannot drop columns without a
table rebuild, so ``downgrade`` only drops ``sync_state`` (a real DROP TABLE)
and logs a warning for the column additions.

Revision ID: mem_002_compression
Revises: mem_001
Create Date: 2026-05-10
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision = "mem_002_compression"
down_revision = "mem_001"
branch_labels = None
depends_on = None


logger = logging.getLogger("alembic.runtime.migration")


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


def upgrade() -> None:
    """Add compression columns and sync_state table idempotently."""
    columns = _existing_columns("memories")

    if "text_raw" not in columns:
        op.execute("ALTER TABLE memories ADD COLUMN text_raw TEXT")
    else:
        logger.info("mem_002: text_raw already present, skipping")

    if "compressed" not in columns:
        op.execute(
            "ALTER TABLE memories ADD COLUMN compressed BOOLEAN NOT NULL DEFAULT 0"
        )
    else:
        logger.info("mem_002: compressed already present, skipping")

    if "compression_provider" not in columns:
        op.execute("ALTER TABLE memories ADD COLUMN compression_provider TEXT")
    else:
        logger.info("mem_002: compression_provider already present, skipping")

    if not _table_exists("sync_state"):
        op.create_table(
            "sync_state",
            sa.Column("backend", sa.Text(), primary_key=True),
            sa.Column("last_sync_at", sa.Float(), nullable=True),
            sa.Column("last_commit_sha", sa.Text(), nullable=True),
            sa.Column("upload_cursor", sa.Integer(), nullable=True),
        )
    else:
        logger.info("mem_002: sync_state already present, skipping")


def downgrade() -> None:
    """Drop ``sync_state``; column drops require manual table rebuild on SQLite.

    The compression columns are nullable / defaulted and harmless to leave in
    place. We deliberately do not implement a column-drop here because SQLite
    requires copying the table minus the dropped columns - a destructive op
    that risks data loss for downstream callers running ``alembic downgrade``
    against a populated DB.
    """
    if _table_exists("sync_state"):
        op.drop_table("sync_state")

    logger.warning(
        "mem_002 downgrade is partial: SQLite drop-column requires manual "
        "table rebuild. Columns text_raw, compressed, compression_provider "
        "left in place on memories."
    )
