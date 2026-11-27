"""Application-layer at-rest encryption for mnemo stores.

A store is encrypted with AES-256-GCM, one value at a time. The key material
comes from ``MNEMO_ENCRYPTION_KEY`` and is never written anywhere; the store
keeps only what is needed to re-derive and verify it (``store_meta``):

``encryption``
    The scheme: ``aes-256-gcm-v1`` or ``none``.
``encryption_kdf`` / ``encryption_kdf_params``
    How the master key is obtained: ``raw`` (the env value is a 32-byte key),
    ``argon2id`` or ``pbkdf2-sha256`` (the env value is a passphrase).
``encryption_salt``
    16 random bytes per store. They salt the passphrase KDF and the HKDF step
    that turns the master key into the data key, so two stores never share a
    data key even when they share a passphrase.
``encryption_key_check``
    A constant encrypted under a key-check subkey. Opening a store with the
    wrong key fails on this value before any row is read.

Every encrypted value is ``enc:v1:`` + base64(nonce || ciphertext || tag) with
a fresh 96-bit nonce. The associated data binds the value to its row id and
column, so moving a ciphertext to another row or column fails authentication.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from mnemo.exceptions import (
    EncryptedDataError,
    EncryptionKeyError,
    WrongEncryptionKey,
)

ENCRYPTION_KEY_ENV = "MNEMO_ENCRYPTION_KEY"

META_SCHEME = "encryption"
META_KDF = "encryption_kdf"
META_KDF_PARAMS = "encryption_kdf_params"
META_SALT = "encryption_salt"
META_KEY_CHECK = "encryption_key_check"
# The scheme flag comes first; every other key is required once it is set.
META_KEYS = (META_SCHEME, META_KDF, META_KDF_PARAMS, META_SALT, META_KEY_CHECK)

SCHEME_AES_GCM_V1 = "aes-256-gcm-v1"
SCHEME_NONE = "none"
VALUE_PREFIX = "enc:v1:"

KDF_RAW = "raw"
KDF_ARGON2ID = "argon2id"
KDF_PBKDF2 = "pbkdf2-sha256"

# OWASP-recommended Argon2id profile (64 MiB, 3 passes, 4 lanes) and the
# PBKDF2-HMAC-SHA256 iteration count used when Argon2id is unavailable.
ARGON2ID_PARAMS = {"iterations": 3, "lanes": 4, "memory_cost": 65536}
PBKDF2_PARAMS = {"iterations": 600_000}

MIN_PASSPHRASE_LENGTH = 12
KEY_BYTES = 32
SALT_BYTES = 16
NONCE_BYTES = 12
TAG_BYTES = 16

_DATA_KEY_INFO = b"mnemo/v1/data-key"
_CHECK_KEY_INFO = b"mnemo/v1/key-check-key"
_KEY_CHECK_AAD = b"mnemo/v1/key-check"
_KEY_CHECK_PLAINTEXT = b"mnemo key check v1"

# Accepted parameter ranges per KDF. The ranges only reject corrupt metadata
# (or values that would make opening the store hang); the key check is what
# proves the parameters are the ones the store was encrypted with.
_KDF_PARAM_BOUNDS: dict[str, dict[str, tuple[int, int]]] = {
    KDF_RAW: {},
    KDF_ARGON2ID: {
        "iterations": (1, 64),
        "lanes": (1, 64),
        "memory_cost": (8, 4 * 1024 * 1024),
    },
    KDF_PBKDF2: {"iterations": (10_000, 100_000_000)},
}

_HEX_KEY_RE = re.compile(r"[0-9a-fA-F]{64}")

KeyKind = Literal["raw", "passphrase"]


@dataclass(frozen=True, slots=True)
class EncryptionKey:
    """A parsed ``MNEMO_ENCRYPTION_KEY`` value. ``repr`` never shows the secret."""

    kind: KeyKind
    secret: bytes = field(repr=False)


def parse_key(value: str) -> EncryptionKey:
    """Parse a key setting into a raw key or a passphrase.

    ``hex:<64 hex chars>`` and ``base64:<32 bytes, standard or URL-safe>``
    are raw keys. Anything else is a passphrase of at least
    ``MIN_PASSPHRASE_LENGTH`` characters (NFC-normalised, so the same text
    typed on different systems derives the same key). Surrounding whitespace
    is ignored. A value that starts with a raw-key prefix but does not decode
    is rejected rather than treated as a passphrase.
    """
    text = value.strip()
    if not text:
        raise EncryptionKeyError(f"{ENCRYPTION_KEY_ENV} is empty")
    if text.startswith("hex:"):
        body = text[len("hex:") :].strip()
        if not _HEX_KEY_RE.fullmatch(body):
            raise EncryptionKeyError(
                "hex: key must be exactly 64 hex characters (32 bytes)"
            )
        return EncryptionKey("raw", bytes.fromhex(body))
    if text.startswith("base64:"):
        return EncryptionKey("raw", _decode_base64_key(text[len("base64:") :].strip()))
    passphrase = unicodedata.normalize("NFC", text)
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise EncryptionKeyError(
            f"passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters"
        )
    return EncryptionKey("passphrase", passphrase.encode("utf-8"))


def load_key(value: str | None = None) -> EncryptionKey | None:
    """Return the configured key, or ``None`` when no key is set.

    ``value=None`` reads ``MNEMO_ENCRYPTION_KEY``; an unset or blank variable
    means "no key". Any other string is parsed as given (``""`` means no key).
    """
    if value is None:
        value = os.environ.get(ENCRYPTION_KEY_ENV, "")
    if not value.strip():
        return None
    return parse_key(value)


def _decode_base64_key(body: str) -> bytes:
    for altchars in (None, b"-_"):
        try:
            secret = base64.b64decode(body, altchars=altchars, validate=True)
        except (binascii.Error, ValueError):
            continue
        if len(secret) == KEY_BYTES:
            return secret
    raise EncryptionKeyError(
        "base64: key must decode (standard or URL-safe alphabet) to exactly 32 bytes"
    )


def _argon2id_available() -> bool:
    """True when the installed cryptography/OpenSSL build can run Argon2id."""
    try:
        Argon2id(
            salt=b"\x00" * SALT_BYTES,
            length=KEY_BYTES,
            iterations=1,
            lanes=1,
            memory_cost=8,
        ).derive(b"probe")
    except UnsupportedAlgorithm:
        return False
    return True


def _derive_master(
    key: EncryptionKey, kdf: str, params: Mapping[str, int], salt: bytes
) -> bytes:
    if kdf == KDF_RAW:
        return key.secret
    if kdf == KDF_ARGON2ID:
        return Argon2id(
            salt=salt,
            length=KEY_BYTES,
            iterations=params["iterations"],
            lanes=params["lanes"],
            memory_cost=params["memory_cost"],
        ).derive(key.secret)
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=salt,
        iterations=params["iterations"],
    ).derive(key.secret)


def _subkey(master: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=KEY_BYTES, salt=salt, info=info
    ).derive(master)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str, what: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EncryptedDataError(f"store {what} is corrupt (not base64)") from exc


def _parse_kdf_params(kdf: str, text: str) -> dict[str, int]:
    try:
        params = json.loads(text)
    except ValueError as exc:
        raise EncryptedDataError(f"store {META_KDF_PARAMS} is corrupt") from exc
    bounds = _KDF_PARAM_BOUNDS[kdf]
    if not isinstance(params, dict) or set(params) != set(bounds):
        raise EncryptedDataError(f"store {META_KDF_PARAMS} do not match {kdf}")
    for name, (low, high) in bounds.items():
        value = params[name]
        if type(value) is not int or not low <= value <= high:
            raise EncryptedDataError(f"store {META_KDF_PARAMS} has an invalid {name}")
    if kdf == KDF_ARGON2ID and params["memory_cost"] < 8 * params["lanes"]:
        raise EncryptedDataError(f"store {META_KDF_PARAMS} has an invalid memory_cost")
    return params


class FieldCipher:
    """Encrypts and decrypts single column values of one store."""

    __slots__ = ("_aead",)

    def __init__(self, data_key: bytes) -> None:
        self._aead = AESGCM(data_key)

    @staticmethod
    def _aad(row_id: str, column: str) -> bytes:
        return f"mnemo/v1/{column}/{row_id}".encode()

    def encrypt(self, row_id: str, column: str, value: str | None) -> str | None:
        """Encrypt ``value`` for ``row_id``/``column``; ``None`` stays ``None``."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(
                f"column {column!r} of row {row_id!r} must be text to encrypt, "
                f"got {type(value).__name__}"
            )
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aead.encrypt(
            nonce, value.encode("utf-8"), self._aad(row_id, column)
        )
        return VALUE_PREFIX + _b64(nonce + sealed)

    def decrypt(self, row_id: str, column: str, value: object) -> str | None:
        """Decrypt a stored value. Anything that is not our ciphertext fails closed."""
        if value is None:
            return None
        where = f"column {column!r} of row {row_id!r}"
        if not isinstance(value, str) or not value.startswith(VALUE_PREFIX):
            raise EncryptedDataError(f"{where} is not encrypted in an encrypted store")
        try:
            raw = base64.b64decode(value[len(VALUE_PREFIX) :], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise EncryptedDataError(f"{where} holds malformed ciphertext") from exc
        if len(raw) < NONCE_BYTES + TAG_BYTES:
            raise EncryptedDataError(f"{where} holds truncated ciphertext")
        try:
            plain = self._aead.decrypt(
                raw[:NONCE_BYTES], raw[NONCE_BYTES:], self._aad(row_id, column)
            )
        except InvalidTag as exc:
            raise EncryptedDataError(
                f"{where} failed authentication (tampered, or moved from another "
                "row, column or store)"
            ) from exc
        return plain.decode("utf-8")


def is_ciphertext(value: object) -> bool:
    """True when ``value`` carries the encrypted-value prefix."""
    return isinstance(value, str) and value.startswith(VALUE_PREFIX)


def new_store_encryption(key: EncryptionKey) -> tuple[dict[str, str], FieldCipher]:
    """Create fresh encryption metadata for a store and its field cipher."""
    salt = os.urandom(SALT_BYTES)
    if key.kind == "raw":
        kdf, params = KDF_RAW, {}
    elif _argon2id_available():
        kdf, params = KDF_ARGON2ID, dict(ARGON2ID_PARAMS)
    else:
        kdf, params = KDF_PBKDF2, dict(PBKDF2_PARAMS)
    master = _derive_master(key, kdf, params, salt)
    check_key = _subkey(master, salt, _CHECK_KEY_INFO)
    nonce = os.urandom(NONCE_BYTES)
    check = AESGCM(check_key).encrypt(nonce, _KEY_CHECK_PLAINTEXT, _KEY_CHECK_AAD)
    meta = {
        META_SCHEME: SCHEME_AES_GCM_V1,
        META_KDF: kdf,
        META_KDF_PARAMS: json.dumps(params, sort_keys=True, separators=(",", ":")),
        META_SALT: _b64(salt),
        META_KEY_CHECK: _b64(nonce + check),
    }
    return meta, FieldCipher(_subkey(master, salt, _DATA_KEY_INFO))


def open_store_encryption(
    meta: Mapping[str, str | None], key: EncryptionKey
) -> FieldCipher:
    """Verify ``key`` against a store's metadata and return its field cipher.

    Raises ``EncryptedDataError`` for unknown or corrupt metadata and
    ``WrongEncryptionKey`` when the key does not match the store.
    """
    scheme = meta.get(META_SCHEME)
    if scheme != SCHEME_AES_GCM_V1:
        raise EncryptedDataError(f"unsupported encryption scheme {scheme!r}")
    missing = [name for name in META_KEYS[1:] if not meta.get(name)]
    if missing:
        raise EncryptedDataError(
            "store encryption metadata is incomplete (missing "
            + ", ".join(missing)
            + ")"
        )
    kdf = str(meta[META_KDF])
    if kdf not in _KDF_PARAM_BOUNDS:
        raise EncryptedDataError(f"unsupported key derivation {kdf!r}")
    params = _parse_kdf_params(kdf, str(meta[META_KDF_PARAMS]))
    salt = _unb64(str(meta[META_SALT]), META_SALT)
    if len(salt) != SALT_BYTES:
        raise EncryptedDataError(f"store {META_SALT} has the wrong length")
    check = _unb64(str(meta[META_KEY_CHECK]), META_KEY_CHECK)
    if len(check) < NONCE_BYTES + TAG_BYTES:
        raise EncryptedDataError(f"store {META_KEY_CHECK} is truncated")

    if kdf == KDF_RAW and key.kind != "raw":
        raise WrongEncryptionKey(
            "this store is encrypted with a raw key (hex:/base64:), but "
            f"{ENCRYPTION_KEY_ENV} holds a passphrase"
        )
    if kdf != KDF_RAW and key.kind == "raw":
        raise WrongEncryptionKey(
            f"this store is encrypted with a passphrase ({kdf}), but "
            f"{ENCRYPTION_KEY_ENV} holds a raw key"
        )
    if kdf == KDF_ARGON2ID and not _argon2id_available():
        raise EncryptedDataError(
            "this store's passphrase is derived with Argon2id, which the installed "
            "cryptography/OpenSSL build does not support; open it where Argon2id "
            "is available"
        )

    master = _derive_master(key, kdf, params, salt)
    check_key = _subkey(master, salt, _CHECK_KEY_INFO)
    try:
        AESGCM(check_key).decrypt(
            check[:NONCE_BYTES], check[NONCE_BYTES:], _KEY_CHECK_AAD
        )
    except InvalidTag as exc:
        raise WrongEncryptionKey(
            f"{ENCRYPTION_KEY_ENV} does not match the key this store was encrypted with"
        ) from exc
    return FieldCipher(_subkey(master, salt, _DATA_KEY_INFO))
