"""Add context_type and archived_at columns to memories table.

Implements ``mem_001_context_types`` from the Phase 1 design (spec
``2026-04-19-mnemo-v2-design.md`` §6). Adds:

* ``context_type TEXT NOT NULL DEFAULT 'conversation'`` — supports
  conversation/fact/preference/skill/task/decision typing for the new
  ``memory(action="capture")`` action.
* ``archived_at DATETIME`` — soft-archive marker for the importance × recency
  archive policy. The legacy ``archived_memories`` table is retained for
  backward compatibility; the new column enables single-table archive flow.

The migration is *idempotent*: it inspects ``PRAGMA table_info(memories)`` and
only adds columns that do not already exist. SQLite cannot drop columns
without a table rebuild, so ``downgrade`` is a no-op with a logged warning.

Revision ID: mem_001
Revises: baseline_001
Create Date: 2026-05-09
"""

from __future__ import annotations

import logging

from alembic import op

# Revision identifiers used by Alembic.
revision = "mem_001"
down_revision = "baseline_001"
branch_labels = None
depends_on = None


logger = logging.getLogger("alembic.runtime.migration")


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    rows = bind.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def upgrade() -> None:
    """Add ``context_type`` and ``archived_at`` columns idempotently."""
    columns = _existing_columns("memories")

    if "context_type" not in columns:
        op.execute(
            "ALTER TABLE memories "
            "ADD COLUMN context_type TEXT NOT NULL DEFAULT 'conversation'"
        )
    else:
        logger.info("mem_001: context_type already present, skipping")

    if "archived_at" not in columns:
        op.execute("ALTER TABLE memories ADD COLUMN archived_at DATETIME")
    else:
        logger.info("mem_001: archived_at already present, skipping")


def downgrade() -> None:
    """SQLite cannot drop columns without rebuilding the table.

    Downgrading this migration in production would require copying the table
    minus the new columns. We deliberately do not implement that here because
    the new columns are nullable / defaulted and harmless to leave in place.
    """
    logger.warning(
        "mem_001 downgrade is a no-op: SQLite drop-column requires manual "
        "table rebuild. Columns context_type and archived_at left in place."
    )
