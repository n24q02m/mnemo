"""Wave A identity core: config fields, claims->principal, role matrix, contextvar."""

from mnemo_mcp.config import Settings
from mnemo_mcp.enterprise.identity import (
    get_current_principal,
    local_principal,
    principal_from_claims,
    reset_current_principal,
    set_current_principal,
)


def test_enterprise_defaults_off(monkeypatch):
    for var in (
        "MNEMO_ENTERPRISE",
        "MNEMO_ENTERPRISE_ISSUERS",
        "MNEMO_ENTERPRISE_AUDIENCE",
        "MNEMO_ENTERPRISE_ROLE_CLAIM",
        "MNEMO_ENTERPRISE_ROLE_MAPPING",
        "MNEMO_ENTERPRISE_TENANT_CLAIM",
        "MNEMO_AUDIT_HASH_KEY",
        "MNEMO_AUDIT_KEY_ID",
        "MNEMO_AUDIT_RETENTION_DAYS",
    ):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.enterprise_enabled is False
    assert s.enterprise_issuers == ""
    assert s.enterprise_audience == ""
    assert s.enterprise_role_claim == "groups"
    assert s.enterprise_role_mapping == "{}"
    assert s.enterprise_tenant_claim == "tid"
    assert s.audit_hash_key == ""
    assert s.audit_key_id == "k1"
    assert s.audit_retention_days == 400


def test_enterprise_env_overrides(monkeypatch):
    monkeypatch.setenv("MNEMO_ENTERPRISE", "true")
    monkeypatch.setenv("MNEMO_ENTERPRISE_ISSUERS", "https://idp.example.com")
    monkeypatch.setenv("MNEMO_AUDIT_HASH_KEY", "sixteen-byte-key")
    s = Settings()
    assert s.enterprise_enabled is True
    assert s.enterprise_issuers == "https://idp.example.com"
    assert s.audit_hash_key == "sixteen-byte-key"


def test_local_principal_is_owner_of_local_tenant():
    p = local_principal()
    assert p.subject == "local" and p.tenant_id == "local"
    assert p.roles == frozenset({"owner"}) and p.method == "local"


def test_principal_from_claims_maps_roles_and_tenant():
    p = principal_from_claims(
        {"sub": "u1", "tid": "acme", "groups": ["mnemo-admin", "unknown-grp"]},
        role_mapping={"mnemo-admin": "admin"},
    )
    assert p.subject == "u1" and p.tenant_id == "acme"
    assert p.roles == frozenset({"admin"})
    assert p.method == "oidc" and p.teams == frozenset()


def test_principal_unmapped_groups_fall_back_to_member():
    p = principal_from_claims({"sub": "u2", "tid": "acme", "groups": ["zzz"]})
    assert p.roles == frozenset({"member"})
    p2 = principal_from_claims({"sub": "u3", "tid": "acme"})
    assert p2.roles == frozenset({"member"})


def test_principal_missing_sub_raises():
    import pytest

    with pytest.raises(ValueError, match="missing sub"):
        principal_from_claims({"tid": "acme"})


def test_principal_tenant_from_issuer_map():
    p = principal_from_claims(
        {"sub": "u4", "iss": "https://idp.example.com"},
        issuer_tenant_map={"https://idp.example.com": "acme"},
    )
    assert p.tenant_id == "acme"


def test_principal_tenant_missing_everywhere_raises():
    import pytest

    with pytest.raises(ValueError, match="no tenant"):
        principal_from_claims({"sub": "u5"})


def test_principal_contextvar_roundtrip():
    assert get_current_principal() is None
    token = set_current_principal(local_principal())
    try:
        assert get_current_principal().subject == "local"
    finally:
        reset_current_principal(token)
    assert get_current_principal() is None
