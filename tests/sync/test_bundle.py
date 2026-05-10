"""Tests for the Phase 2 passport bundle codec.

Covers:
- ``encode_bundle`` / ``decode_bundle`` round-trip preserves section order
  and exact bytes.
- Wrong passphrase raises :class:`InvalidTag` (auth-tag failure).
- Tampered ciphertext raises :class:`InvalidTag` (also AAD tampering).
- Tampered header raises :class:`InvalidTag` (header is part of AEAD AAD).
- Plaintext header is parseable + contains the required v2 fields.
- Multi-section payload preserves insertion order.
- ``hash_passphrase`` + ``verify_passphrase`` round-trip; constant-time
  mismatch returns False.
- Empty passphrase rejected at encode + verify.
"""

from __future__ import annotations

import json
import struct

import pytest
from cryptography.exceptions import InvalidTag

from mnemo_mcp.sync.bundle import (
    decode_bundle,
    encode_bundle,
    hash_passphrase,
    verify_passphrase,
)

_PASS = "correct horse battery staple"


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_round_trip_simple_payload() -> None:
    payload = {
        "manifest.json": json.dumps({"row_count": 2}).encode(),
        "memories.jsonl": b'{"id":"a","content":"hi"}\n{"id":"b","content":"bye"}',
    }
    bundle = encode_bundle(payload, _PASS)
    decoded = decode_bundle(bundle, _PASS)
    assert decoded == payload


def test_round_trip_preserves_section_order() -> None:
    payload = {
        "manifest.json": b"{}",
        "memories.jsonl": b"first",
        "memories_entities.jsonl": b"second",
        "memories_edges.jsonl": b"third",
    }
    bundle = encode_bundle(payload, _PASS)
    decoded = decode_bundle(bundle, _PASS)
    assert list(decoded.keys()) == [
        "manifest.json",
        "memories.jsonl",
        "memories_entities.jsonl",
        "memories_edges.jsonl",
    ]
    assert decoded["memories.jsonl"] == b"first"


def test_round_trip_handles_large_section() -> None:
    """Length-prefix uses uint64 so large sections round-trip cleanly."""
    big = b"x" * (5 * 1024 * 1024)  # 5 MiB
    payload = {"big.bin": big}
    bundle = encode_bundle(payload, _PASS)
    decoded = decode_bundle(bundle, _PASS)
    assert decoded["big.bin"] == big


def test_round_trip_empty_section_value() -> None:
    payload = {"manifest.json": b"", "data.jsonl": b"x"}
    bundle = encode_bundle(payload, _PASS)
    decoded = decode_bundle(bundle, _PASS)
    assert decoded == payload


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------


def test_wrong_passphrase_raises_invalidtag() -> None:
    bundle = encode_bundle({"x": b"hello"}, _PASS)
    with pytest.raises(InvalidTag):
        decode_bundle(bundle, "wrong-passphrase")


def test_tampered_ciphertext_raises_invalidtag() -> None:
    bundle = encode_bundle({"x": b"hello"}, _PASS)
    # Flip the last byte of the ciphertext.
    tampered = bundle[:-1] + bytes([bundle[-1] ^ 0xFF])
    with pytest.raises(InvalidTag):
        decode_bundle(tampered, _PASS)


def test_tampered_header_raises_invalidtag_or_value(_pass: str = _PASS) -> None:
    """Header is part of AEAD associated_data so flipping it triggers
    InvalidTag (when JSON still parses) or ValueError (when it doesn't).
    """
    bundle = encode_bundle({"x": b"hello"}, _pass)
    hdr_len = struct.unpack("!I", bundle[:4])[0]
    header = bytearray(bundle[4 : 4 + hdr_len])
    # Replace the salt hex value's first character with a different hex digit
    # so JSON still parses but AEAD verification fails.
    header_str = header.decode("utf-8")
    obj = json.loads(header_str)
    salt_hex = obj["salt"]
    obj["salt"] = ("a" if salt_hex[0] != "a" else "b") + salt_hex[1:]
    new_header = json.dumps(obj).encode("utf-8")
    if len(new_header) != hdr_len:
        # Re-pack header length if JSON re-encoding changed byte count.
        prefix = struct.pack("!I", len(new_header))
    else:
        prefix = bundle[:4]
    tampered = prefix + new_header + bundle[4 + hdr_len :]
    with pytest.raises(InvalidTag):
        decode_bundle(tampered, _pass)


# ---------------------------------------------------------------------------
# Header inspection
# ---------------------------------------------------------------------------


def test_header_is_plaintext_v2_with_required_fields() -> None:
    bundle = encode_bundle({"x": b"hi"}, _PASS)
    hdr_len = struct.unpack("!I", bundle[:4])[0]
    header = json.loads(bundle[4 : 4 + hdr_len])
    assert header["version"] == 2
    assert header["kdf"] == "argon2id"
    assert header["aead"] == "aes-256-gcm"
    # Salt is 32 bytes hex-encoded (64 hex chars).
    assert len(header["salt"]) == 64
    # Nonce is 12 bytes hex-encoded (24 hex chars).
    assert len(header["nonce"]) == 24


def test_decode_rejects_unsupported_version() -> None:
    bundle = encode_bundle({"x": b"hi"}, _PASS)
    hdr_len = struct.unpack("!I", bundle[:4])[0]
    header = json.loads(bundle[4 : 4 + hdr_len])
    header["version"] = 99
    new_header = json.dumps(header).encode("utf-8")
    new_bundle = struct.pack("!I", len(new_header)) + new_header + bundle[4 + hdr_len :]
    with pytest.raises(ValueError, match="version"):
        decode_bundle(new_bundle, _PASS)


def test_decode_rejects_truncated_bundle() -> None:
    with pytest.raises(ValueError, match="truncated"):
        decode_bundle(b"\x00\x00", _PASS)


# ---------------------------------------------------------------------------
# Empty passphrase guard
# ---------------------------------------------------------------------------


def test_encode_rejects_empty_passphrase() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        encode_bundle({"x": b"hi"}, "")


# ---------------------------------------------------------------------------
# hash_passphrase + verify_passphrase
# ---------------------------------------------------------------------------


def test_hash_verify_round_trip() -> None:
    salt_hex, digest_hex = hash_passphrase("secret")
    assert verify_passphrase("secret", salt_hex, digest_hex) is True


def test_hash_verify_rejects_wrong_passphrase() -> None:
    salt_hex, digest_hex = hash_passphrase("secret")
    assert verify_passphrase("wrong", salt_hex, digest_hex) is False


def test_hash_verify_empty_passphrase_returns_false() -> None:
    salt_hex, digest_hex = hash_passphrase("secret")
    assert verify_passphrase("", salt_hex, digest_hex) is False


def test_hash_verify_malformed_hex_returns_false() -> None:
    assert verify_passphrase("secret", "zz", "yy") is False


def test_hash_passphrase_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        hash_passphrase("")


def test_hash_passphrase_uses_fresh_salt_each_call() -> None:
    """Default behaviour: fresh salt per call so two hashes differ."""
    salt_a, digest_a = hash_passphrase("same")
    salt_b, digest_b = hash_passphrase("same")
    assert salt_a != salt_b
    assert digest_a != digest_b


def test_hash_passphrase_pinned_salt_is_deterministic() -> None:
    """Pinning salt lets test fixtures reproduce known digests."""
    salt = bytes.fromhex("00" * 32)
    salt_a, digest_a = hash_passphrase("same", salt=salt)
    salt_b, digest_b = hash_passphrase("same", salt=salt)
    assert salt_a == salt_b
    assert digest_a == digest_b


# ---------------------------------------------------------------------------
# Header version / KDF / AEAD validation
# ---------------------------------------------------------------------------


def test_decode_rejects_unsupported_kdf() -> None:
    bundle = encode_bundle({"x": b"hi"}, _PASS)
    hdr_len = struct.unpack("!I", bundle[:4])[0]
    header = json.loads(bundle[4 : 4 + hdr_len])
    header["kdf"] = "scrypt"
    new_header = json.dumps(header).encode("utf-8")
    new_bundle = struct.pack("!I", len(new_header)) + new_header + bundle[4 + hdr_len :]
    with pytest.raises(ValueError, match="KDF"):
        decode_bundle(new_bundle, _PASS)


def test_decode_rejects_unsupported_aead() -> None:
    bundle = encode_bundle({"x": b"hi"}, _PASS)
    hdr_len = struct.unpack("!I", bundle[:4])[0]
    header = json.loads(bundle[4 : 4 + hdr_len])
    header["aead"] = "chacha20"
    new_header = json.dumps(header).encode("utf-8")
    new_bundle = struct.pack("!I", len(new_header)) + new_header + bundle[4 + hdr_len :]
    with pytest.raises(ValueError, match="AEAD"):
        decode_bundle(new_bundle, _PASS)


def test_decode_rejects_truncated_no_header_length() -> None:
    """Bundle with fewer than 4 bytes -> ValueError."""
    with pytest.raises(ValueError, match="no header length"):
        decode_bundle(b"abc", _PASS)


def test_decode_rejects_malformed_header_json() -> None:
    """Header bytes that are not valid JSON -> ValueError."""
    bad_header = b"{not-json}"
    bundle = struct.pack("!I", len(bad_header)) + bad_header + b"\x00" * 30
    with pytest.raises(ValueError, match="malformed header JSON"):
        decode_bundle(bundle, _PASS)


def test_encode_rejects_non_bytes_section() -> None:
    """Section value MUST be bytes; str raises TypeError early."""
    from typing import cast

    bad_payload = cast(dict[str, bytes], {"x": "not bytes"})
    with pytest.raises(TypeError, match="bytes"):
        encode_bundle(bad_payload, _PASS)


def test_decode_truncated_framing_raises() -> None:
    """Crafted bundle with bad section framing -> ValueError when unframing."""
    # Build a bundle with framed payload missing trailing data length bytes.
    import os

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from mnemo_mcp.sync.bundle import _derive_key

    salt = os.urandom(32)
    nonce = os.urandom(12)
    header = json.dumps(
        {
            "version": 2,
            "kdf": "argon2id",
            "salt": salt.hex(),
            "aead": "aes-256-gcm",
            "nonce": nonce.hex(),
        }
    ).encode()
    key = _derive_key(_PASS, salt)
    # Truncated framing: only 4 bytes name_len, no actual name
    framed = struct.pack("!I", 100)  # claims a 100-byte name
    ciphertext = AESGCM(key).encrypt(nonce, framed, associated_data=header)
    bundle = struct.pack("!I", len(header)) + header + ciphertext

    with pytest.raises(ValueError, match="truncated section name"):
        decode_bundle(bundle, _PASS)
