"""HMAC chain primitives: canonical bytes, hash, build, verify (incl. tamper)."""

import json

from mnemo_mcp.enterprise.audit import (
    GENESIS,
    build_event,
    canonical_event_bytes,
    verify_rows,
)

KEY = b"sixteen-byte-key"


def base_event(seq: int, prev: str) -> dict:
    return build_event(
        tenant_id="acme",
        seq=seq,
        actor_sub="u1",
        actor_roles=["member"],
        operation="memory.add",
        resource_type="memory",
        resource_id="m1",
        decision="allow",
        details={"k": "v"},
        occurred_at="2026-08-25T00:00:00Z",
        prev_hash=prev,
        key=KEY,
    )


def test_canonical_bytes_are_sorted_and_dense():
    a = canonical_event_bytes({"b": 1, "a": 2})
    assert a == b'{"a":2,"b":1}'
    assert json.loads(a) == {"a": 2, "b": 1}


def test_hash_is_deterministic_and_prev_sensitive():
    e1 = base_event(1, GENESIS)
    e1b = base_event(1, GENESIS)
    assert e1["event_hash"] == e1b["event_hash"]
    assert e1["event_hash"] != base_event(1, "f" * 64)["event_hash"]
    assert e1["prev_hash"] == GENESIS and e1["seq"] == 1


def test_chain_of_two_verifies():
    e1 = base_event(1, GENESIS)
    e2 = base_event(2, e1["event_hash"])
    report = verify_rows("acme", [e1, e2], {"k1": KEY})
    assert report.ok and report.checked == 2 and report.first_bad_seq is None


def test_tampered_details_detected_at_exact_seq():
    e1 = base_event(1, GENESIS)
    e2 = base_event(2, e1["event_hash"])
    tampered = dict(e2, details={"k": "CHANGED"})
    report = verify_rows("acme", [e1, tampered], {"k1": KEY})
    assert (
        not report.ok and report.first_bad_seq == 2 and "hash mismatch" in report.reason
    )


def test_gap_detected():
    e1 = base_event(1, GENESIS)
    e3 = base_event(3, e1["event_hash"])
    report = verify_rows("acme", [e1, e3], {"k1": KEY})
    assert not report.ok and report.first_bad_seq == 3 and "gap" in report.reason


def test_unknown_key_id_detected():
    e1 = base_event(1, GENESIS)
    report = verify_rows("acme", [e1], {"other": KEY})
    assert not report.ok and "unknown key_id" in report.reason
