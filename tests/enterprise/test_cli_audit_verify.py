"""CLI audit verify: exit codes 0/1/2 qua handler trực tiếp (không subprocess)."""

import argparse

import pytest

from mnemo_mcp.cli import _configure_audit, _handle_audit_verify
from mnemo_mcp.db import MemoryDB

KEY = b"sixteen-byte-key"


@pytest.fixture
def db_with_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_AUDIT_HASH_KEY", KEY.decode())
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    db.append_audit_event(
        {
            "tenant_id": "acme",
            "actor_sub": "u1",
            "actor_roles": ["member"],
            "operation": "memory.add",
            "resource_type": "memory",
            "resource_id": "m1",
            "decision": "allow",
            "details": {},
            "occurred_at": "2026-08-25T00:00:00Z",
        },
        key=KEY,
    )
    return tmp_path / "t.db"


def _args(db_path, tenant="acme"):
    p = argparse.ArgumentParser()
    _configure_audit(p)
    return p.parse_args(["verify", "--tenant", tenant, "--db-path", str(db_path)])


def test_verify_ok_exit_0(db_with_chain, capsys):
    assert _handle_audit_verify(_args(db_with_chain)) == 0
    assert "OK" in capsys.readouterr().out


def test_verify_tamper_exit_1(db_with_chain, capsys):
    import sqlite3

    conn = sqlite3.connect(db_with_chain)
    conn.execute(
        "UPDATE enterprise_audit SET details='{\"tampered\":true}' WHERE seq=1"
    )
    conn.commit()
    conn.close()
    assert _handle_audit_verify(_args(db_with_chain)) == 1
    assert "FAIL" in capsys.readouterr().out


def test_missing_key_exit_2(db_with_chain, monkeypatch, capsys):
    monkeypatch.delenv("MNEMO_AUDIT_HASH_KEY", raising=False)
    assert _handle_audit_verify(_args(db_with_chain)) == 2
