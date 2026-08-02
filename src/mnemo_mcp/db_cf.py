"""Cloudflare D1 + Vectorize backend for the Mnemo memory store (S2 Tasks 3-4).

``MemoryDBCfBackend`` presents the same surface as :class:`mnemo_mcp.db.MemoryDB`
but reads and writes a Cloudflare D1 database over the Worker outbound handler
(``src/worker.ts``'s ``d1Outbound``) instead of a local SQLite file. Selection
happens in exactly one place -- :func:`open_memory_db`, driven by the
``MEMORY_DB_BACKEND`` env var -- and the default stays SQLite.

Storage split: rows and the FTS5 index live in D1; dense vectors live in a
Cloudflare Vectorize index reached through ``src/worker.ts``'s
``vectorizeOutbound``. ``migrations/0001_init.sql`` deliberately has no
``memories_vec`` -- D1 cannot load the ``sqlite-vec`` extension -- so there is no
in-database vector table to fall back on. When the store is opened with
``embedding_dims=0`` no Vectorize index is attached, ``vec_enabled`` is ``False``,
and an entry point handed an embedding raises rather than dropping it.

Vector design notes
-------------------

*The 50-candidate ceiling is announced, not absorbed.* Cloudflare Vectorize caps
``topK`` at 50, and ``mcp_core.storage.vectorize.VectorizeBackend.query`` applies
that cap with a bare ``top_k = min(top_k, 50)`` -- no exception, no warning, no
signal of any kind. ``MemoryDB.search`` asks for ``max(limit * 10, 50)``
candidates, so every search with ``limit > 5`` would quietly fuse a full-width
FTS ranking against a 50-deep vector ranking and call the result "top N".
:meth:`MemoryDBCfBackend._vector_candidates` therefore compares the two numbers
itself, logs a WARNING naming both, and records the shortfall on
:attr:`MemoryDBCfBackend.last_vector_cap` so a caller can see it without reading
logs. The cap is not raised anywhere -- it cannot be -- but it is never silent.

*Read-after-write on the vector arm is eventually consistent, and says so.* D1 is
strongly consistent, so a row is FTS-searchable the instant ``add`` returns.
Vectorize is not: an upsert becomes queryable seconds later. The obvious
mitigation, ``VectorizeBackend.wait_until_indexed()``, does NOT work here and is
deliberately not called: it polls ``GET {base}``, and ``vectorizeOutbound`` answers
*every* GET with ``{ready: true}`` unconditionally (``src/worker.ts``). It reports
that the outbound handler is wired, never that a particular mutation landed, so
calling it after an upsert would manufacture exactly the false "indexed" signal
this repo has already paid for once. A per-mutation wait needs a Worker route
that does not exist yet. Until then the behaviour is: a just-added memory is
immediately findable by text and joins the semantic ranking once Vectorize
indexes it. That is written down here, asserted in
``tests/test_db_cf_vectors.py``, and never papered over with a retry loop.

*Superseded rows cannot resurface, by construction.* ``delete`` only sets
``valid_to`` and ``update`` opens a new id while closing the old one, neither of
which Vectorize knows about. Two independent mechanisms cover it. Write side:
both methods delete the closed id's vector via ``POST /deleteByIds``. Read side --
the authoritative one -- every id Vectorize returns is re-fetched from D1 through
the same ``_build_filter_sql`` tail the FTS arm uses, whose first fragment is
``AND m.valid_to IS NULL``; an id that does not survive that query is dropped
from the fusion. The read-side filter holds even if a write-side delete failed or
has not propagated, which is why it is the one the correctness claim rests on.

*Vector loss is loud, and only where it is unavoidable.* A metadata-only
``update`` (no new content, so no new embedding) carries the old vector forward on
SQLite. That is impossible here: Vectorize has no read-by-id, ``VectorizeBackend``
exposes no getter, and ``vectorizeOutbound`` routes no such path, so the vector
cannot be copied to the successor id. The successor is left unvectorised and a
WARNING names the id and the reason, rather than leaving a caller to discover the
gap through degraded recall.

Design notes
------------

*Behaviour is borrowed, not copied.* The scoring pipeline (BM25 normalisation,
RRF fusion, recency/frequency/importance weighting) and the read-only SQL are
taken from ``MemoryDB`` by class-level assignment, through a ``_conn`` adapter
that speaks the sqlite3 slice those methods actually use. Re-typing that SQL
here would let the two backends drift apart silently, which is the one failure
mode a parity test cannot catch after the fact. Methods that need something the
D1 wire cannot give -- ``cursor.rowcount``, a real ``ROLLBACK`` -- are written
out explicitly below instead of borrowed.

*Transport errors are never swallowed.* ``MemoryDB._search_fts`` wraps each FTS
tier in ``except Exception: logger.error(...)`` -- harmless against local SQLite,
but on D1 an HTTP failure would be caught there and the search would return
"no results" for what is actually an outage. :meth:`MemoryDBCfBackend._search_fts`
re-raises any transport error the borrowed body absorbed.

*Only ``POST /query`` is used.* ``src/worker.ts``'s ``d1Outbound`` routes
``/query`` and returns 404 for anything else, so ``D1Backend.executemany``'s
non-INSERT fallback (which POSTs ``/batch``) would 404 against this Worker.
Bulk import below therefore builds its own multi-row INSERT and sends it through
``/query``, chunked to respect D1's hard cap of 100 bound parameters per query
(https://developers.cloudflare.com/d1/platform/limits/) -- a cap
``D1Backend.executemany`` does not model, since it chunks by rows, not params.

*No transactions.* D1 wraps each query in its own implicit transaction and the
``/query`` wire has no BEGIN/COMMIT, so multi-statement writes cannot be atomic
here. :meth:`update` is the only such write; it is ordered so the guarded
``UPDATE ... RETURNING`` is the serialisation point, and it issues a
compensating write plus a loud log if the successor INSERT fails.
"""

from __future__ import annotations

import functools
import inspect
import json
import os
import uuid
from pathlib import Path
from typing import Any, NamedTuple, cast

from loguru import logger
from mcp_core.storage.d1 import D1Backend, d1_backend_from_env
from mcp_core.storage.vectorize import VectorizeBackend, vectorize_backend_from_env

from mnemo_mcp.db import MAX_CONTENT_LENGTH, MAX_TAGS_FILTER, MemoryDB, _now_iso

# Cloudflare D1 rejects a query carrying more than this many bound parameters.
# https://developers.cloudflare.com/d1/platform/limits/
D1_MAX_BOUND_PARAMS = 100

# Cloudflare Vectorize refuses to return more than this many matches from one
# query. `VectorizeBackend.query` already clamps to it -- with a bare
# `top_k = min(top_k, 50)` that raises nothing and logs nothing -- so the number
# is restated here to be compared against the requested pool before the call.
# https://developers.cloudflare.com/vectorize/platform/limits/
VECTORIZE_MAX_TOP_K = 50

# Ids per `POST /deleteByIds` request. A client-side bound to keep a reindex of a
# large store from building one enormous request body; Cloudflare documents no
# hard id count for this endpoint, so this mirrors no platform cap and can be
# raised freely.
VECTORIZE_DELETE_CHUNK = 500


class VectorCandidateCap(NamedTuple):
    """How much of a requested vector candidate pool Vectorize actually served.

    Recorded on :attr:`MemoryDBCfBackend.last_vector_cap` after every search that
    ran the vector arm, so "the fused list is top-N over a truncated vector
    ranking" is observable in-process and not only in the log stream.
    """

    requested: int
    served: int

    @property
    def truncated(self) -> bool:
        return self.served < self.requested


# Tables `MemoryDBCfBackend` reads or writes. wrangler owns schema creation via
# `migrations/0001_init.sql`; this backend only asserts the migration ran.
REQUIRED_TABLES = (
    "memories",
    "memories_fts",
    "store_meta",
    "archived_memories",
)

# Columns written by the bulk-import path, in the order `_process_import_batch`
# emits them. Kept as a constant so the generated multi-row INSERT never
# interpolates anything caller-controlled.
_IMPORT_COLUMNS = (
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
)
_IMPORT_ROWS_PER_STATEMENT = D1_MAX_BOUND_PARAMS // len(_IMPORT_COLUMNS)

_NO_VECTOR_INDEX = (
    "This store was opened with embedding_dims=0, so no Cloudflare Vectorize "
    "index is attached and there is nowhere for the vector to go. D1 itself "
    "cannot hold it: migrations/0001_init.sql has no memories_vec table because "
    "D1 cannot load the sqlite-vec extension. Open the store with the embedding "
    "dimension of the active model (and MCP_VECTORIZE_IDX set) to enable vectors."
)


class _D1Row(dict):
    """A D1 result row that also answers positional lookups.

    D1 returns each row as a JSON object, so key access works out of the box.
    Several borrowed ``MemoryDB`` methods index rows positionally
    (``fetchone()[0]``, ``legacy[3]``) the way ``sqlite3.Row`` allows; JSON
    preserves the SELECT's column order, so position ``n`` is the ``n``-th value.
    """

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class _D1Cursor:
    """Result handle over a materialised D1 row set.

    ``rowcount`` is deliberately absent: ``POST /query`` returns rows only, with
    no "rows changed" counter, so anything that needs a write count uses
    ``RETURNING`` explicitly rather than reading a fabricated number here.
    """

    def __init__(self, conn: _D1Connection, rows: list[_D1Row]) -> None:
        self._conn = conn
        self.rows = rows

    def execute(self, sql: str, params: Any = ()) -> _D1Cursor:
        return self._conn.execute(sql, params)

    def fetchall(self) -> list[_D1Row]:
        return self.rows

    def fetchone(self) -> _D1Row | None:
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class _D1Connection:
    """The slice of the ``sqlite3.Connection`` API the borrowed methods use.

    Every statement is a separate ``POST /query``, which is also how D1 behaves:
    one implicit transaction per query. ``commit`` is therefore a no-op and
    ``rollback`` raises -- a silent no-op rollback would let borrowed code
    believe it had undone a write it could not undo.
    """

    def __init__(self, backend: D1Backend) -> None:
        self._backend = backend
        self._closed = False
        self.last_error: Exception | None = None

    def execute(self, sql: str, params: Any = ()) -> _D1Cursor:
        if self._closed:
            raise RuntimeError("Cannot operate on a closed MemoryDBCfBackend.")
        try:
            rows = self._backend.fetchall(sql, list(params))
        except Exception as exc:
            self.last_error = exc
            raise
        return _D1Cursor(self, [_D1Row(r) for r in rows])

    def cursor(self) -> _D1Cursor:
        return _D1Cursor(self, [])

    def commit(self) -> None:
        """No-op: D1 commits each query on its own."""

    def rollback(self) -> None:
        raise NotImplementedError(
            "The D1 /query wire has no ROLLBACK -- each query is committed on "
            "its own. A caller reaching this needs an explicit compensating "
            "write instead."
        )

    def executescript(self, sql: str) -> None:
        raise NotImplementedError(
            "Schema creation on D1 belongs to wrangler "
            "(`wrangler d1 migrations apply`), not to this backend."
        )

    def close(self) -> None:
        self._closed = True

    def clear_error(self) -> None:
        self.last_error = None

    def raise_if_error(self, what: str) -> None:
        """Re-raise a transport error that borrowed code caught and logged."""
        exc = self.last_error
        if exc is None:
            return
        self.last_error = None
        raise RuntimeError(
            f"{what} against Cloudflare D1 failed; the result set below it is "
            f"incomplete and must not be treated as 'no matches': {exc}"
        ) from exc


def _vectorize_from_env() -> VectorizeBackend:
    """Build the Vectorize client, turning a missing index name into an answer.

    ``vectorize_backend_from_env`` reads ``MCP_VECTORIZE_IDX`` with ``[]`` and so
    fails with a bare ``KeyError('MCP_VECTORIZE_IDX')`` several frames from
    anything that explains it.
    """
    try:
        return vectorize_backend_from_env()
    except KeyError as exc:
        raise RuntimeError(
            "MCP_VECTORIZE_IDX is not set, so the D1 backend has no Cloudflare "
            "Vectorize index to store or query embeddings in. Set it (and "
            "MCP_VECTORIZE_BASE_URL if the Worker is not at the default "
            "http://vectorize.internal), or open the store with EMBEDDING_DIMS=0 "
            "to declare it text-only. Starting without either would leave "
            "semantic search missing with nothing to say so."
        ) from exc


def _vectorize_delete_by_ids(vectors: VectorizeBackend, ids: list[str]) -> None:
    """``POST {base}/deleteByIds`` -- the route ``VectorizeBackend`` omits.

    ``src/worker.ts``'s ``vectorizeOutbound`` serves ``/deleteByIds`` and calls
    ``env.VECTORIZE.deleteByIds``, but ``mcp_core.storage.vectorize`` (1.21.0)
    ships only ``upsert``, ``query`` and ``wait_until_indexed``. This reuses the
    backend's own transport and auth headers rather than opening a second HTTP
    client, so the injected ``http=`` seam the tests rely on keeps covering every
    request the store makes -- including this one.
    """
    if not ids:
        return
    for i in range(0, len(ids), VECTORIZE_DELETE_CHUNK):
        chunk = ids[i : i + VECTORIZE_DELETE_CHUNK]
        body = json.dumps({"ids": chunk}).encode()
        status, _ = vectors._http.request(
            "POST", f"{vectors.base_url}/deleteByIds", body, vectors._headers()
        )
        if status != 200:
            raise RuntimeError(
                f"Vectorize deleteByIds failed: HTTP {status} for {len(chunk)} id(s) "
                f"starting at {chunk[0]!r}. The vectors are still queryable."
            )


def _vector_write(method):
    """Wrap an ``add``-shaped ``MemoryDB`` method to write D1 first, then Vectorize.

    The borrowed body would run ``INSERT INTO memories_vec`` against a table this
    database does not have, so the embedding is withheld from it and sent to
    Vectorize afterwards, keyed by the id the body just allocated. D1 is written
    first on purpose: a row with no vector degrades to text-only recall and is
    repaired by a reindex, whereas a vector whose row was never written is an
    orphan that nothing points at.

    With no Vectorize index attached, an embedding raises instead of being
    dropped -- ``if embedding and self._vec_enabled`` in the borrowed body would
    otherwise accept the vector, store nothing, and report success.
    """
    signature = inspect.signature(method)

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        embedding = bound.arguments.get("embedding")
        if embedding:
            self._require_vectors(method.__name__)
        # Withheld unconditionally: the borrowed body has no reachable vector
        # target on D1 under any setting.
        bound.arguments["embedding"] = None
        memory_id = method(*bound.args, **bound.kwargs)
        if embedding:
            self._upsert_vector(memory_id, embedding)
        return memory_id

    return wrapper


class MemoryDBCfBackend:
    """Cloudflare D1 implementation of the :class:`MemoryDB` surface."""

    # -- Borrowed from MemoryDB -------------------------------------------
    # Pure scoring helpers: they touch only ``self._recency_half_life``.
    _build_filter_sql = MemoryDB._build_filter_sql
    _calc_recency = MemoryDB._calc_recency
    _calc_frequency = MemoryDB._calc_frequency
    _compute_hybrid_scores = MemoryDB._compute_hybrid_scores
    rrf_fuse = staticmethod(MemoryDB.rrf_fuse)

    # Read paths and single-statement writes: they use only
    # ``self._conn.execute`` / ``.cursor()`` and never need a rows-changed count.
    get_store_meta = MemoryDB.get_store_meta
    _set_store_meta = MemoryDB._set_store_meta
    _stamp_embedding_identity = MemoryDB._stamp_embedding_identity
    _guard_embedding_identity = MemoryDB._guard_embedding_identity
    _update_access_stats = MemoryDB._update_access_stats
    list_memories = MemoryDB.list_memories
    get = MemoryDB.get
    stats = MemoryDB.stats
    export_jsonl = MemoryDB.export_jsonl
    list_archived = MemoryDB.list_archived
    check_duplicate = MemoryDB.check_duplicate
    _parse_import_data = MemoryDB._parse_import_data
    _process_import_batch = MemoryDB._process_import_batch

    # Vector-carrying write paths: same bodies, but the embedding is routed to
    # Vectorize instead of to a `memories_vec` table that does not exist here.
    add = _vector_write(MemoryDB.add)
    add_with_context_type = _vector_write(MemoryDB.add_with_context_type)

    def __init__(
        self,
        backend: D1Backend | None = None,
        *,
        vectors: VectorizeBackend | None = None,
        embedding_dims: int = 0,
        recency_half_life_days: float = 7.0,
        embedding_model: str = "",
        reindex_on_model_change: bool = False,
    ) -> None:
        """Open the D1-backed store.

        Args:
            backend: D1 wire client. Defaults to
                :func:`mcp_core.storage.d1.d1_backend_from_env`, which reads
                ``MCP_D1_BASE_URL`` (default ``http://d1.internal``) and
                ``MCP_D1_TOKEN``.
            vectors: Vectorize wire client. Defaults to
                :func:`mcp_core.storage.vectorize.vectorize_backend_from_env`,
                which reads ``MCP_VECTORIZE_BASE_URL`` (default
                ``http://vectorize.internal``) and requires ``MCP_VECTORIZE_IDX``.
                Only consulted when ``embedding_dims > 0``.
            embedding_dims: Vector width, recorded in ``store_meta`` for the
                identity guard. ``0`` declares the store text-only: no Vectorize
                index is attached and an embedding passed anywhere raises.
            recency_half_life_days: Half-life in days for recency decay.
            embedding_model: Active embedding-model identity string.
            reindex_on_model_change: When set, an embedding-identity mismatch
                deletes every stored vector and re-stamps, instead of raising.

        Raises:
            ValueError: On an out-of-range ``embedding_dims``, or when
                ``vectors`` is supplied for a store declared text-only.
            RuntimeError: When the D1 database has not had
                ``migrations/0001_init.sql`` applied, or when vectors are
                requested without ``MCP_VECTORIZE_IDX``.
            EmbeddingModelMismatch: Same contract as :class:`MemoryDB`.
        """
        if type(embedding_dims) is not int:
            raise ValueError(
                f"embedding_dims must be an integer, got {type(embedding_dims).__name__}"
            )
        if not (0 <= embedding_dims <= 10000):
            raise ValueError(
                f"embedding_dims must be between 0 and 10000, got {embedding_dims}"
            )
        if vectors is not None and embedding_dims <= 0:
            raise ValueError(
                "vectors= was supplied with embedding_dims=0. That combination "
                "would attach a Vectorize index the store then refuses to write "
                "to, so it is rejected rather than quietly ignored."
            )

        self._backend = backend if backend is not None else d1_backend_from_env()
        self._conn = _D1Connection(self._backend)
        self._db_path = f"cf-d1:{self._backend.base_url}"
        self._embedding_dims = embedding_dims
        self._embedding_model = embedding_model
        self._reindex_on_model_change = reindex_on_model_change
        self._recency_half_life = float(recency_half_life_days)

        if embedding_dims > 0:
            self._vectors = vectors if vectors is not None else _vectorize_from_env()
        else:
            self._vectors = None
        self._vec_enabled = self._vectors is not None

        #: Width of the last vector candidate pool asked for vs. served. ``None``
        #: until a search runs the vector arm. See :class:`VectorCandidateCap`.
        self.last_vector_cap: VectorCandidateCap | None = None

        self._require_schema()
        self._guard_embedding_identity()

    def _require_schema(self) -> None:
        """Fail at open time when the D1 migration has not been applied.

        Without this the first query fails as an opaque ``HTTP 500`` from the
        Worker, several calls away from the actual cause.
        """
        try:
            rows = self._backend.fetchall(
                "SELECT name FROM sqlite_master WHERE type = 'table'", []
            )
        except Exception as exc:
            raise RuntimeError(
                f"Could not read the schema of the D1 database at "
                f"{self._backend.base_url}: {exc}"
            ) from exc
        present = {r["name"] for r in rows}
        missing = [t for t in REQUIRED_TABLES if t not in present]
        if missing:
            raise RuntimeError(
                f"D1 database at {self._backend.base_url} is missing "
                f"{', '.join(missing)}. Apply the schema first: "
                "`wrangler d1 migrations apply mnemo-memories`."
            )

    @property
    def vec_enabled(self) -> bool:
        """Whether a Cloudflare Vectorize index is attached to this store."""
        return self._vectors is not None

    # -- Vectors -----------------------------------------------------------

    def _require_vectors(self, what: str) -> VectorizeBackend:
        if self._vectors is None:
            raise NotImplementedError(
                f"MemoryDBCfBackend.{what}() was given an embedding, which it "
                f"cannot store or query. {_NO_VECTOR_INDEX}"
            )
        return self._vectors

    def _fit_dims(self, embedding: list[float]) -> list[float]:
        """Truncate or zero-pad to ``embedding_dims``, exactly as SQLite does.

        ``db._serialize_f32`` reshapes every vector to the store's width before
        writing it, so a caller that hands over a differently-sized vector gets
        the same result on both backends rather than an error on one of them.
        """
        vec = [float(x) for x in embedding]
        dims = self._embedding_dims
        if dims > 0:
            if len(vec) > dims:
                vec = vec[:dims]
            elif len(vec) < dims:
                vec = vec + [0.0] * (dims - len(vec))
        return vec

    def _upsert_vector(self, memory_id: str, embedding: list[float]) -> None:
        """Write one vector, keyed by the memory id it belongs to."""
        vectors = self._require_vectors("_upsert_vector")
        vectors.upsert([{"id": memory_id, "values": self._fit_dims(embedding)}])

    def _discard_vectors(self, ids: list[str], context: str) -> None:
        """Delete vectors whose rows are gone, without failing the row change.

        The D1 write that closed those rows has already committed and is the
        state search reads: ``_vector_candidates`` re-checks every Vectorize hit
        against ``valid_to IS NULL``, so a vector that outlives its row cannot
        surface in results. Raising here would report a delete or update that
        did take effect as failed, and a caller retrying it would then be told
        the row was already closed. So the row change stands and the orphan is
        logged at ERROR with its id -- it wastes index space until the next
        reindex, which is a cleanup job, not a correctness one.
        """
        if self._vectors is None or not ids:
            return
        try:
            _vectorize_delete_by_ids(self._vectors, ids)
        except Exception as exc:
            logger.error(
                "[AUDIT] {} closed row(s) {} in D1 but could not delete their "
                "vectors ({}). The rows are gone from search either way -- every "
                "Vectorize hit is re-checked against D1 -- but the vectors are "
                "orphaned in the index until the next reindex.",
                context,
                ", ".join(ids),
                exc,
            )

    def _drop_vectors_for_reindex(self) -> None:
        """Delete every stored vector so the embed pipeline rebuilds them.

        Reached from the borrowed identity guard when the embedding model or
        width changed and ``REINDEX_ON_MODEL_CHANGE`` is set. Vectorize has no
        "delete everything" call, so the ids are read out of D1 -- the store's
        own list of what it ever embedded -- and deleted in batches.

        Failure propagates, unlike :meth:`_discard_vectors`. The guard calls this
        *before* ``_stamp_embedding_identity``, so raising leaves the old stamp in
        place and the next boot retries; swallowing the error would re-stamp the
        new model over an index still holding the old model's vectors, and mixed
        vector spaces at the same width degrade search silently -- the exact
        failure the identity guard exists to prevent.
        """
        vectors = self._vectors
        if vectors is None:
            raise NotImplementedError(
                "REINDEX_ON_MODEL_CHANGE cannot be honoured: no Vectorize index "
                f"is attached to this store. {_NO_VECTOR_INDEX}"
            )
        rows = self._backend.fetchall("SELECT id FROM memories", [])
        ids = [r["id"] for r in rows]
        _vectorize_delete_by_ids(vectors, ids)
        logger.warning(
            "[AUDIT] reindex dropped {} vector(s) from the Vectorize index; they "
            "rebuild on the next embed pass.",
            len(ids),
        )

    def _clear_for_import(self, mode: str) -> None:
        """Clear memories for a replace-mode import, vectors included.

        Overrides the borrowed body, which would run ``DELETE FROM memories_vec``
        against a table this database does not have. Vectors go first: if the
        Vectorize delete fails the D1 rows are still present, so the ids needed
        to retry are still readable. The reverse order would strand every vector
        with no list of what to delete.
        """
        if mode != "replace":
            return
        if self._vectors is not None:
            rows = self._backend.fetchall("SELECT id FROM memories", [])
            _vectorize_delete_by_ids(self._vectors, [r["id"] for r in rows])
        self._backend.execute("DELETE FROM memories", [])

    # -- Search ------------------------------------------------------------

    def _search_fts(self, *args, **kwargs) -> dict[str, dict]:
        """Borrowed FTS search, with swallowed transport errors re-raised."""
        self._conn.clear_error()
        # cast: the borrow is structural -- the body only reaches for
        # ``self._conn`` and the filter helpers, both of which exist here.
        results = MemoryDB._search_fts(cast(MemoryDB, self), *args, **kwargs)
        self._conn.raise_if_error("FTS5 search")
        return results

    def _vector_candidates(
        self,
        embedding: list[float],
        pool: int,
        category: str | None,
        tags: list[str] | None,
        filter_kwargs: dict,
    ) -> dict[str, dict]:
        """Rank ids by Vectorize similarity, then re-authorise each against D1.

        Two things happen here that have no counterpart in the SQLite path.

        First, the candidate pool is capped. ``MemoryDB.search`` asks for
        ``max(limit * 10, 50)`` candidates but Vectorize returns at most
        :data:`VECTORIZE_MAX_TOP_K`, and ``VectorizeBackend.query`` applies that
        cap without a word. The two numbers are compared here so the shortfall
        reaches a log line and :attr:`last_vector_cap` instead of disappearing:
        above ``limit=5`` the fused ranking is top-N over a 50-deep vector arm,
        which is a weaker claim than the SQLite path makes and must not read as
        the same one.

        Second, every returned id is re-fetched from D1 under the caller's
        filters -- whose ``_build_filter_sql`` tail always begins ``AND
        m.valid_to IS NULL``. That is what keeps a superseded or soft-deleted row
        out of the results even when its vector is still in the index, and it is
        also why no metadata filter is sent to Vectorize: filtering there would
        need metadata indexes declared at index-creation time in wrangler, and
        would still not be authoritative about supersession, which only D1 knows.
        The cost is real and one-directional -- a narrow ``category`` filter can
        leave few of the 50 candidates standing -- so it is stated here rather
        than presented as a filtered top-50.

        Transport errors propagate. ``MemoryDB.search`` wraps its vector branch
        in ``except Exception: logger.debug(...)``, which against a network
        backend would turn a Vectorize outage into a search that silently
        returns FTS-only results and looks healthy.
        """
        vectors = self._require_vectors("search")
        top_k = min(pool, VECTORIZE_MAX_TOP_K)
        self.last_vector_cap = VectorCandidateCap(requested=pool, served=top_k)
        if top_k < pool:
            logger.warning(
                "Vector search asked for {} candidates but Cloudflare Vectorize "
                "returns at most {}; the fused ranking below is top-N over a "
                "{}-deep vector arm against a {}-deep FTS arm, not over the whole "
                "store. Lower `limit` (pool = max(limit * 10, 50)) or pass an "
                "explicit `candidate_pool` <= {} to make the two arms match.",
                pool,
                VECTORIZE_MAX_TOP_K,
                top_k,
                pool,
                VECTORIZE_MAX_TOP_K,
            )

        matches = vectors.query(self._fit_dims(embedding), top_k)
        scores: dict[str, float] = {}
        for match in matches:
            mid = match.get("id")
            if mid is None:
                continue
            # Vectorize returns a similarity score, where sqlite-vec returns a
            # distance that db.py converts with ``1.0 - distance``. Both land in
            # [0, 1] and only the ordering feeds RRF.
            scores[mid] = max(0.0, min(1.0, float(match.get("score", 0.0))))
        if not scores:
            return {}

        fragments = ["WHERE m.id IN (SELECT value FROM json_each(?))"]
        params: list = [json.dumps(list(scores))]
        if category:
            fragments.append("AND m.category = ?")
            params.append(category)
        if tags:
            fragments.append(
                "AND m.tags != '[]' AND json_valid(m.tags) AND EXISTS "
                "(SELECT 1 FROM json_each(m.tags) WHERE value IN "
                "(SELECT value FROM json_each(?)))"
            )
            params.append(json.dumps(tags))
        extra_sql, extra_params = self._build_filter_sql(**filter_kwargs)
        if extra_sql:
            fragments.append(extra_sql)
            params.extend(extra_params)

        rows = self._backend.fetchall(
            "SELECT m.* FROM memories m " + " ".join(fragments), params
        )
        # Re-keyed by Vectorize's ranking, not by whatever order D1 returned the
        # rows in. `_compute_hybrid_scores` derives both arms' ranks with a
        # stable sort, so insertion order is what settles a tie between equal
        # scores. Preserving the vector ranking here makes that tie-break
        # meaningful instead of arbitrary.
        #
        # Note this is one place the two backends can legitimately disagree:
        # `MemoryDB.search` re-reads its vector matches with a `WHERE id IN
        # (...)` query, which yields rows in table order rather than by
        # distance, so exactly-tied fused scores can come out ordered
        # differently there. Only the tie-break differs -- any pair whose scores
        # actually differ ranks the same on both -- and the fix belongs in
        # `db.py`, where changing it would move SQLite's output.
        by_id = {row["id"]: row for row in rows}
        return {
            mid: {**dict(by_id[mid]), "vec_score": score}
            for mid, score in scores.items()
            if mid in by_id
        }

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
        """Hybrid FTS5 + Vectorize search. See :meth:`MemoryDB.search`.

        Same shape as the SQLite path and the same fusion: the candidate pool,
        the tiered FTS query, ``_compute_hybrid_scores`` (RRF at k=60, then
        recency/frequency/importance) and the access-stat update are all the
        borrowed ones, so the two backends cannot drift on ranking. Only the
        source of the vector ranking differs -- ``memories_vec`` there, a
        Vectorize index here -- and what that costs is set out in
        :meth:`_vector_candidates`.
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

        pool = candidate_pool if candidate_pool is not None else max(limit * 10, 50)
        results = self._search_fts(query, category, tags, pool, **filter_kwargs)

        # No `and self._vectors is not None` guard: without an index the
        # embedding must raise (inside `_vector_candidates`), not be dropped into
        # an FTS-only search the caller would read as a hybrid one.
        if embedding:
            for mid, row in self._vector_candidates(
                embedding, pool, category, tags, filter_kwargs
            ).items():
                if mid in results:
                    results[mid]["vec_score"] = row["vec_score"]
                else:
                    results[mid] = {**row, "fts_score": 0.0}

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

    # -- Writes that need a rows-changed count or a rollback ---------------

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
        """Supersede a memory with a new version. See :meth:`MemoryDB.update`.

        Not atomic, and cannot be: the ``/query`` wire commits each statement on
        its own. The guarded ``UPDATE ... WHERE valid_to IS NULL RETURNING *``
        runs first, so a competing writer still loses the race exactly as on
        SQLite; if the successor INSERT then fails, the predecessor is reopened
        by a compensating write and the failure is re-raised. Should the
        compensation itself fail, the row id is logged at ERROR -- the one case
        that needs a human -- rather than being reported as a successful update.

        Vectors follow the id: the predecessor's vector is deleted and, when an
        ``embedding`` is supplied, the successor's is written. Without one the
        successor is left unvectorised and a WARNING says so. SQLite carries the
        old vector forward in that case; this backend cannot, because nothing can
        read a vector back out of Vectorize -- ``VectorizeBackend`` exposes no
        getter and ``src/worker.ts``'s ``vectorizeOutbound`` routes no get-by-id --
        and a successor that silently lost its vector would show up only as recall
        that quietly got worse. Re-embedding restores it; note that
        ``server._handle_update`` already re-embeds whenever ``content`` changes,
        so this affects metadata-only edits.
        """
        if embedding is not None:
            self._require_vectors("update")
        if content is not None and len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(
                f"Content length {len(content)} exceeds limit of {MAX_CONTENT_LENGTH}"
            )

        now = _now_iso()
        new_id = uuid.uuid4().hex

        old_row = self._backend.fetchone(
            "UPDATE memories SET valid_to = ?, superseded_by = ? "
            "WHERE id = ? AND valid_to IS NULL RETURNING *",
            [now, new_id, memory_id],
        )
        if old_row is None:
            return None

        new_row = dict(old_row)
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
            new_row["tags"] = "[]" if not tags else json.dumps(tags)
        if source is not None:
            new_row["source"] = source
        if importance is not None:
            new_row["importance"] = max(0.0, min(1.0, importance))

        columns = list(new_row.keys())
        column_list = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)

        try:
            self._backend.execute(
                f"INSERT INTO memories ({column_list}) VALUES ({placeholders})",
                [new_row[c] for c in columns],
            )
        except Exception:
            try:
                self._backend.execute(
                    "UPDATE memories SET valid_to = NULL, superseded_by = NULL "
                    "WHERE id = ? AND superseded_by = ?",
                    [memory_id, new_id],
                )
            except Exception as compensation_error:
                logger.error(
                    "[AUDIT] update id={} FAILED after closing the predecessor, "
                    "and reopening it also failed ({}). Row {} is now closed "
                    "with no successor and needs manual repair.",
                    memory_id,
                    compensation_error,
                    memory_id,
                )
            raise

        if self._vectors is not None:
            self._discard_vectors([memory_id], f"update id={memory_id}")
            if embedding:
                self._upsert_vector(new_id, embedding)
            else:
                logger.warning(
                    "[AUDIT] update id={} -> new_id={} carried no embedding, so "
                    "the successor has no vector and is reachable by text search "
                    "only until it is re-embedded. Vectorize cannot be read back, "
                    "so the predecessor's vector could not be copied forward.",
                    memory_id,
                    new_id,
                )

        logger.info(f"[AUDIT] update id={memory_id} -> new_id={new_id}")
        return new_id

    def delete(self, memory_id: str) -> bool:
        """Soft-close a memory and drop its vector. See :meth:`MemoryDB.delete`."""
        rows = self._backend.fetchall(
            "UPDATE memories SET valid_to = ? WHERE id = ? AND valid_to IS NULL "
            "RETURNING id",
            [_now_iso(), memory_id],
        )
        if not rows:
            return False
        self._discard_vectors([memory_id], f"delete id={memory_id}")
        logger.info(f"[AUDIT] delete id={memory_id}")
        return True

    def update_importance(self, memory_id: str, importance: float) -> bool:
        """Update the importance score. See :meth:`MemoryDB.update_importance`."""
        importance = max(0.0, min(1.0, importance))
        rows = self._backend.fetchall(
            "UPDATE memories SET importance = ? WHERE id = ? RETURNING id",
            [importance, memory_id],
        )
        return bool(rows)

    def archive_old_memories(
        self, days: int = 90, importance_threshold: float = 0.3
    ) -> int:
        """Soft-archive old, low-importance rows. See :meth:`MemoryDB`."""
        rows = self._backend.fetchall(
            "UPDATE memories SET archived_at = ? "
            "WHERE archived_at IS NULL "
            "  AND last_accessed < datetime('now', ?) "
            "  AND importance < ? "
            "RETURNING id",
            [_now_iso(), f"-{days} days", importance_threshold],
        )
        count = len(rows)
        if count > 0:
            logger.info(f"[AUDIT] archived count={count} mode=soft")
        return count

    def archive_by_score(
        self,
        archive_after_days: int | None = None,
        score_threshold: float = 1.0,
    ) -> int:
        """Archive by ``archive_score``. See :meth:`MemoryDB.archive_by_score`."""
        if archive_after_days is None:
            try:
                from mnemo_mcp.config import settings as _settings

                archive_after_days = int(_settings.archive_after_days)
            except Exception:
                archive_after_days = 90
        archive_after_days = max(1, int(archive_after_days))

        rows = self._backend.fetchall(
            "UPDATE memories SET archived_at = ? "
            "WHERE archived_at IS NULL "
            "AND ( MAX(0.0, julianday('now') - julianday(updated_at)) / ? ) "
            "    * (1.0 - MAX(0.0, MIN(1.0, COALESCE(importance, 0.0)))) > ? "
            "RETURNING id",
            [_now_iso(), float(archive_after_days), score_threshold],
        )
        count = len(rows)
        if count > 0:
            logger.info(
                f"[AUDIT] archived_by_score count={count} "
                f"after_days={archive_after_days} threshold={score_threshold}"
            )
        return count

    def restore_memory(self, memory_id: str) -> bool:
        """Restore an archived memory. See :meth:`MemoryDB.restore_memory`."""
        now = _now_iso()
        rows = self._backend.fetchall(
            "UPDATE memories SET archived_at = NULL, last_accessed = ? "
            "WHERE id = ? AND archived_at IS NOT NULL RETURNING id",
            [now, memory_id],
        )
        if rows:
            logger.info(f"[AUDIT] restore id={memory_id} mode=soft")
            return True

        legacy = self._backend.fetchone(
            "SELECT * FROM archived_memories WHERE id = ?", [memory_id]
        )
        if not legacy:
            return False
        self._backend.execute(
            "INSERT OR REPLACE INTO memories "
            "(id, content, category, tags, source, importance, "
            " created_at, updated_at, access_count, last_accessed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                legacy["id"],
                legacy["content"],
                legacy["category"],
                legacy["tags"],
                legacy["source"],
                legacy["importance"],
                legacy["created_at"],
                now,
                legacy["access_count"],
                now,
            ],
        )
        self._backend.execute("DELETE FROM archived_memories WHERE id = ?", [memory_id])
        logger.info(f"[AUDIT] restore id={memory_id} mode=legacy")
        return True

    def _execute_import_batch(
        self, to_insert: list[tuple], mode: str
    ) -> tuple[int, int]:
        """Insert prepared rows with multi-row INSERTs sized for D1's param cap.

        ``RETURNING id`` supplies the inserted count that ``cursor.rowcount``
        would give on SQLite; ``INSERT OR IGNORE`` emits no row for a conflict,
        so the difference is the skipped count.
        """
        if not to_insert:
            return 0, 0
        op = "REPLACE" if mode == "replace" else "IGNORE"
        column_list = ", ".join(_IMPORT_COLUMNS)
        row_placeholder = "(" + ", ".join("?" for _ in _IMPORT_COLUMNS) + ")"

        imported = 0
        for i in range(0, len(to_insert), _IMPORT_ROWS_PER_STATEMENT):
            chunk = to_insert[i : i + _IMPORT_ROWS_PER_STATEMENT]
            values_sql = ", ".join([row_placeholder] * len(chunk))
            flat = [value for row in chunk for value in row]
            rows = self._backend.fetchall(
                f"INSERT OR {op} INTO memories ({column_list}) "
                f"VALUES {values_sql} RETURNING id",
                flat,
            )
            imported += len(rows)

        skipped = len(to_insert) - imported if mode != "replace" else 0
        return imported, skipped

    def import_jsonl(self, data: str | list | dict, mode: str = "merge") -> dict:
        """Import memories from JSONL. See :meth:`MemoryDB.import_jsonl`."""
        self._clear_for_import(mode)
        items, rejected = self._parse_import_data(data)
        imported = 0
        skipped = 0
        now = _now_iso()
        for i in range(0, len(items), 900):
            to_insert, batch_rejected = self._process_import_batch(
                items[i : i + 900], now
            )
            rejected += batch_rejected
            batch_imported, batch_skipped = self._execute_import_batch(to_insert, mode)
            imported += batch_imported
            skipped += batch_skipped
        if imported > 0:
            logger.info(f"[AUDIT] import count={imported} mode={mode}")
        return {"imported": imported, "skipped": skipped, "rejected": rejected}

    # -- Not available on this backend -------------------------------------

    def get_sync_state(self, backend: str) -> dict | None:
        raise NotImplementedError(
            "sync_state is not part of migrations/0001_init.sql, so the D1 "
            "database has no delta-sync cursor table. Add it in a follow-up "
            "migration before running the sync pipeline against cf-d1."
        )

    def upsert_sync_state(
        self,
        backend: str,
        last_sync_at: float | None = None,
        last_commit_sha: str | None = None,
        upload_cursor: int | None = None,
    ) -> None:
        raise NotImplementedError(
            "sync_state is not part of migrations/0001_init.sql, so the D1 "
            "database has no delta-sync cursor table. Add it in a follow-up "
            "migration before running the sync pipeline against cf-d1."
        )

    def close(self) -> None:
        """Release the store.

        There is no persistent connection to close -- each query is its own HTTP
        request -- but the handle is marked closed so later use raises instead of
        quietly succeeding against a store the caller believes it released.
        """
        self._conn.close()


def open_memory_db(
    db_path: Path,
    *,
    embedding_dims: int = 0,
    recency_half_life_days: float = 7.0,
    embedding_model: str = "",
    reindex_on_model_change: bool = False,
) -> MemoryDB | MemoryDBCfBackend:
    """Build the memory store selected by ``MEMORY_DB_BACKEND``.

    This is the only place the variable is read. ``sqlite`` (the default) opens
    the local file at ``db_path``; ``cf-d1`` opens the Cloudflare D1 database
    described by ``MCP_D1_BASE_URL`` / ``MCP_D1_TOKEN`` and ignores ``db_path``.
    An unrecognised value raises rather than falling back, so a typo in the
    Worker's ``vars`` cannot quietly deploy the wrong store.
    """
    kind = os.environ.get("MEMORY_DB_BACKEND", "sqlite").strip().lower()
    if kind in ("", "sqlite"):
        return MemoryDB(
            db_path,
            embedding_dims=embedding_dims,
            recency_half_life_days=recency_half_life_days,
            embedding_model=embedding_model,
            reindex_on_model_change=reindex_on_model_change,
        )
    if kind == "cf-d1":
        return MemoryDBCfBackend(
            embedding_dims=embedding_dims,
            recency_half_life_days=recency_half_life_days,
            embedding_model=embedding_model,
            reindex_on_model_change=reindex_on_model_change,
        )
    raise ValueError(
        f"Unknown MEMORY_DB_BACKEND: {kind!r} (expected 'sqlite' or 'cf-d1')"
    )


__all__ = ["MemoryDBCfBackend", "open_memory_db"]
