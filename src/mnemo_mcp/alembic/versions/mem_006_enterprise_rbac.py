"""Wave B: RBAC schema — tenants/orgs/teams + memories tenant columns.

Spec §4.2. Idempotent like mem_005: every CREATE guarded by an existence
check, ALTER ADD COLUMN guarded per column, so re-running the upgrade (or
upgrading a database that already carries the schema) is a no-op. Legacy
memory rows backfill to ``tenant_id='local'``, ``owner_sub=NULL``,
``visibility='private'`` via the column DEFAULTs, preserving local-mode
semantics (plan: backfill keeps local meaning).
"""

from __future__ import annotations

import logging

from alembic import op

# Revision identifiers used by Alembic.
revision = "mem_006_enterprise_rbac"
down_revision = "mem_005_enterprise_audit"
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


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


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
    """Apply Wave B RBAC schema idempotently."""
    if not _table_exists("tenants"):
        op.execute(
            """
            CREATE TABLE tenants (
              id TEXT PRIMARY KEY NOT NULL,
              name TEXT NOT NULL,
              settings TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL
            )
            """
        )
    else:
        logger.warning("mem_006: tenants already exists, skipping create")

    if not _table_exists("org_members"):
        op.execute(
            """
            CREATE TABLE org_members (
              tenant_id TEXT NOT NULL,
              sub TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'member',
              status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'disabled')),
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (tenant_id, sub)
            )
            """
        )
    else:
        logger.warning("mem_006: org_members already exists, skipping create")

    if not _table_exists("teams"):
        op.execute(
            """
            CREATE TABLE teams (
              id TEXT PRIMARY KEY NOT NULL,
              tenant_id TEXT NOT NULL,
              name TEXT NOT NULL,
              UNIQUE(tenant_id, name)
            )
            """
        )
    else:
        logger.warning("mem_006: teams already exists, skipping create")

    if not _table_exists("team_members"):
        op.execute(
            """
            CREATE TABLE team_members (
              team_id TEXT NOT NULL,
              sub TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY (team_id, sub)
            )
            """
        )
    else:
        logger.warning("mem_006: team_members already exists, skipping create")

    if not _has_column("memories", "tenant_id"):
        op.execute(
            "ALTER TABLE memories ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'local'"
        )
    if not _has_column("memories", "owner_sub"):
        op.execute("ALTER TABLE memories ADD COLUMN owner_sub TEXT NULL")
    if not _has_column("memories", "visibility"):
        op.execute(
            "ALTER TABLE memories ADD COLUMN visibility TEXT NOT NULL"
            " DEFAULT 'private' CHECK(visibility IN ('private', 'team', 'org'))"
        )

    if not _has_index("idx_memories_tenant_vis"):
        op.execute(
            "CREATE INDEX idx_memories_tenant_vis ON memories(tenant_id, visibility)"
        )
    if not _has_index("idx_memories_owner"):
        op.execute("CREATE INDEX idx_memories_owner ON memories(owner_sub)")


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    """Drop the RBAC tables, indexes, and memories columns (reverse order)."""
    if _has_index("idx_memories_owner"):
        op.execute("DROP INDEX IF EXISTS idx_memories_owner")
    if _has_index("idx_memories_tenant_vis"):
        op.execute("DROP INDEX IF EXISTS idx_memories_tenant_vis")

    # DROP COLUMN needs SQLite 3.35+ (already required for UPDATE..RETURNING).
    if _has_column("memories", "visibility"):
        op.execute("ALTER TABLE memories DROP COLUMN visibility")
    if _has_column("memories", "owner_sub"):
        op.execute("ALTER TABLE memories DROP COLUMN owner_sub")
    if _has_column("memories", "tenant_id"):
        op.execute("ALTER TABLE memories DROP COLUMN tenant_id")

    if _table_exists("team_members"):
        op.execute("DROP TABLE IF EXISTS team_members")
    if _table_exists("teams"):
        op.execute("DROP TABLE IF EXISTS teams")
    if _table_exists("org_members"):
        op.execute("DROP TABLE IF EXISTS org_members")
    if _table_exists("tenants"):
        op.execute("DROP TABLE IF EXISTS tenants")
