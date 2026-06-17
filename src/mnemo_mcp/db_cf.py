"""D1 + Vectorize backed MemoryDB for the Cloudflare deployment.

Same public surface as mnemo_mcp.db.MemoryDB but: relational + FTS5 + graph +
bitemporal -> D1 (per-sub scoped); embedding vectors -> Vectorize (per-sub
metadata filter). The Python ranking logic (RRF k=60, recency, frequency,
importance) is ported byte-for-byte from db.py in Task 10; only the storage
transport and the FTS+vector split change. Exposes ``_conn`` (a D1Connection) so
graph.py / temporal/queries.py / sync/delta.py work unchanged.

CRUD is ported from db.py (add L517, get L1195, update L1202, delete L1274,
list_memories L1148); every statement carries ``sub`` so a shared D1 stays
per-user isolated (DECISION D3).
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime

from loguru import logger

from mnemo_mcp._d1_conn import D1Connection

MAX_CONTENT_LENGTH = 5000
MAX_TAGS_FILTER = 50

# D1's HTTP query API caps bound parameters at 100 per statement -- the SQLite
# 999-variable ceiling does NOT apply over D1's wire protocol. The bulk-import
# INSERT binds _IMPORT_COLS columns per row, so a multi-row batch must stay under
# the param ceiling or D1 drops the request (the container disconnects mid-call).
# D1Backend.executemany chunks by ROW count (default 100), which is param-unsafe
# for a wide row, so import_jsonl pre-chunks by the param-derived row budget.
_D1_MAX_BOUND_PARAMS = 100
_IMPORT_COLS = 11
_D1_SAFE_IMPORT_ROWS = max(1, _D1_MAX_BOUND_PARAMS // _IMPORT_COLS)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _build_fts_queries(query: str) -> list[str]:
    """Build tiered FTS5 queries: PHRASE -> AND -> OR (verbatim from db.py:71-93).

    No stop-word filtering -- BM25's IDF naturally down-weights common words and
    the PHRASE->AND->OR fallback ensures precision first, then recall.
    """
    words = [w.strip() for w in query.split() if w.strip()]
    safe = [w.replace('"', '""') for w in words]

    if not safe:
        return []
    if len(safe) == 1:
        return [f'"{safe[0]}"*']

    return [
        '"' + " ".join(safe) + '"',
        " AND ".join(f'"{w}"*' for w in safe),
        " OR ".join(f'"{w}"*' for w in safe),
    ]


class MemoryDBD1:
    def __init__(
        self,
        d1,
        vectorize,
        sub: str = "default",
        embedding_dims: int = 0,
        recency_half_life_days: float = 7.0,
        *,
        embedding_model: str = "",
        reindex_on_model_change: bool = False,
    ) -> None:
        self._d1 = d1
        self._vec = vectorize
        self.sub = sub
        self._embedding_dims = embedding_dims
        self._embedding_model = embedding_model
        self._reindex_on_model_change = reindex_on_model_change
        self._recency_half_life = float(recency_half_life_days)
        self._vec_enabled = embedding_dims > 0
        self._conn = D1Connection(d1, sub=sub)  # for graph.py / temporal / sync
        self._guard_embedding_identity()

    @property
    def vec_enabled(self) -> bool:
        return self._vec_enabled

    def get_store_meta(self, key: str) -> str | None:
        rows = self._d1.execute(
            "SELECT value FROM store_meta WHERE sub = ? AND key = ?", [self.sub, key]
        )
        return rows[0]["value"] if rows else None

    def _set_store_meta(self, key: str, value: str) -> None:
        self._d1.execute(
            "INSERT OR REPLACE INTO store_meta (sub, key, value) VALUES (?, ?, ?)",
            [self.sub, key, value],
        )

    def _stamp_embedding_identity(self) -> None:
        self._set_store_meta("embedding_dims", str(self._embedding_dims))
        if self._embedding_model:
            self._set_store_meta("embedding_model", self._embedding_model)

    def _guard_embedding_identity(self) -> None:
        """Per-sub embedding-identity guard, ported from db.py:227-294.

        Stamps a fresh store with the current ``(embedding_model, embedding_dims)``,
        proceeds on a match, and aborts (EmbeddingModelMismatch) on a dims/model
        change unless ``reindex_on_model_change`` is set -- in which case it
        re-stamps and the embed pass re-upserts this sub's vectors. Per-sub so a
        shared D1 never false-blocks one user on another's identity. Dims are
        always compared (even when a model id is absent) since a dims mismatch is
        the most dangerous corruption; operators MUST set REINDEX_ON_MODEL_CHANGE
        before changing EMBEDDING_DIMS.
        """
        from mnemo_mcp.exceptions import EmbeddingModelMismatch

        if self._embedding_dims <= 0:
            return
        stored_model = self.get_store_meta("embedding_model")
        stored_dims_raw = self.get_store_meta("embedding_dims")
        if stored_dims_raw is None and stored_model is None:
            self._stamp_embedding_identity()
            return
        try:
            stored_dims = int(stored_dims_raw) if stored_dims_raw is not None else 0
        except ValueError:
            stored_dims = 0
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
                "Embedding identity changed (sub={}); REINDEX set -- Vectorize "
                "vectors for this sub will be rebuilt on the next embed pass.",
                self.sub,
            )
            self._stamp_embedding_identity()
            return
        raise EmbeddingModelMismatch(
            stored_model=stored_model or "",
            stored_dims=stored_dims,
            requested_model=self._embedding_model or "",
            requested_dims=self._embedding_dims,
        )

    def add(
        self,
        content: str,
        category: str = "general",
        tags: list[str] | None = None,
        source: str | None = None,
        embedding: list[float] | None = None,
    ) -> str:
        if len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(
                f"Content length {len(content)} exceeds limit of {MAX_CONTENT_LENGTH}"
            )
        memory_id = uuid.uuid4().hex
        now = _now_iso()
        tags_json = "[]" if not tags else json.dumps(tags)
        self._d1.execute(
            "INSERT INTO memories (id, sub, content, category, tags, source, "
            "created_at, updated_at, access_count, last_accessed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            [memory_id, self.sub, content, category, tags_json, source, now, now, now],
        )
        if embedding and self._vec_enabled:
            self._vec.upsert(
                [
                    {
                        "id": f"{self.sub}:{memory_id}",
                        "values": embedding,
                        "metadata": {
                            "sub": self.sub,
                            "mid": memory_id,
                            "category": category,
                            "archived": 0,
                        },
                    }
                ]
            )
        logger.info(f"[AUDIT] add id={memory_id} sub={self.sub} cat={category}")
        return memory_id

    def get(self, memory_id: str) -> dict | None:
        rows = self._d1.execute(
            "SELECT * FROM memories WHERE sub = ? AND id = ?", [self.sub, memory_id]
        )
        return rows[0] if rows else None

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
        if content is not None and len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(
                f"Content length {len(content)} exceeds limit of {MAX_CONTENT_LENGTH}"
            )
        # Port db.py:1226-1257 partial update. D1Backend takes positional params,
        # so the named-param CASE-WHEN becomes COALESCE(?, col): a None param
        # keeps the existing value. NULLing a column is not a supported update
        # (none of these columns are nullable in practice), matching local
        # behaviour where an unprovided field is left unchanged.
        self._d1.execute(
            "UPDATE memories SET "
            "content = COALESCE(?, content), category = COALESCE(?, category), "
            "tags = COALESCE(?, tags), source = COALESCE(?, source), "
            "importance = COALESCE(?, importance), updated_at = ? "
            "WHERE sub = ? AND id = ?",
            [
                content,
                category,
                ("[]" if not tags else json.dumps(tags)) if tags is not None else None,
                source,
                max(0.0, min(1.0, importance)) if importance is not None else None,
                _now_iso(),
                self.sub,
                memory_id,
            ],
        )
        # D1 returns no rows for UPDATE, so rowcount is unavailable; confirm the
        # row exists to distinguish "updated" from "missing id".
        if self.get(memory_id) is None:
            return False
        if embedding and self._vec_enabled:
            self._vec.upsert(
                [
                    {
                        "id": f"{self.sub}:{memory_id}",
                        "values": embedding,
                        "metadata": {"sub": self.sub, "mid": memory_id},
                    }
                ]
            )
        logger.info(f"[AUDIT] update id={memory_id} sub={self.sub}")
        return True

    def delete(self, memory_id: str) -> bool:
        if self.get(memory_id) is None:
            return False
        self._d1.execute(
            "DELETE FROM memories WHERE sub = ? AND id = ?", [self.sub, memory_id]
        )
        # Vectorize delete-by-id is a separate REST op exposed by the Worker
        # /vectorize/deleteByIds handler (Task 14); a stale vector is harmless
        # because search() (Task 10) hydrates rows from D1 and drops vector hits
        # with no matching D1 row.
        logger.info(f"[AUDIT] delete id={memory_id} sub={self.sub}")
        return True

    def list_memories(
        self,
        category: str | None = None,
        limit: int = 20,
        offset: int = 0,
        *,
        include_archived: bool = False,
    ) -> list[dict]:
        limit = max(1, min(int(limit), 100))
        sql = "SELECT * FROM memories WHERE sub = ?"
        params: list = [self.sub]
        if category:
            sql += " AND category = ?"
            params.append(category)
        if not include_archived:
            sql += " AND archived_at IS NULL"
        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        return self._d1.execute(sql, params)

    def get_sync_state(self, backend: str) -> dict | None:
        """Return the per-sub sync cursor for a backend (db.py:690-757 port)."""
        rows = self._d1.execute(
            "SELECT backend, last_sync_at, last_commit_sha, upload_cursor "
            "FROM sync_state WHERE sub = ? AND backend = ?",
            [self.sub, backend],
        )
        return rows[0] if rows else None

    def upsert_sync_state(
        self,
        backend: str,
        last_sync_at: float | None = None,
        last_commit_sha: str | None = None,
        upload_cursor: int | None = None,
    ) -> None:
        """Upsert the per-sub sync cursor; unset fields keep their stored value."""
        existing = self.get_sync_state(backend) or {}
        self._d1.execute(
            "INSERT OR REPLACE INTO sync_state "
            "(sub, backend, last_sync_at, last_commit_sha, upload_cursor) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                self.sub,
                backend,
                last_sync_at
                if last_sync_at is not None
                else existing.get("last_sync_at"),
                last_commit_sha
                if last_commit_sha is not None
                else existing.get("last_commit_sha"),
                upload_cursor
                if upload_cursor is not None
                else existing.get("upload_cursor"),
            ],
        )

    # ------------------------------------------------------------------
    # Hybrid search: D1 FTS5 + Vectorize KNN + app-side RRF (k=60).
    # Ranking math (RRF, recency, frequency, importance) is ported byte-for-byte
    # from db.py; only the data fetch splits into a D1 round-trip + a Vectorize
    # round-trip. FTS carries `WHERE m.sub = ?`; Vectorize filters {"sub": sub}
    # and archived/category are enforced authoritatively during D1 hydration.
    # ------------------------------------------------------------------

    def _build_filter_sql(
        self,
        *,
        context_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        min_importance: float = 0.0,
        include_archived: bool = False,
    ) -> tuple[str, list]:
        """Shared WHERE-tail for the FTS path (ported from db.py:906-938)."""
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

    def _search_fts_d1(
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
        """D1 FTS5 with tiered queries + bm25 weights (ported from db.py:940-1034).

        `WHERE m.sub = ?` scopes the shared FTS index to the current user; the
        bm25 column weights `(0.0, 1.0, 0.0, 5.0)` and the PHRASE->AND->OR tier
        order are kept byte-for-byte so ranking matches the SQLite golden.
        """
        results: dict[str, dict] = {}
        fts_queries = _build_fts_queries(query)
        if not fts_queries:
            return results

        filter_sql = " AND m.sub = ?"
        filter_params: list = [self.sub]
        if category:
            filter_sql += " AND m.category = ?"
            filter_params.append(category)
        if tags:
            filter_sql += (
                " AND m.tags != '[]' AND json_valid(m.tags) AND EXISTS "
                "(SELECT 1 FROM json_each(m.tags) WHERE value IN "
                "(SELECT value FROM json_each(?)))"
            )
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

        for fts_query in fts_queries:
            query_params = [fts_query, *filter_params, limit * 3]
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
                rows = self._d1.execute(fts_sql, query_params)
                if rows:
                    for row in rows:
                        mid = row["id"]
                        results[mid] = {
                            **row,
                            "fts_score": -row["bm25_score"],
                            "vec_score": 0.0,
                        }
                    break  # highest-priority tier with matches wins
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
        """Exponential temporal decay (verbatim from db.py:1036-1050)."""
        try:
            updated = datetime.fromisoformat(updated_at)
            days_old = (now - updated).total_seconds() / 86400
            return 2.0 ** (-days_old / self._recency_half_life)
        except (ValueError, KeyError, TypeError):
            return 0.0

    def _calc_frequency(self, access_count: int) -> float:
        """Logarithmic frequency boost (verbatim from db.py:1052-1055)."""
        freq = math.log1p(access_count) / 10.0
        return min(freq, 1.0)

    def _compute_hybrid_scores(self, results: dict[str, dict]) -> list[dict]:
        """Combine FTS, vector, recency, frequency (verbatim from db.py:1085-1131)."""
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
        """Increment access counts for returned rows (per-sub; db.py:1133-1146)."""
        if not top:
            return
        ids = [m["id"] for m in top]
        ph = ", ".join("?" for _ in ids)
        self._d1.execute(
            "UPDATE memories SET access_count = access_count + 1, last_accessed = ? "
            f"WHERE sub = ? AND id IN ({ph})",
            [_now_iso(), self.sub, *ids],
        )

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
        """Hybrid search: D1 FTS5 + Vectorize KNN fused with app-side RRF (k=60).

        Mirrors db.py:759-904 but fetches FTS from D1 and vectors from Vectorize.
        Writers wait_until_indexed (E.3); archived/category are enforced at D1
        hydration so a stale vector metadata can never leak an archived row.
        """
        if tags and len(tags) > MAX_TAGS_FILTER:
            raise ValueError(
                f"Maximum of {MAX_TAGS_FILTER} tags allowed in search filter"
            )
        limit = max(1, min(int(limit), 100))
        pool = candidate_pool if candidate_pool is not None else max(limit * 10, 50)

        results = self._search_fts_d1(
            query,
            category,
            tags,
            pool,
            context_type=context_type,
            since=since,
            until=until,
            min_importance=min_importance,
            include_archived=include_archived,
        )

        if embedding and self._vec_enabled:
            try:
                matches = self._vec.query(
                    embedding, top_k=pool, metadata_filter={"sub": self.sub}
                )
                missing: list[tuple[str, float]] = []
                for m in matches:
                    mid = (m.get("metadata") or {}).get("mid")
                    if not mid:
                        continue
                    vscore = max(0.0, float(m.get("score", 0.0)))
                    if mid in results:
                        results[mid]["vec_score"] = vscore
                    else:
                        missing.append((mid, vscore))
                if missing:
                    ids = [mid for mid, _ in missing]
                    ph = ", ".join("?" for _ in ids)
                    sql = f"SELECT * FROM memories WHERE sub = ? AND id IN ({ph})"
                    params: list = [self.sub, *ids]
                    if not include_archived:
                        sql += " AND archived_at IS NULL"
                    if category:
                        sql += " AND category = ?"
                        params.append(category)
                    by_id = {r["id"]: r for r in self._d1.execute(sql, params)}
                    score_by_id = dict(missing)
                    for mid, row in by_id.items():
                        results[mid] = {
                            **row,
                            "fts_score": 0.0,
                            "vec_score": score_by_id[mid],
                        }
            except Exception as e:
                logger.debug(f"Vector search error: {e}")

        if not results:
            return []
        scored = self._compute_hybrid_scores(results)
        effective_top = limit if candidate_pool is None else min(pool, len(scored))
        top = scored[:effective_top]
        self._update_access_stats(top)
        for m in top:
            m.pop("fts_score", None)
            m.pop("vec_score", None)
            m.pop("bm25_score", None)
        return top

    def stats(self) -> dict:
        """Per-sub database statistics (ported from db.py:1289-1307)."""
        total_rows = self._d1.execute(
            "SELECT COUNT(*) AS n FROM memories WHERE sub = ?", [self.sub]
        )
        total = total_rows[0]["n"] if total_rows else 0
        cats = self._d1.execute(
            "SELECT category, COUNT(*) AS cnt FROM memories WHERE sub = ? "
            "GROUP BY category ORDER BY cnt DESC",
            [self.sub],
        )
        last = self._d1.execute(
            "SELECT MAX(updated_at) AS m FROM memories WHERE sub = ?", [self.sub]
        )
        return {
            "total_memories": total,
            "categories": {r["category"]: r["cnt"] for r in cats},
            "last_updated": last[0]["m"] if last else None,
            "vec_enabled": self._vec_enabled,
            "db_path": "cf-d1",
        }

    # ------------------------------------------------------------------
    # JSONL export / import -- parity with db.MemoryDB.export_jsonl /
    # import_jsonl, scoped to self.sub. Export reads only this sub's rows;
    # import writes every row under this sub (any `sub` in the payload is
    # ignored), so a single-user dump lands under the importing session's
    # identity (DECISION D3). This is the path the export_memories /
    # import_memories tools take on the CF backend; without it those tools
    # AttributeError on cf-d1 and a memory migration has no canonical route.
    # ------------------------------------------------------------------

    def export_jsonl(self) -> tuple[str, int]:
        """Export this sub's memories as JSONL (mirrors db.py:1309 field set)."""
        query = (
            "SELECT json_object("
            "'id', id, 'content', content, 'category', category, "
            "'tags', json(tags), 'source', source, "
            "'created_at', created_at, 'updated_at', updated_at, "
            "'access_count', access_count, 'last_accessed', last_accessed"
            ") AS json_data "
            "FROM memories WHERE sub = ? ORDER BY created_at"
        )
        rows = self._d1.execute(query, [self.sub])
        out = "".join(r["json_data"] + "\n" for r in rows)
        return out, len(rows)

    @staticmethod
    def _parse_import_data(data: str | list | dict) -> tuple[list[dict], int]:
        """Parse JSONL string / list / dict into dicts (mirrors db.py:1350)."""
        if isinstance(data, list):
            return data, 0
        if isinstance(data, dict):
            return [data], 0
        if isinstance(data, str):
            items: list[dict] = []
            rejected = 0
            for raw in data.strip().split("\n"):
                line = raw.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    rejected += 1
            return items, rejected
        return [], 0

    def _count_rows(self) -> int:
        rows = self._d1.execute(
            "SELECT COUNT(*) AS n FROM memories WHERE sub = ?", [self.sub]
        )
        return rows[0]["n"] if rows else 0

    def import_jsonl(self, data: str | list | dict, mode: str = "merge") -> dict:
        """Import memories under self.sub (mirrors db.py:1434).

        ``mode='merge'`` keeps existing ids (INSERT OR IGNORE); ``'replace'``
        clears this sub's rows first (INSERT OR REPLACE). Rows are inserted
        WITHOUT embeddings -- parity with the local import, which writes rows
        only -- and FTS is trigger-maintained, so imports are immediately
        keyword-searchable. Vectorize is left untouched: a stale vector for a
        replaced id is harmless because search() hydrates from D1 and drops
        vector hits with no matching row. Counts are derived from a
        before/after row count since D1 executemany returns no rowcount.
        """
        items, rejected = self._parse_import_data(data)
        now = _now_iso()
        to_insert: list[list] = []
        for mem in items:
            try:
                content = mem.get("content", "")
                if not content or len(content) > MAX_CONTENT_LENGTH:
                    rejected += 1
                    continue
                tags = mem.get("tags", [])
                tags_json = (
                    "[]"
                    if tags == []
                    else (json.dumps(tags) if isinstance(tags, list) else tags)
                )
                to_insert.append(
                    [
                        mem.get("id", uuid.uuid4().hex),
                        self.sub,
                        content,
                        mem.get("category", "general"),
                        tags_json,
                        mem.get("source"),
                        mem.get("created_at", now),
                        mem.get("updated_at", now),
                        mem.get("access_count", 0),
                        mem.get("last_accessed", now),
                        mem.get("importance", 0.5),
                    ]
                )
            except Exception:
                rejected += 1

        if mode == "replace":
            self._d1.execute("DELETE FROM memories WHERE sub = ?", [self.sub])
        before = self._count_rows()
        if to_insert:
            op = "REPLACE" if mode == "replace" else "IGNORE"
            sql = (
                f"INSERT OR {op} INTO memories "
                "(id, sub, content, category, tags, source, "
                "created_at, updated_at, access_count, last_accessed, importance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )
            # Pre-chunk to the D1 param-safe row budget: each executemany call then
            # expands into a single multi-row INSERT that stays under the 100 bound
            # parameter ceiling (a 264-row import that previously crashed D1 now
            # lands as ~30 safe statements).
            for j in range(0, len(to_insert), _D1_SAFE_IMPORT_ROWS):
                self._d1.executemany(sql, to_insert[j : j + _D1_SAFE_IMPORT_ROWS])
        after = self._count_rows()
        imported = after - before
        skipped = len(to_insert) - imported
        if imported > 0:
            logger.info(f"[AUDIT] import count={imported} sub={self.sub} mode={mode}")
        return {"imported": imported, "skipped": skipped, "rejected": rejected}

    def close(self) -> None:
        return None
