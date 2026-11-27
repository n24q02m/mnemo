"""A store the `mnemo` CLI cannot open exits by the error taxonomy.

Opening the store is where a missing or wrong encryption key, an unreadable
file or a store written by a newer release first shows up. Each of those must
come back as a JSON error envelope with its taxonomy exit code, never as a
traceback.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mnemo import crypto
from mnemo.db import MemoryDB
from mnemo_cli import __main__ as cli
from mnemo_core import results

HEX_KEY = "hex:" + bytes(range(32)).hex()
OTHER_KEY = "hex:" + bytes(range(32, 64)).hex()


@pytest.fixture
def enc_store(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "enc.db"
    db = MemoryDB(path, embedding_dims=0, encryption_key=HEX_KEY)
    try:
        memory_id = db.add("encrypted note", subject="alice")
    finally:
        db.close()
    return path, memory_id


def _fetch(path: Path, memory_id: str, capsys) -> tuple[int, dict, str]:
    rc = cli.main(["fetch", memory_id, "--db", str(path)])
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    return rc, json.loads(captured.out), captured.err


def _assert_error(envelope: dict, code: str) -> str:
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == code
    return envelope["error"]["message"]


@pytest.mark.parametrize(
    "key",
    [None, OTHER_KEY, "a passphrase that is wrong", "hex:zz"],
    ids=["missing", "wrong-hex", "wrong-passphrase", "malformed"],
)
def test_unusable_key_is_auth_denied(enc_store, key, monkeypatch, capsys):
    path, memory_id = enc_store
    if key is None:
        monkeypatch.delenv(crypto.ENCRYPTION_KEY_ENV, raising=False)
    else:
        monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV, key)
    rc, envelope, _ = _fetch(path, memory_id, capsys)
    assert rc == 4
    _assert_error(envelope, results.AUTH_DENIED)


def test_right_key_opens_the_store(enc_store, monkeypatch, capsys):
    path, memory_id = enc_store
    monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV, HEX_KEY)
    rc, envelope, _ = _fetch(path, memory_id, capsys)
    assert rc == 0
    assert envelope["ok"] is True
    assert "encrypted note" in json.dumps(envelope)


def test_unknown_scheme_is_storage(enc_store, monkeypatch, capsys):
    path, memory_id = enc_store
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE store_meta SET value = 'rot13' WHERE key = ?", (crypto.META_SCHEME,)
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV, HEX_KEY)
    rc, envelope, _ = _fetch(path, memory_id, capsys)
    assert rc == 5
    assert "rot13" in _assert_error(envelope, results.STORAGE)


def test_file_that_is_not_a_store_is_storage(tmp_path, monkeypatch, capsys):
    path = tmp_path / "garbage.db"
    path.write_bytes(b"this is not an sqlite database file" * 64)
    monkeypatch.delenv(crypto.ENCRYPTION_KEY_ENV, raising=False)
    rc, envelope, _ = _fetch(path, "any-id", capsys)
    assert rc == 5
    _assert_error(envelope, results.STORAGE)


def test_unexpected_open_failure_is_internal(tmp_path, monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise RuntimeError("injected open failure")

    monkeypatch.setattr(cli, "MemoryDB", broken)
    rc, envelope, _ = _fetch(tmp_path / "x.db", "any-id", capsys)
    assert rc == 1
    message = _assert_error(envelope, results.INTERNAL)
    assert "RuntimeError" in message and "injected open failure" in message
