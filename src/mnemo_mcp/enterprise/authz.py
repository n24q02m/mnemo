"""Single enforcement point for enterprise authorization (spec §3.2).

Deny-by-default: an action absent from the matrix, a missing principal, or a
cross-tenant resource reference is denied. Handlers call check(); they never
hand-roll role logic.
"""

from __future__ import annotations

from dataclasses import dataclass

from mnemo_mcp.enterprise.identity import PrincipalContext

_ROLE_ALLOW: dict[str, frozenset[str]] = {
    "memory.read_own": frozenset({"owner", "admin", "member"}),
    "memory.write_own": frozenset({"owner", "admin", "member"}),
    "memory.read_shared": frozenset({"owner", "admin", "member"}),
    "memory.write_shared": frozenset({"owner", "admin"}),
    "audit.query": frozenset({"owner", "admin", "auditor"}),
    "audit.export": frozenset({"owner", "admin", "auditor"}),
    "admin.manage": frozenset({"owner", "admin"}),
    "admin.transfer": frozenset({"owner", "admin"}),
}


@dataclass(frozen=True)
class ResourceRef:
    type: str
    id: str
    tenant_id: str
    owner_sub: str | None = None
    visibility: str = "private"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


class AuthorizationService:
    ACTIONS: tuple[str, ...] = tuple(_ROLE_ALLOW)

    def check(
        self,
        principal: PrincipalContext | None,
        action: str,
        resource: ResourceRef | None = None,
    ) -> Decision:
        if principal is None:
            return Decision(False, "no principal")
        if resource is not None and resource.tenant_id != principal.tenant_id:
            return Decision(False, "cross-tenant")
        allowed_roles = _ROLE_ALLOW.get(action)
        if allowed_roles is None:
            return Decision(False, f"unknown action: {action}")
        if principal.roles & allowed_roles:
            return Decision(True, "role allowed")
        return Decision(
            False, f"role(s) {sorted(principal.roles)} not allowed for {action}"
        )
