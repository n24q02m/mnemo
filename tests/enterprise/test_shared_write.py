"""Wave B Task 5: shared-write v1 + membership helpers.

Member writes into team/org scope only for rows they own; editing another
member's shared row needs admin/owner (audited). Team-visibility rows
additionally require live team membership on write.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.enterprise.identity import (
    PrincipalContext,
    reset_current_principal,
    set_current_principal,
)
from mnemo_mcp.enterprise.membership import (
    can_write_shared,
    member_status,
    member_teams,
)

NOW = "2026-09-09T00:00:00+00:00"
AUDIT_KEY = "task5-test-key-0123456789abcdef"


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


def _seed_org(db: MemoryDB) -> None:
    db._conn.execute(
        "INSERT OR IGNORE INTO tenants (id, name, created_at) VALUES (?,?,?)",
        ("acme", "acme", NOW),
    )
    for sub, role in (("u1", "member"), ("u2", "member"), ("boss", "admin")):
        db._conn.execute(
            "INSERT OR REPLACE INTO org_members (tenant_id, sub, role, status,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?)",
            ("acme", sub, role, "active", NOW, NOW),
        )
    db._conn.execute(
        "INSERT OR IGNORE INTO teams (id, tenant_id, name) VALUES (?,?,?)",
        ("t-eng", "acme", "eng"),
    )
    db._conn.execute(
        "INSERT OR IGNORE INTO team_members (team_id, sub, created_at) VALUES (?,?,?)",
        ("t-eng", "u1", NOW),
    )
    db._conn.commit()


def _seed_team_memory(db: MemoryDB, mid: str, owner: str) -> None:
    db._conn.execute(
        "INSERT INTO memories (id, content, category, tags, source, created_at,"
        " updated_at, access_count, last_accessed, tenant_id, owner_sub,"
        " visibility) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            mid,
            "alpha shared team notes",
            "general",
            "[]",
            None,
            NOW,
            NOW,
            0,
            NOW,
            "acme",
            owner,
            "team",
        ),
    )
    db._conn.commit()


def _ctx(db: MemoryDB) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "db": db,
        "embedding_model": None,
        "embedding_dims": 0,
    }
    return ctx


# -- membership helpers -------------------------------------------------------


def test_member_teams_reads_db(tmp_path):
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed_org(db)
    try:
        assert member_teams(db, "u1", "acme") == frozenset({"t-eng"})
        assert member_teams(db, "u2", "acme") == frozenset()
        assert member_status(db, "u1", "acme") == "active"
        assert member_status(db, "ghost", "acme") is None
    finally:
        db.close()


@pytest.mark.parametrize(
    ("roles", "visibility", "team", "expected"),
    [
        ({"admin"}, "team", "t-other", True),
        ({"owner"}, "org", None, True),
        ({"member"}, "private", None, True),
        ({"member"}, "team", "t-eng", True),
        ({"member"}, "team", "t-other", False),
        ({"member"}, "team", None, True),  # sits on t-eng: creation allowed
        ({"member"}, "org", None, True),
        ({"member"}, "secret", None, False),
    ],
)
def test_can_write_shared_matrix(roles, visibility, team, expected):
    teams = ("t-eng",) if roles == {"member"} and visibility == "team" else ()
    # The None-team creation case still needs a team seat.
    if roles == {"member"} and visibility == "team" and team is None:
        teams = ("t-eng",)
    p = _principal("u1", tuple(roles), teams=teams)
    assert can_write_shared(p, visibility, team) is expected


def test_can_write_shared_teamless_member_denied():
    p = _principal("u2", ("member",), teams=())
    assert can_write_shared(p, "team", None) is False
    assert can_write_shared(p, "team", "t-eng") is False


# -- protocol: member creates team memory -------------------------------------


def test_member_creates_team_memory(tmp_path, monkeypatch):
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed_org(db)
    try:
        assert can_write_shared(_principal(teams=("t-eng",)), "team", None) is True
        mid = db.add(
            "alpha fresh team notes",
            tenant_id="acme",
            owner_sub="u1",
            visibility="team",
        )
        row = db.get(mid)
        assert row is not None and row["owner_sub"] == "u1"
        # Teammate seat sees it; seatless member does not.
        assert db.get(mid, principal=_principal(teams=("t-eng",))) is not None
        assert db.get(mid, principal=_principal("u2")) is None
    finally:
        db.close()


# -- protocol: edit another member's shared row -------------------------------


@pytest.mark.asyncio
async def test_member_edit_other_team_memory_denied_and_audited(tmp_path, monkeypatch):
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed_org(db)
    _seed_team_memory(db, "v1", owner="u2")
    ctx = _ctx(db)
    token = set_current_principal(_principal("u1", ("member",), teams=("t-eng",)))
    try:
        result = await server_module._handle_update(ctx, "v1", content="hijacked")
    finally:
        reset_current_principal(token)
    assert "error" in result
    rows = db._conn.execute(
        "SELECT operation, decision FROM enterprise_audit WHERE tenant_id = ?",
        ("acme",),
    ).fetchall()
    db.close()
    assert ("memory.write_shared", "deny") in [(r[0], r[1]) for r in rows]


@pytest.mark.asyncio
async def test_admin_edit_other_team_memory_allowed_and_audited(tmp_path, monkeypatch):
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed_org(db)
    _seed_team_memory(db, "v1", owner="u2")
    ctx = _ctx(db)
    token = set_current_principal(_principal("boss", ("admin",), teams=()))
    try:
        result = await server_module._handle_update(ctx, "v1", content="fixed by admin")
    finally:
        reset_current_principal(token)
    assert result.get("status") == "updated"
    rows = db._conn.execute(
        "SELECT operation, decision FROM enterprise_audit WHERE tenant_id = ?",
        ("acme",),
    ).fetchall()
    db.close()
    assert ("memory.write_shared", "allow") in [(r[0], r[1]) for r in rows]
