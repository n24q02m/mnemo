"""Wave B coverage completion: branches Main flagged from the macOS gate.

Each test targets one specific uncovered branch that belongs to Wave B's
own code (membership helpers, the deprovision gate, the update path, the
transfer seam) — no test-for-test's-sake rows.
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
from mnemo_mcp.enterprise.membership import can_write_shared

NOW = "2026-09-10T01:00:00+00:00"
AUDIT_KEY = "sixteen-byte-test-key"


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


def _seed(db: MemoryDB, *, disable_u1: bool = False) -> None:
    db._conn.execute(
        "INSERT OR IGNORE INTO tenants (id, name, created_at) VALUES (?,?,?)",
        ("acme", "acme", NOW),
    )
    db._conn.execute(
        "INSERT OR REPLACE INTO org_members (tenant_id, sub, role, status,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ("acme", "u1", "member", "disabled" if disable_u1 else "active", NOW, NOW),
    )
    db._conn.execute(
        "INSERT OR REPLACE INTO org_members (tenant_id, sub, role, status,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ("acme", "boss", "admin", "active", NOW, NOW),
    )
    db._conn.execute(
        "INSERT OR IGNORE INTO teams (id, tenant_id, name) VALUES (?,?,?)",
        ("t-eng", "acme", "eng"),
    )
    db._conn.commit()


def _seed_memory(db: MemoryDB, mid: str, owner: str, visibility: str = "team") -> None:
    db._conn.execute(
        "INSERT INTO memories (id, content, category, tags, source, created_at,"
        " updated_at, access_count, last_accessed, tenant_id, owner_sub,"
        " visibility) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            mid,
            "alpha seeded content",
            "general",
            "[]",
            None,
            NOW,
            NOW,
            0,
            NOW,
            "acme",
            owner,
            visibility,
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


# -- membership.py 56 (None principal) and 60 (non-member role) ---------------


def test_can_write_shared_none_principal_denied():
    assert can_write_shared(None, "team", None) is False


def test_can_write_shared_non_member_role_denied():
    # auditor is a real Wave A role but carries no shared-write rights.
    p = _principal("aud", ("auditor",), teams=("t-eng",))
    assert can_write_shared(p, "team", "t-eng") is False
    assert can_write_shared(p, "org", None) is False
    assert can_write_shared(p, "private", None) is False


# -- server.py 1131: disabled member denied on the update path -----------------


@pytest.mark.asyncio
async def test_disabled_member_update_denied(tmp_path, monkeypatch):
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed(db, disable_u1=True)
    _seed_memory(db, "v1", owner="u1")
    ctx = _ctx(db)
    token = set_current_principal(_principal("u1"))
    try:
        result = await server_module._handle_update(ctx, "v1", content="nope")
    finally:
        reset_current_principal(token)
    assert "error" in result
    assert "membership disabled" in result["error"]
    rows = db._conn.execute(
        "SELECT operation, decision FROM enterprise_audit WHERE tenant_id = ?",
        ("acme",),
    ).fetchall()
    db.close()
    assert ("auth.failure", "deny") in [(r[0], r[1]) for r in rows]


# -- server.py 1139: update of a missing id under a principal ------------------


@pytest.mark.asyncio
async def test_update_missing_id_reports_not_found(tmp_path, monkeypatch):
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed(db)
    ctx = _ctx(db)
    token = set_current_principal(_principal("u1"))
    try:
        result = await server_module._handle_update(ctx, "ghost", content="x")
    finally:
        reset_current_principal(token)
    db.close()
    assert result["error"] == "Memory ghost not found"


# -- server.py 1183-1199: own team row without a live seat ---------------------


@pytest.mark.asyncio
async def test_revoked_seat_hides_own_team_row(tmp_path, monkeypatch):
    """Seat revocation is DB-authoritative: the row reads as not-found."""
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed(db)
    _seed_memory(db, "v1", owner="u1", visibility="team")
    ctx = _ctx(db)
    # Claims still say t-eng, but team_members has no seat for u1.
    token = set_current_principal(_principal("u1", teams=("t-eng",)))
    try:
        result = await server_module._handle_update(ctx, "v1", content="still mine?")
    finally:
        reset_current_principal(token)
    db.close()
    assert result["error"] == "Memory v1 not found"


# -- server.py add gate 785-805: write_own denial for non-member roles ---------


@pytest.mark.asyncio
async def test_auditor_add_denied_and_audited(tmp_path, monkeypatch):
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed(db)
    db._conn.execute(
        "INSERT OR REPLACE INTO org_members (tenant_id, sub, role, status,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ("acme", "aud", "auditor", "active", NOW, NOW),
    )
    db._conn.commit()
    ctx = _ctx(db)
    token = set_current_principal(_principal("aud", ("auditor",)))
    try:
        result = await server_module._handle_add(ctx, "alpha sneaky write")
    finally:
        reset_current_principal(token)
    assert "error" in result
    rows = db._conn.execute(
        "SELECT operation, decision FROM enterprise_audit WHERE tenant_id = ?",
        ("acme",),
    ).fetchall()
    db.close()
    assert ("memory.write_own", "deny") in [(r[0], r[1]) for r in rows]


# -- server.py delete gate 1266-1326: deprovision + missing id -----------------


@pytest.mark.asyncio
async def test_disabled_member_delete_denied(tmp_path, monkeypatch):
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed(db, disable_u1=True)
    _seed_memory(db, "v1", owner="u1")
    ctx = _ctx(db)
    token = set_current_principal(_principal("u1"))
    try:
        result = await server_module._handle_delete(ctx, "v1")
    finally:
        reset_current_principal(token)
    assert "error" in result
    rows = db._conn.execute(
        "SELECT operation, decision FROM enterprise_audit WHERE tenant_id = ?",
        ("acme",),
    ).fetchall()
    db.close()
    assert ("auth.failure", "deny") in [(r[0], r[1]) for r in rows]


@pytest.mark.asyncio
async def test_delete_missing_id_reports_not_found(tmp_path, monkeypatch):
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed(db)
    ctx = _ctx(db)
    token = set_current_principal(_principal("u1"))
    try:
        result = await server_module._handle_delete(ctx, "ghost")
    finally:
        reset_current_principal(token)
    db.close()
    assert result["error"] == "Memory ghost not found"


# -- server.py transfer: local mode (no principal) is refused ------------------


@pytest.mark.asyncio
async def test_transfer_local_mode_refused(tmp_path):
    from mnemo_mcp import server as server_module

    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed(db)
    ctx = _ctx(db)
    result = await server_module._handle_transfer(ctx, "v1", "boss")
    db.close()
    assert "enterprise principal" in result["error"]


# -- server.py 1310: transfer with missing args --------------------------------


@pytest.mark.asyncio
async def test_transfer_missing_args_rejected(tmp_path):
    from mnemo_mcp import server as server_module

    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed(db)
    ctx = _ctx(db)
    token = set_current_principal(_principal("boss", ("admin",)))
    try:
        result = await server_module._handle_transfer(ctx, None, None)
    finally:
        reset_current_principal(token)
    db.close()
    assert "required for transfer" in result["error"]


# -- server.py 1340: admin transfer of a missing id ----------------------------


@pytest.mark.asyncio
async def test_transfer_missing_row_reports_not_found(tmp_path, monkeypatch):
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed(db)
    ctx = _ctx(db)
    token = set_current_principal(_principal("boss", ("admin",)))
    try:
        result = await server_module._handle_transfer(ctx, "ghost", "u1")
    finally:
        reset_current_principal(token)
    db.close()
    assert result["error"] == "Memory ghost not found"


# -- server.py 1350: transfer target must be an active tenant member ------------


@pytest.mark.asyncio
async def test_transfer_nonmember_target_rejected(tmp_path, monkeypatch):
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed(db)
    _seed_memory(db, "v1", owner="u1")
    ctx = _ctx(db)
    token = set_current_principal(_principal("boss", ("admin",)))
    try:
        result = await server_module._handle_transfer(ctx, "v1", "outsider")
    finally:
        reset_current_principal(token)
    db.close()
    assert "not an active member" in result["error"]
