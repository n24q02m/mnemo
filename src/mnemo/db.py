"""Core SQLite database engine for Mnemo memories.

Provides:
- FTS5 full-text search (always available, zero dependency)
- sqlite-vec vector search (when embeddings are configured)
- CRUD operations with category/tag filtering
- Hybrid search scoring (text + semantic + recency + frequency)
- Alembic schema migrations with backup-before-migrate
- Optional AES-256-GCM at-rest encryption of user data (see ``mnemo.crypto``)
"""

import io
import json
import math
import operator
import re
import shutil
import sqlite3
import struct
import threading
import time
import uuid
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Concatenate, ParamSpec, TypeVar

import sqlite_vec
from loguru import logger

from mnemo import crypto, keyword_scan
from mnemo.exceptions import (
    EmbeddingModelMismatch,
    EncryptedDataError,
    EncryptionError,
    EncryptionKeyMissing,
    StoreNotEncrypted,
)

# Alembic migration constants
_ALEMBIC_INI_PATH = Path(__file__).resolve().parent / "alembic.ini"
_ALEMBIC_SCRIPT_LOCATION = Path(__file__).resolve().parent / "alembic"

_STRUCT_CACHE: dict[int, struct.Struct] = {}

# ---------------------------------------------------------------------------
# The `memories` column set -- one list, shared by every path that serializes a
# row.
#
# Before this existed there were three hand-written lists of different lengths
# (export 9, import 10, sync/delta 15) against a 19-column table, so
# `export_memories` -> `import_memories` silently dropped ten columns and still
# reported success. The lists are gone; these constants replace all of them.
#
# Order and membership must equal `PRAGMA table_info(memories)` on a store built
# by `_init_schema` + the Alembic lineage. That is asserted by
# `tests/test_column_fidelity.py`, which fails when a migration adds a column
# without updating this tuple -- the drift that caused the original defect.
#
# Kept explicit rather than introspected from the open connection. Introspection
# would make the serialized column set a property of whichever database happens
# to be open: a store still missing a column would export without it and import
# clean into a store that has it, which is the same silent data loss one layer
# down. An explicit tuple gives the schema a second opinion to disagree with,
# which is what makes a drift test possible at all.
MEMORY_COLUMNS: tuple[str, ...] = (
    "id",
    "content",
    "category",
    "tags",
    "source",
    "created_at",
    "updated_at",
    "access_count",
    "last_accessed",
    "importance",
    "context_type",
    "archived_at",
    "text_raw",
    "compressed",
    "compression_provider",
    "commit_sha",
    "valid_from",
    "valid_to",
    "superseded_by",
    "subject",
    "confidence",
)

# What the importer writes when a JSONL record omits a column. Mirrors the
# schema's own DEFAULT clauses so an import is indistinguishable from an insert
# that never mentioned the column. `id`, `content` and `tags` are handled
# separately (generated / validated / re-encoded), and the three timestamps
# default to "now", which is not a constant.
_IMPORT_TIMESTAMP_COLUMNS = frozenset({"created_at", "updated_at", "last_accessed"})
_IMPORT_DERIVED_COLUMNS = frozenset({"id", "content", "tags"})
_IMPORT_DEFAULTS: dict[str, object] = {
    "category": "general",
    "source": None,
    "access_count": 0,
    "importance": 0.5,
    "context_type": "conversation",
    "archived_at": None,
    "text_raw": None,
    "compressed": 0,
    "compression_provider": None,
    "commit_sha": None,
    "valid_from": None,
    "valid_to": None,
    "superseded_by": None,
    "subject": None,
    "confidence": 1.0,
}

# `tags` holds a JSON array as TEXT. Emitting it through `json()` makes the
# exported record carry a real array instead of a quoted string, which is the
# shape the importer and every existing consumer expect.
_EXPORT_JSON_OBJECT_ARGS = ", ".join(
    f"'{column}', json({column})" if column == "tags" else f"'{column}', {column}"
    for column in MEMORY_COLUMNS
)

# ``MemoryDB.update`` supersedes a row with a single ``UPDATE ... RETURNING *``
# so the read and the write cannot be split by a competing writer. RETURNING
# landed in SQLite 3.35.0 (https://sqlite.org/lang_returning.html). A Python
# linked against an older library fails at the first update() call with a
# syntax error rather than at install time, so check once at open.
MIN_SQLITE_VERSION = (3, 35, 0)


def _check_sqlite_version() -> None:
    """Raise when the linked SQLite predates ``UPDATE ... RETURNING``."""
    if sqlite3.sqlite_version_info >= MIN_SQLITE_VERSION:
        return
    required = ".".join(str(part) for part in MIN_SQLITE_VERSION)
    raise RuntimeError(
        f"mnemo needs SQLite >= {required} for UPDATE ... RETURNING, but "
        f"this Python is linked against SQLite {sqlite3.sqlite_version}. "
        "Upgrade the SQLite library this Python build uses, or install a "
        "Python distribution that bundles a newer one."
    )


def _serialize_f32(vec: list[float], target_dims: int = 0) -> bytes:
    """Serialize float list to bytes for sqlite-vec.

    Ensures vector consistency with the database schema by truncating or
    zero-padding input vectors to match target_dims if provided.

    Uses a cached struct.Struct instance to avoid recompiling the format
    string on every vector insertion or search, providing a ~30% speedup.
    """
    if target_dims > 0:
        if len(vec) > target_dims:
            vec = vec[:target_dims]
        elif len(vec) < target_dims:
            vec = vec + [0.0] * (target_dims - len(vec))

    n = len(vec)
    try:
        s = _STRUCT_CACHE[n]
    except KeyError:
        s = struct.Struct(f"{n}f")
        _STRUCT_CACHE[n] = s
    return s.pack(*vec)


def _now_iso() -> str:
    """Current UTC timestamp in ISO format."""
    return datetime.now(UTC).isoformat()


# Maximum content length to prevent memory poisoning attacks (OWASP LLM09).
# Limits damage from indirect prompt injection writing oversized payloads.
MAX_CONTENT_LENGTH = 5000
# Maximum tags allowed in a search filter to prevent complexity attacks.
MAX_TAGS_FILTER = 50


def _build_fts_queries(query: str) -> list[str]:
    """Build tiered FTS5 queries: PHRASE -> AND -> OR.

    No stop-word filtering — BM25's IDF naturally down-weights common
    words (any language) and the PHRASE->AND->OR fallback ensures
    precision first, then recall.
    """
    words = [w.strip() for w in query.split() if w.strip()]
    safe = [w.replace('"', '""') for w in words]

    if not safe:
        return []
    if len(safe) == 1:
        return [f'"{safe[0]}"*']

    return [
        # Tier 0: PHRASE — exact phrase match (highest precision)
        '"' + " ".join(safe) + '"',
        # Tier 1: AND — all terms must appear
        " AND ".join(f'"{w}"*' for w in safe),
        # Tier 2: OR — any term matches (broadest fallback)
        " OR ".join(f'"{w}"*' for w in safe),
    ]


def _normalize_fts_scores(results: dict[str, dict]) -> None:
    """Min-max normalise the positive ``fts_score`` values of ``results``.

    Shared by the FTS5 path and the encrypted keyword path so both hand the
    hybrid scorer the same scale. Equal scores all become 1.0.
    """
    fts_nodes = []
    min_f = float("inf")
    max_f = float("-inf")
    for m in results.values():
        val = m["fts_score"]
        if val > 0:
            fts_nodes.append(m)
            if val < min_f:
                min_f = val
            if val > max_f:
                max_f = val

    if fts_nodes:
        rng = max_f - min_f
        if rng > 0:
            for m in fts_nodes:
                m["fts_score"] = (m["fts_score"] - min_f) / rng
        else:
            for m in fts_nodes:
                m["fts_score"] = 1.0


# ---------------------------------------------------------------------------
# At-rest encryption (see mnemo.crypto for the key and value format).
#
# In an encrypted store these columns hold ``enc:v1:`` ciphertext bound to the
# row id and column name. Every other column (category, context_type, the
# timestamps, importance, confidence, counters, ids and supersession pointers)
# stays plaintext so SQL can keep filtering and sorting on it. ``commit_sha``
# is a digest of the content, so it would confirm a guessed content and is
# encrypted too.
ENCRYPTED_MEMORY_COLUMNS: tuple[str, ...] = (
    "content",
    "tags",
    "source",
    "text_raw",
    "subject",
    "commit_sha",
)
# The legacy hard-archive side table holds the same values under the same ids.
ENCRYPTED_ARCHIVE_COLUMNS: tuple[str, ...] = ("content", "tags", "source")
# Knowledge-graph tables. Entity names, relation types and the memory links
# would describe encrypted memories in plaintext, so an encrypted store keeps
# them empty.
GRAPH_TABLES: tuple[str, ...] = (
    "memory_entities",
    "memory_edges",
    "memory_entity_links",
)
# Pre-mem_003 names of the graph tables, still present on stores that were
# never migrated.
LEGACY_GRAPH_TABLES: tuple[str, ...] = ("entities", "relations")

FTS_TRIGGER_NAMES: tuple[str, ...] = ("memories_ai", "memories_ad", "memories_au")
_FTS_TRIGGERS_SQL: tuple[str, ...] = (
    """CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(rowid, id, content, tags)
        VALUES (new.rowid, new.id, new.content, new.tags);
    END""",
    """CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, id, content, tags)
        VALUES ('delete', old.rowid, old.id, old.content, old.tags);
    END""",
    """CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, id, content, tags)
        VALUES ('delete', old.rowid, old.id, old.content, old.tags);
        INSERT INTO memories_fts(rowid, id, content, tags)
        VALUES (new.rowid, new.id, new.content, new.tags);
    END""",
)

GUARD_TRIGGER_PREFIX = "mnemo_guard_"
_GUARD_MESSAGE = (
    "mnemo: store is encrypted; write through MemoryDB with "
    f"{crypto.ENCRYPTION_KEY_ENV} set"
)


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """True when ``name`` is a table in the database behind ``conn``."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    # ``table`` is always one of this module's constants.
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def install_fts_triggers(conn: sqlite3.Connection) -> None:
    """Create the triggers that keep ``memories_fts`` in sync (plaintext only)."""
    for statement in _FTS_TRIGGERS_SQL:
        conn.execute(statement)


def drop_fts_triggers(conn: sqlite3.Connection) -> None:
    """Drop the FTS sync triggers so no write reaches the FTS5 index."""
    for name in FTS_TRIGGER_NAMES:
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")


def _plaintext_condition(columns: Sequence[str]) -> str:
    prefix = crypto.VALUE_PREFIX
    return " OR ".join(
        f"(NEW.{column} IS NOT NULL AND "
        f"substr(NEW.{column}, 1, {len(prefix)}) != '{prefix}')"
        for column in columns
    )


def install_encryption_guards(conn: sqlite3.Connection) -> None:
    """Create triggers that reject plaintext writes to an encrypted store.

    The triggers stop a process that does not hold the key (an older
    release, or a direct SQL client) from adding plaintext next to the
    ciphertext: any INSERT, or UPDATE of an encrypted column, whose value is
    not ``enc:v1:`` ciphertext aborts, and any INSERT into a knowledge-graph
    table aborts. Metadata-only updates (importance, access counters,
    archive and supersession columns) stay allowed. Only columns present in
    the current schema are named, so the triggers never block a migration
    that renames a table.
    """
    abort = f"BEGIN SELECT RAISE(ABORT, '{_GUARD_MESSAGE}'); END"
    statements = []
    for table, secret_columns, short in (
        ("memories", ENCRYPTED_MEMORY_COLUMNS, "memories"),
        ("archived_memories", ENCRYPTED_ARCHIVE_COLUMNS, "archived"),
    ):
        if not table_exists(conn, table):
            continue
        present = _table_columns(conn, table)
        columns = [column for column in secret_columns if column in present]
        if not columns:
            continue
        condition = _plaintext_condition(columns)
        statements.append(
            f"CREATE TRIGGER {GUARD_TRIGGER_PREFIX}{short}_insert BEFORE INSERT "
            f"ON {table} WHEN {condition} {abort}"
        )
        statements.append(
            f"CREATE TRIGGER {GUARD_TRIGGER_PREFIX}{short}_update BEFORE UPDATE OF "
            f"{', '.join(columns)} ON {table} WHEN {condition} {abort}"
        )
    for table in GRAPH_TABLES:
        if table_exists(conn, table):
            statements.append(
                f"CREATE TRIGGER {GUARD_TRIGGER_PREFIX}{table}_insert BEFORE INSERT "
                f"ON {table} {abort}"
            )
    for statement in statements:
        conn.execute(statement)


def drop_encryption_guards(conn: sqlite3.Connection) -> None:
    """Drop every guard trigger installed by :func:`install_encryption_guards`."""
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' "
            "AND substr(name, 1, ?) = ?",
            (len(GUARD_TRIGGER_PREFIX), GUARD_TRIGGER_PREFIX),
        ).fetchall()
    ]
    for name in names:
        quoted = name.replace('"', '""')
        conn.execute(f'DROP TRIGGER IF EXISTS "{quoted}"')


def _tags_match(tags_json: object, wanted: Sequence[str]) -> bool:
    """Python twin of the SQL tag filter that plaintext stores run.

    Mirrors ``tags != '[]' AND json_valid(tags) AND EXISTS (SELECT 1 FROM
    json_each(tags) WHERE value IN wanted)``: an array matches on any
    element, an object on any value and a scalar on itself. Text that is not
    JSON never matches.
    """
    if not isinstance(tags_json, str) or tags_json == "[]":
        return False
    try:
        parsed = json.loads(tags_json)
    except ValueError:
        return False
    if isinstance(parsed, list):
        values = parsed
    elif isinstance(parsed, dict):
        values = list(parsed.values())
    else:
        values = [parsed]
    wanted_set = set(wanted)
    return any(isinstance(value, str) and value in wanted_set for value in values)


_P = ParamSpec("_P")
_T = TypeVar("_T")


class MemoryDB:
    """SQLite database for persistent AI memories."""

    def __init__(
        self,
        db_path: Path,
        embedding_dims: int = 0,
        recency_half_life_days: float = 7.0,
        *,
        embedding_model: str = "",
        reindex_on_model_change: bool = False,
        encryption_key: str | None = None,
    ):
        """Open or create memory database.

        Args:
            db_path: Path to SQLite database file.
            embedding_dims: Embedding dimensions (0 = no vector search).
            recency_half_life_days: Half-life in days for recency decay.
            embedding_model: Active embedding model identity string. Stamped
                into ``store_meta`` on first open and compared on subsequent
                opens to guard against silent vector-store corruption when the
                embedding model changes. Empty string skips the model-id check
                (dims are still guarded).
            reindex_on_model_change: When True and the stored identity mismatches
                the requested one, DROP the vector table + clear stored vectors
                and re-stamp the new identity instead of raising. The embed
                pipeline re-populates on the next pass.
            encryption_key: At-rest encryption key setting (see
                :func:`mnemo.crypto.parse_key`). ``None`` reads
                ``MNEMO_ENCRYPTION_KEY``; an empty string means "no key". An
                encrypted store needs the key it was encrypted with. A new or
                empty store opened with a key is created encrypted.

        Raises:
            EmbeddingModelMismatch: When the stored embedding identity differs
                from the requested one and ``reindex_on_model_change`` is False.
            EncryptionKeyError: When the key setting is malformed. Raised
                before anything is created on disk.
            EncryptionKeyMissing: When the store is encrypted and no key is set.
            WrongEncryptionKey: When the key does not match the store.
            StoreNotEncrypted: When a key is set but the store already holds
                plaintext memories (convert it with ``n24q02m-mnemo encrypt``).
            EncryptionError: For an unknown scheme or corrupt or leftover
                encryption state. The store is never opened as plaintext.
            RuntimeError: When the linked SQLite is older than
                :data:`MIN_SQLITE_VERSION`.
        """
        _check_sqlite_version()
        self._db_path = db_path
        if type(embedding_dims) is not int:
            raise ValueError(
                f"embedding_dims must be an integer, got {type(embedding_dims).__name__}"
            )
        self._embedding_dims = embedding_dims
        if not (0 <= embedding_dims <= 10000):
            raise ValueError(
                f"embedding_dims must be between 0 and 10000, got {embedding_dims}"
            )
        self._embedding_model = embedding_model
        self._reindex_on_model_change = reindex_on_model_change
        self._recency_half_life = float(recency_half_life_days)

        # Parse the key before anything touches the disk, so a malformed key
        # never leaves an empty store behind.
        key = crypto.load_key(encryption_key)
        self._cipher: crypto.FieldCipher | None = None
        # Key and metadata of a new encrypted store, recorded by _init_schema.
        self._pending_encryption: tuple[crypto.EncryptionKey, dict[str, str]] | None = (
            None
        )

        # Create parent directory
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # One connection is shared by asyncio.to_thread workers and the event
        # loop thread, so check_same_thread is off and every use of it holds
        # this lock instead: concurrent callers on one sqlite3 connection
        # interleave their statements, and one caller's commit() or rollback()
        # lands in the middle of another caller's transaction. Reentrant
        # because methods that hold it call other methods that take it too.
        # Code outside this class reaches the connection only through
        # connection() / run().
        #
        # The lock is not enough on its own: pysqlite opens a transaction
        # before the first write and keeps it open until a commit or rollback,
        # so a write that raises part-way, or that finds nothing to change and
        # returns early, would leave it open for the next caller, on any
        # thread, to commit. Each method that owns a write transaction
        # therefore enters the connection as a context manager inside the lock
        # (``with self._lock, self._conn:``), which rolls back when the body
        # raises and commits on every other exit, before the lock is released.
        # Helpers called from such a method take the plain lock only: entering
        # the connection again would commit the caller's transaction early.
        self._lock = threading.RLock()
        with self._lock:
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA busy_timeout = 5000")
            self._conn.execute("PRAGMA foreign_keys = ON")

            # Load sqlite-vec extension for vector search
            self._vec_enabled = False
            if embedding_dims > 0:
                try:
                    self._conn.enable_load_extension(True)
                    sqlite_vec.load(self._conn)
                    self._conn.enable_load_extension(False)
                    self._vec_enabled = True
                    logger.debug(f"sqlite-vec loaded (dims={embedding_dims})")
                except Exception as e:
                    logger.warning(f"sqlite-vec load failed: {e}")

            # Decide plaintext vs encrypted before any schema work, so a store
            # that cannot be opened safely is left exactly as it was found.
            try:
                self._resolve_encryption(key)
            except BaseException:
                self._conn.close()
                raise

        self._init_schema()

        # Run Alembic migrations after the baseline schema is materialised so
        # that fresh databases are stamped at ``baseline_001`` and then walked
        # forward. ``_run_migrations`` is best-effort: failures are logged but
        # never block server startup.
        self._run_migrations()

        if self._cipher is not None:
            self._seal_encrypted_schema()

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection]:
        """Hold the database lock and yield the shared connection.

        The only way for code outside this class to use the connection. The
        block runs as one transaction: it commits when the block exits
        normally and rolls back when it raises, so a half-done write never
        outlives the lock and gets committed by another caller. Fetch every
        result inside the block, and keep slow non-database work (embedding,
        LLM or network calls) outside it.
        """
        with self._lock, self._conn:
            yield self._conn

    def run(
        self,
        fn: Callable[Concatenate[sqlite3.Connection, _P], _T],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _T:
        """Call ``fn(connection, *args, **kwargs)`` inside :meth:`connection`.

        Lets a function that takes a connection run as one locked transaction
        from ``asyncio.to_thread``.
        """
        with self.connection() as conn:
            return fn(conn, *args, **kwargs)

    # ------------------------------------------------------------------
    # At-rest encryption
    # ------------------------------------------------------------------

    @property
    def encrypted(self) -> bool:
        """Whether user data in this store is encrypted at rest."""
        return self._cipher is not None

    def _read_encryption_meta(self) -> dict[str, str | None]:
        placeholders = ", ".join("?" for _ in crypto.META_KEYS)
        with self._lock:
            if not table_exists(self._conn, "store_meta"):
                return {}
            rows = self._conn.execute(
                f"SELECT key, value FROM store_meta WHERE key IN ({placeholders})",
                crypto.META_KEYS,
            ).fetchall()
        return {row[0]: row[1] for row in rows}

    def _resolve_encryption(self, key: crypto.EncryptionKey | None) -> None:
        """Pick the store's mode from its metadata and the configured key.

        Fails closed: an encrypted store without the right key, an unknown
        scheme, or a plaintext store that shows signs of encrypted data all
        raise instead of opening, and nothing is written before the decision.
        """
        if (
            self._open_recorded_encryption(self._read_encryption_meta(), key)
            or key is None
        ):
            return
        self._refuse_plaintext_data()
        meta, self._cipher = crypto.new_store_encryption(key)
        self._pending_encryption = (key, meta)

    def _open_recorded_encryption(
        self, meta: dict[str, str | None], key: crypto.EncryptionKey | None
    ) -> bool:
        """Open the store as ``meta`` records it; True when it is encrypted.

        Raises when the store is encrypted and ``key`` is missing or wrong,
        when the scheme is unknown, and when a store marked plaintext still
        carries encrypted state.
        """
        scheme = meta.get(crypto.META_SCHEME)
        if scheme == crypto.SCHEME_AES_GCM_V1:
            if key is None:
                raise EncryptionKeyMissing(
                    f"{self._db_path} is encrypted at rest; set "
                    f"{crypto.ENCRYPTION_KEY_ENV} to the key it was encrypted with"
                )
            self._cipher = crypto.open_store_encryption(meta, key)
            return True
        if scheme not in (None, crypto.SCHEME_NONE):
            raise EncryptionError(
                f"{self._db_path} uses an unknown encryption scheme {scheme!r}; "
                "it was written by a newer release or is corrupt"
            )
        self._refuse_encrypted_leftovers(meta)
        return False

    def _refuse_plaintext_data(self) -> None:
        """Refuse to start encrypting a store that already holds plaintext."""
        if self._store_has_data():
            raise StoreNotEncrypted(
                f"{self._db_path} holds plaintext memories; run "
                "`n24q02m-mnemo encrypt` to encrypt it in place, or unset "
                f"{crypto.ENCRYPTION_KEY_ENV} to keep using it unencrypted"
            )

    def _record_new_encryption(
        self, key: crypto.EncryptionKey, meta: dict[str, str]
    ) -> None:
        """Record the metadata of a new encrypted store, or adopt a rival's.

        Two processes can open the same empty store with a key at once, each
        with a salt of its own. The metadata is written in one write
        transaction that reads it again first, so the first opener records
        its metadata and never has it overwritten. A later opener adopts that
        metadata when its key matches, and fails with
        :class:`WrongEncryptionKey` when it does not, or with
        :class:`StoreNotEncrypted` when plaintext memories were added in the
        meantime.
        """
        with self._lock:
            # The schema set-up before this point is DDL only, which never
            # leaves a transaction open.
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                if not self._open_recorded_encryption(
                    self._read_encryption_meta(), key
                ):
                    self._refuse_plaintext_data()
                    for meta_key, meta_value in meta.items():
                        self._set_store_meta(meta_key, meta_value)
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                self._conn.close()
                raise

    def _refuse_encrypted_leftovers(self, meta: dict[str, str | None]) -> None:
        """Refuse a store marked plaintext that still carries encrypted state.

        Opening such a store as plaintext would mix new plaintext rows with
        ciphertext the server cannot read, so treat it as damaged instead.
        """
        leftover = [name for name in crypto.META_KEYS[1:] if meta.get(name)]
        with self._lock:
            if leftover:
                reason = "encryption metadata (" + ", ".join(leftover) + ")"
            elif self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'trigger' "
                "AND substr(name, 1, ?) = ? LIMIT 1",
                (len(GUARD_TRIGGER_PREFIX), GUARD_TRIGGER_PREFIX),
            ).fetchone():
                reason = "encryption guard triggers"
            else:
                return
        raise EncryptedDataError(
            f"{self._db_path} is marked unencrypted but still holds {reason}; "
            "restore it from the backup written by `n24q02m-mnemo encrypt` or "
            "`n24q02m-mnemo decrypt`"
        )

    def _store_has_data(self) -> bool:
        """True when any memory, archive or knowledge-graph row exists."""
        tables = ("memories", "archived_memories", *GRAPH_TABLES, *LEGACY_GRAPH_TABLES)
        with self._lock:
            for table in tables:
                if (
                    table_exists(self._conn, table)
                    and self._conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                ):
                    return True
        return False

    def _seal_encrypted_schema(self) -> None:
        """Make sure an encrypted store never indexes or accepts plaintext.

        Runs on every open of an encrypted store, after migrations: it drops
        the FTS5 sync triggers (an older release may have recreated them),
        empties the FTS5 index if anything reached it, and reinstalls the
        guard triggers against the current schema.
        """
        with self._lock, self._conn:
            drop_fts_triggers(self._conn)
            if self._conn.execute(
                "SELECT 1 FROM memories_fts_docsize LIMIT 1"
            ).fetchone():
                self._conn.execute(
                    "INSERT INTO memories_fts(memories_fts) VALUES('delete-all')"
                )
            drop_encryption_guards(self._conn)
            install_encryption_guards(self._conn)

    def _seal(self, row_id: str, column: str, value: str | None) -> str | None:
        """Encrypt one value when the store is encrypted; else return it as is."""
        if self._cipher is None:
            return value
        return self._cipher.encrypt(row_id, column, value)

    def _seal_row(self, row_id: str, values: dict[str, Any]) -> dict[str, Any]:
        """Encrypt the user-data columns of a full row dict bound to ``row_id``."""
        if self._cipher is None:
            return values
        sealed = dict(values)
        for column in ENCRYPTED_MEMORY_COLUMNS:
            if column in sealed:
                sealed[column] = self._cipher.encrypt(row_id, column, sealed[column])
        return sealed

    def decode_row(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        """Return a ``memories`` row as a dict with user data decrypted.

        A plaintext store returns ``dict(row)`` unchanged. An encrypted store
        decrypts every encrypted column present in the row, bound to the
        row's ``id``, and raises :class:`EncryptedDataError` when a value was
        tampered with or moved from another row or column.
        """
        data = dict(row)
        if self._cipher is None:
            return data
        row_id = str(data["id"])
        for column in ENCRYPTED_MEMORY_COLUMNS:
            if column in data:
                data[column] = self._cipher.decrypt(row_id, column, data[column])
        return data

    def _encrypted_subject_matches(
        self, memory_id: str, subject: str, condition: str
    ) -> bool:
        """Check a row's decrypted subject inside the caller's transaction."""
        with self._lock:
            row = self._conn.execute(
                f"SELECT id, subject FROM memories WHERE id = ? AND {condition}",
                (memory_id,),
            ).fetchone()
        return row is not None and self.decode_row(row)["subject"] == subject

    @staticmethod
    def _matches_encrypted_filters(
        data: dict[str, Any], subject: str | None, tags: Sequence[str] | None
    ) -> bool:
        """Apply the subject and tag filters that SQL cannot run on ciphertext."""
        if subject is not None and data.get("subject") != subject:
            return False
        return not tags or _tags_match(data.get("tags"), tags)

    def set_compressed(
        self, memory_id: str, content: str, text_raw: str, provider: str
    ) -> bool:
        """Replace a memory's content with its compressed form in place.

        Keeps the original text in ``text_raw`` and flags the row with the
        compression provider. Returns False when no row has ``memory_id``.
        """
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE memories SET content = ?, text_raw = ?, compressed = 1, "
                "compression_provider = ?, updated_at = ? WHERE id = ?",
                (
                    self._seal(memory_id, "content", content),
                    self._seal(memory_id, "text_raw", text_raw),
                    provider,
                    _now_iso(),
                    memory_id,
                ),
            )
        return cursor.rowcount > 0

    def _init_schema(self) -> None:
        """Initialize database schema.

        Delegates to focused sub-initializers so each concern (core memory
        tables, knowledge graph, archive, vector index) owns its own SQL
        script and can be read / tested in isolation.
        """
        with self._lock:
            self._init_memory_schema()
            self._init_graph_schema()
            self._init_archive_schema()
            self._init_store_meta_schema()
            if self._pending_encryption is not None:
                # A new encrypted store: record the scheme, KDF, salt and key
                # check before migrations run, so mem_008 leaves them alone.
                self._record_new_encryption(*self._pending_encryption)
                self._pending_encryption = None
            # Guard BEFORE _ensure_vec_table: the latter detects an existing
            # memories_vec and silently adopts its stored dimension, which would
            # mask a dims mismatch. The guard compares the REQUESTED identity
            # against the stamped one, and on opt-in reindex drops + recreates the
            # vec table itself.
            self._guard_embedding_identity()
            self._ensure_vec_table(self._embedding_dims)
            self._conn.commit()

    def _init_store_meta_schema(self) -> None:
        """Initialize the ``store_meta`` key/value table.

        Holds store-level identity that the DB layer must read/write at open
        time, independent of (and before) best-effort Alembic migrations. Used
        to record which embedding model + dimension produced the stored vectors
        so a later model change cannot silently corrupt similarity search.
        """
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS store_meta (
                    key TEXT PRIMARY KEY NOT NULL,
                    value TEXT
                )
            """)

    def get_store_meta(self, key: str) -> str | None:
        """Return the ``store_meta`` value for ``key`` or ``None`` if unset."""
        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT value FROM store_meta WHERE key = ?", (key,)
                ).fetchone()
            except sqlite3.OperationalError:
                return None
        if row is None:
            return None
        return row[0] if not isinstance(row, sqlite3.Row) else row["value"]

    def _set_store_meta(self, key: str, value: str) -> None:
        """Insert-or-replace a ``store_meta`` key/value pair."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO store_meta (key, value) VALUES (?, ?)",
                (key, value),
            )

    def _guard_embedding_identity(self) -> None:
        """Stamp or verify the embedding-model identity of the vector store.

        Safe-by-default: a fresh store (no stamp) records the current
        ``(embedding_model, embedding_dims)``; a matching store proceeds; a
        MISMATCH raises :class:`EmbeddingModelMismatch` and touches NO data
        unless ``reindex_on_model_change`` is set, in which case the vector
        table is dropped + cleared and the new identity re-stamped so the embed
        pipeline rebuilds cleanly on the next pass.

        When ``embedding_dims == 0`` the store has no vectors, so there is
        nothing to corrupt and the guard is a no-op.
        """
        if self._embedding_dims <= 0:
            return

        stored_model = self.get_store_meta("embedding_model")
        stored_dims_raw = self.get_store_meta("embedding_dims")

        # Fresh store (no identity recorded yet): stamp current values.
        if stored_dims_raw is None and stored_model is None:
            self._stamp_embedding_identity()
            return

        try:
            stored_dims = int(stored_dims_raw) if stored_dims_raw is not None else 0
        except ValueError:
            stored_dims = 0

        # Compare. The model id is only compared when BOTH a stored id and a
        # requested id are present; dims are always compared (dims mismatch
        # alone already catches the most dangerous corruption case).
        dims_match = stored_dims == self._embedding_dims
        model_match = (
            not stored_model
            or not self._embedding_model
            or stored_model == self._embedding_model
        )
        if dims_match and model_match:
            return

        if self._reindex_on_model_change:
            logger.warning(
                "Embedding identity changed (stored model={!r} dims={}, "
                "requested model={!r} dims={}); REINDEX_ON_MODEL_CHANGE is set "
                "-- dropping stored vectors. They will be rebuilt on the next "
                "embed pass.",
                stored_model,
                stored_dims,
                self._embedding_model,
                self._embedding_dims,
            )
            self._drop_vectors_for_reindex()
            self._stamp_embedding_identity()
            return

        raise EmbeddingModelMismatch(
            stored_model=stored_model or "",
            stored_dims=stored_dims,
            requested_model=self._embedding_model or "",
            requested_dims=self._embedding_dims,
        )

    def _stamp_embedding_identity(self) -> None:
        """Record the current embedding model + dims into ``store_meta``."""
        self._set_store_meta("embedding_dims", str(self._embedding_dims))
        if self._embedding_model:
            self._set_store_meta("embedding_model", self._embedding_model)

    def _drop_vectors_for_reindex(self) -> None:
        """Drop the vector table(s) so they rebuild with the new identity.

        Only the embedding vectors are destroyed -- the ``memories`` rows
        themselves are preserved so the embed pipeline can re-populate vectors
        on the next pass. The dropped table is recreated immediately at the new
        dimension so subsequent inserts have a target.
        """
        with self._lock:
            try:
                self._conn.execute("DROP TABLE IF EXISTS memories_vec")
            except Exception as e:  # pragma: no cover - runtime guard
                logger.warning(f"Failed to drop memories_vec during reindex: {e}")
            try:
                self._conn.execute("DROP TABLE IF EXISTS memory_entities_vec")
            except Exception as e:  # pragma: no cover - runtime guard
                logger.warning(
                    f"Failed to drop memory_entities_vec during reindex: {e}"
                )
            # Recreate memories_vec at the new dimension for immediate writes.
            self._ensure_vec_table(self._embedding_dims)

    def _init_memory_schema(self) -> None:
        """Initialize core memory tables, indexes, FTS5, and importance column."""
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    tags TEXT NOT NULL DEFAULT '[]',
                    source TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    last_accessed TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_memories_category
                    ON memories(category);
                CREATE INDEX IF NOT EXISTS idx_memories_updated
                    ON memories(updated_at);
                CREATE INDEX IF NOT EXISTS idx_memories_accessed
                    ON memories(last_accessed);

                -- Bolt Performance Optimization:
                -- Compound index to eliminate O(N log N) file-sort overhead during
                -- list_memories pagination queries (WHERE category = ? ORDER BY updated_at DESC)
                CREATE INDEX IF NOT EXISTS idx_memories_category_updated
                    ON memories(category, updated_at DESC);
            """)

            # FTS5 full-text search (always available)
            self._conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(
                    id UNINDEXED,
                    content,
                    category UNINDEXED,
                    tags,
                    content=memories,
                    content_rowid=rowid,
                    tokenize='porter unicode61'
                )
            """)

            # FTS5 triggers to keep index in sync. An encrypted store keeps the
            # index empty: FTS5 would store every token in plaintext.
            if self._cipher is None:
                install_fts_triggers(self._conn)

            # Add importance column to memories (migration for existing DBs)
            try:
                self._conn.execute(
                    "ALTER TABLE memories ADD COLUMN importance REAL NOT NULL DEFAULT 0.5"
                )
            except Exception:
                pass  # Column already exists

    def _init_graph_schema(self) -> None:
        """Initialize knowledge graph tables.

        Phase 3 spec §5.2 canonical names:
        - ``memory_entities`` -- entity table (was ``entities`` in Phase 1/2).
        - ``memory_edges`` -- relation table (was ``relations``).
        - ``memory_entity_links`` -- memory<->entity join (was ``memory_entities``).

        Pre-Phase-3 databases continue to live under the old names until the
        ``mem_003_temporal`` Alembic migration renames them in-place. The
        migration runs AFTER ``_init_schema``. Detect legacy DB by presence
        of the old ``entities`` table — when found, skip creating canonical
        tables (the migration will rename in-place) to avoid name collision
        between the legacy ``memory_entities`` join table and the new
        ``memory_entities`` entity table.
        """
        with self._lock:
            legacy_entities = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='entities'"
            ).fetchone()
            if legacy_entities is not None:
                # Pre-Phase-3 DB: leave legacy graph tables untouched. The
                # mem_003_temporal migration will RENAME them to canonical names.
                return

            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS memory_entities (
                    id TEXT PRIMARY KEY NOT NULL,
                    name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_entities_name_type
                    ON memory_entities(name, entity_type);

                CREATE TABLE IF NOT EXISTS memory_edges (
                    id TEXT PRIMARY KEY NOT NULL,
                    source_id TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
                    target_id TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
                    relation_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    memory_id TEXT,
                    valid_from DATETIME,
                    valid_to DATETIME
                );
                CREATE INDEX IF NOT EXISTS idx_memory_edges_source ON memory_edges(source_id);
                CREATE INDEX IF NOT EXISTS idx_memory_edges_target ON memory_edges(target_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_edges_unique
                    ON memory_edges(source_id, target_id, relation_type);

                CREATE TABLE IF NOT EXISTS memory_entity_links (
                    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    entity_id TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
                    PRIMARY KEY (memory_id, entity_id)
                );

                -- Index on entity_id to eliminate full table scans during knowledge graph
                -- traversal in find_related_memory_ids.
                CREATE INDEX IF NOT EXISTS idx_memory_entity_links_entity_id
                    ON memory_entity_links(entity_id);
            """)

    def _init_archive_schema(self) -> None:
        """Initialize archive tables and pagination-supporting indexes."""
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS archived_memories (
                    id TEXT PRIMARY KEY NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    tags TEXT NOT NULL DEFAULT '[]',
                    source TEXT,
                    importance REAL NOT NULL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    last_accessed TEXT NOT NULL,
                    archived_at TEXT NOT NULL
                );

                -- Bolt Performance Optimization:
                -- Index on archived_at DESC to eliminate O(N log N) file-sort overhead during
                -- list_archived pagination queries.
                CREATE INDEX IF NOT EXISTS idx_archived_memories_archived_at
                    ON archived_memories(archived_at DESC);
            """)

    def _ensure_vec_table(self, dims: int) -> None:
        """Idempotently ensure the vector table exists with correct dimensions.

        Attempts to detect existing dimensions from sqlite_master to maintain
        schema consistency.
        """
        if not self._vec_enabled or dims <= 0:
            return

        with self._lock:
            # Try to detect dimension from existing table
            row = self._conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='memories_vec'"
            ).fetchone()

            if row:
                # Extract dimension from 'float[N]'
                match = re.search(r"float\s*\[\s*(\d+)\s*\]", row["sql"], re.IGNORECASE)
                if match:
                    detected_dims = int(match.group(1))
                    if detected_dims != dims:
                        logger.warning(
                            f"memories_vec dimension mismatch: requested {dims}, "
                            f"found {detected_dims}. Using detected dimension."
                        )
                        self._embedding_dims = detected_dims
                return

            # Validate dimension bounds before f-string interpolation to prevent
            # SQL injection via crafted dims and to fail fast on invalid values.
            # sqlite-vec enforces a maximum of 8192 dimensions per vector column.
            if not (1 <= dims <= 8192):
                raise ValueError(
                    f"embedding_dims must be between 1 and 8192, got {dims}"
                )

            # Create table if not exists
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE memories_vec
                USING vec0(
                    id TEXT PRIMARY KEY,
                    embedding float[placeholder_dims]
                )
            """.replace("placeholder_dims", str(dims))
            )
            logger.debug(f"Created memories_vec table with {dims} dims")

    @property
    def vec_enabled(self) -> bool:
        """Whether vector search is available."""
        return self._vec_enabled

    def rows_without_vectors(
        self,
        limit: int,
        *,
        exclude_ids: set[str] | None = None,
    ) -> list[dict]:
        """Return memory rows that do not yet have a stored vector.

        ``exclude_ids`` is used by bounded backfill runs to make progress past
        rows that cannot be embedded (for example, empty content) without
        changing the public backfill interface used by lightweight adapters.
        """
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        if not self._vec_enabled:
            raise RuntimeError("vector storage is not enabled for this database")

        excluded = sorted({str(memory_id) for memory_id in (exclude_ids or set())})
        where = "v.id IS NULL"
        params: list[object] = []
        if excluded:
            placeholders = ", ".join("?" for _ in excluded)
            where += f" AND m.id NOT IN ({placeholders})"
            params.extend(excluded)

        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT m.id, m.content
                FROM memories AS m
                LEFT JOIN memories_vec AS v ON v.id = m.id
                WHERE m.valid_to IS NULL AND {where}
                ORDER BY m.created_at ASC, m.id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self.decode_row(row) for row in rows]

    def write_vector(self, memory_id: str, vector: list[float]) -> None:
        """Persist or replace one memory vector for an active vector store."""
        if not self._vec_enabled:
            raise RuntimeError("vector storage is not enabled for this database")
        with self._lock, self._conn:
            if not self.get(memory_id):
                raise KeyError(f"memory not found: {memory_id}")

            self._conn.execute("DELETE FROM memories_vec WHERE id = ?", (memory_id,))
            self._conn.execute(
                "INSERT INTO memories_vec (id, embedding) VALUES (?, ?)",
                (memory_id, _serialize_f32(vector, self._embedding_dims)),
            )
            self._conn.commit()

    def add(
        self,
        content: str,
        category: str = "general",
        tags: list[str] | None = None,
        source: str | None = None,
        subject: str | None = None,
        embedding: list[float] | None = None,
    ) -> str:
        """Add a new memory.

        Returns:
            Memory ID.

        Raises:
            ValueError: If content exceeds MAX_CONTENT_LENGTH.
        """
        if len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(
                f"Content length {len(content)} exceeds limit of {MAX_CONTENT_LENGTH}"
            )

        memory_id = uuid.uuid4().hex
        now = _now_iso()

        # Bolt Performance Optimization:
        # Prevent expensive json.dumps calls for the default empty list.
        tags_json = "[]" if not tags else json.dumps(tags)

        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO memories (id, content, category, tags, source,
                   subject, created_at, updated_at, access_count, last_accessed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (
                    memory_id,
                    self._seal(memory_id, "content", content),
                    category,
                    self._seal(memory_id, "tags", tags_json),
                    self._seal(memory_id, "source", source),
                    self._seal(memory_id, "subject", subject),
                    now,
                    now,
                    now,
                ),
            )

            # Store embedding if provided
            if embedding and self._vec_enabled:
                self._conn.execute(
                    "INSERT INTO memories_vec (id, embedding) VALUES (?, ?)",
                    (memory_id, _serialize_f32(embedding, self._embedding_dims)),
                )

            self._conn.commit()
        logger.info(f"[AUDIT] add id={memory_id} cat={category} len={len(content)}")
        return memory_id

    def add_with_context_type(
        self,
        content: str,
        context_type: str = "conversation",
        category: str = "general",
        tags: list[str] | None = None,
        source: str | None = None,
        subject: str | None = None,
        embedding: list[float] | None = None,
        importance: float | None = None,
        *,
        text_raw: str | None = None,
        compressed: bool = False,
        compression_provider: str | None = None,
    ) -> str:
        """Add a new memory with an explicit ``context_type``.

        This mirrors :meth:`add` but writes the ``context_type`` column
        introduced by the ``mem_001_context_types`` Alembic migration. Used by
        the ``memory(action="capture")`` Phase 1 action.

        Phase 2 extension (``mem_002_compression`` Alembic migration): callers
        running text through the LLM compression pipeline can pass the
        original uncompressed text via ``text_raw`` and flag the row with
        ``compressed=True`` plus ``compression_provider`` (the literal
        ``"chat-cell"`` when the ``[models.chat]`` provider cell rewrote it).
        Default behaviour preserves Phase 1 (no compression bookkeeping).

        Args:
            content: Memory text content (post-compression when applicable).
            context_type: One of conversation/fact/preference/skill/task/decision.
            category: Free-form category bucket. Defaults to "general".
            tags: Optional list of tag strings.
            source: Optional provenance marker.
            embedding: Optional dense vector for semantic search.
            importance: Optional importance score in [0.0, 1.0].
            text_raw: Original uncompressed text retained for audit / recovery.
                Only set when ``compressed=True``.
            compressed: Flag indicating the LLM compression pipeline rewrote
                ``content``. Defaults to False so unchanged callers keep the
                Phase 1 behaviour.
            compression_provider: Marker for the pipeline that performed the
                compression (``"chat-cell"`` for the ``[models.chat]`` cell).
                NULL when ``compressed=False``.

        Returns:
            Memory ID (32-char hex).

        Raises:
            ValueError: If content exceeds :data:`MAX_CONTENT_LENGTH`.
        """
        if len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(
                f"Content length {len(content)} exceeds limit of {MAX_CONTENT_LENGTH}"
            )

        memory_id = uuid.uuid4().hex
        now = _now_iso()

        # Bolt Performance Optimization:
        # Prevent expensive json.dumps calls for the default empty list.
        tags_json = "[]" if not tags else json.dumps(tags)

        compressed_int = 1 if compressed else 0

        sealed_content = self._seal(memory_id, "content", content)
        sealed_tags = self._seal(memory_id, "tags", tags_json)
        sealed_source = self._seal(memory_id, "source", source)
        sealed_subject = self._seal(memory_id, "subject", subject)
        sealed_text_raw = self._seal(memory_id, "text_raw", text_raw)

        with self._lock, self._conn:
            if importance is not None:
                importance = max(0.0, min(1.0, importance))
                self._conn.execute(
                    """INSERT INTO memories (id, content, category, tags, source,
                       subject, created_at, updated_at, access_count, last_accessed,
                       context_type, importance,
                       text_raw, compressed, compression_provider)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)""",
                    (
                        memory_id,
                        sealed_content,
                        category,
                        sealed_tags,
                        sealed_source,
                        sealed_subject,
                        now,
                        now,
                        now,
                        context_type,
                        importance,
                        sealed_text_raw,
                        compressed_int,
                        compression_provider,
                    ),
                )
            else:
                self._conn.execute(
                    """INSERT INTO memories (id, content, category, tags, source,
                       subject, created_at, updated_at, access_count, last_accessed,
                       context_type,
                       text_raw, compressed, compression_provider)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)""",
                    (
                        memory_id,
                        sealed_content,
                        category,
                        sealed_tags,
                        sealed_source,
                        sealed_subject,
                        now,
                        now,
                        now,
                        context_type,
                        sealed_text_raw,
                        compressed_int,
                        compression_provider,
                    ),
                )

            if embedding and self._vec_enabled:
                self._conn.execute(
                    "INSERT INTO memories_vec (id, embedding) VALUES (?, ?)",
                    (memory_id, _serialize_f32(embedding, self._embedding_dims)),
                )

            self._conn.commit()
        logger.info(
            f"[AUDIT] capture id={memory_id} cat={category} "
            f"ctx_type={context_type} len={len(content)} "
            f"compressed={compressed} provider={compression_provider}"
        )
        return memory_id

    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        embedding: list[float] | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 5,
        *,
        context_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        min_importance: float = 0.0,
        include_archived: bool = False,
        candidate_pool: int | None = None,
        subject: str | None = None,
    ) -> list[dict]:
        """Search memories with hybrid scoring.

        Uses tiered FTS5 queries (AND -> OR fallback), BM25 column weights,
        min-max normalization, RRF fusion (when embedding available),
        plus recency and frequency boosts.

        Phase 1 retrieval polish (spec section 4.2):
        - Reciprocal Rank Fusion (RRF, k=60) over FTS + vec rankings.
        - Cross-encoder rerank applied at the server layer on top of the
          fused candidate set (this method returns the fused list).
        - Temporal decay via :meth:`_calc_recency`.
        - Importance boost: ``score *= (1 + importance)``.
        - Filters: ``context_type``, ``since``/``until`` ISO timestamps,
          ``min_importance``, ``include_archived`` (default ``False``).

        Args:
            query: Free-text query.
            embedding: Optional dense vector for semantic recall.
            category: Restrict to a single category bucket.
            tags: Restrict to memories whose JSON tags array intersects this list.
            limit: Maximum results returned.
            context_type: Filter by context_type column (mem_001 schema).
            since: ISO 8601 timestamp; only memories with
                ``updated_at >= since`` are returned.
            until: ISO 8601 timestamp; only memories with
                ``updated_at <= until`` are returned.
            min_importance: Drop rows whose ``importance < min_importance``.
            include_archived: When False (default), exclude soft-archived
                rows (``archived_at IS NOT NULL``).

        Returns:
            List of memory dicts sorted by relevance.
        """
        if tags and len(tags) > MAX_TAGS_FILTER:
            raise ValueError(
                f"Maximum of {MAX_TAGS_FILTER} tags allowed in search filter"
            )

        if isinstance(limit, int):
            limit = max(1, min(limit, 100))

        filter_kwargs = {
            "context_type": context_type,
            "since": since,
            "until": until,
            "min_importance": min_importance,
            "include_archived": include_archived,
            "subject": subject,
        }

        # 1. FTS5 search (over a wider candidate pool for downstream rerank).
        # Spec section 4.2: rerank tops at ~50 candidates -> top-N. Caller can
        # override via ``candidate_pool`` when it knows the rerank budget.
        pool = candidate_pool if candidate_pool is not None else max(limit * 10, 50)
        # An encrypted store has an empty FTS5 index, so it ranks keywords over
        # the decrypted candidate rows instead (see mnemo.keyword_scan).
        if self._cipher is None:
            results = self._search_fts(query, category, tags, pool, **filter_kwargs)
        else:
            results = self._search_encrypted_keywords(
                query, category, tags, pool, **filter_kwargs
            )

        # 2. Semantic search (if embedding provided)
        if embedding and self._vec_enabled:
            try:
                vec_fragments = ["WHERE v.embedding MATCH ?"]
                vec_params: list = [_serialize_f32(embedding, self._embedding_dims)]

                if category:
                    vec_fragments.append("AND m.category = ?")
                    vec_params.append(category)

                # Tags and subject are ciphertext in an encrypted store; they
                # are filtered in Python below, over the same k nearest rows
                # that SQL would have filtered after the KNN step.
                if tags and self._cipher is None:
                    vec_fragments.append(
                        "AND m.tags != '[]' AND json_valid(m.tags) AND EXISTS (SELECT 1 FROM json_each(m.tags) WHERE value IN (SELECT value FROM json_each(?)))"
                    )
                    vec_params.append(json.dumps(tags))

                sql_filters: dict[str, Any] = dict(filter_kwargs)
                if self._cipher is not None:
                    sql_filters["subject"] = None
                extra_sql, extra_params = self._build_filter_sql(**sql_filters)
                if extra_sql:
                    vec_fragments.append(extra_sql)
                    vec_params.extend(extra_params)

                vec_fragments.append("AND k = ? ORDER BY distance")
                vec_params.append(pool)

                vec_sql = """
                    SELECT v.id, v.distance
                    FROM memories_vec v
                    JOIN memories m ON v.id = m.id
                    placeholder_fragments
                """.replace("placeholder_fragments", " ".join(vec_fragments))

                with self._lock:
                    vec_rows = self._conn.execute(vec_sql, vec_params).fetchall()

                missing_ids = []
                vec_scores = {}
                for row in vec_rows:
                    mid = row["id"]
                    vec_score = max(0.0, 1.0 - row["distance"])
                    vec_scores[mid] = vec_score
                    if mid in results:
                        results[mid]["vec_score"] = vec_score
                    else:
                        missing_ids.append(mid)

                if missing_ids:
                    with self._lock:
                        missing_mems = self._conn.execute(
                            "SELECT * FROM memories WHERE id IN (SELECT value FROM json_each(?))",
                            (json.dumps(missing_ids),),
                        ).fetchall()
                    for mem in missing_mems:
                        data = self.decode_row(mem)
                        if self._cipher is not None and not (
                            self._matches_encrypted_filters(data, subject, tags)
                        ):
                            continue
                        mid = data["id"]
                        results[mid] = {
                            **data,
                            "fts_score": 0.0,
                            "vec_score": vec_scores[mid],
                        }
            except EncryptionError:
                # Tampered ciphertext must surface, never read as "no hits".
                raise
            except Exception as e:
                logger.debug(f"Vector search error: {e}")

        if not results:
            return []

        # 3. Compute hybrid score
        scored = self._compute_hybrid_scores(results)

        # 4. Slice to either ``limit`` (default) or up to ``candidate_pool``
        # when caller wants a wider rerank window. Access stats only update
        # for the rows we actually return, so a candidate_pool=50 request
        # does not silently inflate access counts on borderline matches.
        effective_top = limit if candidate_pool is None else min(pool, len(scored))
        top = scored[:effective_top]
        self._update_access_stats(top)

        # Clean up internal scores from output
        for m in top:
            m.pop("fts_score", None)
            m.pop("vec_score", None)
            m.pop("bm25_score", None)

        return top

    def _build_filter_sql(
        self,
        *,
        context_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        min_importance: float = 0.0,
        include_archived: bool = False,
        subject: str | None = None,
    ) -> tuple[str, list]:
        """Build the shared WHERE-tail used by FTS + vec search paths.

        Phase 1 retrieval polish filters live on the ``memories`` table only
        (mem_001 schema additions). Returns SQL fragment to append to a
        ``WHERE m.... = ...`` clause and the matching positional params so
        FTS and vec can compose the same filter set without duplication.

        Bitemporal (mem_003): always excludes superseded/soft-deleted rows
        (``valid_to IS NOT NULL``) -- neither FTS nor vec search should ever
        surface a historical version, regardless of ``include_archived``.
        """
        fragments = ["AND m.valid_to IS NULL"]
        params: list = []
        if context_type is not None:
            fragments.append("AND m.context_type = ?")
            params.append(context_type)
        if since is not None:
            fragments.append("AND m.updated_at >= ?")
            params.append(since)
        if until is not None:
            fragments.append("AND m.updated_at <= ?")
            params.append(until)
        if min_importance > 0.0:
            fragments.append("AND COALESCE(m.importance, 0.0) >= ?")
            params.append(float(min_importance))
        if not include_archived:
            fragments.append("AND m.archived_at IS NULL")
        if subject is not None:
            # MN-3 enforcement: scoped recall sees only its subject's rows.
            # NULL-subject (legacy/unattributed) rows stay invisible here;
            # subject=None keeps the unfiltered legacy view.
            fragments.append("AND m.subject = ?")
            params.append(subject)

        return " " + " ".join(fragments) if fragments else "", params

    def _search_fts(
        self,
        query: str,
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 5,
        *,
        context_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        min_importance: float = 0.0,
        include_archived: bool = False,
        subject: str | None = None,
    ) -> dict[str, dict]:
        """Execute FTS5 search with tiered queries and BM25 column weights.

        Combines PHRASE, AND, and OR tiers into a single UNION ALL query
        with a CTE to select only the highest-priority tier with matches,
        eliminating N+1 query overhead from the tiered fallback loop.
        """
        results: dict[str, dict] = {}
        fts_queries = _build_fts_queries(query)
        if not fts_queries:
            return results

        # Bolt Performance Optimization:
        # Deferred join pattern. We only select m.id in the inner query instead of
        # m.* to avoid evaluating large columns for rows that will be filtered out by LIMIT.
        filter_fragments = []
        filter_params: list = []
        if category:
            filter_fragments.append("AND m.category = ?")
            filter_params.append(category)
        if tags:
            filter_fragments.append(
                "AND m.tags != '[]' AND json_valid(m.tags) AND EXISTS (SELECT 1 FROM json_each(m.tags) WHERE value IN (SELECT value FROM json_each(?)))"
            )
            filter_params.append(json.dumps(tags))

        extra_sql, extra_params = self._build_filter_sql(
            context_type=context_type,
            since=since,
            until=until,
            min_importance=min_importance,
            include_archived=include_archived,
            subject=subject,
        )
        if extra_sql:
            filter_fragments.append(extra_sql)
            filter_params.extend(extra_params)

        filter_sql = " ".join(filter_fragments)

        # Bolt Performance Optimization:
        # Evaluate tiers sequentially in Python rather than combining them into a single
        # UNION ALL query. In SQLite, UNION ALL forces evaluation of all branches before
        # applying limits. Breaking early prevents expensive broad query execution (like OR).
        for fts_query in fts_queries:
            query_params = [fts_query] + filter_params + [limit * 3]
            fts_sql = """
                WITH best_tier AS (
                    SELECT m.id,
                           bm25(memories_fts, 0.0, 1.0, 0.0, 5.0) AS bm25_score
                    FROM memories_fts f
                    JOIN memories m ON f.id = m.id
                    WHERE memories_fts MATCH ? placeholder_filter_sql
                    ORDER BY bm25_score
                    LIMIT ?
                )
                SELECT m.*, b.bm25_score
                FROM best_tier b
                JOIN memories m ON b.id = m.id
                ORDER BY b.bm25_score
            """.replace("placeholder_filter_sql", filter_sql)

            try:
                with self._lock:
                    rows = self._conn.execute(fts_sql, query_params).fetchall()
                if rows:
                    for row in rows:
                        mid = row["id"]
                        results[mid] = {
                            **dict(row),
                            "fts_score": -row["bm25_score"],
                            "vec_score": 0.0,
                        }
                    break  # Found results in this tier, skip broader fallbacks
            except Exception as e:
                logger.error(f"FTS search failed for tier '{fts_query}': {e}")

        _normalize_fts_scores(results)
        return results

    def _search_encrypted_keywords(
        self,
        query: str,
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 5,
        *,
        context_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        min_importance: float = 0.0,
        include_archived: bool = False,
        subject: str | None = None,
    ) -> dict[str, dict]:
        """Keyword search for an encrypted store, without an FTS5 index.

        SQL applies every filter on plaintext columns (category, context
        type, time window, importance, archive and supersession state). The
        remaining rows are decrypted, filtered on subject and tags, and ranked
        by :func:`mnemo.keyword_scan.rank` with the FTS5 query tiers and bm25
        weights. Returns the same mapping shape as :meth:`_search_fts`.
        Cost is linear in the number of rows that pass the SQL filters.
        """
        results: dict[str, dict] = {}
        if not keyword_scan.build_tiers(query):
            return results

        sql = "SELECT m.* FROM memories m WHERE 1 = 1"
        params: list = []
        if category:
            sql += " AND m.category = ?"
            params.append(category)
        extra_sql, extra_params = self._build_filter_sql(
            context_type=context_type,
            since=since,
            until=until,
            min_importance=min_importance,
            include_archived=include_archived,
        )
        sql += extra_sql + " ORDER BY m.rowid"
        params.extend(extra_params)

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        candidates = [
            data
            for data in (self.decode_row(row) for row in rows)
            if self._matches_encrypted_filters(data, subject, tags)
        ]
        ranked = keyword_scan.rank(
            query, [(c["content"], c["tags"]) for c in candidates], limit * 3
        )
        for index, score in ranked:
            data = candidates[index]
            results[data["id"]] = {
                **data,
                "bm25_score": -score,
                "fts_score": score,
                "vec_score": 0.0,
            }
        _normalize_fts_scores(results)
        return results

    def _calc_recency(self, updated_at: str, now: datetime) -> float:
        """Calculate recency boost using configurable half-life.

        Phase 1 retrieval polish: spec section 4.2 calls for an exponential
        temporal decay using ``RECENCY_HALF_LIFE_DAYS``. We honour the
        per-instance ``self._recency_half_life`` (constructor argument) and
        compute ``2 ** (-days_old / half_life)`` so older memories smoothly
        decay toward 0 without hitting the boundary.
        """
        try:
            updated = datetime.fromisoformat(updated_at)
            days_old = (now - updated).total_seconds() / 86400
            return 2.0 ** (-days_old / self._recency_half_life)
        except (ValueError, KeyError, TypeError):
            return 0.0

    def _calc_frequency(self, access_count: int) -> float:
        """Calculate logarithmic frequency boost."""
        freq = math.log1p(access_count) / 10.0
        return min(freq, 1.0)

    @staticmethod
    def rrf_fuse(
        fts_results: list[str],
        vec_results: list[str],
        k: int = 60,
    ) -> list[tuple[str, float]]:
        """Reciprocal Rank Fusion over two ranked id lists.

        Standard RRF: ``score = sum(1 / (k + rank_in_list))`` where ``rank``
        is 1-based. ``k=60`` is the canonical default from
        Cormack et al. 2009; spec section 4.2 keeps that value so behaviour
        matches well-known information-retrieval baselines.

        Args:
            fts_results: Memory ids sorted by FTS rank (best first).
            vec_results: Memory ids sorted by vector similarity (best first).
            k: Smoothing constant (default 60).

        Returns:
            List of ``(id, fused_score)`` sorted by score descending.
        """
        scores: dict[str, float] = {
            mid: 1.0 / (k + rank) for rank, mid in enumerate(fts_results, start=1)
        }
        for rank, mid in enumerate(vec_results, start=1):
            if mid in scores:
                scores[mid] += 1.0 / (k + rank)
            else:
                scores[mid] = 1.0 / (k + rank)
        return sorted(scores.items(), key=operator.itemgetter(1), reverse=True)

    def _compute_hybrid_scores(self, results: dict[str, dict]) -> list[dict]:
        """Compute final scores combining FTS, vector, recency, and frequency."""
        now = datetime.now(UTC)
        scored: list[dict] = []
        recency_cache = {}
        freq_cache = {}

        has_vec = False
        for m in results.values():
            if "vec_score" in m and m["vec_score"] > 0:
                has_vec = True
                break

        if has_vec:
            k = 60
            fts_ranked = sorted(
                results.keys(),
                key=lambda x: results[x].get("fts_score", 0.0),
                reverse=True,
            )
            vec_ranked = sorted(
                results.keys(),
                key=lambda x: results[x].get("vec_score", 0.0),
                reverse=True,
            )
            scores: dict[str, float] = {
                mid: 1.0 / (k + rank) for rank, mid in enumerate(fts_ranked, start=1)
            }
            for rank, mid in enumerate(vec_ranked, start=1):
                scores[mid] += 1.0 / (k + rank)

            for mid, mem in results.items():
                rrf = scores[mid]

                updated_at = mem.get("updated_at", "")
                if updated_at not in recency_cache:
                    recency_cache[updated_at] = self._calc_recency(updated_at, now)

                ac = mem.get("access_count", 0)
                if ac not in freq_cache:
                    freq_cache[ac] = self._calc_frequency(ac)

                rrf_norm = rrf * (k + 1) / 2.0
                # Phase 1 retrieval polish: temporal decay multiplied into the
                # base, then importance boost ``score *= (1 + importance)``
                # so highly-rated memories outrank equal-relevance peers.
                base = (
                    rrf_norm * 0.7
                    + recency_cache[updated_at] * 0.2
                    + freq_cache[ac] * 0.1
                )

                imp = mem.get("importance")
                mem["score"] = base * (1.0 + float(imp)) if imp else base
                scored.append(mem)
        else:
            for mem in results.values():
                fts = mem.get("fts_score", 0.0)

                updated_at = mem.get("updated_at", "")
                if updated_at not in recency_cache:
                    recency_cache[updated_at] = self._calc_recency(updated_at, now)

                ac = mem.get("access_count", 0)
                if ac not in freq_cache:
                    freq_cache[ac] = self._calc_frequency(ac)

                base = (
                    fts * 0.6 + recency_cache[updated_at] * 0.3 + freq_cache[ac] * 0.1
                )

                imp = mem.get("importance")
                mem["score"] = base * (1.0 + float(imp)) if imp else base
                scored.append(mem)

        scored.sort(key=operator.itemgetter("score"), reverse=True)  # type: ignore[arg-type]
        return scored

    def _update_access_stats(self, top: list[dict]) -> None:
        """Increment access counts for returned search results."""
        if not top:
            return

        ids = [m["id"] for m in top]
        with self._lock, self._conn:
            self._conn.execute(
                """UPDATE memories
                    SET access_count = access_count + 1,
                        last_accessed = ?
                    WHERE id IN (SELECT value FROM json_each(?))""",
                (_now_iso(), json.dumps(ids)),
            )
            self._conn.commit()

    def list_memories(
        self,
        category: str | None = None,
        limit: int = 20,
        offset: int = 0,
        *,
        include_archived: bool = False,
    ) -> list[dict]:
        """List memories with optional category filter.

        Phase 1 archive policy: by default exclude soft-archived rows
        (``archived_at IS NOT NULL``). Pass ``include_archived=True`` to see
        them — symmetric with :meth:`search` semantics.

        Bitemporal (mem_003): always excludes superseded/soft-deleted rows
        (``valid_to IS NOT NULL``), independent of ``include_archived`` --
        archival and supersession are orthogonal states.
        """
        if isinstance(limit, int):
            limit = max(1, min(limit, 100))

        if category:
            if include_archived:
                sql = (
                    "SELECT * FROM memories "
                    "WHERE category = ? AND valid_to IS NULL "
                    "ORDER BY updated_at DESC "
                    "LIMIT ? OFFSET ?"
                )
            else:
                sql = (
                    "SELECT * FROM memories "
                    "WHERE category = ? AND archived_at IS NULL AND valid_to IS NULL "
                    "ORDER BY updated_at DESC "
                    "LIMIT ? OFFSET ?"
                )
            with self._lock:
                rows = self._conn.execute(sql, (category, limit, offset)).fetchall()
        else:
            if include_archived:
                sql = (
                    "SELECT * FROM memories "
                    "WHERE valid_to IS NULL "
                    "ORDER BY updated_at DESC "
                    "LIMIT ? OFFSET ?"
                )
            else:
                sql = (
                    "SELECT * FROM memories "
                    "WHERE archived_at IS NULL AND valid_to IS NULL "
                    "ORDER BY updated_at DESC "
                    "LIMIT ? OFFSET ?"
                )
            with self._lock:
                rows = self._conn.execute(sql, (limit, offset)).fetchall()

        return [self.decode_row(r) for r in rows]

    def get(self, memory_id: str, subject: str | None = None) -> dict | None:
        """Get a single memory by ID.

        Bitemporal (mem_003): only returns the row when it is still current
        (``valid_to IS NULL``). A superseded/soft-deleted id returns None --
        callers must switch to the id returned by :meth:`update`.

        MN-3 subject contract (same semantics as search): ``subject=None``
        is the unfiltered legacy view; a named subject sees only rows whose
        subject matches -- rows captured with a NULL subject (legacy or
        unattributed) are invisible to a scoped fetch.
        """
        sql = "SELECT * FROM memories WHERE id = ? AND valid_to IS NULL"
        params: list = [memory_id]
        if subject is not None and self._cipher is None:
            sql += " AND subject = ?"
            params.append(subject)
        with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
        if not row:
            return None
        data = self.decode_row(row)
        if subject is not None and data.get("subject") != subject:
            return None
        return data

    def update(
        self,
        memory_id: str,
        content: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        source: str | None = None,
        importance: float | None = None,
        embedding: list[float] | None = None,
    ) -> str | None:
        """Update an existing memory by superseding it with a new version.

        Bitemporal supersession (spec §6, mem_003): the old row is closed
        (``valid_to=now``, ``superseded_by=<new id>``) and a new row is
        inserted carrying forward every field not explicitly overridden here
        (plus fresh ``created_at``/``updated_at``/``last_accessed`` and a
        reset ``access_count``). This makes ``update`` id-changing: callers
        must switch to the returned id for subsequent get/search/delete
        calls -- the old id no longer resolves via :meth:`get`/:meth:`search`
        /:meth:`list_memories` (see call-site filters), only via
        ``temporal.queries.memories_as_of`` for historical ``as_of`` lookups.

        Returns:
            The new memory's id, or ``None`` if ``memory_id`` was not found
            (already deleted or already superseded).

        Raises:
            ValueError: If content exceeds MAX_CONTENT_LENGTH.
        """
        if content is not None and len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(
                f"Content length {len(content)} exceeds limit of {MAX_CONTENT_LENGTH}"
            )

        now = _now_iso()
        new_id = uuid.uuid4().hex

        # Supersession is several writes on a connection opened in legacy
        # autocommit-by-statement mode, so every exit path has to close the
        # transaction the first write opens -- otherwise a half-applied
        # supersession stays pending and the next unrelated commit() makes it
        # durable, leaving the predecessor closed against a successor row that
        # was never written.
        with self._lock:
            try:
                # Close the predecessor and read it back in ONE statement. Split
                # into SELECT-then-UPDATE, a competing writer can supersede the
                # same row in between, which leaves two live rows and a broken
                # supersession chain; the ``valid_to IS NULL`` guard is what makes
                # the loser of that race fall through to the not-found branch.
                old_row = self._conn.execute(
                    "UPDATE memories SET valid_to = ?, superseded_by = ? "
                    "WHERE id = ? AND valid_to IS NULL RETURNING *",
                    (now, new_id, memory_id),
                ).fetchone()
                if old_row is None:
                    # pysqlite opens a write transaction for an UPDATE even when it
                    # matches zero rows. Returning without closing it would hold
                    # the database locked against every other writer for as long as
                    # this connection lives.
                    self._conn.rollback()
                    return None

                # RETURNING yields the row AFTER the update was applied, so the
                # two columns it just wrote have to be reset for the successor.
                # In an encrypted store every value is bound to its row id, so
                # the predecessor is decrypted here and re-encrypted below
                # under the successor's id.
                new_row = self.decode_row(old_row)
                new_row["id"] = new_id
                new_row["created_at"] = now
                new_row["updated_at"] = now
                new_row["last_accessed"] = now
                new_row["access_count"] = 0
                new_row["valid_from"] = now
                new_row["valid_to"] = None
                new_row["superseded_by"] = None
                if "commit_sha" in new_row:
                    new_row["commit_sha"] = None

                if content is not None:
                    new_row["content"] = content
                if category is not None:
                    new_row["category"] = category
                if tags is not None:
                    # Bolt Performance Optimization:
                    # Prevent expensive json.dumps calls for the default empty list.
                    new_row["tags"] = "[]" if not tags else json.dumps(tags)
                if source is not None:
                    new_row["source"] = source
                if importance is not None:
                    new_row["importance"] = max(0.0, min(1.0, importance))

                new_row = self._seal_row(new_id, new_row)
                columns = list(new_row.keys())
                column_list = ", ".join(columns)
                placeholders = ", ".join("?" for _ in columns)

                self._conn.execute(
                    f"INSERT INTO memories ({column_list}) VALUES ({placeholders})",
                    [new_row[c] for c in columns],
                )

                # Embedding: an explicit value replaces; otherwise carry the old
                # vector forward under the new id so semantic search keeps working
                # for metadata-only edits (content-only re-embedding is the
                # caller's responsibility, e.g. server._handle_update).
                if self._vec_enabled:
                    # memories_vec is a virtual table; it does not support RETURNING.
                    old_vec = self._conn.execute(
                        "SELECT embedding FROM memories_vec WHERE id = ?", (memory_id,)
                    ).fetchone()
                    self._conn.execute(
                        "DELETE FROM memories_vec WHERE id = ?", (memory_id,)
                    )
                    if embedding:
                        self._conn.execute(
                            "INSERT INTO memories_vec (id, embedding) VALUES (?, ?)",
                            (new_id, _serialize_f32(embedding, self._embedding_dims)),
                        )
                    elif old_vec is not None:
                        self._conn.execute(
                            "INSERT INTO memories_vec (id, embedding) VALUES (?, ?)",
                            (new_id, old_vec["embedding"]),
                        )

                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

        logger.info(f"[AUDIT] update id={memory_id} -> new_id={new_id}")
        return new_id

    def delete(self, memory_id: str, *, subject: str | None = None) -> bool:
        """Delete a memory by ID, optionally scoped to ``subject``. Returns True if found and deleted.

        Bitemporal (mem_003): soft-closes the row (``valid_to=now``) instead
        of physically removing it, so it drops out of get/search/list (same
        observable behaviour as a hard delete) while remaining available to
        ``temporal.queries.memories_as_of`` for historical ``as_of`` lookups
        and to ``history_for_entity`` for audit trails. ``superseded_by``
        stays NULL -- deletion has no forward pointer, unlike ``update``.
        """
        sql = "UPDATE memories SET valid_to = ? WHERE id = ? AND valid_to IS NULL"
        params: list[object] = [_now_iso(), memory_id]
        if subject is not None and self._cipher is None:
            sql += " AND subject = ?"
            params.append(subject)

        with self._lock, self._conn:
            if (
                subject is not None
                and self._cipher is not None
                and not self._encrypted_subject_matches(
                    memory_id, subject, "valid_to IS NULL"
                )
            ):
                return False
            cursor = self._conn.execute(sql, params)

            if cursor.rowcount == 0:
                return False

            if self._vec_enabled:
                self._conn.execute(
                    "DELETE FROM memories_vec WHERE id = ?", (memory_id,)
                )

            self._conn.commit()
        logger.info(f"[AUDIT] delete id={memory_id}")
        return True

    def soft_archive(self, memory_id: str, *, subject: str | None = None) -> bool:
        """Soft-archive a single memory (set ``archived_at=now``) with optional subject scoping."""
        now = _now_iso()
        sql = "UPDATE memories SET archived_at = ?, last_accessed = ? WHERE id = ? AND archived_at IS NULL"
        params: list[object] = [now, now, memory_id]
        if subject is not None and self._cipher is None:
            sql += " AND subject = ?"
            params.append(subject)
        with self._lock, self._conn:
            if (
                subject is not None
                and self._cipher is not None
                and not self._encrypted_subject_matches(
                    memory_id, subject, "archived_at IS NULL"
                )
            ):
                return False
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
        if cursor.rowcount > 0:
            logger.info(f"[AUDIT] soft_archive id={memory_id} subject={subject!r}")
            return True
        return False

    def set_confidence(self, memory_id: str, confidence: float) -> bool:
        """Update the ``confidence`` trust score ``[0.0, 1.0]`` for a memory."""
        clamped = max(0.0, min(1.0, float(confidence)))
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE memories SET confidence = ? WHERE id = ?",
                (clamped, memory_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def detect_contradictions(
        self,
        content: str,
        *,
        subject: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Find active memories that appear to contradict ``content``.

        Uses deterministic polarity inversion (negation markers in EN/VI or
        preference/state verbs) plus lexical overlap over existing active rows.
        """
        neg_cues = (
            "not ",
            "never ",
            "no longer ",
            "stopped ",
            "instead of ",
            "switched from ",
            "không ",
            "khong ",
            "ngừng ",
            "thay vì ",
        )
        raw_tokens = [
            tok.lower()
            for tok in re.findall(r"[A-Za-z0-9_.\-À-ỹ]{3,}", content)
            if tok.lower()
            not in {
                "the",
                "and",
                "for",
                "with",
                "not",
                "never",
                "longer",
                "instead",
                "switched",
                "from",
                "stopped",
                "use",
                "using",
                "prefer",
                "prefers",
                "không",
                "khong",
                "dùng",
                "dung",
                "thay",
                "ngừng",
                "đã",
                "của",
            }
        ]
        keywords = list(dict.fromkeys(raw_tokens))[:6]
        if not keywords:
            return []
        candidates = self.search(
            " ".join(keywords),
            limit=max(1, min(limit * 2, 20)),
            subject=subject,
        )
        new_neg = any(cue in content.lower() for cue in neg_cues)
        contradictions: list[dict] = []
        for cand in candidates:
            cand_text = str(cand.get("content", ""))
            cand_low = cand_text.lower()
            overlap = [k for k in keywords if k in cand_low]
            if not overlap:
                continue
            cand_neg = any(cue in cand_low for cue in neg_cues)
            if cand_neg != new_neg or (
                len(overlap) >= 2 and cand_text.strip() != content.strip()
            ):
                contradictions.append(
                    {
                        "id": cand["id"],
                        "content": cand_text,
                        "overlap": overlap,
                        "polarity_conflict": cand_neg != new_neg,
                    }
                )
        return contradictions[:limit]

    def stats(self) -> dict:
        """Get database statistics.

        Bitemporal (mem_003): counts/aggregates only current rows
        (``valid_to IS NULL``) -- superseded/soft-deleted history is not
        double-counted into totals or category breakdowns.
        """
        with self._lock:
            categories = self._conn.execute(
                "SELECT category, COUNT(*) as cnt, MAX(updated_at) as max_updated FROM memories "
                "WHERE valid_to IS NULL GROUP BY category ORDER BY cnt DESC"
            ).fetchall()

        total = sum(row["cnt"] for row in categories)
        last_updated = max(
            (
                row["max_updated"]
                for row in categories
                if row["max_updated"] is not None
            ),
            default=None,
        )

        return {
            "total_memories": total,
            "categories": {r["category"]: r["cnt"] for r in categories},
            "last_updated": last_updated,
            "vec_enabled": self._vec_enabled,
            "db_path": str(self._db_path),
        }

    def export_jsonl(self) -> tuple[str, int]:
        """Export all memories as JSONL string.

        Returns:
            Tuple of (jsonl_string, count_of_records).
        """
        if self._cipher is not None:
            return self._export_encrypted_jsonl()

        # Bolt Performance Optimization: Offload JSON construction to SQLite.
        # Avoids O(N) Python dict creations and json.dumps calls, resulting in ~78% faster exports.
        #
        # The argument list is generated from MEMORY_COLUMNS so the export cannot
        # fall behind the schema; it is built once at import time from our own
        # identifiers and never sees caller input.
        query = f"""
            SELECT json_object({_EXPORT_JSON_OBJECT_ARGS}) as json_data
            FROM memories
            ORDER BY created_at
        """
        with self._lock:
            cursor = self._conn.execute(query)
            output = io.StringIO()
            count = 0

            for row in cursor:
                output.write(row[0])
                output.write("\n")
                count += 1

        return output.getvalue(), count

    def _export_encrypted_jsonl(self) -> tuple[str, int]:
        """Export an encrypted store as decrypted JSONL.

        Produces the same records as the plaintext export: columns in
        :data:`MEMORY_COLUMNS` order, ``tags`` as a JSON array, compact
        separators and non-ASCII text kept as is (what SQLite's
        ``json_object`` emits). The output is plaintext; protect it.
        """
        columns = ", ".join(MEMORY_COLUMNS)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {columns} FROM memories ORDER BY created_at"
            ).fetchall()
            output = io.StringIO()
            for row in rows:
                record = self.decode_row(row)
                record["tags"] = json.loads(record["tags"])
                output.write(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                )
                output.write("\n")
        return output.getvalue(), len(rows)

    def _clear_for_import(self, mode: str) -> None:
        """Clear memories if mode is 'replace'."""
        with self._lock:
            if mode == "replace":
                self._conn.execute("DELETE FROM memories")
                if self._vec_enabled:
                    self._conn.execute("DELETE FROM memories_vec")

    def _parse_import_data(self, data: str | list | dict) -> tuple[list[dict], int]:
        """Parse input data into a list of dictionaries."""
        rejected = 0
        if isinstance(data, list):
            return data, 0
        if isinstance(data, dict):
            return [data], 0
        if isinstance(data, str):
            items = []
            for line in data.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    rejected += 1
            return items, rejected
        return [], 0

    def _process_import_batch(
        self, batch_items: list[dict], now: str
    ) -> tuple[list[tuple], int]:
        """Validate and format a batch of memories for database insertion."""
        to_insert = []
        rejected = 0
        for mem in batch_items:
            try:
                memory_id = mem.get("id", uuid.uuid4().hex)
                content = mem.get("content", "")
                if not content or len(content) > MAX_CONTENT_LENGTH:
                    logger.warning(
                        f"[AUDIT] import rejected id={memory_id} "
                        f"len={len(content)} exceeds {MAX_CONTENT_LENGTH}"
                    )
                    rejected += 1
                    continue
                tags = mem.get("tags", [])

                # Bolt Performance Optimization:
                # Prevent expensive json.dumps calls for the default empty list.
                tags_json = (
                    "[]"
                    if tags == []
                    else (json.dumps(tags) if isinstance(tags, list) else tags)
                )

                derived = {"id": memory_id, "content": content, "tags": tags_json}
                row = {}
                for column in MEMORY_COLUMNS:
                    if column in _IMPORT_DERIVED_COLUMNS:
                        row[column] = derived[column]
                    elif column in _IMPORT_TIMESTAMP_COLUMNS:
                        row[column] = mem.get(column, now)
                    else:
                        row[column] = mem.get(column, _IMPORT_DEFAULTS[column])
                if self._cipher is not None:
                    # Values are bound to the row id, so it has to be text;
                    # a non-text user-data value is rejected, not stored.
                    if not isinstance(memory_id, str):
                        raise TypeError("memory id must be text to encrypt")
                    row = self._seal_row(memory_id, row)
                to_insert.append(tuple(row[column] for column in MEMORY_COLUMNS))
            except Exception:
                rejected += 1
                continue
        return to_insert, rejected

    def _execute_import_batch(
        self, to_insert: list[tuple], mode: str
    ) -> tuple[int, int]:
        """Execute the batch insertion and return (imported, skipped) counts."""
        if not to_insert:
            return 0, 0
        with self._lock:
            cursor = self._conn.cursor()
            # Column list and placeholders come from MEMORY_COLUMNS, never from the
            # imported records, so the statement carries no caller-controlled text.
            columns = ", ".join(MEMORY_COLUMNS)
            placeholders = ", ".join("?" for _ in MEMORY_COLUMNS)
            op = "REPLACE" if mode == "replace" else "IGNORE"
            sql = f"INSERT OR {op} INTO memories ({columns}) VALUES ({placeholders})"
            cursor.executemany(sql, to_insert)
            imported = cursor.rowcount
            skipped = len(to_insert) - imported if mode != "replace" else 0
        return imported, skipped

    def import_jsonl(self, data: str | list | dict, mode: str = "merge") -> dict:
        """Import memories from JSONL string.

        Args:
            data: JSONL string (one JSON object per line).
            mode: "merge" (skip existing) or "replace" (clear + import).

        Returns:
            Dict with import stats (imported, skipped, rejected).
        """
        with self._lock, self._conn:
            self._clear_for_import(mode)
            items, rejected = self._parse_import_data(data)
            imported = 0
            skipped = 0
            BATCH_SIZE = 900
            now = _now_iso()
            for i in range(0, len(items), BATCH_SIZE):
                batch_items = items[i : i + BATCH_SIZE]
                to_insert, batch_rejected = self._process_import_batch(batch_items, now)
                rejected += batch_rejected
                batch_imported, batch_skipped = self._execute_import_batch(
                    to_insert, mode
                )
                imported += batch_imported
                skipped += batch_skipped
            self._conn.commit()
        if imported > 0:
            logger.info(f"[AUDIT] import count={imported} mode={mode}")
        return {"imported": imported, "skipped": skipped, "rejected": rejected}

    def archive_old_memories(
        self, days: int = 90, importance_threshold: float = 0.3
    ) -> int:
        """Soft-archive old, low-importance memories using ``archived_at``.

        Phase 1 archive policy (spec section 4.2): rather than moving rows
        to a separate ``archived_memories`` table (legacy pre-T3 behaviour),
        flip the ``archived_at`` column added by ``mem_001_context_types``.
        Search/list default to ``include_archived=False`` so archived rows
        disappear from normal recall while staying restorable.

        Args:
            days: Archive when ``last_accessed < now - days``.
            importance_threshold: Archive only when ``importance < threshold``.

        Returns:
            Count of newly archived rows (already-archived rows are skipped).
        """
        with self._lock, self._conn:
            cursor = self._conn.cursor()

            # Bolt Performance Optimization:
            # Replaced SELECT + Python loop + executemany with a single pure SQL UPDATE.
            # This completely bypasses Python's runtime memory allocation and execution
            # overhead for date math and iteration, executing entirely in SQLite.
            now = _now_iso()
            cursor.execute(
                """UPDATE memories
                   SET archived_at = ?
                   WHERE archived_at IS NULL
                     AND last_accessed < datetime('now', ?)
                     AND importance < ?""",
                (now, f"-{days} days", importance_threshold),
            )
            count = cursor.rowcount
            if count > 0:
                self._conn.commit()
                logger.info(f"[AUDIT] archived count={count} mode=soft")
        return count

    def archive_by_score(
        self,
        archive_after_days: int | None = None,
        score_threshold: float = 1.0,
    ) -> int:
        """Archive memories whose ``archive_score > score_threshold``.

        Implements the Phase 1 spec scoring formula::

            recency_factor = days_since_updated / archive_after_days
            archive_score = recency_factor * (1 - importance)

        A row is archived (``archived_at`` set) when ``archive_score`` strictly
        exceeds ``score_threshold`` (default 1.0). With the default threshold:

        - Recently-updated rows (``recency_factor < 1``) never archive.
        - High-importance rows (``importance ~ 1``) need a much higher
          recency_factor to flip — they survive longer than low-importance
          neighbours of the same age.

        Args:
            archive_after_days: Denominator for ``recency_factor``. Defaults
                to ``settings.archive_after_days`` (90 days) when ``None``.
            score_threshold: Boundary above which a row is archived (>1.0).

        Returns:
            Count of newly archived rows.
        """
        if archive_after_days is None:
            try:
                from mnemo.config import settings as _settings

                archive_after_days = int(_settings.archive_after_days)
            except Exception:
                archive_after_days = 90
        archive_after_days = max(1, int(archive_after_days))

        with self._lock, self._conn:
            cursor = self._conn.cursor()
            archive_ts = _now_iso()

            # Bolt Performance Optimization:
            # Replaced Python row iteration, datetime parsing, and executemany
            # with a single native SQL UPDATE statement.
            # This completely bypasses Python's runtime overhead, leveraging SQLite's
            # julianday() to compute dates natively.
            query = """
            UPDATE memories
            SET archived_at = ?
            WHERE archived_at IS NULL
            AND (
                MAX(0.0, julianday('now') - julianday(updated_at)) / ?
            ) * (1.0 - MAX(0.0, MIN(1.0, COALESCE(importance, 0.0)))) > ?
            """

            cursor.execute(
                query, (archive_ts, float(archive_after_days), score_threshold)
            )
            count = cursor.rowcount

            if count > 0:
                self._conn.commit()
                logger.info(
                    f"[AUDIT] archived_by_score count={count} "
                    f"after_days={archive_after_days} threshold={score_threshold}"
                )
        return count

    def restore_memory(self, memory_id: str) -> bool:
        """Restore an archived memory back to active.

        Phase 1: prefer the new soft-archive path (clear ``archived_at`` on
        the row in ``memories``). Fall back to the legacy ``archived_memories``
        copy-back behaviour for backward compatibility with pre-mem_001 DBs
        that still hold rows in the side table.
        """
        with self._lock, self._conn:
            cursor = self._conn.cursor()
            now = _now_iso()

            # Bolt Performance Optimization:
            # Avoided N+1 SELECT overhead by executing UPDATE directly and checking rowcount.
            # This completely bypasses Python's memory allocation for the SELECT result.
            # New path: row exists in memories and is soft-archived.
            cursor.execute(
                "UPDATE memories SET archived_at = NULL, last_accessed = ? "
                "WHERE id = ? AND archived_at IS NOT NULL",
                (now, memory_id),
            )
            if cursor.rowcount > 0:
                self._conn.commit()
                logger.info(f"[AUDIT] restore id={memory_id} mode=soft")
                return True

            # Legacy path: row was hard-moved to archived_memories.
            legacy = cursor.execute(
                "SELECT * FROM archived_memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if not legacy:
                return False
            cursor.execute(
                """INSERT OR REPLACE INTO memories
                   (id, content, category, tags, source, importance,
                    created_at, updated_at, access_count, last_accessed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    legacy[0],
                    legacy[1],
                    legacy[2],
                    legacy[3],
                    legacy[4],
                    legacy[5],
                    legacy[6],
                    now,
                    legacy[8],
                    now,
                ),
            )
            cursor.execute("DELETE FROM archived_memories WHERE id = ?", (memory_id,))
            self._conn.commit()
            logger.info(f"[AUDIT] restore id={memory_id} mode=legacy")
            return True

    def list_archived(self, limit: int = 20) -> list[dict]:
        """List archived memories from BOTH the soft-archive column and the
        legacy ``archived_memories`` side table.

        Soft-archived rows live in ``memories WHERE archived_at IS NOT NULL``;
        legacy rows live in the standalone ``archived_memories`` table from
        the pre-mem_001 hard-archive code path. Returning both keeps existing
        behaviour intact while exposing the new soft-archive lifecycle.
        """
        if isinstance(limit, int):
            limit = max(1, min(limit, 100))
        with self._lock:
            cursor = self._conn.cursor()

            # Bolt Performance Optimization:
            # Offload merging and pagination entirely to SQLite via UNION ALL.
            # This completely bypasses the O(N log N) Python-side file-sort overhead
            # and unnecessary memory allocation for rows that would be discarded.
            rows = cursor.execute(
                """
                SELECT id, content, category, tags, importance, archived_at
                FROM (
                    SELECT id, content, category, tags, importance, archived_at
                    FROM memories
                    WHERE archived_at IS NOT NULL
                    UNION ALL
                    SELECT id, content, category, tags, importance, archived_at
                    FROM archived_memories
                )
                ORDER BY archived_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        merged = []
        for r in rows:
            # Archived rows in both tables keep their ids, so the values
            # decrypt with the same row binding.
            plain = self.decode_row({"id": r[0], "content": r[1], "tags": r[3]})
            tags_val = plain["tags"]
            merged.append(
                {
                    "id": r[0],
                    "content": plain["content"][:200],
                    "category": r[2],
                    "tags": [] if tags_val == "[]" else json.loads(tags_val),
                    "importance": r[4],
                    "archived_at": r[5],
                }
            )

        return merged

    def check_duplicate(self, content: str, threshold: float = 0.9) -> dict | None:
        """Check if similar memory exists. Returns match info or None."""
        words = content.split()[:10]
        query = " ".join(words)
        if not query.strip():
            return None
        results = self.search(query=query, limit=3)

        if not results:
            return None

        top = results[0]
        content_words = set(content.lower().split())
        top_words = set(top["content"].lower().split())
        if not content_words:
            return None
        overlap = len(content_words & top_words) / max(
            len(content_words), len(top_words)
        )

        if overlap > threshold:
            return {
                "duplicate": True,
                "existing_id": top["id"],
                "existing_content": top["content"][:200],
                "similarity": round(overlap, 2),
            }
        elif overlap > 0.7:
            return {
                "similar": True,
                "existing_id": top["id"],
                "existing_content": top["content"][:200],
                "similarity": round(overlap, 2),
            }
        return None

    def update_importance(self, memory_id: str, importance: float) -> bool:
        """Update importance score for a memory."""
        importance = max(0.0, min(1.0, importance))
        with self._lock, self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "UPDATE memories SET importance = ? WHERE id = ?",
                (importance, memory_id),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            self._conn.close()

    def _run_migrations(self) -> None:
        """Run Alembic migrations to head, with backup-before-migrate.

        Workflow:
        1. Inspect ``alembic_version`` via raw SQL on the existing connection.
           Absent table => either a fresh DB (just initialised by
           ``_init_schema``, will be stamped) or a pre-Alembic DB.
        2. If a target migration would actually run (current revision != head),
           copy ``memories.db`` to ``memories.db.bak.<unix-ts>`` first.
        3. Stamp ``baseline_001`` for unstamped DBs, then call
           ``alembic.command.upgrade(config, "head")``.

        Any failure is logged via loguru and swallowed so server startup is
        not blocked by migration issues.
        """
        if not _ALEMBIC_INI_PATH.exists():
            logger.debug(
                f"Alembic config not found at {_ALEMBIC_INI_PATH}, "
                "skipping migrations (likely a wheel install without alembic dir)"
            )
            return

        try:
            from alembic import command
            from alembic.config import Config
            from alembic.script import ScriptDirectory
        except ImportError as e:  # pragma: no cover - dep is required at runtime
            logger.warning(f"Alembic import failed, skipping migrations: {e}")
            return

        try:
            with self._lock:
                self._conn.commit()  # Flush any pending baseline writes

            cfg = Config(str(_ALEMBIC_INI_PATH))
            cfg.set_main_option("script_location", str(_ALEMBIC_SCRIPT_LOCATION))
            cfg.set_main_option(
                "sqlalchemy.url", f"sqlite:///{self._db_path.resolve().as_posix()}"
            )

            script = ScriptDirectory.from_config(cfg)
            head_rev = script.get_current_head()

            current_rev = self._read_alembic_version()

            if current_rev == head_rev:
                logger.debug(f"DB already at head revision {head_rev}")
                return

            if current_rev is None:
                # Pre-Alembic / freshly initialised database: stamp baseline_001
                # so subsequent upgrades only apply migrations after baseline.
                logger.info("Stamping database at baseline_001")
                command.stamp(cfg, "baseline_001")
                current_rev = "baseline_001"
                if current_rev == head_rev:
                    return

            if self._cipher is not None:
                # Guard triggers name the current columns, and a trigger that
                # names a missing column breaks ALTER TABLE ... RENAME. They are
                # reinstalled against the migrated schema right after.
                with self._lock, self._conn:
                    drop_encryption_guards(self._conn)

            # Backup before applying any forward migration
            self._backup_db_file()

            logger.info(f"Running Alembic upgrade: {current_rev} -> {head_rev}")
            command.upgrade(cfg, "head")
            logger.info(f"Alembic upgrade complete (head={head_rev})")

            # Phase 3 post-migration backfill: commit_sha + valid_from for
            # legacy memory rows. Run on the DB's own connection to avoid
            # the WAL conflict that occurs when Alembic's separate
            # connection updates rows while FTS5 triggers are active.
            self._backfill_phase3_temporal()
        except Exception as e:  # pragma: no cover - runtime guard
            logger.warning(f"Alembic migration failed: {e}")

    def _backfill_phase3_temporal(self) -> None:
        """Backfill ``commit_sha`` and ``valid_from`` for pre-Phase-3 rows.

        ``commit_sha`` <- ``sha256(content)`` so the audit trail (Phase 3
        Task 5) can verify lineage of legacy rows from the moment of
        migration.

        ``valid_from`` <- ``created_at`` so bitemporal queries against
        legacy data return the row from its original creation timestamp
        (otherwise the column default ``CURRENT_TIMESTAMP`` would set
        valid_from = migration time, breaking ``as_of`` queries against
        historical data).
        """
        import hashlib

        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
                ).fetchone()
                if cursor is None:
                    return
                cols = {
                    row[1]
                    for row in self._conn.execute(
                        "PRAGMA table_info(memories)"
                    ).fetchall()
                }
                if "commit_sha" not in cols or "valid_from" not in cols:
                    # Phase 3 columns missing -- migration did not run.
                    return

                rows = self._conn.execute(
                    "SELECT id, content, created_at FROM memories "
                    "WHERE commit_sha IS NULL OR valid_from IS NULL"
                ).fetchall()
                if not rows:
                    return

                # Legacy rows may not be indexed in memories_fts (the FTS5
                # trigger only fires from this connection's INSERT). Force
                # an FTS rebuild before running UPDATEs so the AFTER UPDATE
                # trigger does not corrupt the contentless FTS index with a
                # DELETE on an unindexed rowid ("database disk image is
                # malformed" on Windows SQLite). An encrypted store has no FTS
                # triggers and must keep its index empty, so it skips this.
                if self._cipher is None:
                    try:
                        self._conn.execute(
                            "INSERT INTO memories_fts(memories_fts) VALUES('rebuild')"
                        )
                        self._conn.commit()
                    except Exception:
                        pass

                batch = []
                for row in rows:
                    is_row = isinstance(row, sqlite3.Row)
                    row_id = row["id"] if is_row else row[0]
                    content = row["content"] if is_row else row[1]
                    created_at = row["created_at"] if is_row else row[2]
                    if self._cipher is not None:
                        content = self._cipher.decrypt(row_id, "content", content)
                    digest = hashlib.sha256((content or "").encode("utf-8")).hexdigest()
                    # The digest would confirm a guessed content, so it is
                    # stored encrypted like the content itself.
                    batch.append(
                        (self._seal(row_id, "commit_sha", digest), created_at, row_id)
                    )

                self._conn.executemany(
                    "UPDATE memories SET "
                    "  commit_sha = COALESCE(commit_sha, ?), "
                    "  valid_from = COALESCE(valid_from, ?) "
                    "WHERE id = ?",
                    batch,
                )
                self._conn.commit()
                logger.info(
                    f"Phase 3 backfill: commit_sha + valid_from for {len(rows)} legacy rows"
                )
            except Exception as e:
                # The failure is swallowed below, so no caller's context
                # manager will see it: undo the partial backfill here.
                self._conn.rollback()
                logger.warning(f"Phase 3 temporal backfill failed: {e}")

    def _read_alembic_version(self) -> str | None:
        """Return the current ``alembic_version`` revision, or ``None`` if unstamped."""
        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone()
            except sqlite3.OperationalError:
                return None
        if not row:
            return None
        return row[0] if not isinstance(row, sqlite3.Row) else row["version_num"]

    def _backup_db_file(self) -> Path | None:
        """Copy the SQLite DB file to ``<path>.bak.<unix-ts>`` and return the path.

        Returns ``None`` if the source file does not exist (fresh in-memory DB
        in tests). WAL/SHM sidecars are also copied when present so the backup
        is internally consistent.
        """
        if not self._db_path.exists():
            return None

        ts = int(time.time())
        backup_path = self._db_path.with_suffix(self._db_path.suffix + f".bak.{ts}")
        try:
            shutil.copy2(self._db_path, backup_path)
            for sidecar in ("-wal", "-shm"):
                src = self._db_path.with_suffix(self._db_path.suffix + sidecar)
                if src.exists():
                    shutil.copy2(
                        src, backup_path.with_suffix(backup_path.suffix + sidecar)
                    )
            logger.info(f"DB backup created at {backup_path}")
            return backup_path
        except Exception as e:  # pragma: no cover - runtime guard
            logger.warning(f"DB backup failed: {e}")
            return None
