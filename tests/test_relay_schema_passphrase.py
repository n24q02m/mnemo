"""Tests for the Phase 2 relay schema + passphrase storage hardening.

Covers:
- ``RELAY_SCHEMA`` exposes the 5 S3 fields + the ``SYNC_PASSPHRASE`` field.
- ``_harden_passphrase`` converts raw ``SYNC_PASSPHRASE`` to
  ``SYNC_PASSPHRASE_SALT`` + ``SYNC_PASSPHRASE_HASH`` (Argon2id) and DROPS
  the raw value from the persisted config.
- Empty / missing passphrase is silently dropped (not stored as empty).
- Round-trip: hash stored by harden ``verify_passphrase`` returns True for
  the original passphrase, False for a wrong one.
- ``RELAY_SCHEMA`` capabilityInfo mentions Phase 2 passport sync.
"""

from __future__ import annotations

from mnemo_mcp.credential_state import _harden_passphrase
from mnemo_mcp.relay_schema import RELAY_SCHEMA
from mnemo_mcp.sync.bundle import verify_passphrase

# ---------------------------------------------------------------------------
# Schema surface
# ---------------------------------------------------------------------------


def test_relay_schema_includes_s3_fields() -> None:
    keys = {f["key"] for f in RELAY_SCHEMA["fields"]}
    assert {
        "SYNC_S3_BUCKET",
        "SYNC_S3_REGION",
        "SYNC_S3_ENDPOINT",
        "SYNC_S3_ACCESS_KEY_ID",
        "SYNC_S3_SECRET_ACCESS_KEY",
    }.issubset(keys), f"missing S3 fields in {keys}"


def test_relay_schema_includes_passphrase_field() -> None:
    keys = {f["key"] for f in RELAY_SCHEMA["fields"]}
    assert "SYNC_PASSPHRASE" in keys

    pass_field = next(
        f for f in RELAY_SCHEMA["fields"] if f["key"] == "SYNC_PASSPHRASE"
    )
    assert pass_field["type"] == "password"
    assert "Argon2id" in pass_field["helpText"]
    # Help text must explicitly warn about lost passphrase = unrecoverable.
    assert "lost passphrase" in pass_field["helpText"].lower()


def test_relay_schema_capability_info_mentions_passport_sync() -> None:
    capabilities = {info["label"] for info in RELAY_SCHEMA["capabilityInfo"]}
    assert any("Passport" in label for label in capabilities)


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
