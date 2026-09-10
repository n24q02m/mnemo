"""Wave B Task 6: deprovision gate + audited transfer ownership.

Deprovision: ``org_members.status='disabled'`` blocks the next request with
an audited 403. Transfer: admin/owner moves ``owner_sub`` on one memory in
one statement with an ``admin.transfer`` audit event; members are denied.
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

NOW = "2026-09-10T00:00:00+00:00"
AUDIT_KEY = "task6-test-key-0123456789abcdef"


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


def _seed(db: MemoryDB, *, disabled: bool = False) -> None:
    db._conn.execute(
        "INSERT OR IGNORE INTO tenants (id, name, created_at) VALUES (?,?,?)",
        ("acme", "acme", NOW),
    )
    db._conn.execute(
        "INSERT OR REPLACE INTO org_members (tenant_id, sub, role, status,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ("acme", "u1", "member", "disabled" if disabled else "active", NOW, NOW),
    )
    db._conn.execute(
        "INSERT OR REPLACE INTO org_members (tenant_id, sub, role, status,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ("acme", "boss", "admin", "active", NOW, NOW),
    )
    db._conn.execute(
        "INSERT INTO memories (id, content, category, tags, source, created_at,"
        " updated_at, access_count, last_accessed, tenant_id, owner_sub,"
        " visibility) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "v1",
            "alpha victim notes",
            "general",
            "[]",
            None,
            NOW,
            NOW,
            0,
            NOW,
            "acme",
            "u1",
            "private",
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


def _audit_ops(db: MemoryDB) -> list[tuple[str, str]]:
    rows = db._conn.execute(
        "SELECT operation, decision FROM enterprise_audit WHERE tenant_id = ?"
        " ORDER BY seq",
        ("acme",),
    ).fetchall()
    return [(r["operation"], r["decision"]) for r in rows]


@pytest.mark.asyncio
async def test_disabled_member_request_denied_and_audited(tmp_path, monkeypatch):
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed(db, disabled=True)
    ctx = _ctx(db)
    token = set_current_principal(_principal("u1"))
    try:
        result = await server_module._handle_add(ctx, "alpha fresh memory")
    finally:
        reset_current_principal(token)
    assert "error" in result
    assert "not authorized" in result["error"]
    assert ("auth.failure", "deny") in _audit_ops(db)
    # The disabled member's write never landed.
    assert {r["id"] for r in db.list_memories()} == {"v1"}
    db.close()


@pytest.mark.asyncio
async def test_admin_transfer_ownership_audited(tmp_path, monkeypatch):
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed(db)
    ctx = _ctx(db)
    token = set_current_principal(_principal("boss", ("admin",)))
    try:
        result = await server_module._handle_transfer(ctx, "v1", "u1")
    finally:
        reset_current_principal(token)
    assert result.get("status") == "transferred"
    row = db.get("v1")
    assert row is not None and row["owner_sub"] == "u1"
    ops = _audit_ops(db)
    assert ("admin.transfer", "allow") in ops
    db.close()


@pytest.mark.asyncio
async def test_member_transfer_denied(tmp_path, monkeypatch):
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed(db)
    ctx = _ctx(db)
    token = set_current_principal(_principal("u1"))
    try:
        result = await server_module._handle_transfer(ctx, "v1", "boss")
    finally:
        reset_current_principal(token)
    assert "error" in result
    row = db.get("v1")
    assert row is not None and row["owner_sub"] == "u1"  # unchanged
    assert ("admin.transfer", "deny") in _audit_ops(db)
    db.close()


@pytest.mark.asyncio
async def test_transfer_missing_target_denied(tmp_path, monkeypatch):
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "m.db", embedding_dims=0)
    _seed(db)
    ctx = _ctx(db)
    token = set_current_principal(_principal("boss", ("admin",)))
    try:
        result = await server_module._handle_transfer(ctx, "v1", "ghost")
    finally:
        reset_current_principal(token)
    assert "error" in result
    assert "ghost" in result["error"]
    db.close()
