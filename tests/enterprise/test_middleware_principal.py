"""auth_scope wiring: principal built only when enterprise mode is on."""

import pytest

from mnemo_mcp.enterprise.identity import get_current_principal


@pytest.fixture
def captured():
    """Re-implementation of server._per_request_sub_scope's contract: import the
    real factory once Task 7 extracts it — test calls the extracted function."""

    from mnemo_mcp.server import _build_request_scope  # extracted factory (Task 7)

    async def run(claims, enterprise_enabled):
        scope = _build_request_scope(enterprise_enabled)
        seen = {}

        async def next_():
            seen["principal"] = get_current_principal()

        await scope(claims, next_)
        return seen

    return run


@pytest.mark.asyncio
async def test_enterprise_on_builds_principal(captured, monkeypatch):
    seen = await captured({"sub": "u1", "tid": "acme", "groups": ["mnemo-admin"]}, True)
    assert seen["principal"] is not None
    assert seen["principal"].tenant_id == "acme"


@pytest.mark.asyncio
async def test_enterprise_off_keeps_none(captured):
    seen = await captured({"sub": "u1", "tid": "acme"}, False)
    assert seen["principal"] is None


@pytest.mark.asyncio
async def test_enterprise_on_bad_claims_yields_none_not_raise(captured):
    seen = await captured({"tid": "acme"}, True)  # missing sub
    assert seen["principal"] is None
