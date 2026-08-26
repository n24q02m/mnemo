-- Wave A: enterprise audit hash chain table (parity with SQLite mem_005).
-- Same DDL as src/mnemo_mcp/alembic/versions/mem_005_enterprise_audit.py:
-- per-tenant append-only audit events with UNIQUE(tenant_id, seq) chain
-- ordering and prev_hash/event_hash HMAC-SHA256 linkage. No FTS, no
-- sqlite-vec, no PRAGMA, no explicit transaction (D1 constraints).

CREATE TABLE IF NOT EXISTS enterprise_audit (
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
);

CREATE INDEX IF NOT EXISTS idx_enterprise_audit_tenant_time
  ON enterprise_audit(tenant_id, occurred_at);
