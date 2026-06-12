"""Add store_meta key/value table for vector-store embedding identity.

The vector store records the ``(embedding_model, embedding_dims)`` that
produced its stored vectors so a later embedding-model change cannot silently
mix incompatible vectors and corrupt similarity search (guarded in
``db.MemoryDB._guard_embedding_identity``). This table holds that identity (and
is available for any future store-level key/value metadata).

The table is also created via ``CREATE TABLE IF NOT EXISTS`` in the DB init
path so the guard works even on wheel installs without the alembic dir; this
migration keeps the schema in the Alembic lineage for parity with the other
tables. Idempotent: inspects ``sqlite_master`` before creating.

Revision ID: mem_004_store_meta
Revises: mem_003_temporal
Create Date: 2026-06-12
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision = "mem_004_store_meta"
down_revision = "mem_003_temporal"
branch_labels = None
depends_on = None


logger = logging.getLogger("alembic.runtime.migration")


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    row = bind.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def upgrade() -> None:
    """Create the ``store_meta`` table idempotently."""
    if not _table_exists("store_meta"):
        op.create_table(
            "store_meta",
            sa.Column("key", sa.Text(), primary_key=True),
            sa.Column("value", sa.Text(), nullable=True),
        )
    else:
        logger.info("mem_004: store_meta already present, skipping")


def downgrade() -> None:
    """Drop the ``store_meta`` table."""
    if _table_exists("store_meta"):
        op.drop_table("store_meta")
