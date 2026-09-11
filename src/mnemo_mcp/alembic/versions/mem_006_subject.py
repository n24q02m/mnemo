"""MN-3: per-subject recall enforcement (subject column + index).

Adds ``memories.subject TEXT`` (nullable) and ``idx_memories_subject``.

Semantics (pinned in the campaign packet, 2026-09-11):

* Every pilot-tier capture persists its subject; ``NULL`` subject marks a
  legacy / unattributed row.
* Subject-scoped search filters ``subject = ?`` — ``NULL`` rows are
  invisible to scoped probes.
* ``subject=None`` recall keeps the unfiltered legacy view.

The migration is idempotent: the ALTER inspects ``PRAGMA table_info``
before mutating, so re-running on an already-upgraded DB is a no-op.
``downgrade`` is a no-op for the column (Phase 1 / Phase 2 additive
precedent); the index is dropped.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision = "mem_006_subject"
down_revision = "mem_005_enterprise_audit"


def _column_exists(column: str) -> bool:
    rows = op.get_bind().execute(sa.text("PRAGMA table_info(memories)")).fetchall()
    return any(row[1] == column for row in rows)


def upgrade() -> None:
    """Apply subject enforcement schema idempotently."""
    if not _column_exists("subject"):
        op.execute("ALTER TABLE memories ADD COLUMN subject TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS idx_memories_subject ON memories(subject)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memories_subject")
    # Additive-column precedent (mem_003): the column itself stays.
