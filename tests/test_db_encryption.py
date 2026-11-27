"""At-rest encryption through the public MemoryDB API.

Covers the roundtrip of every user-data column, fail-closed opens, the
on-disk guarantee (no plaintext in the database file, its WAL or its shared
memory file, and nothing in the FTS5 index), ciphertext swap detection, the
guard triggers that stop plaintext writes, the ``mem_008`` migration, and
keyword plus vector search parity with a plaintext store.

Every key here is an obvious, non-secret test value built at runtime.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mnemo import crypto
from mnemo.db import MEMORY_COLUMNS, MemoryDB
from mnemo.exceptions import (
    EncryptedDataError,
    EncryptionError,
    EncryptionKeyError,
    EncryptionKeyMissing,
    StoreNotEncrypted,
    WrongEncryptionKey,
)
from mnemo.temporal import queries

HEX_KEY = "hex:" + bytes(range(32)).hex()
OTHER_KEY = "hex:" + bytes(range(32, 64)).hex()
MARKER = "zqxplaintextmarker"

_HAS_VEC = hasattr(sqlite3.Connection, "enable_load_extension")


def _open(path: Path, key: str | None = HEX_KEY, **kwargs) -> MemoryDB:
    kwargs.setdefault("embedding_dims", 0)
    return MemoryDB(path, encryption_key=key, **kwargs)


def _get(db: MemoryDB, memory_id: str) -> dict[str, Any]:
    row = db.get(memory_id)
    assert row is not None, memory_id
    return row


@pytest.fixture
def enc_path(tmp_path: Path) -> Path:
    return tmp_path / "enc.db"


@pytest.fixture
def enc_db(enc_path: Path):
    db = _open(enc_path)
    yield db
    db.close()


def _raw(db: MemoryDB, sql: str, params: tuple = ()) -> list[tuple]:
    with db.connection() as conn:
        return [tuple(row) for row in conn.execute(sql, params).fetchall()]


def _sidecar_bytes(path: Path) -> dict[str, bytes]:
    out = {}
    for suffix in ("", "-wal", "-shm"):
        candidate = path.with_name(path.name + suffix)
        if candidate.exists():
            out[suffix or "db"] = candidate.read_bytes()
    return out


# ---------------------------------------------------------------------------
# roundtrip
# ---------------------------------------------------------------------------


class TestRoundtrip:
    def test_store_reports_encrypted(self, enc_db, tmp_db):
        assert enc_db.encrypted is True
        assert tmp_db.encrypted is False
        assert enc_db.get_store_meta(crypto.META_SCHEME) == crypto.SCHEME_AES_GCM_V1
        assert tmp_db.get_store_meta(crypto.META_SCHEME) == crypto.SCHEME_NONE

    def test_add_get_roundtrip(self, enc_db):
        mid = enc_db.add(
            f"remember {MARKER}",
            category="notes",
            tags=["alpha", MARKER],
            source=f"src-{MARKER}",
            subject="alice",
        )
        row = enc_db.get(mid)
        assert row["content"] == f"remember {MARKER}"
        assert json.loads(row["tags"]) == ["alpha", MARKER]
        assert row["source"] == f"src-{MARKER}"
        assert row["subject"] == "alice"
        assert row["category"] == "notes"

        raw = _raw(
            enc_db,
            "SELECT content, tags, source, subject FROM memories WHERE id = ?",
            (mid,),
        )[0]
        for value in raw:
            assert value.startswith(crypto.VALUE_PREFIX)
            assert MARKER not in value

    def test_empty_tags_are_encrypted_too(self, enc_db):
        mid = enc_db.add("no tags here")
        assert enc_db.get(mid)["tags"] == "[]"
        (tags,) = _raw(enc_db, "SELECT tags FROM memories WHERE id = ?", (mid,))[0]
        assert crypto.is_ciphertext(tags)

    def test_add_with_context_type_roundtrip(self, enc_db):
        mid = enc_db.add_with_context_type(
            "dense",
            context_type="fact",
            text_raw=f"original {MARKER}",
            compressed=True,
            compression_provider="chat-cell",
            importance=0.9,
            subject="bob",
        )
        row = enc_db.get(mid)
        assert row["text_raw"] == f"original {MARKER}"
        assert row["context_type"] == "fact"
        assert row["importance"] == 0.9
        (text_raw,) = _raw(
            enc_db, "SELECT text_raw FROM memories WHERE id = ?", (mid,)
        )[0]
        assert crypto.is_ciphertext(text_raw)

    def test_add_with_context_type_without_importance(self, enc_db):
        mid = enc_db.add_with_context_type("plain capture", source="s")
        assert enc_db.get(mid)["source"] == "s"

    def test_list_memories_decrypts(self, enc_db):
        enc_db.add("first", category="a")
        enc_db.add("second", category="b")
        assert {m["content"] for m in enc_db.list_memories()} == {"first", "second"}
        assert [m["content"] for m in enc_db.list_memories(category="a")] == ["first"]

    def test_get_subject_scope(self, enc_db):
        mid = enc_db.add("scoped", subject="alice")
        assert enc_db.get(mid, subject="alice")["content"] == "scoped"
        assert enc_db.get(mid, subject="bob") is None
        assert enc_db.get("missing") is None

    def test_update_reencrypts_under_new_id(self, enc_db):
        mid = enc_db.add("old text", tags=["t"], source="s", subject="alice")
        new_id = enc_db.update(mid, content=f"new {MARKER}", tags=["u"])
        assert new_id and new_id != mid
        row = enc_db.get(new_id)
        assert row["content"] == f"new {MARKER}"
        assert json.loads(row["tags"]) == ["u"]
        assert row["source"] == "s"
        assert row["subject"] == "alice"
        assert enc_db.get(mid) is None
        # The superseded row still decrypts under its own id.
        history = {
            r["id"]: r for r in queries.memories_as_of(enc_db, "9999-01-01T00:00:00")
        }
        assert new_id in history
        assert enc_db.update("missing", content="x") is None

    def test_update_keeps_fields_when_not_overridden(self, enc_db):
        mid = enc_db.add("keep me", tags=["k"], subject="carol")
        new_id = enc_db.update(mid, importance=0.8)
        row = enc_db.get(new_id)
        assert row["content"] == "keep me"
        assert json.loads(row["tags"]) == ["k"]
        assert row["importance"] == 0.8

    def test_delete_with_subject(self, enc_db):
        mid = enc_db.add("to delete", subject="alice")
        assert enc_db.delete(mid, subject="bob") is False
        assert enc_db.get(mid) is not None
        assert enc_db.delete(mid, subject="alice") is True
        assert enc_db.get(mid) is None
        assert enc_db.delete(mid) is False

    def test_delete_without_subject(self, enc_db):
        mid = enc_db.add("to delete")
        assert enc_db.delete(mid) is True

    def test_soft_archive_list_archived_restore(self, enc_db):
        mid = enc_db.add(f"archive {MARKER}", tags=["arch"], subject="alice")
        assert enc_db.soft_archive(mid, subject="bob") is False
        assert enc_db.soft_archive(mid, subject="alice") is True
        assert enc_db.soft_archive(mid) is False
        archived = enc_db.list_archived()
        assert archived == [
            {
                "id": mid,
                "content": f"archive {MARKER}",
                "category": "general",
                "tags": ["arch"],
                "importance": 0.5,
                "archived_at": archived[0]["archived_at"],
            }
        ]
        assert enc_db.restore_memory(mid) is True
        assert enc_db.get(mid)["content"] == f"archive {MARKER}"

    def test_soft_archive_without_subject(self, enc_db):
        mid = enc_db.add("archive me")
        assert enc_db.soft_archive(mid) is True

    def test_set_compressed(self, enc_db, tmp_db):
        for db in (enc_db, tmp_db):
            mid = db.add("long original text")
            assert db.set_compressed(mid, "dense", "long original text", "chat-cell")
            row = db.get(mid)
            assert row["content"] == "dense"
            assert row["text_raw"] == "long original text"
            assert row["compressed"] == 1
            assert row["compression_provider"] == "chat-cell"
            assert db.set_compressed("missing", "a", "b", "chat-cell") is False

    def test_export_import_roundtrip(self, enc_db, tmp_path):
        enc_db.add(f"exported {MARKER}", tags=["x", "y"], source="s", subject="alice")
        enc_db.add("second row")
        jsonl, count = enc_db.export_jsonl()
        assert count == 2
        records = [json.loads(line) for line in jsonl.splitlines()]
        assert [list(r) for r in records] == [list(MEMORY_COLUMNS)] * 2
        assert records[0]["content"] == f"exported {MARKER}"
        assert records[0]["tags"] == ["x", "y"]
        assert records[0]["subject"] == "alice"
        assert not any(crypto.VALUE_PREFIX in line for line in jsonl.splitlines())

        other = _open(tmp_path / "other.db", OTHER_KEY)
        try:
            stats = other.import_jsonl(jsonl)
            assert stats == {"imported": 2, "skipped": 0, "rejected": 0}
            row = _get(other, records[0]["id"])
            assert row["content"] == f"exported {MARKER}"
            assert json.loads(row["tags"]) == ["x", "y"]
            assert other.import_jsonl(jsonl) == {
                "imported": 0,
                "skipped": 2,
                "rejected": 0,
            }
            assert other.import_jsonl(jsonl, mode="replace")["imported"] == 2
        finally:
            other.close()

    def test_export_matches_plaintext_shape(self, enc_db, tmp_db):
        for db in (enc_db, tmp_db):
            db.import_jsonl(
                [
                    {
                        "id": "fixed-id",
                        "content": "Ghi nhớ: cà phê đen",
                        "tags": ["vi", "đ"],
                        "source": "s",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                        "last_accessed": "2026-01-01T00:00:00+00:00",
                    }
                ]
            )
        enc_jsonl, _ = enc_db.export_jsonl()
        plain_jsonl, _ = tmp_db.export_jsonl()
        assert json.loads(enc_jsonl) == json.loads(plain_jsonl)

    def test_import_rejects_non_text_sensitive_values(self, enc_db):
        stats = enc_db.import_jsonl([{"content": "ok", "source": 5}])
        assert stats == {"imported": 0, "skipped": 0, "rejected": 1}

    def test_tags_given_as_json_text_are_kept(self, enc_db):
        enc_db.import_jsonl([{"id": "j1", "content": "c", "tags": '["a"]'}])
        assert json.loads(enc_db.get("j1")["tags"]) == ["a"]

    def test_backfill_encrypts_commit_sha(self, enc_db):
        mid = enc_db.add("hash me")
        with enc_db.connection() as conn:
            conn.execute("UPDATE memories SET commit_sha = NULL, valid_from = NULL")
        enc_db._backfill_phase3_temporal()
        row = enc_db.get(mid)
        assert row["commit_sha"] == hashlib.sha256(b"hash me").hexdigest()
        (sha,) = _raw(enc_db, "SELECT commit_sha FROM memories WHERE id = ?", (mid,))[0]
        assert crypto.is_ciphertext(sha)

    def test_metadata_writes_still_work(self, enc_db):
        mid = enc_db.add("meta")
        assert enc_db.update_importance(mid, 0.7) is True
        assert enc_db.set_confidence(mid, 0.4) is True
        assert enc_db.archive_old_memories(days=0, importance_threshold=1.0) >= 0
        assert enc_db.stats()["total_memories"] == 1

    def test_check_duplicate_and_contradictions_use_decrypted_text(self, enc_db):
        enc_db.add("user prefers dark roast coffee")
        dup = enc_db.check_duplicate("user prefers dark roast coffee")
        assert dup and dup["existing_content"] == "user prefers dark roast coffee"
        found = enc_db.detect_contradictions("user never prefers dark roast coffee")
        assert found and found[0]["content"] == "user prefers dark roast coffee"


# ---------------------------------------------------------------------------
# fail closed
# ---------------------------------------------------------------------------


def _seed(path: Path) -> str:
    db = _open(path)
    try:
        return db.add(f"keep {MARKER}", subject="alice")
    finally:
        db.close()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestFailClosed:
    def test_missing_key_refuses_to_open(self, enc_path, monkeypatch):
        mid = _seed(enc_path)
        before = _digest(enc_path)
        monkeypatch.delenv(crypto.ENCRYPTION_KEY_ENV, raising=False)
        with pytest.raises(EncryptionKeyMissing, match=crypto.ENCRYPTION_KEY_ENV):
            MemoryDB(enc_path, embedding_dims=0)
        with pytest.raises(EncryptionKeyMissing):
            _open(enc_path, "")
        assert _digest(enc_path) == before
        db = _open(enc_path)
        try:
            assert _get(db, mid)["content"] == f"keep {MARKER}"
        finally:
            db.close()

    def test_wrong_key_refuses_to_open(self, enc_path):
        mid = _seed(enc_path)
        before = _digest(enc_path)
        with pytest.raises(WrongEncryptionKey):
            _open(enc_path, OTHER_KEY)
        with pytest.raises(WrongEncryptionKey):
            _open(enc_path, "a passphrase that is wrong")
        assert _digest(enc_path) == before
        db = _open(enc_path)
        try:
            assert _get(db, mid)["content"] == f"keep {MARKER}"
        finally:
            db.close()

    def test_key_from_environment(self, enc_path, monkeypatch):
        monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV, HEX_KEY)
        db = MemoryDB(enc_path, embedding_dims=0)
        try:
            assert db.encrypted
            mid = db.add("env keyed")
        finally:
            db.close()
        reopened = _open(enc_path)
        try:
            assert _get(reopened, mid)["content"] == "env keyed"
        finally:
            reopened.close()

    def test_malformed_key_never_creates_a_store(self, tmp_path):
        target = tmp_path / "never.db"
        with pytest.raises(EncryptionKeyError):
            _open(target, "hex:zz")
        assert not target.exists()

    def test_plaintext_store_with_data_refuses_a_key(self, tmp_path):
        path = tmp_path / "plain.db"
        plain = MemoryDB(path, embedding_dims=0)
        mid = plain.add("plain data")
        plain.close()
        with pytest.raises(StoreNotEncrypted, match="mnemo encrypt"):
            _open(path)
        again = MemoryDB(path, embedding_dims=0)
        try:
            assert _get(again, mid)["content"] == "plain data"
            assert not again.encrypted
        finally:
            again.close()

    def test_empty_plaintext_store_becomes_encrypted(self, tmp_path):
        path = tmp_path / "empty.db"
        MemoryDB(path, embedding_dims=0).close()
        db = _open(path)
        try:
            assert db.encrypted
            mid = db.add("now encrypted")
        finally:
            db.close()
        reopened = _open(path)
        try:
            assert _get(reopened, mid)["content"] == "now encrypted"
        finally:
            reopened.close()

    def test_unknown_scheme_refuses_to_open(self, enc_path):
        _seed(enc_path)
        conn = sqlite3.connect(enc_path)
        conn.execute(
            "UPDATE store_meta SET value = 'rot13' WHERE key = ?",
            (crypto.META_SCHEME,),
        )
        conn.commit()
        conn.close()
        with pytest.raises(EncryptionError, match="rot13"):
            _open(enc_path)
        with pytest.raises(EncryptionError, match="rot13"):
            _open(enc_path, "")

    def test_missing_encryption_meta_refuses_to_open(self, enc_path):
        _seed(enc_path)
        conn = sqlite3.connect(enc_path)
        conn.execute("DELETE FROM store_meta WHERE key = ?", (crypto.META_SALT,))
        conn.commit()
        conn.close()
        with pytest.raises(EncryptedDataError):
            _open(enc_path)

    @pytest.mark.parametrize(
        ("tamper", "reason"),
        [
            (
                "INSERT INTO store_meta (key, value) VALUES ('encryption_salt', 'AAAA')",
                "encryption metadata \\(encryption_salt\\)",
            ),
            (
                "CREATE TRIGGER mnemo_guard_memories_insert BEFORE INSERT ON memories "
                "BEGIN SELECT RAISE(ABORT, 'blocked'); END",
                "encryption guard triggers",
            ),
            (
                "UPDATE memories SET content = 'enc:v1:AAAA'",
                "encrypted memory rows",
            ),
        ],
        ids=["meta", "guards", "rows"],
    )
    def test_plaintext_store_with_encrypted_leftovers_refuses_to_open(
        self, tmp_path, tamper, reason
    ):
        path = tmp_path / "plain.db"
        plain = MemoryDB(path, embedding_dims=0)
        plain.add("plain data")
        plain.close()
        conn = sqlite3.connect(path)
        conn.execute(tamper)
        conn.commit()
        conn.close()
        with pytest.raises(EncryptedDataError, match=f"still holds {reason}"):
            MemoryDB(path, embedding_dims=0)
        with pytest.raises(EncryptedDataError, match=f"still holds {reason}"):
            _open(path)

    def test_row_swap_is_detected(self, enc_db):
        first = enc_db.add("first secret")
        second = enc_db.add("second secret")
        conn = sqlite3.connect(enc_db._db_path)
        try:
            (c1,) = conn.execute(
                "SELECT content FROM memories WHERE id = ?", (first,)
            ).fetchone()
            conn.execute("DROP TRIGGER IF EXISTS mnemo_guard_memories_update")
            conn.execute("UPDATE memories SET content = ? WHERE id = ?", (c1, second))
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(EncryptedDataError, match=second):
            enc_db.get(second)
        assert enc_db.get(first)["content"] == "first secret"

    def test_column_swap_is_detected(self, enc_db):
        mid = enc_db.add("content value", source="source value")
        with enc_db.connection() as conn:
            conn.execute("UPDATE memories SET source = content WHERE id = ?", (mid,))
        with pytest.raises(EncryptedDataError, match="source"):
            enc_db.get(mid)

    def test_guards_block_plaintext_writes(self, enc_db):
        mid = enc_db.add("guarded")
        conn = sqlite3.connect(enc_db._db_path)
        try:
            with pytest.raises(sqlite3.IntegrityError, match="encrypted"):
                conn.execute(
                    "INSERT INTO memories (id, content, category, tags, created_at,"
                    " updated_at, last_accessed) VALUES ('x', 'plain', 'g', '[]',"
                    " 'n', 'n', 'n')"
                )
            with pytest.raises(sqlite3.IntegrityError, match="encrypted"):
                conn.execute(
                    "UPDATE memories SET content = 'plain' WHERE id = ?", (mid,)
                )
            with pytest.raises(sqlite3.IntegrityError, match="encrypted"):
                conn.execute(
                    "INSERT INTO memory_entities (id, name, entity_type, created_at,"
                    " updated_at) VALUES ('e', 'Alice', 'person', 'n', 'n')"
                )
            with pytest.raises(sqlite3.IntegrityError, match="encrypted"):
                conn.execute(
                    "INSERT INTO archived_memories (id, content, created_at,"
                    " updated_at, last_accessed, archived_at)"
                    " VALUES ('a', 'plain', 'n', 'n', 'n', 'n')"
                )
            # Metadata-only writes stay allowed.
            conn.execute("UPDATE memories SET importance = 0.1 WHERE id = ?", (mid,))
            conn.commit()
        finally:
            conn.close()
        assert enc_db.get(mid)["content"] == "guarded"

    def test_guards_are_reinstalled_on_open(self, enc_path):
        _seed(enc_path)
        conn = sqlite3.connect(enc_path)
        conn.execute("DROP TRIGGER mnemo_guard_memories_insert")
        conn.commit()
        conn.close()
        _open(enc_path).close()
        conn = sqlite3.connect(enc_path)
        try:
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                )
            }
        finally:
            conn.close()
        assert "mnemo_guard_memories_insert" in names
        assert not names & {"memories_ai", "memories_ad", "memories_au"}

    def test_fts_triggers_recreated_by_old_code_are_dropped(self, enc_path):
        _seed(enc_path)
        conn = sqlite3.connect(enc_path)
        conn.execute(
            "CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN "
            "INSERT INTO memories_fts(rowid, id, content, tags) "
            "VALUES (new.rowid, new.id, new.content, new.tags); END"
        )
        conn.commit()
        conn.close()
        db = _open(enc_path)
        try:
            db.add(f"after {MARKER}")
            assert _raw(db, "SELECT count(*) FROM memories_fts_docsize") == [(0,)]
        finally:
            db.close()


# ---------------------------------------------------------------------------
# no plaintext on disk
# ---------------------------------------------------------------------------


class TestNoPlaintextOnDisk:
    def _populate(self, db: MemoryDB) -> None:
        a = db.add(
            f"content {MARKER}",
            tags=[MARKER],
            source=f"source {MARKER}",
            subject=f"subject{MARKER}",
        )
        db.add_with_context_type(
            "dense", text_raw=f"raw {MARKER}", compressed=True, compression_provider="p"
        )
        b = db.update(a, content=f"updated {MARKER}")
        assert b is not None
        db.soft_archive(b)
        db.import_jsonl([{"content": f"imported {MARKER}", "tags": [MARKER]}])

    def test_database_wal_and_shm_hold_no_plaintext(self, enc_db):
        self._populate(enc_db)
        marker = MARKER.encode()
        for name, blob in _sidecar_bytes(enc_db._db_path).items():
            assert marker not in blob, name
        with enc_db.connection() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for name, blob in _sidecar_bytes(enc_db._db_path).items():
            assert marker not in blob, name
        enc_db.close()
        for name, blob in _sidecar_bytes(enc_db._db_path).items():
            assert marker not in blob, name

    def test_fts_index_holds_nothing(self, enc_db):
        self._populate(enc_db)
        assert _raw(enc_db, "SELECT count(*) FROM memories_fts_docsize") == [(0,)]
        assert _raw(
            enc_db,
            "SELECT count(*) FROM memories_fts WHERE memories_fts MATCH ?",
            (MARKER,),
        ) == [(0,)]


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

CORPUS = [
    ("alpha project uses sqlite for storage", "tech", ["db"], "alice"),
    ("beta project prefers postgres database", "tech", ["db", "infra"], "bob"),
    ("coffee preference is black coffee every morning", "personal", ["food"], "alice"),
    ("Project alpha deadline is friday", "work", ["work"], "alice"),
    ("Ghi nhớ: người dùng thích cà phê đen", "personal", ["vi"], None),
]


def _fill(db: MemoryDB, embeddings: list[list[float]] | None = None) -> dict[str, str]:
    # Every store gets the same ids. Ranking breaks ties by row order, and the
    # row order of an ``IN (...)`` lookup follows the id index, so random ids
    # would make the plaintext and the encrypted store disagree by chance.
    counter = itertools.count(1)
    ids = {}
    with patch("mnemo.db.uuid.uuid4", side_effect=lambda: uuid.UUID(int=next(counter))):
        for index, (content, category, tags, subject) in enumerate(CORPUS):
            ids[content] = db.add(
                content,
                category=category,
                tags=tags,
                subject=subject,
                embedding=embeddings[index] if embeddings else None,
            )
    return ids


@pytest.fixture
def search_pair(tmp_path):
    plain = MemoryDB(tmp_path / "plain.db", embedding_dims=0)
    enc = _open(tmp_path / "enc-search.db")
    _fill(plain)
    _fill(enc)
    yield plain, enc
    plain.close()
    enc.close()


UNFILTERED_QUERIES = {
    "alpha": [CORPUS[0][0], CORPUS[3][0]],
    "proj": [CORPUS[0][0], CORPUS[1][0], CORPUS[3][0]],
    "alpha project": [CORPUS[0][0]],
    "postgres sqlite": [CORPUS[0][0], CORPUS[1][0]],
    "coffee": [CORPUS[2][0]],
    "db": [CORPUS[0][0], CORPUS[1][0]],
    "cà phê": [CORPUS[4][0]],
    "ca phe": [CORPUS[4][0]],
    "zebra": [],
    "": [],
    "!!!": [],
}


class TestEncryptedKeywordSearch:
    @pytest.mark.parametrize("query", list(UNFILTERED_QUERIES))
    def test_matches_plaintext_fts(self, search_pair, query):
        plain, enc = search_pair
        plain_hits = plain.search(query, limit=10)
        enc_hits = enc.search(query, limit=10)
        assert {r["content"] for r in enc_hits} == set(UNFILTERED_QUERIES[query])
        assert [r["content"] for r in enc_hits] == [r["content"] for r in plain_hits]
        for a, b in zip(plain_hits, enc_hits, strict=True):
            assert set(a) == set(b)

    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            ({"category": "tech"}, {CORPUS[0][0], CORPUS[1][0]}),
            ({"subject": "alice"}, {CORPUS[0][0], CORPUS[3][0]}),
            ({"tags": ["infra"]}, {CORPUS[1][0]}),
            ({"tags": ["db"], "subject": "alice"}, {CORPUS[0][0]}),
            ({"tags": ["nope"]}, set()),
        ],
    )
    def test_filters_match_plaintext(self, search_pair, kwargs, expected):
        plain, enc = search_pair
        enc_hits = {r["content"] for r in enc.search("project", limit=10, **kwargs)}
        plain_hits = {r["content"] for r in plain.search("project", limit=10, **kwargs)}
        assert enc_hits == plain_hits == expected

    def test_archived_and_superseded_rows_are_hidden(self, search_pair):
        _, enc = search_pair
        hits = enc.search("alpha", limit=10)
        enc.soft_archive(hits[0]["id"])
        assert len(enc.search("alpha", limit=10)) == 1
        assert len(enc.search("alpha", limit=10, include_archived=True)) == 2
        remaining = enc.search("alpha", limit=10)[0]["id"]
        enc.update(remaining, content="gamma replaced")
        assert enc.search("alpha", limit=10) == []

    def test_search_updates_access_stats(self, search_pair):
        _, enc = search_pair
        hit = enc.search("coffee", limit=1)[0]
        assert enc.get(hit["id"])["access_count"] == 1

    def test_candidate_pool_window(self, search_pair):
        _, enc = search_pair
        assert len(enc.search("proj", limit=1, candidate_pool=50)) == 3

    def test_too_many_tags_rejected(self, search_pair):
        _, enc = search_pair
        with pytest.raises(ValueError, match="tags"):
            enc.search("x", tags=[str(i) for i in range(51)])

    def test_tag_filter_handles_odd_tag_json(self, enc_db):
        enc_db.import_jsonl(
            [
                {"id": "obj", "content": "project obj", "tags": '{"k": "db"}'},
                {"id": "scalar", "content": "project scalar", "tags": '"db"'},
                {"id": "bad", "content": "project bad", "tags": "not json"},
            ]
        )
        hits = {r["id"] for r in enc_db.search("project", tags=["db"], limit=10)}
        assert hits == {"obj", "scalar"}


EMBEDDINGS = [
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 0.0, 1.0],
    [0.9, 0.1, 0.0],
    [0.0, 0.1, 0.9],
]


@pytest.mark.skipif(not _HAS_VEC, reason="sqlite extension loading unavailable")
class TestEncryptedVectorSearch:
    @pytest.fixture
    def vec_pair(self, tmp_path):
        plain = MemoryDB(tmp_path / "plain-vec.db", embedding_dims=3)
        enc = _open(tmp_path / "enc-vec.db", embedding_dims=3)
        _fill(plain, EMBEDDINGS)
        _fill(enc, EMBEDDINGS)
        yield plain, enc
        plain.close()
        enc.close()

    def test_vector_only_recall(self, vec_pair):
        plain, enc = vec_pair
        enc_hits = enc.search("nomatchword", embedding=[1.0, 0.0, 0.0], limit=2)
        plain_hits = plain.search("nomatchword", embedding=[1.0, 0.0, 0.0], limit=2)
        assert [r["content"] for r in enc_hits] == [r["content"] for r in plain_hits]
        assert enc_hits[0]["content"] == CORPUS[0][0]
        assert set(enc_hits[0]) == set(plain_hits[0])

    def test_vector_recall_respects_subject_and_tags(self, vec_pair):
        plain, enc = vec_pair
        for kwargs in ({"subject": "bob"}, {"tags": ["vi"]}, {"category": "work"}):
            enc_hits = {
                r["content"]
                for r in enc.search("nomatch", embedding=[1.0, 0.0, 0.0], **kwargs)
            }
            plain_hits = {
                r["content"]
                for r in plain.search("nomatch", embedding=[1.0, 0.0, 0.0], **kwargs)
            }
            assert enc_hits == plain_hits
            assert len(enc_hits) == 1

    def test_hybrid_recall(self, vec_pair):
        _, enc = vec_pair
        hits = {
            r["content"]
            for r in enc.search("postgres", embedding=[0.0, 0.0, 1.0], limit=5)
        }
        assert CORPUS[1][0] in hits and CORPUS[2][0] in hits

    def test_rows_without_vectors_and_write_vector(self, tmp_path):
        db = _open(tmp_path / "backfill.db", embedding_dims=3)
        try:
            mid = db.add(f"needs vector {MARKER}")
            rows = db.rows_without_vectors(5)
            assert rows == [{"id": mid, "content": f"needs vector {MARKER}"}]
            db.write_vector(mid, [0.1, 0.2, 0.3])
            assert db.rows_without_vectors(5) == []
        finally:
            db.close()

    def test_update_carries_vector(self, vec_pair):
        _, enc = vec_pair
        (target,) = enc.search("postgres", limit=1)
        assert target["content"] == CORPUS[1][0]
        new_id = enc.update(target["id"], content="beta replaced text")
        # Every live row, the new version included, still has a vector.
        assert enc.rows_without_vectors(10) == []
        hits = {
            r["id"]: r["content"]
            for r in enc.search("nomatch", embedding=[0.0, 1.0, 0.0], limit=5)
        }
        assert hits[new_id] == "beta replaced text"
        assert target["id"] not in hits


# ---------------------------------------------------------------------------
# temporal queries
# ---------------------------------------------------------------------------


class TestTemporalQueries:
    def test_memories_as_of_decrypts(self, enc_db):
        enc_db.add(f"now {MARKER}")
        assert [r["content"] for r in queries.memories_as_of(enc_db)] == [
            f"now {MARKER}"
        ]

    def test_build_timeline_filters_after_decryption(self, enc_db):
        for index in range(3):
            enc_db.add(f"alice note {index}", subject="alice")
            enc_db.add(f"bob coffee {index}", subject="bob")
        alice = queries.build_timeline(enc_db, subject="alice", limit=2)
        assert [r["content"] for r in alice] == ["alice note 0", "alice note 1"]
        assert all(r["timeline_state"] == "active" for r in alice)
        coffee = queries.build_timeline(enc_db, entity="COFFEE", limit=10)
        assert [r["content"] for r in coffee] == [f"bob coffee {i}" for i in range(3)]
        none = queries.build_timeline(enc_db, subject="alice", entity="coffee")
        assert none == []

    def test_graph_queries_are_empty(self, enc_db):
        enc_db.add("Alice works on mnemo")
        assert queries.entity_search(enc_db, name="Alice") == []
        assert queries.history_for_entity(enc_db, "any") == []


# ---------------------------------------------------------------------------
# migration
# ---------------------------------------------------------------------------


def _alembic_cfg(db_path: Path):
    from alembic.config import Config

    from mnemo.db import _ALEMBIC_INI_PATH, _ALEMBIC_SCRIPT_LOCATION

    cfg = Config(str(_ALEMBIC_INI_PATH))
    cfg.set_main_option("script_location", str(_ALEMBIC_SCRIPT_LOCATION))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.resolve().as_posix()}")
    return cfg


class TestMigration:
    def test_head_is_mem_008(self):
        from alembic.script import ScriptDirectory

        cfg = _alembic_cfg(Path("unused.db"))
        assert (
            ScriptDirectory.from_config(cfg).get_current_head()
            == "mem_008_encryption_meta"
        )

    def test_existing_plaintext_db_migrates(self, tmp_path):
        path = tmp_path / "legacy.db"
        db = MemoryDB(path, embedding_dims=0)
        mid = db.add("legacy row")
        db.close()
        # Rewind the store to the previous head, as written by an older release.
        conn = sqlite3.connect(path)
        conn.execute("DELETE FROM store_meta WHERE key = ?", (crypto.META_SCHEME,))
        conn.execute("UPDATE alembic_version SET version_num = 'mem_007_confidence'")
        conn.commit()
        conn.close()

        db = MemoryDB(path, embedding_dims=0)
        try:
            assert db.get_store_meta(crypto.META_SCHEME) == crypto.SCHEME_NONE
            assert db._read_alembic_version() == "mem_008_encryption_meta"
            assert _get(db, mid)["content"] == "legacy row"
            assert db.search("legacy")[0]["id"] == mid
        finally:
            db.close()
        assert list(tmp_path.glob("legacy.db.bak.*"))

    def test_downgrade_removes_flag_on_plaintext_store(self, tmp_path):
        from alembic import command

        path = tmp_path / "down.db"
        MemoryDB(path, embedding_dims=0).close()
        command.downgrade(_alembic_cfg(path), "mem_007_confidence")
        conn = sqlite3.connect(path)
        try:
            assert (
                conn.execute(
                    "SELECT value FROM store_meta WHERE key = ?", (crypto.META_SCHEME,)
                ).fetchone()
                is None
            )
        finally:
            conn.close()

    def test_downgrade_refuses_encrypted_store(self, enc_path):
        from alembic import command

        _seed(enc_path)
        with pytest.raises(RuntimeError, match="mnemo decrypt"):
            command.downgrade(_alembic_cfg(enc_path), "mem_007_confidence")
