"""Encrypt or decrypt an existing store in place, offline.

``n24q02m-mnemo encrypt`` and ``n24q02m-mnemo decrypt`` call
:func:`encrypt_store` and :func:`decrypt_store`. Opening a store never
converts it (see ``MemoryDB``), so this module is the only way to turn a
plaintext store with data into an encrypted one, or back.

Every rewrite follows the same steps:

1. Open the store once through ``MemoryDB`` so it is migrated to the current
   schema, and check the key against it.
2. Take an exclusive lock. A store that another process (the server) has
   open is refused, never rewritten under it.
3. Write a self-contained backup next to the store: a consistent copy taken
   through the SQLite backup API, switched to rollback-journal mode so it is
   one file, integrity-checked, flushed to disk, and only then renamed to its
   final ``<store>.<encrypt|decrypt>-<UTC time>.bak`` name.
4. Rewrite every row in one transaction.
5. Verify the result. When the rewrite or the verification fails, the
   backup is copied back into the store under the same lock.

After an encrypt, ``VACUUM`` and a truncating WAL checkpoint remove the
plaintext that freed pages and the write-ahead log would otherwise keep. The
backup written by encrypt holds that plaintext by design; the command tells
the operator to delete it securely once the store has been checked.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from mnemo import crypto
from mnemo.db import (
    ENCRYPTED_ARCHIVE_COLUMNS,
    ENCRYPTED_MEMORY_COLUMNS,
    FTS_TRIGGER_NAMES,
    GRAPH_TABLES,
    GUARD_TRIGGER_PREFIX,
    LEGACY_GRAPH_TABLES,
    MEMORY_COLUMNS,
    MemoryDB,
    drop_encryption_guards,
    drop_fts_triggers,
    install_encryption_guards,
    install_fts_triggers,
    table_exists,
)
from mnemo.exceptions import (
    EncryptedDataError,
    EncryptionError,
    EncryptionKeyMissing,
    GraphDataPresentError,
    StoreBusyError,
    StoreRewriteError,
)

# How long to wait for other connections to let go of the store before
# reporting it busy.
LOCK_TIMEOUT_MS = 2000

# Rows rewritten per SELECT, so memory use does not grow with the store.
_BATCH_ROWS = 500

# Entity-name embeddings. Cleared with the rest of the knowledge graph when
# the operator asks for it; needs the sqlite-vec extension to be loadable.
_ENTITY_VECTOR_TABLE = "memory_entities_vec"

Transform = Callable[[str, str, Any], str | None]


@dataclass(frozen=True, slots=True)
class RewriteResult:
    """Outcome of :func:`encrypt_store` or :func:`decrypt_store`.

    ``action`` is ``"encrypted"``, ``"decrypted"``, ``"already-encrypted"``
    or ``"not-encrypted"``. The counts are rows rewritten (zero when nothing
    was done) and ``backup_path`` is ``None`` when nothing was done.
    """

    action: str
    db_path: Path
    backup_path: Path | None
    memories: int
    archived: int
    graph_rows_dropped: int


def encrypt_store(
    db_path: Path, key_str: str, *, drop_graph: bool = False
) -> RewriteResult:
    """Encrypt a plaintext store in place.

    Args:
        db_path: The store's SQLite file.
        key_str: Key setting, in the ``MNEMO_ENCRYPTION_KEY`` format.
        drop_graph: Delete knowledge-graph rows instead of refusing. Entity
            names and relations are not encrypted, so an encrypted store
            keeps the graph empty.

    Raises:
        FileNotFoundError: No store exists at ``db_path``.
        EncryptionKeyError: ``key_str`` is malformed.
        WrongEncryptionKey: The store is already encrypted with another key.
        StoreBusyError: Another process has the store open.
        GraphDataPresentError: The store holds knowledge-graph rows and
            ``drop_graph`` is False. Nothing is changed.
        StoreRewriteError: The rewrite or its verification failed. The
            message says whether the backup was restored.
    """
    key = crypto.parse_key(key_str)
    _require_store(db_path)
    if _prepare(db_path, key_str):
        return RewriteResult("already-encrypted", db_path, None, 0, 0, 0)

    conn = _lock_store(db_path)
    try:
        _require_scheme(conn, db_path, crypto.SCHEME_NONE)
        _require_current_schema(conn, db_path)
        graph_rows = _count_graph_rows(conn)
        if graph_rows and not drop_graph:
            raise GraphDataPresentError(
                f"{db_path} holds {graph_rows} knowledge-graph rows (entity names "
                "and relations), which at-rest encryption does not cover; rerun "
                "with --drop-graph to delete them, or keep the store unencrypted"
            )
        backup = _write_backup(conn, db_path, "encrypt")
        meta, cipher = crypto.new_store_encryption(key)
        try:
            conn.execute("BEGIN IMMEDIATE")
            drop_fts_triggers(conn)
            drop_encryption_guards(conn)
            memories = _rewrite(
                conn, "memories", ENCRYPTED_MEMORY_COLUMNS, cipher.encrypt
            )
            archived = _rewrite(
                conn, "archived_memories", ENCRYPTED_ARCHIVE_COLUMNS, cipher.encrypt
            )
            dropped = _drop_graph_rows(conn) if graph_rows else 0
            conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('delete-all')")
            for name, value in meta.items():
                conn.execute(
                    "INSERT OR REPLACE INTO store_meta (key, value) VALUES (?, ?)",
                    (name, value),
                )
            install_encryption_guards(conn)
            conn.execute("COMMIT")
            # Freed pages and the WAL still hold the old plaintext.
            conn.execute("VACUUM")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            _verify_encrypted(conn, cipher, memories, archived)
        except Exception as exc:
            _fail(conn, db_path, backup, "encrypt", exc)
    finally:
        conn.close()
    return RewriteResult("encrypted", db_path, backup, memories, archived, dropped)


def decrypt_store(db_path: Path, key_str: str) -> RewriteResult:
    """Decrypt an encrypted store in place, back to plaintext.

    Raises the same errors as :func:`encrypt_store`, except that a wrong key
    is always an error here, since there is nothing to decrypt without it.
    """
    key = crypto.parse_key(key_str)
    _require_store(db_path)
    if not _prepare(db_path, key_str):
        return RewriteResult("not-encrypted", db_path, None, 0, 0, 0)

    conn = _lock_store(db_path)
    try:
        meta = _require_scheme(conn, db_path, crypto.SCHEME_AES_GCM_V1)
        cipher = crypto.open_store_encryption(meta, key)
        backup = _write_backup(conn, db_path, "decrypt")
        try:
            conn.execute("BEGIN IMMEDIATE")
            drop_encryption_guards(conn)
            memories = _rewrite(
                conn, "memories", ENCRYPTED_MEMORY_COLUMNS, cipher.decrypt
            )
            archived = _rewrite(
                conn, "archived_memories", ENCRYPTED_ARCHIVE_COLUMNS, cipher.decrypt
            )
            placeholders = ", ".join("?" for _ in crypto.META_KEYS[1:])
            conn.execute(
                f"DELETE FROM store_meta WHERE key IN ({placeholders})",
                crypto.META_KEYS[1:],
            )
            conn.execute(
                "INSERT OR REPLACE INTO store_meta (key, value) VALUES (?, ?)",
                (crypto.META_SCHEME, crypto.SCHEME_NONE),
            )
            conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
            install_fts_triggers(conn)
            conn.execute("COMMIT")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            _verify_decrypted(conn, memories, archived)
        except Exception as exc:
            _fail(conn, db_path, backup, "decrypt", exc)
    finally:
        conn.close()
    return RewriteResult("decrypted", db_path, backup, memories, archived, 0)


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------


def _require_store(db_path: Path) -> None:
    if not db_path.is_file():
        raise FileNotFoundError(f"no store at {db_path}")


def _prepare(db_path: Path, key_str: str) -> bool:
    """Migrate the store and check the key; return True when it is encrypted.

    Opening without a key first means a plaintext store is never handed a
    key, which would make an empty plaintext store encrypted as a side
    effect of ``decrypt``.
    """
    try:
        MemoryDB(db_path, embedding_dims=0, encryption_key="").close()
    except EncryptionKeyMissing:
        MemoryDB(db_path, embedding_dims=0, encryption_key=key_str).close()
        return True
    return False


def _lock_store(db_path: Path) -> sqlite3.Connection:
    """Open ``db_path`` holding an exclusive lock until the connection closes."""
    conn = sqlite3.connect(
        str(db_path), timeout=LOCK_TIMEOUT_MS / 1000, isolation_level=None
    )
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(f"PRAGMA busy_timeout = {int(LOCK_TIMEOUT_MS)}")
        # In exclusive locking mode the lock taken by the first write
        # transaction is kept until the connection closes, so no other
        # process can open the store while it is being rewritten.
        conn.execute("PRAGMA locking_mode = EXCLUSIVE")
        conn.execute("BEGIN EXCLUSIVE")
        conn.execute("COMMIT")
        _load_vector_extension(conn)
    except sqlite3.OperationalError as exc:
        conn.close()
        raise StoreBusyError(
            f"{db_path} is open in another process; stop the mnemo server (and "
            "any other mnemo process using this store), then retry"
        ) from exc
    return conn


def _load_vector_extension(conn: sqlite3.Connection) -> bool:
    """Load sqlite-vec so the entity-vector table can be cleared, if possible."""
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except (AttributeError, ImportError, sqlite3.Error):
        return False
    return True


def _read_meta(conn: sqlite3.Connection) -> dict[str, str | None]:
    placeholders = ", ".join("?" for _ in crypto.META_KEYS)
    rows = conn.execute(
        f"SELECT key, value FROM store_meta WHERE key IN ({placeholders})",
        crypto.META_KEYS,
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def _require_scheme(
    conn: sqlite3.Connection, db_path: Path, scheme: str
) -> dict[str, str | None]:
    meta = _read_meta(conn)
    found = meta.get(crypto.META_SCHEME)
    if found != scheme:
        raise EncryptionError(
            f"{db_path} changed while the rewrite was being prepared (encryption "
            f"scheme {found!r}, expected {scheme!r}); nothing was changed, retry"
        )
    return meta


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _require_current_schema(conn: sqlite3.Connection, db_path: Path) -> None:
    """Refuse a store whose migration did not complete.

    Migrations are best effort when a store is opened, so a store can stay
    at an older schema. Encrypting it would leave newer user-data columns,
    added later by a migration, outside the rewrite.
    """
    missing = sorted(set(MEMORY_COLUMNS) - _columns(conn, "memories"))
    if missing:
        raise StoreRewriteError(
            f"{db_path} is not at the current schema (memories is missing "
            f"{', '.join(missing)}); start the server once so it migrates, then "
            "retry; nothing was changed"
        )


def _count_graph_rows(conn: sqlite3.Connection) -> int:
    total = 0
    for table in (*GRAPH_TABLES, *LEGACY_GRAPH_TABLES):
        if table_exists(conn, table):
            total += conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    with contextlib.suppress(sqlite3.Error):
        if table_exists(conn, _ENTITY_VECTOR_TABLE):
            total += conn.execute(
                f"SELECT count(*) FROM {_ENTITY_VECTOR_TABLE}"
            ).fetchone()[0]
    return total


# ---------------------------------------------------------------------------
# Backup and restore
# ---------------------------------------------------------------------------


def _write_backup(conn: sqlite3.Connection, db_path: Path, action: str) -> Path:
    """Write a consistent, single-file copy of the store and return its path."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    final = db_path.with_name(f"{db_path.name}.{action}-{stamp}.bak")
    tmp = final.with_name(final.name + ".tmp")
    # The encrypt backup holds plaintext: create it readable by the owner only.
    os.close(os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    try:
        dest = sqlite3.connect(str(tmp), isolation_level=None)
        try:
            conn.backup(dest)
            dest.execute("PRAGMA journal_mode = DELETE")
            check = dest.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            dest.close()
        if check != "ok":
            raise StoreRewriteError(f"backup copy failed its integrity check: {check}")
        _fsync(tmp)
        os.replace(tmp, final)
        _fsync_directory(final.parent)
    except BaseException:
        for leftover in (tmp, tmp.with_name(tmp.name + "-journal")):
            with contextlib.suppress(OSError):
                leftover.unlink()
        raise
    return final


def _fsync(path: Path) -> None:
    fd = os.open(path, os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_directory(path: Path) -> None:
    """Persist a rename. Windows cannot open a directory, and needs no flush."""
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _restore(conn: sqlite3.Connection, backup: Path) -> None:
    """Copy ``backup`` back into the store through the locked connection."""
    if conn.in_transaction:
        conn.execute("ROLLBACK")
    source = sqlite3.connect(str(backup))
    try:
        source.backup(conn)
    finally:
        source.close()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _fail(
    conn: sqlite3.Connection,
    db_path: Path,
    backup: Path,
    action: str,
    exc: Exception,
) -> NoReturn:
    """Restore the backup after a failed rewrite and raise StoreRewriteError."""
    try:
        _restore(conn, backup)
    except Exception as restore_exc:
        raise StoreRewriteError(
            f"{action} of {db_path} failed: {exc}; restore failed too "
            f"({restore_exc}); the store may be damaged, so replace it by hand "
            f"with the backup {backup}"
        ) from exc
    raise StoreRewriteError(
        f"{action} of {db_path} failed: {exc}; the store was restored from the "
        f"backup {backup}, which you may now delete"
    ) from exc


# ---------------------------------------------------------------------------
# Rewrite
# ---------------------------------------------------------------------------


def _rewrite(
    conn: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
    transform: Transform,
) -> int:
    """Apply ``transform(row_id, column, value)`` to ``columns`` of every row."""
    if not table_exists(conn, table):
        return 0
    present = _columns(conn, table)
    targets = [column for column in columns if column in present]
    selected = ", ".join(targets)
    assignments = ", ".join(f"{column} = ?" for column in targets)
    query = f"SELECT rowid, id, {selected} FROM {table}"
    total = 0
    last: int | None = None
    while True:
        if last is None:
            rows = conn.execute(
                f"{query} ORDER BY rowid LIMIT ?", (_BATCH_ROWS,)
            ).fetchall()
        else:
            rows = conn.execute(
                f"{query} WHERE rowid > ? ORDER BY rowid LIMIT ?", (last, _BATCH_ROWS)
            ).fetchall()
        if not rows:
            return total
        updates = []
        for row in rows:
            row_id = str(row["id"])
            values = [transform(row_id, column, row[column]) for column in targets]
            updates.append((*values, row[0]))
        conn.executemany(f"UPDATE {table} SET {assignments} WHERE rowid = ?", updates)
        total += len(rows)
        last = rows[-1][0]


def _drop_graph_rows(conn: sqlite3.Connection) -> int:
    total = 0
    # Links, edges and relations first: they reference the entities.
    for table in (
        "memory_entity_links",
        "memory_edges",
        "memory_entities",
        "relations",
        "entities",
    ):
        if table_exists(conn, table):
            total += conn.execute(f"DELETE FROM {table}").rowcount
    if table_exists(conn, _ENTITY_VECTOR_TABLE):
        with contextlib.suppress(sqlite3.OperationalError):
            # Without sqlite-vec loaded the vectors stay; they hold no text.
            total += conn.execute(f"DELETE FROM {_ENTITY_VECTOR_TABLE}").rowcount
    return total


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _quick_check(conn: sqlite3.Connection) -> None:
    result = conn.execute("PRAGMA quick_check").fetchone()[0]
    if result != "ok":
        raise EncryptedDataError(f"integrity check failed after the rewrite: {result}")


def _triggers(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
    }


def _count(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _decrypt_all(
    conn: sqlite3.Connection,
    cipher: crypto.FieldCipher,
    table: str,
    columns: Sequence[str],
) -> int:
    """Decrypt every encrypted value of ``table``; raise on the first failure."""
    if not table_exists(conn, table):
        return 0
    present = _columns(conn, table)
    targets = [column for column in columns if column in present]
    count = 0
    for row in conn.execute(f"SELECT id, {', '.join(targets)} FROM {table}"):
        row_id = str(row["id"])
        for column in targets:
            cipher.decrypt(row_id, column, row[column])
        count += 1
    return count


def _verify_encrypted(
    conn: sqlite3.Connection,
    cipher: crypto.FieldCipher,
    memories: int,
    archived: int,
) -> None:
    """Check that an encrypted store holds only ciphertext and an empty index."""
    _quick_check(conn)
    meta = _read_meta(conn)
    if meta.get(crypto.META_SCHEME) != crypto.SCHEME_AES_GCM_V1 or not all(
        meta.get(name) for name in crypto.META_KEYS[1:]
    ):
        raise EncryptedDataError("encryption metadata was not recorded")
    found = (
        _decrypt_all(conn, cipher, "memories", ENCRYPTED_MEMORY_COLUMNS),
        _decrypt_all(conn, cipher, "archived_memories", ENCRYPTED_ARCHIVE_COLUMNS),
    )
    if found != (memories, archived):
        raise EncryptedDataError(
            f"row counts changed during the rewrite: {found} != {(memories, archived)}"
        )
    if _count(conn, "memories_fts_docsize"):
        raise EncryptedDataError("the full-text index still holds rows")
    triggers = _triggers(conn)
    if triggers & set(FTS_TRIGGER_NAMES):
        raise EncryptedDataError("full-text index triggers are still installed")
    if f"{GUARD_TRIGGER_PREFIX}memories_insert" not in triggers:
        raise EncryptedDataError("guard triggers were not installed")
    if any(_count(conn, table) for table in (*GRAPH_TABLES, *LEGACY_GRAPH_TABLES)):
        raise EncryptedDataError("knowledge-graph tables still hold rows")


def _verify_decrypted(conn: sqlite3.Connection, memories: int, archived: int) -> None:
    """Check that a decrypted store is a plain, fully indexed store again."""
    _quick_check(conn)
    meta = _read_meta(conn)
    if meta != {crypto.META_SCHEME: crypto.SCHEME_NONE}:
        raise EncryptedDataError("encryption metadata was not removed")
    found = (_count(conn, "memories"), _count(conn, "archived_memories"))
    if found != (memories, archived):
        raise EncryptedDataError(
            f"row counts changed during the rewrite: {found} != {(memories, archived)}"
        )
    triggers = _triggers(conn)
    if not set(FTS_TRIGGER_NAMES) <= triggers:
        raise EncryptedDataError("full-text index triggers were not reinstalled")
    if any(name.startswith(GUARD_TRIGGER_PREFIX) for name in triggers):
        raise EncryptedDataError("guard triggers were not removed")
    if _count(conn, "memories_fts_docsize") != memories:
        raise EncryptedDataError("the full-text index was not rebuilt")
