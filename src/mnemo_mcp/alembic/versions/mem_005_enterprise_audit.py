"""Wave A: enterprise audit hash chain table.

Implements the ``enterprise_audit`` per-tenant HMAC chain store from the
Mnemo enterprise Wave A plan (``2026-08-25-mnemo-enterprise-wave-a-plan.md``
Task 5) and spec ``2026-08-25-mnemo-enterprise-design.md`` §4.1.

Adds:

* ``enterprise_audit`` -- append-only per-tenant audit events with
  ``UNIQUE(tenant_id, seq)`` chain ordering and ``prev_hash``/``event_hash``
  HMAC-SHA256 linkage (primitives in ``mnemo_mcp.enterprise.audit``).
* ``idx_enterprise_audit_tenant_time`` -- tenant + occurred_at query index.

Idempotent: guarded by ``_table_exists`` / ``_has_index`` so re-running on a
migrated database is a no-op.

Revision ID: mem_005_enterprise_audit
Revises: mem_004_store_meta
Create Date: 2026-08-25
"""

from __future__ import annotations

import logging

from alembic import op

# Revision identifiers used by Alembic.
revision = "mem_005_enterprise_audit"
down_revision = "mem_004_store_meta"
branch_labels = None
depends_on = None


logger = logging.getLogger("alembic.runtime.migration")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    """Apply Wave A enterprise audit schema idempotently."""
    if not _table_exists("enterprise_audit"):
        op.execute(
            """
            CREATE TABLE enterprise_audit (
              id TEXT PRIMARY KEY NOT NULL,
              tenant_id TEXT NOT NULL,
              seq INTEGER NOT NULL,
              actor_sub TEXT NOT NULL,
              actor_roles TEXT NOT NULL,
              operation TEXT NOT NULL,
              resource_type TEXT NOT NULL,
              resource_id TEXT NOT NULL,
              decision TEXT NOT NULL,
              prev_hash TEXT NOT NULL,
              event_hash TEXT NOT NULL,
              key_id TEXT NOT NULL,
              details TEXT NOT NULL,
              occurred_at TEXT NOT NULL,
              UNIQUE(tenant_id, seq)
            )
            """
        )
    else:
        logger.warning("mem_005: enterprise_audit already exists, skipping create")

    if not _has_index("idx_enterprise_audit_tenant_time"):
        op.execute(
            """
            CREATE INDEX idx_enterprise_audit_tenant_time
              ON enterprise_audit(tenant_id, occurred_at)
            """
        )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    """Drop the enterprise audit table and its index."""
    if _has_index("idx_enterprise_audit_tenant_time"):
        op.execute("DROP INDEX IF EXISTS idx_enterprise_audit_tenant_time")

    if _table_exists("enterprise_audit"):
        op.execute("DROP TABLE IF EXISTS enterprise_audit")
