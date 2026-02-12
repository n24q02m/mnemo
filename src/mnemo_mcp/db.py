"""Core SQLite database engine for Mnemo memories.

Provides:
- FTS5 full-text search (always available, zero dependency)
- sqlite-vec vector search (when embeddings are configured)
- CRUD operations with category/tag filtering
- Hybrid search scoring (text + semantic + recency + frequency)
"""

import json
import math
import sqlite3
import struct
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlite_vec
from loguru import logger


def _serialize_f32(vec: list[float]) -> bytes:
    """Serialize float list to bytes for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


def _now_iso() -> str:
    """Current UTC timestamp in ISO format."""
    return datetime.now(UTC).isoformat()


class MemoryDB:
    """SQLite database for persistent AI memories."""

    def __init__(self, db_path: Path, embedding_dims: int = 0):
        """Open or create memory database.

        Args:
            db_path: Path to SQLite database file.
            embedding_dims: Embedding dimensions (0 = no vector search).
        """
        self._db_path = db_path
        self._embedding_dims = embedding_dims

        # Create parent directory
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Open connection
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")

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

        # sqlite-vec virtual table (only if enabled)
        if self._vec_enabled and self._embedding_dims > 0:
            # Check if vec table exists
            row = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memories_vec'"
            ).fetchone()
            if not row:
                self._conn.execute(f"""
                    CREATE VIRTUAL TABLE memories_vec
                    USING vec0(
                        id TEXT PRIMARY KEY,
                        embedding float[{self._embedding_dims}]
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
        """
        memory_id = uuid.uuid4().hex[:12]
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
        logger.debug(f"Added memory {memory_id}: {content[:50]}...")
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

        Combines FTS5 text search + semantic search + recency + frequency.

        Returns:
            List of memory dicts sorted by relevance.
        """
        results: dict[str, dict] = {}

        # 1. FTS5 text search
        # Convert natural language query to FTS5 OR query with prefix matching
        # "which dataframe library" → "which* OR dataframe* OR library*"
        words = [w.strip() for w in query.split() if w.strip()]
        if words:
            safe_words = [w.replace('"', '""') for w in words]
            fts_query = " OR ".join(f'"{w}"*' for w in safe_words)
        else:
            fts_query = query.replace('"', '""')
        try:
            rows = self._conn.execute(
                """SELECT m.*, rank
                   FROM memories_fts f
                   JOIN memories m ON f.id = m.id
                   WHERE memories_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (fts_query, limit * 2),
            ).fetchall()

            for row in rows:
                mid = row["id"]
                # FTS5 rank is negative (lower = better), normalize to 0-1
                fts_score = 1.0 / (1.0 + abs(row["rank"]))
                results[mid] = {
                    **dict(row),
                    "fts_score": fts_score,
                    "vec_score": 0.0,
                }
        except Exception:
            # FTS5 can fail on complex queries, silently skip
            pass

        # 2. Semantic search (if embedding provided)
        if embedding and self._vec_enabled:
            try:
                vec_rows = self._conn.execute(
                    """SELECT id, distance
                       FROM memories_vec
                       WHERE embedding MATCH ?
                       ORDER BY distance
                       LIMIT ?""",
                    (_serialize_f32(embedding), limit * 2),
                ).fetchall()

                for row in vec_rows:
                    mid = row["id"]
                    # Distance is cosine distance (0 = identical), convert to similarity
                    vec_score = 1.0 - row["distance"]
                    if mid in results:
                        results[mid]["vec_score"] = vec_score
                    else:
                        # Fetch full memory
                        mem = self._conn.execute(
                            "SELECT * FROM memories WHERE id = ?", (mid,)
                        ).fetchone()
                        if mem:
                            results[mid] = {
                                **dict(mem),
                                "fts_score": 0.0,
                                "vec_score": vec_score,
                            }
            except Exception as e:
                logger.debug(f"Vector search error: {e}")

        if not results:
            return []

        # 3. Apply category/tag filters
        if category:
            results = {
                k: v for k, v in results.items() if v.get("category") == category
            }
        if tags:

            def _has_tags(mem: dict) -> bool:
                mem_tags = json.loads(mem.get("tags", "[]"))
                return any(t in mem_tags for t in tags)

            results = {k: v for k, v in results.items() if _has_tags(v)}

        # 4. Compute hybrid score
        now = datetime.now(UTC)
        scored = []
        for mem in results.values():
            fts = mem.get("fts_score", 0.0)
            vec = mem.get("vec_score", 0.0)

            # Recency boost (exponential decay, half-life = 7 days)
            try:
                updated = datetime.fromisoformat(mem["updated_at"])
                days_old = (now - updated).total_seconds() / 86400
                recency = 2.0 ** (-days_old / 7.0)
            except (ValueError, KeyError):
                recency = 0.0

            # Frequency boost (logarithmic)
            freq = math.log1p(mem.get("access_count", 0)) / 10.0
            freq = min(freq, 1.0)

            # Weighted combination
            if vec > 0:
                score = fts * 0.35 + vec * 0.35 + recency * 0.2 + freq * 0.1
            else:
                score = fts * 0.6 + recency * 0.3 + freq * 0.1

            mem["score"] = score
            scored.append(mem)

        # Sort by score descending
        scored.sort(key=lambda m: m["score"], reverse=True)

        # Update access counts for returned results
        top = scored[:limit]
        if top:
            ids = [m["id"] for m in top]
            placeholders = ",".join("?" for _ in ids)
            self._conn.execute(
                f"""UPDATE memories
                    SET access_count = access_count + 1,
                        last_accessed = ?
                    WHERE id IN ({placeholders})""",
                [_now_iso(), *ids],
            )
            self._conn.commit()

        # Clean up internal scores from output
        for m in top:
            m.pop("fts_score", None)
            m.pop("vec_score", None)
            m.pop("rank", None)

        return top

    def list_memories(
        self,
        category: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """List memories with optional category filter."""
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
        """Update an existing memory. Returns True if found and updated."""
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

    def export_jsonl(self) -> str:
        """Export all memories as JSONL string."""
        rows = self._conn.execute(
            "SELECT * FROM memories ORDER BY created_at"
        ).fetchall()

        lines = []
        for row in rows:
            d = dict(row)
            d["tags"] = json.loads(d["tags"])
            lines.append(json.dumps(d, ensure_ascii=False))

        return "\n".join(lines)

    def import_jsonl(self, data: str, mode: str = "merge") -> dict:
        """Import memories from JSONL string.

        Args:
            data: JSONL string (one JSON object per line).
            mode: "merge" (skip existing) or "replace" (clear + import).

        Returns:
            Dict with import stats.
        """
        if mode == "replace":
            self._conn.execute("DELETE FROM memories")
            if self._vec_enabled:
                self._conn.execute("DELETE FROM memories_vec")

        imported = 0
        skipped = 0

        for line in data.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            mem = json.loads(line)
            memory_id = mem.get("id", uuid.uuid4().hex[:12])

            # Check if exists (for merge mode)
            if mode == "merge":
                existing = self.get(memory_id)
                if existing:
                    skipped += 1
                    continue

            tags = mem.get("tags", [])
            if isinstance(tags, list):
                tags_json = json.dumps(tags)
            else:
                tags_json = tags

            now = _now_iso()
            self._conn.execute(
                """INSERT OR REPLACE INTO memories
                   (id, content, category, tags, source,
                    created_at, updated_at, access_count, last_accessed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    memory_id,
                    mem["content"],
                    mem.get("category", "general"),
                    tags_json,
                    mem.get("source"),
                    mem.get("created_at", now),
                    mem.get("updated_at", now),
                    mem.get("access_count", 0),
                    mem.get("last_accessed", now),
                ),
            )
            imported += 1

        self._conn.commit()
        return {"imported": imported, "skipped": skipped}

    def close(self) -> None:
        """Close database connection."""
        self._conn.close()
