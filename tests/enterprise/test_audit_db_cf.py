"""D1 enterprise_audit parity: append/verify qua cùng surface với SQLite.

Fixture: tái dùng đúng fixture của tests/test_db_cf.py (FakeD1Worker chạy trên
SQLite thật đã apply migrations/0001-0003, bọc trong D1Backend). Fixture
``cf_backend`` dưới đây chỉ áp thêm migrations/0004_enterprise_audit.sql lên
``d1_conn`` rồi dựng backend từ ``fake_worker`` -- không fake mới.
"""

from __future__ import annotations

import pathlib
import sqlite3

import pytest

# d1_conn / fake_worker come from tests/enterprise/conftest.py, which
# re-exports the exact doubles from tests/test_db_cf.py (no new fake).
from mnemo_mcp.db_cf import D1Backend, MemoryDBCfBackend

KEY = b"sixteen-byte-key"

FIELDS = {
    "tenant_id": "acme",
    "actor_sub": "u1",
    "actor_roles": ["member"],
    "operation": "memory.add",
    "resource_type": "memory",
    "resource_id": "m1",
    "decision": "allow",
    "details": {"k": "v"},
    "occurred_at": "2026-08-25T00:00:00Z",
}
_MIGRATION_4 = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "migrations"
    / "0004_enterprise_audit.sql"
)


@pytest.fixture
def cf_backend(d1_conn, fake_worker) -> MemoryDBCfBackend:
    d1_conn.executescript(_MIGRATION_4.read_text(encoding="utf-8"))
    return MemoryDBCfBackend(D1Backend(base_url="http://d1.internal", http=fake_worker))


def test_cf_append_and_verify(cf_backend):
    e1 = cf_backend.append_audit_event(dict(FIELDS), key=KEY)
    assert e1["seq"] == 1
    cf_backend.append_audit_event(dict(FIELDS, resource_id="m2"), key=KEY)
    report = cf_backend.verify_audit_chain("acme", {"k1": KEY})
    assert report.ok and report.checked == 2


def test_cf_append_retries_on_unique_conflict(cf_backend):
    """Race D1: SELECT prev rồi INSERT có thể bị chen — retry tối đa 3 lần.

    Stub bọc `cf_backend._conn`: lần INSERT đầu (execute chứa
    "INSERT INTO enterprise_audit") raise IntegrityError đúng message UNIQUE;
    lần sau delegate vào connection thật. Không cần D1 thật để test retry.
    """
    real_conn = cf_backend._conn
    state = {"inserts": 0}

    class FlakyConn:
        def execute(self, sql, params=()):
            if "INSERT INTO enterprise_audit" in sql:
                state["inserts"] += 1
                if state["inserts"] == 1:
                    raise sqlite3.IntegrityError(
                        "UNIQUE constraint failed: enterprise_audit.tenant_id,"
                        " enterprise_audit.seq"
                    )
            return real_conn.execute(sql, params)

    cf_backend._conn = FlakyConn()
    try:
        event = cf_backend.append_audit_event(dict(FIELDS), key=KEY)
    finally:
        cf_backend._conn = real_conn
    assert event["seq"] == 1 and state["inserts"] == 2
    assert cf_backend.verify_audit_chain("acme", {"k1": KEY}).ok
