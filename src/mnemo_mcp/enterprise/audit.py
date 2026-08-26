"""Tamper-evident audit chain primitives (spec §4.1).

Per-tenant HMAC-SHA256 chain: event_hash = HMAC(key, prev_hash || canonical).
Keys come from skret-injected env at deploy time (C2) — never from this repo.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass

GENESIS = "0" * 64


def canonical_event_bytes(event: dict) -> bytes:
    return json.dumps(
        event, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def compute_event_hash(key: bytes, prev_hash: str, event: dict) -> str:
    """`event` PHẢI chưa chứa field event_hash (sort_keys bỏ qua field vắng mặt)."""
    return hmac.new(
        key, prev_hash.encode("utf-8") + canonical_event_bytes(event), hashlib.sha256
    ).hexdigest()


def build_event(
    *,
    tenant_id: str,
    seq: int,
    actor_sub: str,
    actor_roles: list[str],
    operation: str,
    resource_type: str,
    resource_id: str,
    decision: str,
    details: dict,
    occurred_at: str,
    prev_hash: str,
    key: bytes,
    key_id: str = "k1",
) -> dict:
    event: dict = {
        "id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "seq": seq,
        "actor_sub": actor_sub,
        "actor_roles": actor_roles,
        "operation": operation,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "decision": decision,
        "prev_hash": prev_hash,
        "key_id": key_id,
        "details": details,
        "occurred_at": occurred_at,
    }
    # Hash excludes the random storage `id` so identical semantic events
    # produce identical hashes (determinism contract); verify_rows mirrors
    # this exclusion.
    event["event_hash"] = compute_event_hash(
        key, prev_hash, {k: v for k, v in event.items() if k != "id"}
    )
    return event


@dataclass(frozen=True)
class VerifyReport:
    tenant_id: str
    checked: int
    ok: bool
    first_bad_seq: int | None
    reason: str


def verify_rows(
    tenant_id: str, rows: list[dict], keys: dict[str, bytes]
) -> VerifyReport:
    """rows: dict cột DB theo seq tăng dần (JSON columns đã parse lại)."""
    prev = GENESIS
    expected_seq = 1
    for index, row in enumerate(rows):
        seq = int(row["seq"])
        checked = index
        if seq != expected_seq:
            return VerifyReport(tenant_id, checked, False, seq, f"gap at seq {seq}")
        key = keys.get(row["key_id"])
        if key is None:
            return VerifyReport(
                tenant_id, checked, False, seq, f"unknown key_id {row['key_id']}"
            )
        payload = {k: v for k, v in row.items() if k not in ("event_hash", "id")}
        recomputed = compute_event_hash(key, row["prev_hash"], payload)
        if (
            not hmac.compare_digest(recomputed, row["event_hash"])
            or row["prev_hash"] != prev
        ):
            return VerifyReport(
                tenant_id, checked, False, seq, f"hash mismatch at seq {seq}"
            )
        prev = row["event_hash"]
        expected_seq += 1
    return VerifyReport(tenant_id, len(rows), True, None, "ok")
