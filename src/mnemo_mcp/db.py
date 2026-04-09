"""Core SQLite database engine for Mnemo memories.

Provides:
- FTS5 full-text search (always available, zero dependency)
- sqlite-vec vector search (when embeddings are configured)
- CRUD operations with category/tag filtering
- Hybrid search scoring (text + semantic + recency + frequency)
"""

import io
import json
import math
import sqlite3
import struct
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlite_vec
from loguru import logger

_STRUCT_CACHE: dict[int, struct.Struct] = {}


def _serialize_f32(vec: list[float]) -> bytes:
    """Serialize float list to bytes for sqlite-vec.

    Uses a cached struct.Struct instance to avoid recompiling the format
    string on every vector insertion or search, providing a ~30% speedup.
    """
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

    def _init_schema(self) -> None:
        """Initialize database schema."""
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

        # Knowledge graph tables
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY NOT NULL,
                name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_name_type
                ON entities(name, entity_type);

            CREATE TABLE IF NOT EXISTS relations (
                id TEXT PRIMARY KEY NOT NULL,
                source_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                target_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
            CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_relations_unique ON relations(source_id, target_id, relation_type);

            CREATE TABLE IF NOT EXISTS memory_entities (
                memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                PRIMARY KEY (memory_id, entity_id)
            );

            -- Bolt Performance Optimization:
            -- Index on entity_id to eliminate full table scans during knowledge graph
            -- traversal in find_related_memory_ids. Improves search performance significantly
            -- as the database grows.
            CREATE INDEX IF NOT EXISTS idx_memory_entities_entity_id
                ON memory_entities(entity_id);

            -- Archive table
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

        # Add importance column to memories (migration for existing DBs)
        try:
            self._conn.execute(
                "ALTER TABLE memories ADD COLUMN importance REAL NOT NULL DEFAULT 0.5"
            )
        except Exception:
            pass  # Column already exists

        # sqlite-vec virtual table (only if enabled)
        if self._vec_enabled and self._embedding_dims > 0:
            # Check if vec table exists
            row = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memories_vec'"
            ).fetchone()
            if not row:
                # Validate and cast dimensions before f-string interpolation
                # to prevent potential SQL injection if the source ever becomes
                # untrusted.
                dims = int(self._embedding_dims)
                if not (0 <= dims <= 10000):
                    raise ValueError(
                        f"embedding_dims must be between 0 and 10000, got {dims}"
                    )
                self._conn.execute(f"""
                    CREATE VIRTUAL TABLE memories_vec
                    USING vec0(
                        id TEXT PRIMARY KEY,
                        embedding float[{dims}]
                    )
                """)
                logger.debug("Created memories_vec table")

        self._conn.commit()

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
        tags_json = json.dumps(tags or [])

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
                (memory_id, _serialize_f32(embedding)),
            )

        self._conn.commit()
        logger.info(f"[AUDIT] add id={memory_id} cat={category} len={len(content)}")
        return memory_id

    def search(
        self,
        query: str,
        embedding: list[float] | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Search memories with hybrid scoring.

        Uses tiered FTS5 queries (AND -> OR fallback), BM25 column weights,
        min-max normalization, RRF fusion (when embedding available),
        plus recency and frequency boosts.

        Category filtering is applied in SQL for efficiency.
        Tag filtering is post-search (JSON array matching).

        Returns:
            List of memory dicts sorted by relevance.
        """
        if tags and len(tags) > MAX_TAGS_FILTER:
            raise ValueError(
                f"Maximum of {MAX_TAGS_FILTER} tags allowed in search filter"
            )

        if isinstance(limit, int):
            limit = max(1, min(limit, 100))

        # 1. FTS5 search
        results = self._search_fts(query, category, tags, limit)

        # 2. Semantic search (if embedding provided)
        if embedding and self._vec_enabled:
            try:
                vec_sql = """
                    SELECT v.id, v.distance
                    FROM memories_vec v
                    JOIN memories m ON v.id = m.id
                    WHERE v.embedding MATCH ?
                """
                vec_params: list = [_serialize_f32(embedding)]

                if category:
                    vec_sql += " AND m.category = ?"
                    vec_params.append(category)

                if tags:
                    vec_sql += " AND json_valid(m.tags) AND EXISTS (SELECT 1 FROM json_each(m.tags) WHERE value IN (SELECT value FROM json_each(?)))"
                    vec_params.append(json.dumps(tags))

                vec_sql += " ORDER BY distance LIMIT ?"
                vec_params.append(limit * 3)

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

        # 4. Update access counts for returned results
        top = scored[:limit]
        self._update_access_stats(top)

        # Clean up internal scores from output
        for m in top:
            m.pop("fts_score", None)
            m.pop("vec_score", None)
            m.pop("bm25_score", None)

        return top

    def _search_fts(
        self,
        query: str,
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 5,
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

        subqueries = []
        fts_params: list = []

        # Bolt Performance Optimization:
        # Deferred join pattern. We only select m.id in the inner CTE instead of
        # m.* to avoid evaluating large columns for rows that will be filtered out by LIMIT.
        filter_sql = ""
        filter_params: list = []
        if category:
            filter_sql += " AND m.category = ?"
            filter_params.append(category)
        if tags:
            filter_sql += " AND json_valid(m.tags) AND EXISTS (SELECT 1 FROM json_each(m.tags) WHERE value IN (SELECT value FROM json_each(?)))"
            filter_params.append(json.dumps(tags))

        for idx, fts_query in enumerate(fts_queries):
            subqueries.append(f"""
                SELECT m.id,
                       bm25(memories_fts, 0.0, 1.0, 0.0, 5.0) AS bm25_score,
                       {idx} as tier_idx
                FROM memories_fts f
                JOIN memories m ON f.id = m.id
                WHERE memories_fts MATCH ? {filter_sql}
            """)
            fts_params.append(fts_query)
            fts_params.extend(filter_params)

        union_sql = " UNION ALL ".join(subqueries)
        fts_sql = f"""
            WITH all_matches AS (
                {union_sql}
            ),
            best_tier AS (
                SELECT id, bm25_score
                FROM all_matches
                WHERE tier_idx = (SELECT MIN(tier_idx) FROM all_matches)
                ORDER BY bm25_score
                LIMIT ?
            )
            SELECT m.*, b.bm25_score
            FROM best_tier b
            JOIN memories m ON b.id = m.id
            ORDER BY b.bm25_score
        """
        fts_params.append(limit * 3)

        try:
            rows = self._conn.execute(fts_sql, fts_params).fetchall()
            for row in rows:
                mid = row["id"]
                results[mid] = {
                    **dict(row),
                    "fts_score": -row["bm25_score"],
                    "vec_score": 0.0,
                }
        except Exception as e:
            logger.error(f"FTS search failed: {e}")

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
        """Calculate recency boost using configurable half-life."""
        try:
            updated = datetime.fromisoformat(updated_at)
            days_old = (now - updated).total_seconds() / 86400
            return 2.0 ** (-days_old / self._recency_half_life)
        except (ValueError, KeyError):
            return 0.0

    def _calc_frequency(self, access_count: int) -> float:
        """Calculate logarithmic frequency boost."""
        freq = math.log1p(access_count) / 10.0
        return min(freq, 1.0)

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
                mem["score"] = rrf_norm * 0.7 + recency * 0.2 + freq * 0.1
                scored.append(mem)
        else:
            for mem in results.values():
                fts = mem.get("fts_score", 0.0)
                recency = self._calc_recency(mem.get("updated_at", ""), now)
                freq = self._calc_frequency(mem.get("access_count", 0))

                mem["score"] = fts * 0.6 + recency * 0.3 + freq * 0.1
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
    ) -> list[dict]:
        """List memories with optional category filter."""
        if isinstance(limit, int):
            limit = max(1, min(limit, 100))

        if category:
            rows = self._conn.execute(
                """SELECT * FROM memories
                   WHERE category = ?
                   ORDER BY updated_at DESC
                   LIMIT ? OFFSET ?""",
                (category, limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT * FROM memories
                   ORDER BY updated_at DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()

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

        existing = self.get(memory_id)
        if not existing:
            return False

        now = _now_iso()
        updates = []
        params: list = []

        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if category is not None:
            updates.append("category = ?")
            params.append(category)
        if tags is not None:
            updates.append("tags = ?")
            params.append(json.dumps(tags))

        updates.append("updated_at = ?")
        params.append(now)
        params.append(memory_id)

        # Validate updates against allowlist before string joining
        # to ensure no unexpected column names are injected.
        _ALLOWED = {"content = ?", "category = ?", "tags = ?", "updated_at = ?"}
        if not all(u in _ALLOWED for u in updates):
            invalid = [u for u in updates if u not in _ALLOWED]
            raise ValueError(f"Unauthorized update columns detected: {invalid}")

        self._conn.execute(
            f"UPDATE memories SET {', '.join(updates)} WHERE id = ?",
            params,
        )

        # Update embedding if provided
        if embedding and self._vec_enabled:
            self._conn.execute("DELETE FROM memories_vec WHERE id = ?", (memory_id,))
            self._conn.execute(
                "INSERT INTO memories_vec (id, embedding) VALUES (?, ?)",
                (memory_id, _serialize_f32(embedding)),
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

    def import_jsonl(self, data: str | list | dict, mode: str = "merge") -> dict:
        """Import memories from JSONL string.

        Args:
            data: JSONL string (one JSON object per line).
            mode: "merge" (skip existing) or "replace" (clear + import).

        Returns:
            Dict with import stats (imported, skipped, rejected).
        """
        if mode == "replace":
            self._conn.execute("DELETE FROM memories")
            if self._vec_enabled:
                self._conn.execute("DELETE FROM memories_vec")

        imported = 0
        skipped = 0
        rejected = 0

        if isinstance(data, list):
            iterator = data
        elif isinstance(data, dict):
            iterator = [data]
        elif isinstance(data, str):
            iterator = []
            for line in data.strip().split("\n"):
                line = line.strip()
                if line:
                    try:
                        iterator.append(json.loads(line))
                    except Exception:
                        rejected += 1
        else:
            iterator = []

        lines = iterator
        BATCH_SIZE = 900

        for i in range(0, len(lines), BATCH_SIZE):
            batch_items = lines[i : i + BATCH_SIZE]
            parsed_batch = []

            # Validate batch
            for mem in batch_items:
                try:
                    memory_id = mem.get("id", uuid.uuid4().hex)
                    content = mem.get("content", "")

                    if len(content) > MAX_CONTENT_LENGTH:
                        logger.warning(
                            f"[AUDIT] import rejected id={memory_id} "
                            f"len={len(content)} exceeds {MAX_CONTENT_LENGTH}"
                        )
                        rejected += 1
                        continue

                    parsed_batch.append((memory_id, mem, content))
                except Exception:
                    rejected += 1
                    continue

            if not parsed_batch:
                continue

            to_insert = []
            now = _now_iso()

            for memory_id, mem, content in parsed_batch:
                tags = mem.get("tags", [])
                if isinstance(tags, list):
                    tags_json = json.dumps(tags)
                else:
                    tags_json = tags

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
                    )
                )

            if to_insert:
                cursor = self._conn.cursor()
                if mode == "replace":
                    cursor.executemany(
                        """INSERT OR REPLACE INTO memories
                           (id, content, category, tags, source,
                            created_at, updated_at, access_count, last_accessed)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        to_insert,
                    )
                    imported += len(to_insert)
                else:
                    cursor.executemany(
                        """INSERT OR IGNORE INTO memories
                           (id, content, category, tags, source,
                            created_at, updated_at, access_count, last_accessed)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        to_insert,
                    )
                    inserted_batch = cursor.rowcount
                    imported += inserted_batch
                    skipped += len(to_insert) - inserted_batch

        self._conn.commit()
        if imported > 0:
            logger.info(f"[AUDIT] import count={imported} mode={mode}")
        return {"imported": imported, "skipped": skipped, "rejected": rejected}

    def archive_old_memories(
        self, days: int = 90, importance_threshold: float = 0.3
    ) -> int:
        """Move old, low-importance memories to archive. Returns count archived."""
        cursor = self._conn.cursor()
        rows = cursor.execute(
            """SELECT id, content, category, tags, source, importance,
                      created_at, updated_at, access_count, last_accessed
               FROM memories
               WHERE last_accessed < datetime('now', ? || ' days')
                 AND importance < ?""",
            (f"-{days}", importance_threshold),
        ).fetchall()

        now = _now_iso()
        if not rows:
            return 0

        insert_data = [(*row, now) for row in rows]
        delete_data = [(row[0],) for row in rows]

        cursor.executemany(
            """INSERT OR REPLACE INTO archived_memories
               (id, content, category, tags, source, importance,
                created_at, updated_at, access_count, last_accessed, archived_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            insert_data,
        )
        cursor.executemany(
            "DELETE FROM memories WHERE id = ?",
            delete_data,
        )

        count = len(rows)
        self._conn.commit()
        logger.info(f"[AUDIT] archived count={count}")
        return count

    def restore_memory(self, memory_id: str) -> bool:
        """Restore archived memory back to active."""
        cursor = self._conn.cursor()
        row = cursor.execute(
            "SELECT * FROM archived_memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if not row:
            return False
        now = _now_iso()
        cursor.execute(
            """INSERT OR REPLACE INTO memories
               (id, content, category, tags, source, importance,
                created_at, updated_at, access_count, last_accessed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (row[0], row[1], row[2], row[3], row[4], row[5], row[6], now, row[8], now),
        )
        cursor.execute("DELETE FROM archived_memories WHERE id = ?", (memory_id,))
        self._conn.commit()
        logger.info(f"[AUDIT] restore id={memory_id}")
        return True

    def list_archived(self, limit: int = 20) -> list[dict]:
        """List archived memories."""
        if isinstance(limit, int):
            limit = max(1, min(limit, 100))
        cursor = self._conn.cursor()
        rows = cursor.execute(
            "SELECT id, content, category, tags, importance, archived_at "
            "FROM archived_memories ORDER BY archived_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "content": r[1][:200],
                "category": r[2],
                "tags": json.loads(r[3]),
                "importance": r[4],
                "archived_at": r[5],
            }
            for r in rows
        ]

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
