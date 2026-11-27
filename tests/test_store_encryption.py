"""Offline store rewrite: ``n24q02m-mnemo encrypt`` / ``decrypt``.

Each rewrite takes a self-contained backup first, rewrites every row in one
transaction while holding an exclusive lock, verifies the result, and puts
the backup back when anything fails. Every key here is an obvious, non-secret
test value built at runtime.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mnemo import cli, crypto, store_encryption
from mnemo.db import MemoryDB
from mnemo.exceptions import (
    EncryptedDataError,
    EncryptionError,
    EncryptionKeyMissing,
    GraphDataPresentError,
    StoreBusyError,
    StoreNotEncrypted,
    StoreRewriteError,
    WrongEncryptionKey,
)

HEX_KEY = "hex:" + bytes(range(32)).hex()
OTHER_KEY = "hex:" + bytes(range(32, 64)).hex()
MARKER = "zqxplaintextmarker"


@pytest.fixture(autouse=True)
def _fast_lock_timeout(monkeypatch):
    monkeypatch.setattr(store_encryption, "LOCK_TIMEOUT_MS", 50)


@pytest.fixture
def plain_store(tmp_path: Path) -> Path:
    path = tmp_path / "memories.db"
    db = MemoryDB(path, embedding_dims=0)
    try:
        db.add(
            f"alpha {MARKER} project notes",
            category="tech",
            tags=["db", MARKER],
            source=f"src {MARKER}",
            subject="alice",
        )
        db.add_with_context_type(
            "compressed summary",
            text_raw=f"raw original {MARKER}",
            compressed=True,
            compression_provider="chat-cell",
        )
        archived = db.add(f"archived {MARKER}")
        db.soft_archive(archived)
        superseded = db.add(f"old version {MARKER}")
        db.update(superseded, content=f"new version {MARKER}")
    finally:
        db.close()
    return path


def _export(path: Path, key: str = "") -> list[dict]:
    db = MemoryDB(path, embedding_dims=0, encryption_key=key)
    try:
        jsonl, _ = db.export_jsonl()
    finally:
        db.close()
    return [json.loads(line) for line in jsonl.splitlines()]


def _scan(path: Path) -> bool:
    """True when the marker appears in the database or any sidecar file."""
    for suffix in ("", "-wal", "-shm"):
        candidate = path.with_name(path.name + suffix)
        if candidate.exists() and MARKER.encode() in candidate.read_bytes():
            return True
    return False


def _meta(path: Path) -> dict[str, str]:
    conn = sqlite3.connect(path)
    try:
        return dict(conn.execute("SELECT key, value FROM store_meta").fetchall())
    finally:
        conn.close()


def _triggers(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            )
        }
    finally:
        conn.close()


def _backups(path: Path, action: str) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.{action}-*.bak"))


def _leftover_tmp(path: Path) -> list[Path]:
    return [p for p in path.parent.iterdir() if p.name.endswith(".tmp")]


def _get(db: MemoryDB, memory_id: str) -> dict[str, Any]:
    row = db.get(memory_id)
    assert row is not None, memory_id
    return row


def tmp_plain(store: Path) -> Path:
    """A second plaintext store with data, next to ``store``."""
    path = store.with_name("other-plain.db")
    db = MemoryDB(path, embedding_dims=0, encryption_key="")
    try:
        db.add("plain row")
    finally:
        db.close()
    return path


def _run_cli(argv: list[str], monkeypatch, key: str | None = HEX_KEY) -> int:
    if key is None:
        monkeypatch.delenv(crypto.ENCRYPTION_KEY_ENV, raising=False)
    else:
        monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV, key)
    return cli.main(argv)


class TestEncryptDecryptCli:
    def test_encrypt_then_decrypt_roundtrip(self, plain_store, monkeypatch, capsys):
        before = _export(plain_store)
        assert _scan(plain_store)

        assert _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch) == 0
        out = capsys.readouterr().out
        assert "Encrypted" in out
        assert "delete it securely" in out

        # The backup is a plaintext, self-contained SQLite file.
        (backup,) = _backups(plain_store, "encrypt")
        assert backup.name in out
        conn = sqlite3.connect(backup)
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
            contents = [r[0] for r in conn.execute("SELECT content FROM memories")]
        finally:
            conn.close()
        assert any(MARKER in c for c in contents)
        assert not backup.with_name(backup.name + "-wal").exists()

        # The store itself holds no plaintext and only works with the key.
        assert not _scan(plain_store)
        assert _meta(plain_store)[crypto.META_SCHEME] == crypto.SCHEME_AES_GCM_V1
        triggers = _triggers(plain_store)
        assert "mnemo_guard_memories_insert" in triggers
        assert not triggers & {"memories_ai", "memories_ad", "memories_au"}
        with pytest.raises(EncryptionKeyMissing):
            MemoryDB(plain_store, embedding_dims=0, encryption_key="")
        with pytest.raises(StoreNotEncrypted):
            MemoryDB(tmp_plain(plain_store), embedding_dims=0, encryption_key=HEX_KEY)
        assert _export(plain_store, HEX_KEY) == before

        db = MemoryDB(plain_store, embedding_dims=0, encryption_key=HEX_KEY)
        try:
            assert db.encrypted
            hits = db.search("alpha project")
            assert hits and MARKER in hits[0]["content"]
            assert db.list_archived()[0]["content"] == f"archived {MARKER}"
            raw = db._conn.execute(
                "SELECT count(*) FROM memories WHERE text_raw IS NOT NULL"
                " AND substr(text_raw, 1, 7) != 'enc:v1:'"
            ).fetchone()[0]
            assert raw == 0
        finally:
            db.close()

        # The search above bumped access stats, so compare with the state the
        # encrypted store holds right before it is decrypted.
        encrypted_state = _export(plain_store, HEX_KEY)
        assert _run_cli(["decrypt", "--db", str(plain_store)], monkeypatch) == 0
        out = capsys.readouterr().out
        assert "Decrypted" in out
        assert crypto.ENCRYPTION_KEY_ENV in out
        assert len(_backups(plain_store, "decrypt")) == 1

        assert _meta(plain_store).get(crypto.META_SCHEME) == crypto.SCHEME_NONE
        assert not set(_meta(plain_store)) & set(crypto.META_KEYS[1:])
        triggers = _triggers(plain_store)
        assert {"memories_ai", "memories_ad", "memories_au"} <= triggers
        assert not any(name.startswith("mnemo_guard_") for name in triggers)
        assert _export(plain_store) == encrypted_state

        db = MemoryDB(plain_store, embedding_dims=0, encryption_key="")
        try:
            assert not db.encrypted
            assert MARKER in db.search("alpha project")[0]["content"]
            fts_rows = db._conn.execute(
                "SELECT count(*) FROM memories_fts_docsize"
            ).fetchone()[0]
            mem_rows = db._conn.execute("SELECT count(*) FROM memories").fetchone()[0]
            assert fts_rows == mem_rows
        finally:
            db.close()
        assert _leftover_tmp(plain_store) == []

    def test_operations_are_idempotent(self, plain_store, monkeypatch, capsys):
        assert _run_cli(["decrypt", "--db", str(plain_store)], monkeypatch) == 0
        assert "not encrypted" in capsys.readouterr().out
        assert _backups(plain_store, "decrypt") == []

        assert _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch) == 0
        capsys.readouterr()
        assert _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch) == 0
        assert "already encrypted" in capsys.readouterr().out
        assert len(_backups(plain_store, "encrypt")) == 1

    def test_already_encrypted_with_wrong_key(self, plain_store, monkeypatch, capsys):
        assert _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch) == 0
        capsys.readouterr()
        rc = _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch, OTHER_KEY)
        assert rc == 2
        assert "mnemo:" in capsys.readouterr().err

    def test_decrypt_with_wrong_key_changes_nothing(
        self, plain_store, monkeypatch, capsys
    ):
        assert _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch) == 0
        snapshot = _export(plain_store, HEX_KEY)
        capsys.readouterr()
        rc = _run_cli(["decrypt", "--db", str(plain_store)], monkeypatch, OTHER_KEY)
        assert rc == 2
        assert "key" in capsys.readouterr().err.lower()
        assert _backups(plain_store, "decrypt") == []
        assert _export(plain_store, HEX_KEY) == snapshot

    def test_missing_store(self, tmp_path, monkeypatch, capsys):
        target = tmp_path / "nope.db"
        assert _run_cli(["encrypt", "--db", str(target)], monkeypatch) == 2
        assert "no store" in capsys.readouterr().err
        assert not target.exists()
        assert _run_cli(["decrypt", "--db", str(target)], monkeypatch) == 2

    def test_malformed_key(self, plain_store, monkeypatch, capsys):
        rc = _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch, "hex:00")
        assert rc == 2
        assert "hex" in capsys.readouterr().err
        assert _backups(plain_store, "encrypt") == []

    def test_key_prompt_when_env_unset(self, plain_store, monkeypatch):
        with patch("getpass.getpass", side_effect=[HEX_KEY, HEX_KEY]) as prompt:
            assert (
                _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch, None) == 0
            )
        assert prompt.call_count == 2
        with patch("getpass.getpass", side_effect=[HEX_KEY]) as prompt:
            assert (
                _run_cli(["decrypt", "--db", str(plain_store)], monkeypatch, None) == 0
            )
        assert prompt.call_count == 1

    def test_key_prompt_mismatch_and_empty(self, plain_store, monkeypatch, capsys):
        with patch("getpass.getpass", side_effect=[HEX_KEY, OTHER_KEY]):
            assert (
                _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch, None) == 2
            )
        assert "do not match" in capsys.readouterr().err
        with patch("getpass.getpass", side_effect=[""]):
            assert (
                _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch, None) == 2
            )
        assert "empty" in capsys.readouterr().err
        with patch("getpass.getpass", side_effect=[""]):
            assert (
                _run_cli(["decrypt", "--db", str(plain_store)], monkeypatch, None) == 2
            )
        assert _backups(plain_store, "encrypt") == []

    def test_namespace_and_default_paths(self, monkeypatch, capsys):
        from mnemo.runtime import db_path_for_namespace

        for namespace in ("default", "team"):
            path = db_path_for_namespace(namespace)
            db = MemoryDB(path, embedding_dims=0)
            db.add(f"{namespace} {MARKER}")
            db.close()

        assert _run_cli(["encrypt", "--namespace", "team"], monkeypatch) == 0
        assert not _scan(db_path_for_namespace("team"))
        assert _scan(db_path_for_namespace("default"))
        assert _run_cli(["encrypt"], monkeypatch) == 0
        assert not _scan(db_path_for_namespace("default"))
        capsys.readouterr()
        assert _run_cli(["encrypt", "--namespace", "../escape"], monkeypatch) == 2
        assert "namespace" in capsys.readouterr().err

    def test_db_and_namespace_are_exclusive(self, tmp_path, monkeypatch):
        with pytest.raises(SystemExit) as exc:
            _run_cli(
                ["encrypt", "--db", str(tmp_path / "x.db"), "--namespace", "team"],
                monkeypatch,
            )
        assert exc.value.code == 2

    def test_store_at_previous_revision_is_migrated_first(
        self, plain_store, monkeypatch
    ):
        conn = sqlite3.connect(plain_store)
        conn.execute("DELETE FROM store_meta WHERE key = ?", (crypto.META_SCHEME,))
        conn.execute("UPDATE alembic_version SET version_num = 'mem_007_confidence'")
        conn.commit()
        conn.close()
        assert _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch) == 0
        assert not _scan(plain_store)
        db = MemoryDB(plain_store, embedding_dims=0, encryption_key=HEX_KEY)
        try:
            assert db._read_alembic_version() == "mem_008_encryption_meta"
        finally:
            db.close()


def _add_graph(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        (memory_id,) = conn.execute("SELECT id FROM memories LIMIT 1").fetchone()
        conn.execute(
            "INSERT INTO memory_entities (id, name, entity_type, created_at,"
            " updated_at) VALUES ('e1', ?, 'person', 'n', 'n')",
            (f"Alice {MARKER}",),
        )
        conn.execute(
            "INSERT INTO memory_entity_links (memory_id, entity_id) VALUES (?, 'e1')",
            (memory_id,),
        )
        conn.commit()
    finally:
        conn.close()


class TestKnowledgeGraph:
    def test_refuses_store_with_graph_rows(self, plain_store, monkeypatch, capsys):
        _add_graph(plain_store)
        assert _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch) == 2
        assert "--drop-graph" in capsys.readouterr().err
        assert _backups(plain_store, "encrypt") == []
        with pytest.raises(GraphDataPresentError):
            store_encryption.encrypt_store(plain_store, HEX_KEY)

    def test_drop_graph(self, plain_store, monkeypatch, capsys):
        _add_graph(plain_store)
        rc = _run_cli(
            ["encrypt", "--db", str(plain_store), "--drop-graph"], monkeypatch
        )
        assert rc == 0
        assert "2 knowledge-graph rows" in capsys.readouterr().out
        assert not _scan(plain_store)
        conn = sqlite3.connect(plain_store)
        try:
            for table in ("memory_entities", "memory_entity_links", "memory_edges"):
                assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
        finally:
            conn.close()


class TestFailureRollsBack:
    def _assert_plain_and_intact(self, path: Path, before: list[dict]) -> None:
        assert _meta(path).get(crypto.META_SCHEME) == crypto.SCHEME_NONE
        assert {"memories_ai", "memories_ad", "memories_au"} <= _triggers(path)
        assert _export(path) == before
        db = MemoryDB(path, embedding_dims=0, encryption_key="")
        try:
            assert MARKER in db.search("alpha")[0]["content"]
        finally:
            db.close()
        assert _leftover_tmp(path) == []

    def test_failure_mid_rewrite_restores_backup(
        self, plain_store, monkeypatch, capsys
    ):
        before = _export(plain_store)
        real_encrypt = crypto.FieldCipher.encrypt
        calls = {"n": 0}

        def flaky(self, row_id, column, value):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("injected failure")
            return real_encrypt(self, row_id, column, value)

        monkeypatch.setattr(crypto.FieldCipher, "encrypt", flaky)
        assert _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch) == 1
        err = capsys.readouterr().err
        assert "injected failure" in err
        assert "restored" in err
        assert calls["n"] == 3
        assert len(_backups(plain_store, "encrypt")) == 1
        self._assert_plain_and_intact(plain_store, before)

    def test_failed_verification_restores_backup(self, plain_store, monkeypatch):
        before = _export(plain_store)

        def broken(*args, **kwargs):
            raise EncryptedDataError("verification failed (injected)")

        monkeypatch.setattr(store_encryption, "_verify_encrypted", broken)
        with pytest.raises(StoreRewriteError, match="injected"):
            store_encryption.encrypt_store(plain_store, HEX_KEY)
        self._assert_plain_and_intact(plain_store, before)

    def test_non_text_value_fails_closed(self, plain_store, monkeypatch, capsys):
        conn = sqlite3.connect(plain_store)
        conn.execute("UPDATE memories SET source = x'0001' WHERE source IS NOT NULL")
        conn.commit()
        conn.close()
        assert _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch) == 1
        assert "source" in capsys.readouterr().err
        assert _meta(plain_store).get(crypto.META_SCHEME) == crypto.SCHEME_NONE

    def test_failed_restore_reports_backup(self, plain_store, monkeypatch):
        def broken_verify(*args, **kwargs):
            raise EncryptedDataError("verification failed (injected)")

        def broken_restore(*args, **kwargs):
            raise OSError("disk gone (injected)")

        monkeypatch.setattr(store_encryption, "_verify_encrypted", broken_verify)
        monkeypatch.setattr(store_encryption, "_restore", broken_restore)
        with pytest.raises(StoreRewriteError) as exc:
            store_encryption.encrypt_store(plain_store, HEX_KEY)
        message = str(exc.value)
        assert "restore failed" in message
        (backup,) = _backups(plain_store, "encrypt")
        assert str(backup) in message

    def test_failed_decrypt_keeps_store_encrypted(self, plain_store, monkeypatch):
        store_encryption.encrypt_store(plain_store, HEX_KEY)
        snapshot = _export(plain_store, HEX_KEY)
        real_decrypt = crypto.FieldCipher.decrypt
        calls = {"n": 0}

        def flaky(self, row_id, column, value):
            calls["n"] += 1
            if calls["n"] == 4:
                raise EncryptedDataError("injected decrypt failure")
            return real_decrypt(self, row_id, column, value)

        monkeypatch.setattr(crypto.FieldCipher, "decrypt", flaky)
        with pytest.raises(StoreRewriteError, match="injected decrypt failure"):
            store_encryption.decrypt_store(plain_store, HEX_KEY)
        monkeypatch.setattr(crypto.FieldCipher, "decrypt", real_decrypt)
        assert _meta(plain_store)[crypto.META_SCHEME] == crypto.SCHEME_AES_GCM_V1
        assert "mnemo_guard_memories_insert" in _triggers(plain_store)
        assert not _scan(plain_store)
        assert _export(plain_store, HEX_KEY) == snapshot

    def test_failed_decrypt_verification(self, plain_store, monkeypatch):
        store_encryption.encrypt_store(plain_store, HEX_KEY)

        def broken(*args, **kwargs):
            raise EncryptedDataError("decrypt verification failed (injected)")

        monkeypatch.setattr(store_encryption, "_verify_decrypted", broken)
        with pytest.raises(StoreRewriteError, match="injected"):
            store_encryption.decrypt_store(plain_store, HEX_KEY)
        assert _meta(plain_store)[crypto.META_SCHEME] == crypto.SCHEME_AES_GCM_V1
        assert not _scan(plain_store)


class TestPreconditions:
    def test_open_store_is_busy(self, plain_store, monkeypatch, capsys):
        holder = MemoryDB(plain_store, embedding_dims=0)
        try:
            with pytest.raises(StoreBusyError):
                store_encryption.encrypt_store(plain_store, HEX_KEY)
            assert _run_cli(["encrypt", "--db", str(plain_store)], monkeypatch) == 2
            assert "stop the mnemo server" in capsys.readouterr().err
        finally:
            holder.close()
        assert _backups(plain_store, "encrypt") == []
        assert _meta(plain_store).get(crypto.META_SCHEME) == crypto.SCHEME_NONE

    def test_result_fields(self, plain_store):
        result = store_encryption.encrypt_store(plain_store, HEX_KEY)
        assert result.action == "encrypted"
        assert result.db_path == plain_store
        assert result.backup_path is not None and result.backup_path.exists()
        assert result.memories == 5
        assert result.archived == 0
        assert result.graph_rows_dropped == 0
        again = store_encryption.encrypt_store(plain_store, HEX_KEY)
        assert again.action == "already-encrypted"
        assert again.backup_path is None
        with pytest.raises(WrongEncryptionKey):
            store_encryption.encrypt_store(plain_store, OTHER_KEY)
        done = store_encryption.decrypt_store(plain_store, HEX_KEY)
        assert done.action == "decrypted"
        assert done.memories == 5
        noop = store_encryption.decrypt_store(plain_store, HEX_KEY)
        assert noop.action == "not-encrypted"

    def test_legacy_archive_rows_are_rewritten(self, plain_store):
        conn = sqlite3.connect(plain_store)
        conn.execute(
            "INSERT INTO archived_memories (id, content, category, tags, source,"
            " importance, created_at, updated_at, access_count, last_accessed,"
            " archived_at) VALUES ('legacy1', ?, 'general', ?, ?, 0.2, 'c', 'u',"
            " 0, 'l', '2026-01-01T00:00:00+00:00')",
            (f"legacy {MARKER}", json.dumps([MARKER]), f"legacy source {MARKER}"),
        )
        conn.commit()
        conn.close()
        result = store_encryption.encrypt_store(plain_store, HEX_KEY)
        assert result.archived == 1
        assert not _scan(plain_store)
        db = MemoryDB(plain_store, embedding_dims=0, encryption_key=HEX_KEY)
        try:
            legacy = [r for r in db.list_archived() if r["id"] == "legacy1"][0]
            assert legacy["content"] == f"legacy {MARKER}"
            assert legacy["tags"] == [MARKER]
            assert db.restore_memory("legacy1") is True
            row = _get(db, "legacy1")
            assert row["content"] == f"legacy {MARKER}"
            assert row["source"] == f"legacy source {MARKER}"
        finally:
            db.close()
        store_encryption.decrypt_store(plain_store, HEX_KEY)
        db = MemoryDB(plain_store, embedding_dims=0, encryption_key="")
        try:
            assert _get(db, "legacy1")["content"] == f"legacy {MARKER}"
        finally:
            db.close()

    def test_decrypt_store_with_legacy_archive_rows(self, plain_store):
        conn = sqlite3.connect(plain_store)
        conn.execute(
            "INSERT INTO archived_memories (id, content, created_at, updated_at,"
            " last_accessed, archived_at) VALUES ('legacy2', ?, 'c', 'u', 'l', 'a')",
            (f"legacy two {MARKER}",),
        )
        conn.commit()
        conn.close()
        store_encryption.encrypt_store(plain_store, HEX_KEY)
        result = store_encryption.decrypt_store(plain_store, HEX_KEY)
        assert result.archived == 1
        conn = sqlite3.connect(plain_store)
        try:
            assert conn.execute(
                "SELECT content FROM archived_memories WHERE id = 'legacy2'"
            ).fetchone() == (f"legacy two {MARKER}",)
        finally:
            conn.close()


def _connect(path: Path, **kwargs: Any) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, **kwargs)
    conn.row_factory = sqlite3.Row
    return conn


class _DamagedCopy(sqlite3.Connection):
    """A connection whose integrity check reports damage."""

    def execute(self, sql: str, *args: Any) -> sqlite3.Cursor:
        if sql == "PRAGMA quick_check":
            return super().execute("SELECT 'page 2 is never used'")
        return super().execute(sql, *args)


class _NoExtensions(sqlite3.Connection):
    """A connection built without extension loading."""

    def enable_load_extension(self, enabled: bool, /) -> None:
        raise sqlite3.OperationalError("not authorized")


class TestVerificationChecks:
    """Each post-rewrite check catches the fault it is there for."""

    @pytest.mark.parametrize(
        ("tamper", "message"),
        [
            (
                "DELETE FROM store_meta WHERE key = 'encryption_salt'",
                "metadata was not recorded",
            ),
            (
                "INSERT INTO memories_fts_docsize (id, sz) VALUES (1, x'00')",
                "full-text index still holds rows",
            ),
            ("FTS", "full-text index triggers are still installed"),
            (
                "DROP TRIGGER mnemo_guard_memories_insert",
                "guard triggers were not installed",
            ),
            ("GRAPH", "knowledge-graph tables still hold rows"),
        ],
        ids=["meta", "fts-rows", "fts-triggers", "guards", "graph"],
    )
    def test_encrypted_store_checks(self, plain_store, tamper, message):
        result = store_encryption.encrypt_store(plain_store, HEX_KEY)
        conn = _connect(plain_store)
        try:
            cipher = crypto.open_store_encryption(
                store_encryption._read_meta(conn), crypto.parse_key(HEX_KEY)
            )
            store_encryption._verify_encrypted(
                conn, cipher, result.memories, result.archived
            )
            if tamper == "FTS":
                store_encryption.install_fts_triggers(conn)
            elif tamper == "GRAPH":
                # Only the guards stop graph inserts; lift them for the test.
                for table in ("memory_entities", "memory_entity_links"):
                    conn.execute(f"DROP TRIGGER mnemo_guard_{table}_insert")
                _add_graph(plain_store)
            else:
                conn.execute(tamper)
            with pytest.raises(EncryptedDataError, match=message):
                store_encryption._verify_encrypted(
                    conn, cipher, result.memories, result.archived
                )
        finally:
            conn.close()

    def test_encrypted_row_count_check(self, plain_store):
        result = store_encryption.encrypt_store(plain_store, HEX_KEY)
        conn = _connect(plain_store)
        try:
            cipher = crypto.open_store_encryption(
                store_encryption._read_meta(conn), crypto.parse_key(HEX_KEY)
            )
            with pytest.raises(EncryptedDataError, match="row counts changed"):
                store_encryption._verify_encrypted(
                    conn, cipher, result.memories + 1, result.archived
                )
        finally:
            conn.close()

    @pytest.mark.parametrize(
        ("tamper", "message"),
        [
            (
                "INSERT INTO store_meta (key, value) VALUES ('encryption_salt', 'AAAA')",
                "metadata was not removed",
            ),
            ("DROP TRIGGER memories_au", "triggers were not reinstalled"),
            (
                "CREATE TRIGGER mnemo_guard_memories_insert BEFORE INSERT ON "
                "memories BEGIN SELECT RAISE(ABORT, 'blocked'); END",
                "guard triggers were not removed",
            ),
            ("DELETE FROM memories_fts_docsize", "index was not rebuilt"),
        ],
        ids=["meta", "fts-triggers", "guards", "fts-rows"],
    )
    def test_decrypted_store_checks(self, plain_store, tamper, message):
        store_encryption.encrypt_store(plain_store, HEX_KEY)
        result = store_encryption.decrypt_store(plain_store, HEX_KEY)
        conn = _connect(plain_store)
        try:
            store_encryption._verify_decrypted(conn, result.memories, result.archived)
            with pytest.raises(EncryptedDataError, match="row counts changed"):
                store_encryption._verify_decrypted(
                    conn, result.memories, result.archived + 1
                )
            conn.execute(tamper)
            with pytest.raises(EncryptedDataError, match=message):
                store_encryption._verify_decrypted(
                    conn, result.memories, result.archived
                )
        finally:
            conn.close()

    def test_integrity_check_failure(self, tmp_path):
        conn = _connect(tmp_path / "damaged.db", factory=_DamagedCopy)
        try:
            with pytest.raises(EncryptedDataError, match="page 2 is never used"):
                store_encryption._quick_check(conn)
        finally:
            conn.close()

    def test_missing_tables_are_skipped(self, tmp_path):
        conn = _connect(tmp_path / "empty.db")
        cipher = crypto.new_store_encryption(crypto.parse_key(HEX_KEY))[1]
        try:
            assert (
                store_encryption._rewrite(conn, "memories", ["content"], cipher.encrypt)
                == 0
            )
            assert (
                store_encryption._decrypt_all(conn, cipher, "memories", ["content"])
                == 0
            )
        finally:
            conn.close()


class TestRewriteGuards:
    def test_scheme_changed_since_prepare(self, plain_store):
        conn = _connect(plain_store)
        try:
            with pytest.raises(EncryptionError, match="changed while the rewrite"):
                store_encryption._require_scheme(
                    conn, plain_store, crypto.SCHEME_AES_GCM_V1
                )
        finally:
            conn.close()

    def test_store_below_current_schema(self, tmp_path):
        path = tmp_path / "old.db"
        conn = _connect(path)
        try:
            conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT)")
            with pytest.raises(StoreRewriteError, match="not at the current schema"):
                store_encryption._require_current_schema(conn, path)
        finally:
            conn.close()

    def test_damaged_backup_is_discarded(self, plain_store, monkeypatch):
        real_connect = sqlite3.connect
        source = _connect(plain_store)

        def connect(database, *args, **kwargs):
            if str(database).endswith(".tmp"):
                kwargs["factory"] = _DamagedCopy
            return real_connect(database, *args, **kwargs)

        monkeypatch.setattr(sqlite3, "connect", connect)
        try:
            with pytest.raises(StoreRewriteError, match="integrity check"):
                store_encryption._write_backup(source, plain_store, "encrypt")
        finally:
            source.close()
        assert _backups(plain_store, "encrypt") == []
        assert _leftover_tmp(plain_store) == []

    def test_store_without_extension_loading(self, tmp_path):
        conn = _connect(tmp_path / "plain.db", factory=_NoExtensions)
        try:
            assert store_encryption._load_vector_extension(conn) is False
        finally:
            conn.close()
