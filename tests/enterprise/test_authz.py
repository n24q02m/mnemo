"""Wave A role matrix: deny-by-default, per-role allow, cross-tenant deny."""

import pytest

from mnemo_mcp.enterprise.authz import AuthorizationService, ResourceRef
from mnemo_mcp.enterprise.identity import PrincipalContext


def principal(roles: set[str], tenant: str = "acme") -> PrincipalContext:
    return PrincipalContext(subject="u1", tenant_id=tenant, roles=frozenset(roles))


MEMBER_ACTIONS = ["memory.read_own", "memory.write_own", "memory.read_shared"]
ADMIN_ONLY = ["memory.write_shared", "admin.manage", "admin.transfer"]
AUDITOR_ACTIONS = ["audit.query", "audit.export"]


@pytest.mark.parametrize("action", MEMBER_ACTIONS)
def test_member_allowed(action):
    assert AuthorizationService().check(principal({"member"}), action).allowed


@pytest.mark.parametrize("action", ADMIN_ONLY)
def test_member_denied_on_admin_actions(action):
    d = AuthorizationService().check(principal({"member"}), action)
    assert not d.allowed and d.reason


@pytest.mark.parametrize("action", ADMIN_ONLY)
def test_admin_allowed(action):
    assert AuthorizationService().check(principal({"admin"}), action).allowed


@pytest.mark.parametrize("action", AUDITOR_ACTIONS)
def test_auditor_split(action):
    svc = AuthorizationService()
    assert svc.check(principal({"auditor"}), action).allowed
    assert not svc.check(principal({"auditor"}), "memory.read_own").allowed


def test_owner_passes_everything():
    svc = AuthorizationService()
    for action in (*MEMBER_ACTIONS, *ADMIN_ONLY, *AUDITOR_ACTIONS):
        assert svc.check(principal({"owner"}), action).allowed


def test_unknown_action_denied():
    d = AuthorizationService().check(principal({"owner"}), "memory.nuke")
    assert not d.allowed and "unknown action" in d.reason


def test_cross_tenant_denied_even_for_owner():
    res = ResourceRef(type="memory", id="m1", tenant_id="other")
    d = AuthorizationService().check(principal({"owner"}), "memory.read_own", res)
    assert not d.allowed and d.reason == "cross-tenant"


def test_same_tenant_resource_allowed():
    res = ResourceRef(type="memory", id="m1", tenant_id="acme")
    assert (
        AuthorizationService()
        .check(principal({"member"}), "memory.read_own", res)
        .allowed
    )


def test_no_principal_denied():
    import contextvars  # noqa: F401  (document intent)

    from mnemo_mcp.enterprise.authz import Decision  # noqa: F401

    d = AuthorizationService().check(None, "memory.read_own")
    assert not d.allowed and d.reason == "no principal"
