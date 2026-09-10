"""Membership reads + shared-write v1 rule (spec §4.2).

Shared-write v1 stays narrow: a member may write into team/org scope only
for rows they own; touching another member's shared row needs the
owner/admin lifecycle (audited). Team-visibility rows additionally need a
live team seat, read from the database rather than trusted from claims.

Row access uses mapping access (``row["col"]``) so the helpers work on
both the SQLite backend (``sqlite3.Row``) and the Cloudflare backend
(``_D1Row``, a dict). The membership tables are outside the CF
connection-scope table set, so these statements pass ``_scope_sql``
untouched on both backends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mnemo_mcp.enterprise.identity import PrincipalContext

_TEAM_SEATS_SQL = (
    "SELECT tm.team_id FROM team_members tm"
    " JOIN teams t ON t.id = tm.team_id"
    " WHERE tm.sub = ? AND t.tenant_id = ?"
)

_MEMBER_STATUS_SQL = "SELECT status FROM org_members WHERE tenant_id = ? AND sub = ?"


def member_teams(db: Any, sub: str, tenant: str) -> frozenset[str]:
    """Live team seats for ``sub`` in ``tenant`` (authoritative, not claims)."""
    rows = db._conn.execute(_TEAM_SEATS_SQL, (sub, tenant)).fetchall()
    return frozenset(row["team_id"] for row in rows)


def member_status(db: Any, sub: str, tenant: str) -> str | None:
    """``org_members.status`` for ``sub``; ``None`` when not a member."""
    row = db._conn.execute(_MEMBER_STATUS_SQL, (tenant, sub)).fetchone()
    return row["status"] if row is not None else None


def can_write_shared(
    principal: PrincipalContext | None,
    visibility: str,
    team_id: str | None = None,
) -> bool:
    """Pure shared-scope write rule (no I/O).

    Owner/admin bypass everything. A member may always write their own
    (private) scope and the org scope of their tenant; team scope needs
    the named seat, or — when no single team is addressed (creation) —
    any live seat on ``principal.teams``. Unknown visibilities deny.
    """
    if principal is None:
        return False
    if principal.roles & {"owner", "admin"}:
        return True
    if "member" not in principal.roles:
        return False
    if visibility == "private":
        return True
    if visibility == "team":
        if team_id is not None:
            return team_id in principal.teams
        return bool(principal.teams)
    if visibility == "org":
        return True
    return False
