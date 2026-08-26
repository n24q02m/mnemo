"""Verified-identity principal for the enterprise profile.

A PrincipalContext is built ONLY from JWT claims that mcp-core already
verified (server.py auth_scope). Tool arguments can never mint one.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field

_current_principal: ContextVar[PrincipalContext | None] = ContextVar(
    "current_principal", default=None
)


@dataclass(frozen=True)
class PrincipalContext:
    subject: str
    tenant_id: str
    roles: frozenset[str]
    teams: frozenset[str] = field(default=frozenset())
    method: str = "oidc"
    claims: Mapping[str, object] = field(default_factory=dict)


def local_principal() -> PrincipalContext:
    """stdio / single-user HTTP principal — legacy behavior, unchanged."""
    return PrincipalContext(
        subject="local",
        tenant_id="local",
        roles=frozenset({"owner"}),
        method="local",
        claims={},
    )


def principal_from_claims(
    claims: dict,
    *,
    role_claim: str = "groups",
    role_mapping: dict[str, str] | None = None,
    tenant_claim: str = "tid",
    issuer_tenant_map: dict[str, str] | None = None,
) -> PrincipalContext:
    subject = claims.get("sub")
    if not subject:
        raise ValueError("claims missing sub")
    tenant = claims.get(tenant_claim)
    if not tenant:
        tenant = (issuer_tenant_map or {}).get(claims.get("iss", ""))
    if not tenant:
        raise ValueError("no tenant claim or issuer mapping")
    mapping = role_mapping or {}
    roles = {mapping[g] for g in claims.get(role_claim, []) or [] if g in mapping}
    return PrincipalContext(
        subject=str(subject),
        tenant_id=str(tenant),
        roles=frozenset(roles) if roles else frozenset({"member"}),
        method="oidc",
        claims=dict(claims),
    )


def get_current_principal() -> PrincipalContext | None:
    return _current_principal.get()


def set_current_principal(p: PrincipalContext | None) -> object:
    return _current_principal.set(p)


def reset_current_principal(token: object) -> None:
    _current_principal.reset(token)  # ty: ignore[invalid-argument-type]
