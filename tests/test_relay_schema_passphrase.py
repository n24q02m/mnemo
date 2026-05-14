"""Tests for the Phase 2 passphrase storage hardening + relay schema scope.

After the 2026-05-14 Test B scope-correction, the relay form is API
keys only. S3 + passphrase are deployment-mode (operator env config),
so the schema MUST NOT expose them as per-user fields.

Covers:
- ``RELAY_SCHEMA`` MUST NOT include S3 fields or ``SYNC_PASSPHRASE``.
- ``_harden_passphrase`` still converts a raw ``SYNC_PASSPHRASE``
  (read from env, not from the form) to Argon2id hash and drops the
  raw value so on-disk config never contains the plaintext.
- Empty / missing passphrase is silently dropped (not stored).
- Round-trip: hash stored by harden ``verify_passphrase`` returns True
  for the original passphrase, False for a wrong one.
- ``RELAY_SCHEMA`` capabilityInfo mentions the deployment-mode XOR.
"""

from __future__ import annotations

from mnemo_mcp.credential_state import _harden_passphrase
from mnemo_mcp.relay_schema import RELAY_SCHEMA
from mnemo_mcp.sync.bundle import verify_passphrase

# ---------------------------------------------------------------------------
# Schema surface
# ---------------------------------------------------------------------------


def test_relay_schema_excludes_s3_fields() -> None:
    """S3 config belongs to operator env, not per-user relay form."""
    keys = {f["key"] for f in RELAY_SCHEMA["fields"]}
    forbidden = {
        "SYNC_S3_BUCKET",
        "SYNC_S3_REGION",
        "SYNC_S3_ENDPOINT",
        "SYNC_S3_ACCESS_KEY_ID",
        "SYNC_S3_SECRET_ACCESS_KEY",
    }
    leaked = keys & forbidden
    assert not leaked, f"S3 fields leaked into relay form (operator env only): {leaked}"


def test_relay_schema_excludes_passphrase_field() -> None:
    """Passphrase is operator env (SYNC_PASSPHRASE), not relay form."""
    keys = {f["key"] for f in RELAY_SCHEMA["fields"]}
    assert "SYNC_PASSPHRASE" not in keys, (
        "SYNC_PASSPHRASE must be operator env, not per-user relay field"
    )


def test_relay_schema_capability_info_mentions_xor_passport_sync() -> None:
    capabilities = {info["label"] for info in RELAY_SCHEMA["capabilityInfo"]}
    assert any("Passport" in label for label in capabilities)
    # Capability info must document the XOR (mutually exclusive) semantics.
    passport_info = next(
        info for info in RELAY_SCHEMA["capabilityInfo"] if "Passport" in info["label"]
    )
    desc = passport_info.get("description", "").lower()
    assert "mutually exclusive" in desc or "xor" in desc.lower(), (
        f"capabilityInfo must explain XOR semantics: {passport_info}"
    )


# ---------------------------------------------------------------------------
# _harden_passphrase: raw -> Argon2id hash on disk
# ---------------------------------------------------------------------------


def test_harden_passphrase_replaces_raw_with_hash() -> None:
    config = {
        "JINA_AI_API_KEY": "jina-key",
        "SYNC_PASSPHRASE": "secret-phrase",
    }
    out = _harden_passphrase(config)

    assert "SYNC_PASSPHRASE" not in out, "raw passphrase must NOT be persisted"
    assert "SYNC_PASSPHRASE_SALT" in out
    assert "SYNC_PASSPHRASE_HASH" in out
    # Other keys preserved.
    assert out["JINA_AI_API_KEY"] == "jina-key"


def test_harden_passphrase_round_trip_verifies() -> None:
    out = _harden_passphrase({"SYNC_PASSPHRASE": "hunter2"})

    assert verify_passphrase(
        "hunter2",
        out["SYNC_PASSPHRASE_SALT"],
        out["SYNC_PASSPHRASE_HASH"],
    )
    assert not verify_passphrase(
        "wrong",
        out["SYNC_PASSPHRASE_SALT"],
        out["SYNC_PASSPHRASE_HASH"],
    )


def test_harden_passphrase_drops_empty() -> None:
    out = _harden_passphrase({"SYNC_PASSPHRASE": "", "JINA_AI_API_KEY": "x"})

    assert "SYNC_PASSPHRASE" not in out
    assert "SYNC_PASSPHRASE_SALT" not in out
    assert "SYNC_PASSPHRASE_HASH" not in out
    assert out["JINA_AI_API_KEY"] == "x"


def test_harden_passphrase_drops_whitespace_only() -> None:
    out = _harden_passphrase({"SYNC_PASSPHRASE": "   "})
    assert "SYNC_PASSPHRASE" not in out
    assert "SYNC_PASSPHRASE_SALT" not in out
    assert "SYNC_PASSPHRASE_HASH" not in out


def test_harden_passphrase_does_not_mutate_caller() -> None:
    """Defensive copy: caller's dict stays untouched."""
    original = {"SYNC_PASSPHRASE": "x"}
    _ = _harden_passphrase(original)
    assert original == {"SYNC_PASSPHRASE": "x"}


def test_harden_passphrase_no_passphrase_returns_config_unchanged() -> None:
    config = {"GEMINI_API_KEY": "ai-key"}
    out = _harden_passphrase(config)
    assert out == config
