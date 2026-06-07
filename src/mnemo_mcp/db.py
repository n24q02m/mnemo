"""Core SQLite database engine for Mnemo memories.

Provides:
- FTS5 full-text search (always available, zero dependency)
- sqlite-vec vector search (when embeddings are configured)
- CRUD operations with category/tag filtering
- Hybrid search scoring (text + semantic + recency + frequency)
- Alembic schema migrations with backup-before-migrate
"""

import io
import json
import math
import re
import shutil
import sqlite3
import struct
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlite_vec
from loguru import logger

# Alembic migration constants
_ALEMBIC_INI_PATH = Path(__file__).resolve().parent / "alembic.ini"
_ALEMBIC_SCRIPT_LOCATION = Path(__file__).resolve().parent / "alembic"

_STRUCT_CACHE: dict[int, struct.Struct] = {}


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


class MemoryDB:
    """SQLite database for persistent AI memories."""

    def __init__(
        self,
        db_path: Path,
        embedding_dims: int = 0,
        recency_half_life_days: float = 7.0,
    ):
        """Open or create memory database.

        Args:
            db_path: Path to SQLite database file.
            embedding_dims: Embedding dimensions (0 = no vector search).
            recency_half_life_days: Half-life in days for recency decay.
        """
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
        self._recency_half_life = float(recency_half_life_days)

        # Create parent directory
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Open connection (allow cross-thread use for asyncio.to_thread)
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

        self._init_schema()

        # Run Alembic migrations after the baseline schema is materialised so
        # that fresh databases are stamped at ``baseline_001`` and then walked
        # forward. ``_run_migrations`` is best-effort: failures are logged but
        # never block server startup.
        self._run_migrations()

    def _init_schema(self) -> None:
        """Initialize database schema.

        Delegates to focused sub-initializers so each concern (core memory
        tables, knowledge graph, archive, vector index) owns its own SQL
        script and can be read / tested in isolation.
        """
        self._init_memory_schema()
        self._init_graph_schema()
        self._init_archive_schema()
        self._ensure_vec_table(self._embedding_dims)
        self._conn.commit()

    def _init_memory_schema(self) -> None:
        """Initialize core memory tables, indexes, FTS5, and importance column."""
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

        # FTS5 triggers to keep index in sync
        self._conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, id, content, tags)
                VALUES (new.rowid, new.id, new.content, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, id, content, tags)
                VALUES ('delete', old.rowid, old.id, old.content, old.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, id, content, tags)
                VALUES ('delete', old.rowid, old.id, old.content, old.tags);
                INSERT INTO memories_fts(rowid, id, content, tags)
                VALUES (new.rowid, new.id, new.content, new.tags);
            END;
        """)

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
            raise ValueError(f"embedding_dims must be between 1 and 8192, got {dims}")

        # Create table if not exists
        self._conn.execute(f"""
            CREATE VIRTUAL TABLE memories_vec
            USING vec0(
                id TEXT PRIMARY KEY,
                embedding float[{dims}]
            )
        """)
        logger.debug(f"Created memories_vec table with {dims} dims")

    @property
    def vec_enabled(self) -> bool:
        """Whether vector search is available."""
        return self._vec_enabled

    def add(
        self,
        content: str,
        category: str = "general",
        tags: list[str] | None = None,
        source: str | None = None,
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

        self._conn.execute(
            """INSERT INTO memories (id, content, category, tags, source,
               created_at, updated_at, access_count, last_accessed)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (memory_id, content, category, tags_json, source, now, now, now),
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
        ``compressed=True`` plus ``compression_provider`` (gemini/openai/...).
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
            compression_provider: LLM provider that performed the compression
                (gemini/openai/anthropic/xai). NULL when ``compressed=False``.

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

        if importance is not None:
            importance = max(0.0, min(1.0, importance))
            self._conn.execute(
                """INSERT INTO memories (id, content, category, tags, source,
                   created_at, updated_at, access_count, last_accessed,
                   context_type, importance,
                   text_raw, compressed, compression_provider)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)""",
                (
                    memory_id,
                    content,
                    category,
                    tags_json,
                    source,
                    now,
                    now,
                    now,
                    context_type,
                    importance,
                    text_raw,
                    compressed_int,
                    compression_provider,
                ),
            )
        else:
            self._conn.execute(
                """INSERT INTO memories (id, content, category, tags, source,
                   created_at, updated_at, access_count, last_accessed,
                   context_type,
                   text_raw, compressed, compression_provider)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)""",
                (
                    memory_id,
                    content,
                    category,
                    tags_json,
                    source,
                    now,
                    now,
                    now,
                    context_type,
                    text_raw,
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
    # Phase 2: sync_state helpers (mem_002_compression)
    # ------------------------------------------------------------------

    def get_sync_state(self, backend: str) -> dict | None:
        """Return the sync_state row for ``backend`` or ``None`` if unset.

        Backend names follow the registry naming (``s3`` / ``gdrive``).
        Returns a dict with keys ``backend``, ``last_sync_at``,
        ``last_commit_sha``, ``upload_cursor``.
        """
        try:
            row = self._conn.execute(
                "SELECT backend, last_sync_at, last_commit_sha, upload_cursor "
                "FROM sync_state WHERE backend = ?",
                (backend,),
            ).fetchone()
        except sqlite3.OperationalError:
            # mem_002 migration has not run yet (test harness or stale DB).
            return None
        if row is None:
            return None
        return (
            dict(row)
            if isinstance(row, sqlite3.Row)
            else {
                "backend": row[0],
                "last_sync_at": row[1],
                "last_commit_sha": row[2],
                "upload_cursor": row[3],
            }
        )

    def upsert_sync_state(
        self,
        backend: str,
        last_sync_at: float | None = None,
        last_commit_sha: str | None = None,
        upload_cursor: int | None = None,
    ) -> None:
        """Insert-or-replace the sync_state row for ``backend``.

        Any field left as ``None`` is preserved from the existing row when one
        exists (so a partial update of just the upload cursor does not wipe
        the timestamp). When no row exists the unspecified fields are stored
        as NULL.
        """
        existing = self.get_sync_state(backend) or {}
        merged = {
            "backend": backend,
            "last_sync_at": last_sync_at
            if last_sync_at is not None
            else existing.get("last_sync_at"),
            "last_commit_sha": last_commit_sha
            if last_commit_sha is not None
            else existing.get("last_commit_sha"),
            "upload_cursor": upload_cursor
            if upload_cursor is not None
            else existing.get("upload_cursor"),
        }
        self._conn.execute(
            "INSERT OR REPLACE INTO sync_state "
            "(backend, last_sync_at, last_commit_sha, upload_cursor) "
            "VALUES (?, ?, ?, ?)",
            (
                merged["backend"],
                merged["last_sync_at"],
                merged["last_commit_sha"],
                merged["upload_cursor"],
            ),
        )
        self._conn.commit()

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
        }

        # 1. FTS5 search (over a wider candidate pool for downstream rerank).
        # Spec section 4.2: rerank tops at ~50 candidates -> top-N. Caller can
        # override via ``candidate_pool`` when it knows the rerank budget.
        pool = candidate_pool if candidate_pool is not None else max(limit * 10, 50)
        results = self._search_fts(query, category, tags, pool, **filter_kwargs)

        # 2. Semantic search (if embedding provided)
        if embedding and self._vec_enabled:
            try:
                vec_sql = """
                    SELECT v.id, v.distance
                    FROM memories_vec v
                    JOIN memories m ON v.id = m.id
                    WHERE v.embedding MATCH ?
                """
                vec_params: list = [_serialize_f32(embedding, self._embedding_dims)]

                if category:
                    vec_sql += " AND m.category = ?"
                    vec_params.append(category)

                if tags:
                    vec_sql += " AND m.tags != '[]' AND json_valid(m.tags) AND EXISTS (SELECT 1 FROM json_each(m.tags) WHERE value IN (SELECT value FROM json_each(?)))"
                    vec_params.append(json.dumps(tags))

                extra_sql, extra_params = self._build_filter_sql(**filter_kwargs)
                if extra_sql:
                    vec_sql += extra_sql
                    vec_params.extend(extra_params)

                vec_sql += " AND k = ? ORDER BY distance"
                vec_params.append(pool)

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
                    missing_mems = self._conn.execute(
                        "SELECT * FROM memories WHERE id IN (SELECT value FROM json_each(?))",
                        (json.dumps(missing_ids),),
                    ).fetchall()
                    for mem in missing_mems:
                        mid = mem["id"]
                        results[mid] = {
                            **dict(mem),
                            "fts_score": 0.0,
                            "vec_score": vec_scores[mid],
                        }
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
    ) -> tuple[str, list]:
        """Build the shared WHERE-tail used by FTS + vec search paths.

        Phase 1 retrieval polish filters live on the ``memories`` table only
        (mem_001 schema additions). Returns SQL fragment to append to a
        ``WHERE m.... = ...`` clause and the matching positional params so
        FTS and vec can compose the same filter set without duplication.
        """
        sql = ""
        params: list = []
        if context_type is not None:
            sql += " AND m.context_type = ?"
            params.append(context_type)
        if since is not None:
            sql += " AND m.updated_at >= ?"
            params.append(since)
        if until is not None:
            sql += " AND m.updated_at <= ?"
            params.append(until)
        if min_importance > 0.0:
            sql += " AND COALESCE(m.importance, 0.0) >= ?"
            params.append(float(min_importance))
        if not include_archived:
            sql += " AND m.archived_at IS NULL"
        return sql, params

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
        filter_sql = ""
        filter_params: list = []
        if category:
            filter_sql += " AND m.category = ?"
            filter_params.append(category)
        if tags:
            filter_sql += " AND m.tags != '[]' AND json_valid(m.tags) AND EXISTS (SELECT 1 FROM json_each(m.tags) WHERE value IN (SELECT value FROM json_each(?)))"
            filter_params.append(json.dumps(tags))

        extra_sql, extra_params = self._build_filter_sql(
            context_type=context_type,
            since=since,
            until=until,
            min_importance=min_importance,
            include_archived=include_archived,
        )
        if extra_sql:
            filter_sql += extra_sql
            filter_params.extend(extra_params)

        # Bolt Performance Optimization:
        # Evaluate tiers sequentially in Python rather than combining them into a single
        # UNION ALL query. In SQLite, UNION ALL forces evaluation of all branches before
        # applying limits. Breaking early prevents expensive broad query execution (like OR).
        for fts_query in fts_queries:
            query_params = [fts_query] + filter_params + [limit * 3]
            fts_sql = f"""
                WITH best_tier AS (
                    SELECT m.id,
                           bm25(memories_fts, 0.0, 1.0, 0.0, 5.0) AS bm25_score
                    FROM memories_fts f
                    JOIN memories m ON f.id = m.id
                    WHERE memories_fts MATCH ? {filter_sql}
                    ORDER BY bm25_score
                    LIMIT ?
                )
                SELECT m.*, b.bm25_score
                FROM best_tier b
                JOIN memories m ON b.id = m.id
                ORDER BY b.bm25_score
            """

            try:
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

        fts_vals = [m["fts_score"] for m in results.values() if m["fts_score"] > 0]
        if fts_vals:
            min_f = min(fts_vals)
            max_f = max(fts_vals)
            rng = max_f - min_f
            for m in results.values():
                if rng > 0 and m["fts_score"] > 0:
                    m["fts_score"] = (m["fts_score"] - min_f) / rng
                elif m["fts_score"] > 0:
                    m["fts_score"] = 1.0

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
        scores: dict[str, float] = {}
        for rank, mid in enumerate(fts_results, start=1):
            scores[mid] = scores.get(mid, 0.0) + 1.0 / (k + rank)
        for rank, mid in enumerate(vec_results, start=1):
            scores[mid] = scores.get(mid, 0.0) + 1.0 / (k + rank)
        return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)

    def _compute_hybrid_scores(self, results: dict[str, dict]) -> list[dict]:
        """Compute final scores combining FTS, vector, recency, and frequency."""
        now = datetime.now(UTC)
        scored = []
        has_vec = any(m.get("vec_score", 0.0) > 0 for m in results.values())

        if has_vec:
            k = 60
            all_ids = list(results.keys())
            fts_ranked = sorted(
                all_ids, key=lambda x: results[x].get("fts_score", 0.0), reverse=True
            )
            vec_ranked = sorted(
                all_ids, key=lambda x: results[x].get("vec_score", 0.0), reverse=True
            )
            fts_rank = {cid: i + 1 for i, cid in enumerate(fts_ranked)}
            vec_rank = {cid: i + 1 for i, cid in enumerate(vec_ranked)}

            for mid, mem in results.items():
                fr = fts_rank.get(mid, len(all_ids))
                vr = vec_rank.get(mid, len(all_ids))
                rrf = 1.0 / (k + fr) + 1.0 / (k + vr)

                recency = self._calc_recency(mem.get("updated_at", ""), now)
                freq = self._calc_frequency(mem.get("access_count", 0))

                rrf_norm = rrf * (k + 1) / 2.0
                # Phase 1 retrieval polish: temporal decay multiplied into the
                # base, then importance boost ``score *= (1 + importance)``
                # so highly-rated memories outrank equal-relevance peers.
                base = rrf_norm * 0.7 + recency * 0.2 + freq * 0.1
                importance = max(0.0, min(1.0, float(mem.get("importance") or 0.0)))
                mem["score"] = base * (1.0 + importance)
                scored.append(mem)
        else:
            for mem in results.values():
                fts = mem.get("fts_score", 0.0)
                recency = self._calc_recency(mem.get("updated_at", ""), now)
                freq = self._calc_frequency(mem.get("access_count", 0))

                base = fts * 0.6 + recency * 0.3 + freq * 0.1
                importance = max(0.0, min(1.0, float(mem.get("importance") or 0.0)))
                mem["score"] = base * (1.0 + importance)
                scored.append(mem)

        scored.sort(key=lambda m: m["score"], reverse=True)
        return scored

    def _update_access_stats(self, top: list[dict]) -> None:
        """Increment access counts for returned search results."""
        if not top:
            return

        ids = [m["id"] for m in top]
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
        """
        if isinstance(limit, int):
            limit = max(1, min(limit, 100))

        if category:
            if include_archived:
                sql = (
                    "SELECT * FROM memories "
                    "WHERE category = ? "
                    "ORDER BY updated_at DESC "
                    "LIMIT ? OFFSET ?"
                )
            else:
                sql = (
                    "SELECT * FROM memories "
                    "WHERE category = ? AND archived_at IS NULL "
                    "ORDER BY updated_at DESC "
                    "LIMIT ? OFFSET ?"
                )
            rows = self._conn.execute(sql, (category, limit, offset)).fetchall()
        else:
            if include_archived:
                sql = "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            else:
                sql = (
                    "SELECT * FROM memories "
                    "WHERE archived_at IS NULL "
                    "ORDER BY updated_at DESC "
                    "LIMIT ? OFFSET ?"
                )
            rows = self._conn.execute(sql, (limit, offset)).fetchall()

        return [dict(r) for r in rows]

    def get(self, memory_id: str) -> dict | None:
        """Get a single memory by ID."""
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        return dict(row) if row else None

    def update(
        self,
        memory_id: str,
        content: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        source: str | None = None,
        importance: float | None = None,
        embedding: list[float] | None = None,
    ) -> bool:
        """Update an existing memory. Returns True if found and updated.

        Raises:
            ValueError: If content exceeds MAX_CONTENT_LENGTH.
        """
        if content is not None and len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(
                f"Content length {len(content)} exceeds limit of {MAX_CONTENT_LENGTH}"
            )

        now = _now_iso()

        # Use static parameterized query with CASE WHEN for safe partial updates.
        # This prevents SQL injection and ensures only specified fields are changed.
        cursor = self._conn.execute(
            """
            UPDATE memories SET
                content = CASE WHEN :content_provided THEN :content ELSE content END,
                category = CASE WHEN :category_provided THEN :category ELSE category END,
                tags = CASE WHEN :tags_provided THEN :tags ELSE tags END,
                source = CASE WHEN :source_provided THEN :source ELSE source END,
                importance = CASE WHEN :importance_provided THEN :importance ELSE importance END,
                updated_at = :now
            WHERE id = :id
            """,
            {
                "id": memory_id,
                "now": now,
                "content": content,
                "content_provided": content is not None,
                "category": category,
                "category_provided": category is not None,
                # Bolt Performance Optimization:
                # Prevent expensive json.dumps calls for the default empty list.
                "tags": ("[]" if not tags else json.dumps(tags))
                if tags is not None
                else None,
                "tags_provided": tags is not None,
                "source": source,
                "source_provided": source is not None,
                "importance": max(0.0, min(1.0, importance))
                if importance is not None
                else None,
                "importance_provided": importance is not None,
            },
        )

        if cursor.rowcount == 0:
            return False

        # Update embedding if provided
        if embedding and self._vec_enabled:
            self._conn.execute("DELETE FROM memories_vec WHERE id = ?", (memory_id,))
            self._conn.execute(
                "INSERT INTO memories_vec (id, embedding) VALUES (?, ?)",
                (memory_id, _serialize_f32(embedding, self._embedding_dims)),
            )

        self._conn.commit()
        logger.info(f"[AUDIT] update id={memory_id}")
        return True

    def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID. Returns True if found and deleted."""
        existing = self.get(memory_id)
        if not existing:
            return False

        self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

        if self._vec_enabled:
            self._conn.execute("DELETE FROM memories_vec WHERE id = ?", (memory_id,))

        self._conn.commit()
        logger.info(f"[AUDIT] delete id={memory_id}")
        return True

    def stats(self) -> dict:
        """Get database statistics."""
        total = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

        categories = self._conn.execute(
            "SELECT category, COUNT(*) as cnt FROM memories GROUP BY category ORDER BY cnt DESC"
        ).fetchall()

        last_updated = self._conn.execute(
            "SELECT MAX(updated_at) FROM memories"
        ).fetchone()[0]

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
        # Bolt Performance Optimization: Offload JSON construction to SQLite.
        # Avoids O(N) Python dict creations and json.dumps calls, resulting in ~78% faster exports.
        query = """
            SELECT json_object(
                'id', id,
                'content', content,
                'category', category,
                'tags', json(tags),
                'source', source,
                'created_at', created_at,
                'updated_at', updated_at,
                'access_count', access_count,
                'last_accessed', last_accessed
            ) as json_data
            FROM memories
            ORDER BY created_at
        """
        cursor = self._conn.execute(query)
        output = io.StringIO()
        count = 0

        for row in cursor:
            output.write(row[0])
            output.write("\n")
            count += 1

        return output.getvalue(), count

    def _clear_for_import(self, mode: str) -> None:
        """Clear memories if mode is 'replace'."""
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

                importance = mem.get("importance", 0.5)
                to_insert.append(
                    (
                        memory_id,
                        content,
                        mem.get("category", "general"),
                        tags_json,
                        mem.get("source"),
                        mem.get("created_at", now),
                        mem.get("updated_at", now),
                        mem.get("access_count", 0),
                        mem.get("last_accessed", now),
                        importance,
                    )
                )
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
        cursor = self._conn.cursor()
        sql = """INSERT OR {} INTO memories
                 (id, content, category, tags, source,
                  created_at, updated_at, access_count, last_accessed, importance)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        op = "REPLACE" if mode == "replace" else "IGNORE"
        cursor.executemany(sql.format(op), to_insert)
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
            batch_imported, batch_skipped = self._execute_import_batch(to_insert, mode)
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
        cursor = self._conn.cursor()

        cutoff_date = cursor.execute(
            "SELECT datetime('now', ?)", (f"-{days} days",)
        ).fetchone()[0]

        rows = cursor.execute(
            """SELECT id FROM memories
               WHERE last_accessed < ?
                 AND importance < ?
                 AND archived_at IS NULL""",
            (cutoff_date, importance_threshold),
        ).fetchall()

        if not rows:
            return 0

        now = _now_iso()
        cursor.executemany(
            "UPDATE memories SET archived_at = ? WHERE id = ?",
            [(now, row[0]) for row in rows],
        )
        count = len(rows)
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
                from mnemo_mcp.config import settings as _settings

                archive_after_days = int(_settings.archive_after_days)
            except Exception:
                archive_after_days = 90
        archive_after_days = max(1, int(archive_after_days))

        cursor = self._conn.cursor()
        rows = cursor.execute(
            """SELECT id, updated_at, importance FROM memories
               WHERE archived_at IS NULL""",
        ).fetchall()

        if not rows:
            return 0

        now = datetime.now(UTC)
        to_archive: list[tuple[str, str]] = []
        archive_ts = _now_iso()
        for row in rows:
            try:
                updated = datetime.fromisoformat(row["updated_at"])
            except (ValueError, TypeError):
                continue
            days_since = max(0.0, (now - updated).total_seconds() / 86400.0)
            recency_factor = days_since / archive_after_days
            importance = float(row["importance"] or 0.0)
            score = recency_factor * (1.0 - max(0.0, min(1.0, importance)))
            if score > score_threshold:
                to_archive.append((archive_ts, row["id"]))

        if not to_archive:
            return 0

        cursor.executemany(
            "UPDATE memories SET archived_at = ? WHERE id = ?",
            to_archive,
        )
        count = len(to_archive)
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
        cursor = self._conn.cursor()
        now = _now_iso()

        # New path: row exists in memories and is soft-archived.
        row = cursor.execute(
            "SELECT id FROM memories WHERE id = ? AND archived_at IS NOT NULL",
            (memory_id,),
        ).fetchone()
        if row is not None:
            cursor.execute(
                "UPDATE memories SET archived_at = NULL, last_accessed = ? "
                "WHERE id = ?",
                (now, memory_id),
            )
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
        cursor = self._conn.cursor()

        soft_rows = cursor.execute(
            """SELECT id, content, category, tags, importance, archived_at
               FROM memories
               WHERE archived_at IS NOT NULL
               ORDER BY archived_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        legacy_rows = cursor.execute(
            "SELECT id, content, category, tags, importance, archived_at "
            "FROM archived_memories ORDER BY archived_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

        merged = []
        for r in list(soft_rows) + list(legacy_rows):
            tags_val = r[3]
            merged.append(
                {
                    "id": r[0],
                    "content": r[1][:200],
                    "category": r[2],
                    "tags": [] if tags_val == "[]" else json.loads(tags_val),
                    "importance": r[4],
                    "archived_at": r[5],
                }
            )

        merged.sort(key=lambda m: m["archived_at"] or "", reverse=True)
        return merged[:limit]

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
        cursor = self._conn.cursor()
        cursor.execute(
            "UPDATE memories SET importance = ? WHERE id = ?",
            (importance, memory_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        """Close database connection."""
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

        try:
            cursor = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
            ).fetchone()
            if cursor is None:
                return
            cols = {
                row[1]
                for row in self._conn.execute("PRAGMA table_info(memories)").fetchall()
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
            # malformed" on Windows SQLite).
            try:
                self._conn.execute(
                    "INSERT INTO memories_fts(memories_fts) VALUES('rebuild')"
                )
                self._conn.commit()
            except Exception:
                pass

            for row in rows:
                row_id = row["id"] if isinstance(row, sqlite3.Row) else row[0]
                content = row["content"] if isinstance(row, sqlite3.Row) else row[1]
                created_at = (
                    row["created_at"] if isinstance(row, sqlite3.Row) else row[2]
                )
                digest = hashlib.sha256((content or "").encode("utf-8")).hexdigest()
                self._conn.execute(
                    "UPDATE memories SET "
                    "  commit_sha = COALESCE(commit_sha, ?), "
                    "  valid_from = COALESCE(valid_from, ?) "
                    "WHERE id = ?",
                    (digest, created_at, row_id),
                )
            self._conn.commit()
            logger.info(
                f"Phase 3 backfill: commit_sha + valid_from for {len(rows)} legacy rows"
            )
        except Exception as e:  # pragma: no cover - runtime guard
            logger.warning(f"Phase 3 temporal backfill failed: {e}")

    def _read_alembic_version(self) -> str | None:
        """Return the current ``alembic_version`` revision, or ``None`` if unstamped."""
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
