"""Unit tests for mnemo.crypto: key parsing, KDF selection, field cipher.

Every key here is an obvious, non-secret test value built at runtime.
"""

from __future__ import annotations

import base64
import json

import pytest

from mnemo import crypto
from mnemo.exceptions import (
    EncryptedDataError,
    EncryptionKeyError,
    WrongEncryptionKey,
)

RAW_BYTES = bytes(range(32))
HEX_KEY = "hex:" + RAW_BYTES.hex()
B64_KEY = "base64:" + base64.b64encode(RAW_BYTES).decode()
PASSPHRASE = "correct horse battery staple test"


class TestParseKey:
    def test_hex_key(self):
        key = crypto.parse_key(HEX_KEY)
        assert key.kind == "raw"
        assert key.secret == RAW_BYTES

    def test_base64_key(self):
        key = crypto.parse_key(B64_KEY)
        assert key.kind == "raw"
        assert key.secret == RAW_BYTES

    def test_urlsafe_base64_key(self):
        raw = b"\xfb\xff" * 16
        key = crypto.parse_key("base64:" + base64.urlsafe_b64encode(raw).decode())
        assert key.secret == raw

    def test_surrounding_whitespace_is_ignored(self):
        assert crypto.parse_key(f"  {HEX_KEY}\r\n").secret == RAW_BYTES

    def test_passphrase(self):
        key = crypto.parse_key(PASSPHRASE)
        assert key.kind == "passphrase"
        assert key.secret == PASSPHRASE.encode("utf-8")

    def test_repr_hides_secret(self):
        assert RAW_BYTES.hex() not in repr(crypto.parse_key(HEX_KEY))
        assert PASSPHRASE not in repr(crypto.parse_key(PASSPHRASE))

    @pytest.mark.parametrize(
        "value",
        [
            "hex:abcd",  # too short
            "hex:" + "zz" * 32,  # not hex
            "base64:AAAA",  # too short
            "base64:!!!not-base64!!!",
            "short",  # passphrase under the minimum
            "",
            "   ",
        ],
    )
    def test_malformed_values_are_rejected(self, value):
        with pytest.raises(EncryptionKeyError):
            crypto.parse_key(value)

    def test_malformed_prefixed_value_is_not_treated_as_passphrase(self):
        # A long but broken "hex:" value must fail instead of silently becoming
        # a passphrase that happens to start with "hex:".
        with pytest.raises(EncryptionKeyError, match="hex"):
            crypto.parse_key("hex:" + "0" * 63)


class TestStoreEncryptionMeta:
    def test_raw_key_meta_never_contains_the_key(self):
        meta, _ = crypto.new_store_encryption(crypto.parse_key(HEX_KEY))
        assert meta[crypto.META_SCHEME] == crypto.SCHEME_AES_GCM_V1
        assert meta[crypto.META_KDF] == "raw"
        blob = json.dumps(meta)
        assert RAW_BYTES.hex() not in blob
        assert base64.b64encode(RAW_BYTES).decode() not in blob
        assert set(meta) == set(crypto.META_KEYS)

    def test_passphrase_uses_argon2id(self):
        meta, _ = crypto.new_store_encryption(crypto.parse_key(PASSPHRASE))
        assert meta[crypto.META_KDF] == "argon2id"
        params = json.loads(meta[crypto.META_KDF_PARAMS])
        assert params == {"iterations": 3, "lanes": 4, "memory_cost": 65536}
        assert PASSPHRASE not in json.dumps(meta)

    def test_passphrase_falls_back_to_pbkdf2(self, monkeypatch):
        monkeypatch.setattr(crypto, "_argon2id_available", lambda: False)
        meta, cipher = crypto.new_store_encryption(crypto.parse_key(PASSPHRASE))
        assert meta[crypto.META_KDF] == "pbkdf2-sha256"
        assert json.loads(meta[crypto.META_KDF_PARAMS]) == {"iterations": 600_000}
        reopened = crypto.open_store_encryption(meta, crypto.parse_key(PASSPHRASE))
        token = cipher.encrypt("row", "content", "hello")
        assert reopened.decrypt("row", "content", token) == "hello"

    def test_argon2id_store_fails_closed_without_argon2id(self, monkeypatch):
        meta, _ = crypto.new_store_encryption(crypto.parse_key(PASSPHRASE))
        monkeypatch.setattr(crypto, "_argon2id_available", lambda: False)
        with pytest.raises(EncryptedDataError, match="Argon2id"):
            crypto.open_store_encryption(meta, crypto.parse_key(PASSPHRASE))

    def test_argon2id_unsupported_algorithm_is_detected(self, monkeypatch):
        from cryptography.exceptions import UnsupportedAlgorithm

        class _Unsupported:
            def __init__(self, *args, **kwargs):
                raise UnsupportedAlgorithm("argon2id not supported")

        monkeypatch.setattr(crypto, "Argon2id", _Unsupported)
        assert crypto._argon2id_available() is False

    def test_salt_is_random_per_store(self):
        key = crypto.parse_key(HEX_KEY)
        first, _ = crypto.new_store_encryption(key)
        second, _ = crypto.new_store_encryption(key)
        assert first[crypto.META_SALT] != second[crypto.META_SALT]

    def test_reopen_with_same_key(self):
        key = crypto.parse_key(B64_KEY)
        meta, cipher = crypto.new_store_encryption(key)
        reopened = crypto.open_store_encryption(meta, crypto.parse_key(HEX_KEY))
        token = cipher.encrypt("id1", "content", "secret text")
        assert reopened.decrypt("id1", "content", token) == "secret text"

    def test_wrong_raw_key_is_detected_by_key_check(self):
        meta, _ = crypto.new_store_encryption(crypto.parse_key(HEX_KEY))
        with pytest.raises(WrongEncryptionKey):
            crypto.open_store_encryption(meta, crypto.parse_key("hex:" + "ab" * 32))

    def test_wrong_passphrase_is_detected_by_key_check(self):
        meta, _ = crypto.new_store_encryption(crypto.parse_key(PASSPHRASE))
        with pytest.raises(WrongEncryptionKey):
            crypto.open_store_encryption(
                meta, crypto.parse_key("a different passphrase entirely")
            )

    def test_key_kind_mismatch_is_reported(self):
        meta, _ = crypto.new_store_encryption(crypto.parse_key(HEX_KEY))
        with pytest.raises(WrongEncryptionKey, match="raw key"):
            crypto.open_store_encryption(meta, crypto.parse_key(PASSPHRASE))
        meta, _ = crypto.new_store_encryption(crypto.parse_key(PASSPHRASE))
        with pytest.raises(WrongEncryptionKey, match="passphrase"):
            crypto.open_store_encryption(meta, crypto.parse_key(HEX_KEY))

    @pytest.mark.parametrize("missing", list(crypto.META_KEYS[1:]))
    def test_incomplete_meta_fails_closed(self, missing):
        meta, _ = crypto.new_store_encryption(crypto.parse_key(HEX_KEY))
        meta = {k: v for k, v in meta.items() if k != missing}
        with pytest.raises(EncryptedDataError):
            crypto.open_store_encryption(meta, crypto.parse_key(HEX_KEY))

    def test_unknown_scheme_fails_closed(self):
        meta, _ = crypto.new_store_encryption(crypto.parse_key(HEX_KEY))
        meta[crypto.META_SCHEME] = "aes-512-imaginary"
        with pytest.raises(EncryptedDataError, match="aes-512-imaginary"):
            crypto.open_store_encryption(meta, crypto.parse_key(HEX_KEY))

    def test_unknown_kdf_fails_closed(self):
        meta, _ = crypto.new_store_encryption(crypto.parse_key(HEX_KEY))
        meta[crypto.META_KDF] = "md5"
        with pytest.raises(EncryptedDataError, match="md5"):
            crypto.open_store_encryption(meta, crypto.parse_key(HEX_KEY))

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            (crypto.META_SALT, "!!!"),
            (crypto.META_KEY_CHECK, "!!!"),
            (crypto.META_KDF_PARAMS, "not json"),
        ],
    )
    def test_corrupt_meta_fails_closed(self, field, value):
        meta, _ = crypto.new_store_encryption(crypto.parse_key(PASSPHRASE))
        meta[field] = value
        with pytest.raises(EncryptedDataError):
            crypto.open_store_encryption(meta, crypto.parse_key(PASSPHRASE))

    def test_argon2id_memory_cap(self):
        assert (
            crypto.ARGON2ID_MAX_MEMORY_COST == 4 * crypto.ARGON2ID_PARAMS["memory_cost"]
        )
        at_cap = dict(
            crypto.ARGON2ID_PARAMS, memory_cost=crypto.ARGON2ID_MAX_MEMORY_COST
        )
        assert (
            crypto._parse_kdf_params(crypto.KDF_ARGON2ID, json.dumps(at_cap)) == at_cap
        )

    def test_argon2id_memory_above_the_cap_is_refused(self):
        meta, _ = crypto.new_store_encryption(crypto.parse_key(HEX_KEY))
        meta[crypto.META_KDF] = crypto.KDF_ARGON2ID
        meta[crypto.META_KDF_PARAMS] = json.dumps(
            dict(
                crypto.ARGON2ID_PARAMS,
                memory_cost=crypto.ARGON2ID_MAX_MEMORY_COST + 1,
            )
        )
        with pytest.raises(EncryptedDataError, match="invalid memory_cost"):
            crypto.open_store_encryption(meta, crypto.parse_key(PASSPHRASE))

    def test_tampered_key_check_is_wrong_key(self):
        meta, _ = crypto.new_store_encryption(crypto.parse_key(HEX_KEY))
        raw = bytearray(base64.b64decode(meta[crypto.META_KEY_CHECK]))
        raw[-1] ^= 0x01
        meta[crypto.META_KEY_CHECK] = base64.b64encode(bytes(raw)).decode()
        with pytest.raises(WrongEncryptionKey):
            crypto.open_store_encryption(meta, crypto.parse_key(HEX_KEY))


_WHERE = "column 'content' of row 'row-1'"


@pytest.fixture
def cipher() -> crypto.FieldCipher:
    _, field_cipher = crypto.new_store_encryption(crypto.parse_key(HEX_KEY))
    return field_cipher


class TestFieldCipher:
    def test_roundtrip_unicode(self, cipher):
        text = "Ghi nhớ: người dùng thích cà phê đen"
        token = cipher.encrypt("row-1", "content", text)
        assert token.startswith(crypto.VALUE_PREFIX)
        assert text not in token
        assert cipher.decrypt("row-1", "content", token) == text

    def test_none_stays_none(self, cipher):
        assert cipher.encrypt("row-1", "source", None) is None
        assert cipher.decrypt("row-1", "source", None) is None

    def test_fresh_nonce_per_value(self, cipher):
        first = cipher.encrypt("row-1", "content", "same")
        second = cipher.encrypt("row-1", "content", "same")
        assert first != second
        nonce_a = base64.b64decode(first[len(crypto.VALUE_PREFIX) :])[:12]
        nonce_b = base64.b64decode(second[len(crypto.VALUE_PREFIX) :])[:12]
        assert nonce_a != nonce_b

    def test_row_swap_is_detected(self, cipher):
        token = cipher.encrypt("row-1", "content", "belongs to row 1")
        with pytest.raises(EncryptedDataError, match="row-2"):
            cipher.decrypt("row-2", "content", token)

    def test_column_swap_is_detected(self, cipher):
        token = cipher.encrypt("row-1", "content", "belongs to content")
        with pytest.raises(EncryptedDataError, match="source"):
            cipher.decrypt("row-1", "source", token)

    def test_tampered_ciphertext_is_detected(self, cipher):
        token = cipher.encrypt("row-1", "content", "intact")
        raw = bytearray(base64.b64decode(token[len(crypto.VALUE_PREFIX) :]))
        raw[15] ^= 0x01
        bad = crypto.VALUE_PREFIX + base64.b64encode(bytes(raw)).decode()
        with pytest.raises(EncryptedDataError, match=_WHERE):
            cipher.decrypt("row-1", "content", bad)

    @pytest.mark.parametrize(
        "value",
        [
            "plain text",
            b"bytes",
            42,
            crypto.VALUE_PREFIX + "%%%",
            crypto.VALUE_PREFIX,
            crypto.VALUE_PREFIX + "AAAA",
        ],
    )
    def test_non_ciphertext_fails_closed(self, cipher, value):
        # Every failure names the row and column, so the bad row can be found.
        with pytest.raises(EncryptedDataError, match=_WHERE):
            cipher.decrypt("row-1", "content", value)

    def test_encrypt_rejects_non_text(self, cipher):
        with pytest.raises(TypeError):
            cipher.encrypt("row-1", "content", 42)  # type: ignore[arg-type]

    def test_other_store_key_cannot_decrypt(self, cipher):
        _, other = crypto.new_store_encryption(crypto.parse_key(HEX_KEY))
        token = cipher.encrypt("row-1", "content", "store one")
        with pytest.raises(EncryptedDataError):
            other.decrypt("row-1", "content", token)

    def test_is_ciphertext(self):
        assert crypto.is_ciphertext(crypto.VALUE_PREFIX + "abc")
        assert not crypto.is_ciphertext("plain")
        assert not crypto.is_ciphertext(None)
