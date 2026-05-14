"""Baseline revision: lock existing schema.

This revision is intentionally a no-op. It exists to anchor the migration
chain at the schema produced by ``MemoryDB._init_schema`` prior to Alembic
adoption (memories + memories_fts + memories_vec + entities + relations +
memory_entities + archived_memories, with the pre-Alembic ``importance``
column ALTER inside ``_init_memory_schema``).

Revision ID: baseline_001
Revises:
Create Date: 2026-05-09
"""

from __future__ import annotations

# Revision identifiers used by Alembic.
revision = "baseline_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: schema produced by ``MemoryDB._init_schema`` is the baseline."""
    return None


def downgrade() -> None:
    """No-op: there is no schema state earlier than baseline to roll back to."""
    return None
