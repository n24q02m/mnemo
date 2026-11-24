"""Add confidence column for memory poisoning and trust scoring.

Revision ID: mem_007_confidence
Revises: mem_006_subject
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mem_007_confidence"
down_revision: str | Sequence[str] | None = "mem_006_subject"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``confidence`` column to ``memories`` if absent."""
    bind = op.get_bind()
    cols = {
        row[1]
        for row in bind.execute(sa.text("PRAGMA table_info(memories)")).fetchall()
    }
    if "confidence" not in cols:
        op.add_column(
            "memories",
            sa.Column(
                "confidence",
                sa.Float(),
                nullable=False,
                server_default=sa.text("1.0"),
            ),
        )


def downgrade() -> None:
    """Drop ``confidence`` column from ``memories`` if present."""
    bind = op.get_bind()
    cols = {
        row[1]
        for row in bind.execute(sa.text("PRAGMA table_info(memories)")).fetchall()
    }
    if "confidence" in cols:
        op.drop_column("memories", "confidence")
