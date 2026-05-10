"""Passport bundle codec - AES-256-GCM payload + Argon2id KDF (Phase 2 Task 6).

Spec reference: ``2026-04-19-mnemo-v2-design.md`` section 5.5.

Bundle layout (bytes)::

    [4 bytes]    header_len (big-endian uint32)
    [N bytes]    header (UTF-8 JSON)
                   {"version": 2, "kdf": "argon2id",
                    "salt": "<hex>", "aead": "aes-256-gcm",
                    "nonce": "<hex>"}
    [M bytes]    AES-256-GCM ciphertext (associated_data = header)

Header is plaintext so an operator inspecting an opaque bundle can read
the version + KDF parameters without the passphrase. The ciphertext is
opaque - tampering anywhere flips the GCM auth tag and ``decode_bundle``
raises :class:`cryptography.exceptions.InvalidTag`.

Inside the ciphertext the payload is framed as length-prefixed sections::

    [4 bytes]    section_name_len (uint32 BE)
    [N bytes]    section_name (UTF-8)
    [8 bytes]    section_data_len (uint64 BE)
    [M bytes]    section_data

Sections used by the Phase 2 passport bundle:

- ``manifest.json`` - bundle metadata (row counts, since timestamp,
  schema_version, created_at)
- ``memories.jsonl`` - one JSON object per memory row
- ``memories_entities.jsonl`` - knowledge graph entity rows
- ``memories_edges.jsonl`` - memory<->entity link rows

Phase 3 may add ``embeddings.bin`` for vector exports.

Passphrase handling:

- :func:`encode_bundle` derives a 256-bit key from the passphrase via
  Argon2id (32-byte salt per bundle, 3 iterations, 4 lanes, 64MiB memory
  cost - matches OWASP 2024 recommendations).
- :func:`hash_passphrase` + :func:`verify_passphrase` provide a constant-
  time gate so the relay form can store an Argon2id hash in
  ``config.enc`` instead of the raw passphrase. The gate uses
  :func:`hmac.compare_digest` so timing attacks against the digest leak
  no information about the passphrase.
"""

from __future__ import annotations

import hmac
import json
import os
import struct
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

# ---------------------------------------------------------------------------
# KDF + AEAD parameters (versioned via header field "version")
# ---------------------------------------------------------------------------

_HEADER_VERSION: Final[int] = 2
_KDF_NAME: Final[str] = "argon2id"
_AEAD_NAME: Final[str] = "aes-256-gcm"

#: Argon2id salt length (bytes). 32 bytes is well above the 16-byte minimum
#: in RFC 9106 and matches the 256-bit AES key length symmetry.
_SALT_LEN: Final[int] = 32

#: AES-GCM nonce length. 12 bytes is the spec-mandated value.
_NONCE_LEN: Final[int] = 12

#: AES-256 key length.
_KEY_LEN: Final[int] = 32

#: Argon2id parameters - matches OWASP 2024 baseline for interactive use.
_ARGON2_ITERATIONS: Final[int] = 3
_ARGON2_LANES: Final[int] = 4
_ARGON2_MEMORY_COST: Final[int] = 64 * 1024  # 64 MiB


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Argon2id-derive a 256-bit AES key from ``passphrase`` + ``salt``."""
    kdf = Argon2id(
        salt=salt,
        length=_KEY_LEN,
        iterations=_ARGON2_ITERATIONS,
        lanes=_ARGON2_LANES,
        memory_cost=_ARGON2_MEMORY_COST,
    )
    return kdf.derive(passphrase.encode("utf-8"))


# ---------------------------------------------------------------------------
# Public bundle codec
# ---------------------------------------------------------------------------


def encode_bundle(payload: dict[str, bytes], passphrase: str) -> bytes:
    """Encode ``payload`` sections into an encrypted passport bundle.

    Args:
        payload: Dict mapping section name (e.g. ``"memories.jsonl"``) to
            raw section bytes. Insertion order is preserved on decode so
            callers can rely on ordering for post-decryption manifest
            inspection.
        passphrase: User passphrase (UTF-8). Argon2id-derived to a
            256-bit AES key.

    Returns:
        Self-contained bundle bytes (header + ciphertext).

    Raises:
        ValueError: If ``passphrase`` is empty (refuse to encrypt without
            a real key - prevents accidental zero-passphrase artefacts).
    """
    if not passphrase:
        raise ValueError("encode_bundle: passphrase must be non-empty")

    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    header = json.dumps(
        {
            "version": _HEADER_VERSION,
            "kdf": _KDF_NAME,
            "salt": salt.hex(),
            "aead": _AEAD_NAME,
            "nonce": nonce.hex(),
        }
    ).encode("utf-8")

    framed = _frame_payload(payload)
    key = _derive_key(passphrase, salt)
    ciphertext = AESGCM(key).encrypt(nonce, framed, associated_data=header)
    return struct.pack("!I", len(header)) + header + ciphertext


def decode_bundle(bundle: bytes, passphrase: str) -> dict[str, bytes]:
    """Decode + decrypt ``bundle`` using ``passphrase``.

    Args:
        bundle: Bytes produced by :func:`encode_bundle` (or a
          forward-compatible v2 header).
        passphrase: User passphrase that was used during encode.

    Returns:
        Section name -> bytes dict in the same insertion order used at
        encode time.

    Raises:
        ValueError: Header length / version mismatch / malformed JSON.
        cryptography.exceptions.InvalidTag: Wrong passphrase OR ciphertext
            tampering (GCM auth tag mismatch). Both surface the same
            exception so the caller cannot tell them apart - this is by
            design (no passphrase oracle).
    """
    if len(bundle) < 4:
        raise ValueError("decode_bundle: bundle truncated (no header length)")
    hdr_len = struct.unpack("!I", bundle[:4])[0]
    if 4 + hdr_len > len(bundle):
        raise ValueError("decode_bundle: bundle truncated (header overrun)")

    header_bytes = bundle[4 : 4 + hdr_len]
    try:
        header = json.loads(header_bytes)
    except json.JSONDecodeError as e:
        raise ValueError(f"decode_bundle: malformed header JSON: {e}") from e

    if header.get("version") != _HEADER_VERSION:
        raise ValueError(
            f"decode_bundle: unsupported version {header.get('version')!r} "
            f"(this build supports v{_HEADER_VERSION})"
        )
    if header.get("kdf") != _KDF_NAME:
        raise ValueError(
            f"decode_bundle: unsupported KDF {header.get('kdf')!r} "
            f"(this build supports {_KDF_NAME})"
        )
    if header.get("aead") != _AEAD_NAME:
        raise ValueError(
            f"decode_bundle: unsupported AEAD {header.get('aead')!r} "
            f"(this build supports {_AEAD_NAME})"
        )

    salt = bytes.fromhex(header["salt"])
    nonce = bytes.fromhex(header["nonce"])
    ciphertext = bundle[4 + hdr_len :]

    key = _derive_key(passphrase, salt)
    framed = AESGCM(key).decrypt(nonce, ciphertext, associated_data=header_bytes)
    return _unframe_payload(framed)


# ---------------------------------------------------------------------------
# Section framing
# ---------------------------------------------------------------------------


def _frame_payload(payload: dict[str, bytes]) -> bytes:
    """Concatenate ``payload`` into the length-prefixed framing format."""
    out = bytearray()
    for name, data in payload.items():
        if not isinstance(data, bytes):
            raise TypeError(
                f"encode_bundle: section {name!r} value must be bytes, "
                f"got {type(data).__name__}"
            )
        name_bytes = name.encode("utf-8")
        out += struct.pack("!I", len(name_bytes))
        out += name_bytes
        out += struct.pack("!Q", len(data))
        out += data
    return bytes(out)


def _unframe_payload(framed: bytes) -> dict[str, bytes]:
    """Reverse of :func:`_frame_payload`."""
    payload: dict[str, bytes] = {}
    offset = 0
    n = len(framed)
    while offset < n:
        if offset + 4 > n:
            raise ValueError("decode_bundle: truncated section name length")
        name_len = struct.unpack("!I", framed[offset : offset + 4])[0]
        offset += 4
        if offset + name_len > n:
            raise ValueError("decode_bundle: truncated section name")
        name = framed[offset : offset + name_len].decode("utf-8")
        offset += name_len
        if offset + 8 > n:
            raise ValueError("decode_bundle: truncated section data length")
        data_len = struct.unpack("!Q", framed[offset : offset + 8])[0]
        offset += 8
        if offset + data_len > n:
            raise ValueError("decode_bundle: truncated section data")
        payload[name] = framed[offset : offset + data_len]
        offset += data_len
    return payload


# ---------------------------------------------------------------------------
# Passphrase hashing (relay form storage gate)
# ---------------------------------------------------------------------------


def hash_passphrase(passphrase: str, salt: bytes | None = None) -> tuple[str, str]:
    """Argon2id-hash ``passphrase`` for storage in encrypted ``config.enc``.

    Returns ``(salt_hex, digest_hex)`` so callers can store both fields
    in ``config.enc`` and pass them back to :func:`verify_passphrase`
    on subsequent unlock attempts.

    The salt is generated fresh when ``salt`` is None (production path);
    callers can pin a known salt for deterministic test fixtures.
    """
    if not passphrase:
        raise ValueError("hash_passphrase: passphrase must be non-empty")
    salt = salt if salt is not None else os.urandom(_SALT_LEN)
    digest = _derive_key(passphrase, salt)
    return salt.hex(), digest.hex()


def verify_passphrase(passphrase: str, salt_hex: str, digest_hex: str) -> bool:
    """Constant-time check ``passphrase`` against a stored Argon2id digest.

    Returns False on any malformed input (hex parse fail, wrong length)
    so a corrupted ``config.enc`` cannot trigger an exception that would
    otherwise look like a passphrase-mismatch oracle to a calling tool.
    """
    if not passphrase:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    fresh = _derive_key(passphrase, salt)
    return hmac.compare_digest(fresh, expected)
