"""Wave B Task 4: RBAC parity on the Cloudflare D1 backend.

Mirrors the SQLite enforcement semantics from test_rbac_enforcement.py
through the FakeD1Worker double (real SQLite carrying migrations
0001+0002+0003+0005): cross-tenant reads are empty-not-error, team rows
need active team membership, and no principal keeps legacy behavior.
"""

from __future__ import annotations

import sqlite3

import pytest
from test_db_cf import FakeD1Worker, _cf_db

from mnemo_mcp.db_cf import MemoryDBCfBackend
from mnemo_mcp.enterprise.identity import PrincipalContext

NOW = "2026-09-09T00:00:00+00:00"


def _principal(
    sub="u1", roles=("member",), tenant="acme", teams=()
) -> PrincipalContext:
    return PrincipalContext(
        subject=sub,
        tenant_id=tenant,
        roles=frozenset(roles),
        teams=frozenset(teams),
        method="oidc",
    )


@pytest.fixture
def seeded_conn(d1_conn: sqlite3.Connection) -> sqlite3.Connection:
    d1_conn.execute(
        "INSERT OR IGNORE INTO tenants (id, name, created_at) VALUES (?,?,?)",
        ("acme", "acme", NOW),
    )
    d1_conn.execute(
        "INSERT OR IGNORE INTO tenants (id, name, created_at) VALUES (?,?,?)",
        ("other", "other", NOW),
    )
    d1_conn.execute(
        "INSERT OR REPLACE INTO org_members (tenant_id, sub, role, status,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ("acme", "u1", "member", "active", NOW, NOW),
    )
    d1_conn.execute(
        "INSERT OR IGNORE INTO teams (id, tenant_id, name) VALUES (?,?,?)",
        ("t-eng", "acme", "eng"),
    )
    d1_conn.execute(
        "INSERT OR IGNORE INTO team_members (team_id, sub, created_at) VALUES (?,?,?)",
        ("t-eng", "u1", NOW),
    )
    d1_conn.execute(
        "INSERT INTO memories (sub, id, content, category, tags, source,"
        " created_at, updated_at, access_count, last_accessed,"
        " tenant_id, owner_sub, visibility)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "sub-a",
            "a1",
            "alpha acme teams notes",
            "general",
            "[]",
            None,
            NOW,
            NOW,
            0,
            NOW,
            "acme",
            "u2",
            "team",
        ),
    )
    d1_conn.execute(
        "INSERT INTO memories (sub, id, content, category, tags, source,"
        " created_at, updated_at, access_count, last_accessed,"
        " tenant_id, owner_sub, visibility)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "sub-a",
            "b1",
            "alpha other tenant secrets",
            "general",
            "[]",
            None,
            NOW,
            NOW,
            0,
            NOW,
            "other",
            "u9",
            "org",
        ),
    )
    return d1_conn


@pytest.fixture
def cf_sub_a(
    fake_worker: FakeD1Worker, seeded_conn: sqlite3.Connection
) -> MemoryDBCfBackend:
    return _cf_db(fake_worker, sub="sub-a")


def test_cf_cross_tenant_search_is_empty_not_error(cf_sub_a: MemoryDBCfBackend):
    res = cf_sub_a.search("alpha", principal=_principal(), sub="sub-a")
    assert {r["id"] for r in res} == {"a1"}


def test_cf_team_row_needs_membership(cf_sub_a: MemoryDBCfBackend):
    assert cf_sub_a.get("a1", principal=_principal(), sub="sub-a") is not None
    outsider = _principal("u3", ("member",), teams=())
    assert cf_sub_a.get("a1", principal=outsider, sub="sub-a") is None


def test_cf_local_mode_sees_everything(cf_sub_a: MemoryDBCfBackend):
    assert {r["id"] for r in cf_sub_a.search("alpha")} == {"a1", "b1"}
    assert {r["id"] for r in cf_sub_a.list_memories()} == {"a1", "b1"}


def test_cf_add_pins_tenant_columns(
    fake_worker: FakeD1Worker, seeded_conn: sqlite3.Connection
):
    db = _cf_db(fake_worker, sub="sub-a")
    mid = db.add(
        "alpha fresh cf memory", tenant_id="acme", owner_sub="u1", visibility="team"
    )
    row = db.get(mid)
    assert row is not None
    assert (row["tenant_id"], row["owner_sub"], row["visibility"]) == (
        "acme",
        "u1",
        "team",
    )
    assert row["sub"] == "sub-a"
