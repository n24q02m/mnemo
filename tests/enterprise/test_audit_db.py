"""SQLite enterprise_audit: append, chain verify, tamper detect, idempotent migration."""

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.enterprise.audit import GENESIS

KEY = b"sixteen-byte-key"


def fields(seq_hint: str = "m1") -> dict:
    return {
        "tenant_id": "acme",
        "actor_sub": "u1",
        "actor_roles": ["member"],
        "operation": "memory.add",
        "resource_type": "memory",
        "resource_id": seq_hint,
        "decision": "allow",
        "details": {"k": "v"},
        "occurred_at": "2026-08-25T00:00:00Z",
    }


def test_append_returns_chained_event(tmp_db: MemoryDB):
    e1 = tmp_db.append_audit_event(fields(), key=KEY)
    assert e1["seq"] == 1 and e1["prev_hash"] == GENESIS
    e2 = tmp_db.append_audit_event(fields("m2"), key=KEY)
    assert e2["seq"] == 2 and e2["prev_hash"] == e1["event_hash"]


def test_verify_ok_then_tamper(tmp_db: MemoryDB):
    tmp_db.append_audit_event(fields(), key=KEY)
    tmp_db.append_audit_event(fields("m2"), key=KEY)
    report = tmp_db.verify_audit_chain("acme", {"k1": KEY})
    assert report.ok and report.checked == 2
    tmp_db._conn.execute(
        "UPDATE enterprise_audit SET details = ? WHERE seq = 2", ('{"k":"EVIL"}',)
    )
    tmp_db._conn.commit()
    report = tmp_db.verify_audit_chain("acme", {"k1": KEY})
    assert not report.ok and report.first_bad_seq == 2


def test_tenants_chain_independently(tmp_db: MemoryDB):
    a = dict(fields(), tenant_id="acme")
    b = dict(fields(), tenant_id="other")
    tmp_db.append_audit_event(a, key=KEY)
    tmp_db.append_audit_event(b, key=KEY)
    tmp_db.append_audit_event(a, key=KEY)  # acme seq 2, prev = acme seq 1
    assert tmp_db.verify_audit_chain("acme", {"k1": KEY}).ok
    assert tmp_db.verify_audit_chain("other", {"k1": KEY}).ok


def test_migration_idempotent(tmp_db: MemoryDB):
    # MemoryDB.__init__ đã chạy migrations; bảng tồn tại, rỗng, có UNIQUE(tenant_id, seq).
    rows = tmp_db._conn.execute("SELECT COUNT(*) FROM enterprise_audit").fetchone()
    assert rows[0] == 0
    table_sql = tmp_db._conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='enterprise_audit'"
    ).fetchone()[0]
    assert "UNIQUE(tenant_id, seq)" in table_sql
