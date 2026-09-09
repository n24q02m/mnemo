"""Wave B Task 3: SQLite enforcement — tenant/visibility filter + write pinning.

(a) enterprise principal search sees own-tenant rows only (cross-tenant is
empty, never an error); (b) no principal keeps legacy behavior; (c) add pins
owner_sub/tenant_id from the principal; (d) a member mutating another
member's memory is denied and audited as authz.deny.
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

NOW = "2026-09-09T00:00:00Z"
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


def _seed_memory(
    db: MemoryDB,
    mid: str,
    content: str,
    *,
    tenant: str = "acme",
    owner: str | None = "u1",
    visibility: str = "private",
) -> None:
    db._conn.execute(
        "INSERT INTO memories (id, content, category, tags, source, created_at,"
        " updated_at, access_count, last_accessed, tenant_id, owner_sub,"
        " visibility) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            mid,
            content,
            "general",
            "[]",
            None,
            NOW,
            NOW,
            0,
            NOW,
            tenant,
            owner,
            visibility,
        ),
    )
    db._conn.commit()


def _seed_membership(
    db: MemoryDB, tenant: str = "acme", sub: str = "u1", team: str = "t-eng"
) -> None:
    db._conn.execute(
        "INSERT OR IGNORE INTO tenants (id, name, created_at) VALUES (?,?,?)",
        (tenant, tenant, NOW),
    )
    db._conn.execute(
        "INSERT OR REPLACE INTO org_members (tenant_id, sub, role, status,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (tenant, sub, "member", "active", NOW, NOW),
    )
    db._conn.execute(
        "INSERT OR IGNORE INTO teams (id, tenant_id, name) VALUES (?,?,?)",
        (team, tenant, "eng"),
    )
    db._conn.execute(
        "INSERT OR IGNORE INTO team_members (team_id, sub, created_at) VALUES (?,?,?)",
        (team, sub, NOW),
    )
    db._conn.commit()


def _ids(rows: list[dict]) -> set[str]:
    return {r["id"] for r in rows}


def test_cross_tenant_search_is_empty_not_error(tmp_db: MemoryDB):
    _seed_memory(tmp_db, "a1", "alpha project launch plans", tenant="acme")
    _seed_memory(tmp_db, "b1", "alpha competitor takeover designs", tenant="other")
    res = tmp_db.search("alpha", principal=_principal())
    assert _ids(res) == {"a1"}


def test_local_mode_search_sees_everything(tmp_db: MemoryDB):
    _seed_memory(tmp_db, "a1", "alpha project launch plans", tenant="acme")
    _seed_memory(tmp_db, "b1", "alpha competitor takeover designs", tenant="other")
    assert _ids(tmp_db.search("alpha")) == {"a1", "b1"}


def test_private_row_visible_only_to_owner(tmp_db: MemoryDB):
    _seed_membership(tmp_db, sub="u1")
    _seed_membership(tmp_db, sub="u2")
    _seed_memory(tmp_db, "p1", "alpha personal diary entry", owner="u1")
    assert _ids(tmp_db.search("alpha", principal=_principal("u1"))) == {"p1"}
    assert tmp_db.search("alpha", principal=_principal("u2")) == []


def test_team_row_visible_to_teammate(tmp_db: MemoryDB):
    _seed_membership(tmp_db, sub="u1")
    _seed_membership(tmp_db, sub="u2")
    _seed_memory(tmp_db, "t1", "alpha team sprint notes", owner="u2", visibility="team")
    assert _ids(tmp_db.search("alpha", principal=_principal("u1"))) == {"t1"}


def test_list_and_get_enforce_tenant(tmp_db: MemoryDB):
    _seed_memory(tmp_db, "a1", "alpha project launch plans", tenant="acme")
    _seed_memory(tmp_db, "b1", "alpha competitor takeover designs", tenant="other")
    assert _ids(tmp_db.list_memories(principal=_principal())) == {"a1"}
    assert len(tmp_db.list_memories()) == 2
    assert tmp_db.get("b1", principal=_principal()) is None
    assert tmp_db.get("b1") is not None


def test_add_pins_owner_and_tenant(tmp_db: MemoryDB):
    mid = tmp_db.add("alpha pinned memory", tenant_id="acme", owner_sub="u1")
    row = tmp_db.get(mid)
    assert row is not None
    assert (row["tenant_id"], row["owner_sub"], row["visibility"]) == (
        "acme",
        "u1",
        "private",
    )


def test_add_defaults_to_local_semantics(tmp_db: MemoryDB):
    mid = tmp_db.add("alpha legacy memory")
    row = tmp_db.get(mid)
    assert row is not None
    assert (row["tenant_id"], row["owner_sub"], row["visibility"]) == (
        "local",
        None,
        "private",
    )


@pytest.fixture
def enterprise_ctx(tmp_path, monkeypatch):
    """Server ctx over a fresh DB with membership rows and an audit key."""
    from mnemo_mcp import server as server_module

    monkeypatch.setattr(server_module.settings, "audit_hash_key", AUDIT_KEY)
    db = MemoryDB(tmp_path / "enforce.db", embedding_dims=0)
    _seed_membership(db, sub="u1")
    _seed_membership(db, sub="u2")
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "db": db,
        "embedding_model": None,
        "embedding_dims": 0,
    }
    yield ctx, db
    db.close()


@pytest.mark.asyncio
async def test_member_update_other_memory_denied_and_audited(enterprise_ctx):
    from mnemo_mcp import server as server_module

    ctx, db = enterprise_ctx
    _seed_memory(db, "v1", "alpha victim notes", owner="u2", visibility="team")
    token = set_current_principal(_principal("u1", {"member"}, teams={"eng"}))
    try:
        result = await server_module._handle_update(ctx, "v1", content="hijacked")
    finally:
        reset_current_principal(token)
    assert "error" in result
    rows = db._conn.execute(
        "SELECT operation, decision FROM enterprise_audit WHERE tenant_id = ?",
        ("acme",),
    ).fetchall()
    # The deny audit names the attempted action; the decision captures deny.
    assert ("memory.write_shared", "deny") in [(r[0], r[1]) for r in rows]
    assert db.get("v1")["content"] == "alpha victim notes"


@pytest.mark.asyncio
async def test_owner_update_own_memory_allowed(enterprise_ctx):
    from mnemo_mcp import server as server_module

    ctx, db = enterprise_ctx
    _seed_memory(db, "v1", "alpha personal notes", owner="u1")
    token = set_current_principal(_principal("u1", roles=("member",)))
    try:
        result = await server_module._handle_update(ctx, "v1", content="edited notes")
    finally:
        reset_current_principal(token)
    assert result.get("status") == "updated"
    assert db.get(result["id"])["content"] == "edited notes"


@pytest.mark.asyncio
async def test_member_delete_other_memory_denied(enterprise_ctx):
    from mnemo_mcp import server as server_module

    ctx, db = enterprise_ctx
    _seed_memory(db, "v1", "alpha victim notes", owner="u2", visibility="team")
    token = set_current_principal(_principal("u1"))
    try:
        result = await server_module._handle_delete(ctx, "v1")
    finally:
        reset_current_principal(token)
    assert "error" in result
    assert db.get("v1") is not None
