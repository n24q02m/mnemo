-- Wave B: RBAC schema — tenants/orgs/teams + memories tenant columns.
-- Parity with SQLite mem_006_enterprise_rbac.py (spec §4.2): same table set,
-- same memories columns and defaults, same two indexes. One statement per
-- write, zero bound parameters, no engine directives — D1 applies each
-- statement on its own. Legacy memory rows already carry the DEFAULTs
-- ('local', NULL, 'private') from the column definitions, matching the
-- SQLite backfill semantic.

CREATE TABLE IF NOT EXISTS tenants (
  id TEXT PRIMARY KEY NOT NULL,
  name TEXT NOT NULL,
  settings TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS org_members (
  tenant_id TEXT NOT NULL,
  sub TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'member',
  status TEXT NOT NULL DEFAULT 'active'
    CHECK(status IN ('active', 'disabled')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, sub)
);

CREATE TABLE IF NOT EXISTS teams (
  id TEXT PRIMARY KEY NOT NULL,
  tenant_id TEXT NOT NULL,
  name TEXT NOT NULL,
  UNIQUE(tenant_id, name)
);

CREATE TABLE IF NOT EXISTS team_members (
  team_id TEXT NOT NULL,
  sub TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (team_id, sub)
);

ALTER TABLE memories ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'local';

ALTER TABLE memories ADD COLUMN owner_sub TEXT NULL;

ALTER TABLE memories ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private', 'team', 'org'));

CREATE INDEX IF NOT EXISTS idx_memories_tenant_vis ON memories(tenant_id, visibility);

CREATE INDEX IF NOT EXISTS idx_memories_owner ON memories(owner_sub);
