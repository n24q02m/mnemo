"""Mnemo MCP Server - Persistent AI memory with embedded sync.

MCP Interface:
- memory tool: add/search/list/update/delete/export/import/stats
- config tool: status/sync/set/warmup/setup_sync
- help tool: full documentation on demand
- Resources: mnemo://stats
- Prompts: save_summary, recall_context
"""

import asyncio
import difflib
import json
import os
import socket
import sys
import typing
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version as _pkgver

from loguru import logger
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from mnemo_mcp.config import settings
from mnemo_mcp.db import MemoryDB
from mnemo_mcp.runtime import (
    DEFAULT_EMBEDDING_DIMS,
    build_authenticator,
    cell_configured,
    current_sub,
    db_path_for_namespace,
    hull_settings,
    model_cell,
)

# Resolved via importlib.metadata (not ``from mnemo_mcp import __version__``)
# to avoid a circular import: ``mnemo_mcp/__init__`` imports ``server.main``.
__version__ = _pkgver("mnemo-mcp")

# Storage width for sqlite-vec. All embeddings are fitted to this size so
# switching models never breaks the vector table; the default matches the
# native width of the default [models.embed] cell (voyage-4-lite). Override
# via EMBEDDING_DIMS when the host configures a different-width model.
_DEFAULT_EMBEDDING_DIMS = DEFAULT_EMBEDDING_DIMS

# Per-call wall-clock budget for one embed request (see _embed).
EMBED_CALL_DEADLINE_S = 45


def _default_embedding_dims() -> int:
    """Return the storage width for fresh stores (EMBEDDING_DIMS overrides)."""
    return settings.resolve_embedding_dims() or _DEFAULT_EMBEDDING_DIMS


# --- Lifespan ---


def _supported_model_ids(model_cls) -> set[str]:
    """Read model ids from a fastretrieval facade's public registry."""
    return {
        item["model"] if isinstance(item, dict) else item
        for item in model_cls.list_supported_models()
    }


def _register_embed_spec(**kwargs) -> None:
    """Register a dense-text BYO model through fastretrieval's public API."""
    from fastretrieval import CustomModelSpec

    CustomModelSpec(**kwargs).register()


def _maybe_register_custom_embed(model_id: str) -> None:
    """Register an explicit local embedding model when it is not in the registry."""
    from fastretrieval import TextEmbedding

    supported_ids = {item.casefold() for item in _supported_model_ids(TextEmbedding)}
    if model_id.casefold() in supported_ids:
        return

    dim = settings.local_embedding_dim or settings.resolve_embedding_dims()
    if dim <= 0:
        dim = _DEFAULT_EMBEDDING_DIMS

    try:
        _register_embed_spec(
            model_id=model_id,
            hf=model_id,
            model_file=settings.local_embedding_model_file,
            dim=dim,
            pooling=settings.local_embedding_pooling,
            normalization=settings.local_embedding_normalize,
        )
        logger.info(f"Registered custom local embedding model: {model_id}")
    except ValueError as e:
        # Already registered (embedding backend re-init) or invalid spec --
        # non-fatal; the existing registration is reused.
        logger.debug(f"Custom embedding registration skipped: {e}")


def _register_reranker_spec(**kwargs) -> None:
    """Register a cross-encoder BYO model through fastretrieval."""
    from fastretrieval import CustomRerankerSpec

    CustomRerankerSpec(**kwargs).register()


def _maybe_register_custom_rerank(model_id: str) -> None:
    """Register an explicit local reranker when it is not in the registry."""
    from fastretrieval import TextCrossEncoder

    if model_id.casefold() in {
        item.casefold() for item in _supported_model_ids(TextCrossEncoder)
    }:
        return

    try:
        _register_reranker_spec(
            model_id=model_id,
            hf=model_id,
            model_file=settings.local_rerank_model_file,
        )
        logger.info(f"Registered custom local reranker: {model_id}")
    except ValueError as e:
        # Already registered (reranker backend re-init) or invalid spec --
        # non-fatal; the existing registration is reused.
        logger.debug(f"Custom reranker registration skipped: {e}")


async def _init_embedding_backend(ctx: dict) -> None:
    """Initialize the embedding backend from the host's provider config.

    Cloud when the ``[models.embed]`` cell has a key (no silent local
    fallback -- a broken cell must surface, not quietly switch models);
    otherwise the local ONNX leg. Neither: FTS5-only mode. Runs as a
    background task so the server accepts connections immediately.
    """
    from mnemo_mcp.embedder import init_backend

    embedding_dims = ctx["embedding_dims"]

    if cell_configured("embed"):
        try:
            backend = init_backend("cloud")
            native_dims = await backend.check_available()
            if native_dims > 0:
                if embedding_dims == 0:
                    embedding_dims = _default_embedding_dims()
                model = model_cell("embed").model
                logger.info(
                    f"Embedding: {model} "
                    f"(native={native_dims}, stored={embedding_dims})"
                )
                ctx["embedding_model"] = model
                ctx["embedding_dims"] = embedding_dims
                return
            logger.warning("Embedding cell model not available")
        except Exception as e:
            logger.warning(f"Embedding cell probe failed: {e}")
        logger.error(
            "Cloud embedding configured but unavailable -- staying FTS5-only. "
            "Fix the [models.embed] cell or unset its key to use local ONNX."
        )
        return

    if settings.disable_local_embed:
        logger.info(
            "Embedding: unavailable (DISABLE_LOCAL_EMBED set + no embed cell "
            "configured, FTS5 mode)"
        )
        return

    local_model = settings.resolve_local_embedding_model()
    try:
        await asyncio.to_thread(_maybe_register_custom_embed, local_model)
        backend = await asyncio.to_thread(init_backend, "local", local_model)
        native_dims = await asyncio.to_thread(backend.check_available)
        if native_dims > 0:
            if embedding_dims == 0:
                embedding_dims = _default_embedding_dims()
            logger.info(
                f"Embedding: local {local_model} "
                f"(native={native_dims}, stored={embedding_dims})"
            )
            ctx["embedding_model"] = local_model
            ctx["embedding_dims"] = embedding_dims
        else:
            logger.error("Local embedding model not available")
    except Exception as e:
        logger.error(f"Local embedding init failed: {e}")


async def _init_reranker_backend() -> None:
    """Initialize the reranker: rerank cell when configured, else local ONNX."""
    from mnemo_mcp.reranker import clear_reranker, init_reranker

    clear_reranker()

    if not settings.rerank_enabled:
        logger.debug("Reranking disabled")
        return

    if cell_configured("rerank"):
        try:
            backend = await asyncio.to_thread(init_reranker, "cloud")
            available = await asyncio.to_thread(backend.check_available)
            if available:
                logger.info(f"Reranker: {model_cell('rerank').model}")
                return
            clear_reranker()
        except Exception as e:
            logger.warning(f"Rerank cell probe failed: {e}")
            clear_reranker()
        logger.warning(
            "Rerank cell configured but unavailable -- falling back to local ONNX"
        )

    if settings.disable_local_rerank:
        logger.info(
            "Reranker: unavailable (DISABLE_LOCAL_RERANK set + no usable rerank cell)"
        )
        return

    local_model = settings.resolve_local_rerank_model()
    try:
        await asyncio.to_thread(_maybe_register_custom_rerank, local_model)
        backend = await asyncio.to_thread(init_reranker, "local", local_model)
        available = await asyncio.to_thread(backend.check_available)
        if available:
            logger.info(f"Reranker: local {local_model}")
        else:
            logger.error("Local reranker not available")
            clear_reranker()
    except Exception as e:
        logger.error(f"Local reranker init failed: {e}")
        clear_reranker()


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Initialize DB and embedding/rerank backends on startup.

    Embedding backend init runs as a background task so the server accepts
    connections immediately. Tools gracefully degrade to FTS5-only search
    until the embedding model is ready. The host-root store
    (``~/.mnemo/memories.db``) serves the shared default namespace; mode-3
    namespaces resolve their own per-sub store lazily in :func:`_get_ctx`.
    """
    # 1. Resolve initial embedding dims (may be refined by background task).
    # The identity stamped in store_meta guards against silent vector-space
    # corruption when the model changes.
    embedding_dims = settings.resolve_embedding_dims()
    if embedding_dims == 0:
        embedding_dims = _default_embedding_dims()

    if cell_configured("embed"):
        embedding_model_identity = model_cell("embed").model
    else:
        embedding_model_identity = settings.resolve_local_embedding_model()

    db_path = db_path_for_namespace("default")
    db = MemoryDB(
        db_path,
        embedding_dims=embedding_dims,
        recency_half_life_days=settings.recency_half_life_days,
        embedding_model=embedding_model_identity,
        reindex_on_model_change=settings.reindex_on_model_change,
    )
    stats = db.stats()
    logger.info(
        f"Database: {stats['db_path']} ({stats['total_memories']} memories, "
        f"vec={'on' if db.vec_enabled else 'off'})"
    )

    # Shared context -- embedding_model starts as None (not ready yet).
    # Background task updates it in-place once the backend is validated.
    ctx = {
        "db": db,
        "embedding_model": None,
        "embedding_dims": embedding_dims,
    }

    # 2. Initialize embedding backend in background (non-blocking).
    # This avoids blocking the server start on model download (~570 MB)
    # or cloud API validation. Tools degrade to FTS5-only until ready.
    embedding_task = asyncio.create_task(_init_embedding_backend(ctx))

    # 3. Initialize reranker backend in background (non-blocking).
    reranker_task = asyncio.create_task(_init_reranker_backend())

    try:
        yield ctx
    finally:
        # Cancel background init tasks if still running
        for task in (embedding_task, reranker_task):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        db.close()
        logger.info("Mnemo MCP Server stopped")


# --- Server ---

mcp = FastMCP(
    "Mnemo",
    instructions="Persistent AI memory. Proactively save preferences, decisions, facts. Search before recommending.",
    lifespan=lifespan,
)
# FastMCP (mcp.server.fastmcp) has no ``version=`` kwarg; set it on the
# lowlevel server so initialize's serverInfo.version reports the package
# version instead of the MCP SDK version.
mcp._mcp_server.version = __version__


# --- Helper ---


_sub_db_cache: dict[str, MemoryDB] = {}


def _get_ctx(ctx: Context | None) -> tuple[MemoryDB, str | None, int]:
    """Resolve the caller's store, model, and dimensions (per-namespace, Q2).

    The lifespan opens the host-root store for the shared default namespace.
    In multi mode every other namespace gets its own isolated
    ``~/.mnemo/subs/<namespace>/memories.db`` (cached per process), so two
    users on one process can never read each other's data.
    """
    lc = ctx.request_context.lifespan_context
    db: MemoryDB = lc["db"]
    namespace = current_sub()
    if namespace != "default":
        sub_db = _sub_db_cache.get(namespace)
        if sub_db is None:
            embedding_dims = lc["embedding_dims"]
            if cell_configured("embed"):
                embedding_model = model_cell("embed").model
            else:
                embedding_model = settings.resolve_local_embedding_model()
            sub_db = MemoryDB(
                db_path_for_namespace(namespace),
                embedding_dims=embedding_dims,
                recency_half_life_days=settings.recency_half_life_days,
                embedding_model=embedding_model,
                reindex_on_model_change=settings.reindex_on_model_change,
            )
            _sub_db_cache[namespace] = sub_db
        db = sub_db
    return db, lc["embedding_model"], lc["embedding_dims"]


def _json(obj: object) -> str:
    """Serialize to dense JSON."""
    # Bolt Performance Optimization:
    # Removing indent=2 drastically reduces payload size for large lists
    # of memories, reducing serialization time and network/token overhead.
    return json.dumps(obj, separators=(",", ":"))


# W6.4: `memory` deprecation -- map each composite-tool action to its
# granular single-purpose tool replacement, where one exists. Actions with
# no entry (capture/archive_now/as_of/compress/entity_search/entity_graph/
# history) are Phase 3 / typed-capture features not yet split out; callers
# keep using the composite tool for those until a granular equivalent ships.
_GRANULAR_TOOL_FOR_ACTION: dict[str, str] = {
    "add": "add_memory",
    "search": "search_memory",
    "list": "list_memories",
    "update": "update_memory",
    "delete": "delete_memory",
    "export": "export_memories",
    "import": "import_memories",
    "stats": "memory_stats",
    "restore": "restore_memory",
    "archived": "archived_memories",
    "consolidate": "consolidate_memories",
}


def _deprecation_notice(action: str | None) -> dict[str, str | None]:
    """Build the `_deprecation` field attached to every `memory()` response."""
    granular_tool = _GRANULAR_TOOL_FOR_ACTION.get(action or "")
    if granular_tool:
        message = (
            "The 'memory' composite tool is deprecated and will be removed "
            f"in a future release. Use '{granular_tool}' instead of "
            f"action={action!r}."
        )
    else:
        message = (
            "The 'memory' composite tool is deprecated and will be removed "
            f"in a future release. No granular tool exists yet for "
            f"action={action!r}."
        )
    return {"message": message, "use_instead": granular_tool}


def _format_memory(mem: dict) -> dict:
    """Format a raw memory dict for tool output.

    - Parse ``tags`` from JSON string to list
    - Round ``score`` to 3 decimal places
    """
    tags_val = mem.get("tags")
    if isinstance(tags_val, str):
        # Bolt Performance Optimization:
        # Prevent expensive json.loads calls for the default empty list.
        # This occurs frequently when returning search and list results.
        if tags_val == "[]":
            mem["tags"] = []
        else:
            try:
                mem["tags"] = json.loads(tags_val)
            except (json.JSONDecodeError, TypeError):
                pass
    if "score" in mem:
        mem["score"] = round(mem["score"], 3)
    return mem


async def _embed(
    text: str,
    model: str | None,
    dims: int,
    is_query: bool = False,
    *,
    backend=None,
) -> list[float] | None:
    """Embed text if embedding is available.

    Args:
        text: Text to embed.
        model: Embedding model name.
        dims: Target dimensions (MRL truncation).
        is_query: If True, request the backend's query role for asymmetric
            retrieval. Document embeddings use the document role.
    """
    if not model:
        return None

    from mnemo_mcp.embedder import EmbeddingRole, get_backend

    backend = backend or get_backend()
    if backend is None:
        # Should not happen if model is set (implies init succeeded), but safe guard.
        logger.warning(f"Embedding backend not initialized despite model={model}")
        return None

    role: EmbeddingRole = "query" if is_query else "document"
    try:
        # Hard per-call deadline: the backend's internal retry budget
        # (MAX_RETRIES x client timeout) can otherwise stall a tool call for
        # minutes on a flaky network. Bounded here, degraded to FTS5 below.
        async with asyncio.timeout(EMBED_CALL_DEADLINE_S):
            return await backend.embed_single(text, dims, role=role)
    except TimeoutError:
        logger.warning(
            f"Embedding exceeded {EMBED_CALL_DEADLINE_S}s ({model}); "
            "degrading to FTS5 for this call"
        )
        return None
    except Exception as e:
        from mnemo_mcp.embedder import _is_retryable

        if _is_retryable(e):
            # Transient (rate-limit / network; the backend already exhausted
            # its retries). Degrade THIS call to FTS5 -- the next may succeed.
            logger.warning(
                f"Embedding transiently unavailable ({model}); "
                f"degrading to FTS5 for this call: {e}"
            )
            return None
        # Permanent config/capability error (bad key, unknown model, dims the
        # backend could not work around): every embed will fail. Surface it
        # loudly instead of silently returning None and hiding a broken
        # semantic search behind a FTS5 fallback.
        logger.error(
            f"Embedding permanently failing ({model}): {e}. "
            "Check the [models.embed] cell (base_url / model / HULL_EMBED_API_KEY)."
        )
        raise


async def _handle_add(
    ctx: Context | None,
    content: str | None,
    category: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, typing.Any]:
    db, embedding_model, embedding_dims = _get_ctx(ctx)
    from mnemo_mcp.embedder import get_backend

    embedding_backend = get_backend()

    if not content:
        return {
            "error": "content is required for add",
            "example": "action='add', content='User prefers Python for data tasks', category='preference', tags=['python']",
            "suggestion": "Provide the 'content' parameter to save a new memory.",
        }

    # Dedup check before insert
    dedup_warning = None
    try:
        dedup_result = await asyncio.to_thread(
            db.check_duplicate, content, settings.dedup_threshold
        )
        if dedup_result and dedup_result.get("duplicate"):
            dedup_warning = dedup_result
        elif dedup_result and dedup_result.get("similar"):
            dedup_warning = dedup_result
    except Exception as e:
        logger.warning(f"Dedup check failed (non-blocking): {e}")

    embedding = await _embed(
        content,
        embedding_model,
        embedding_dims,
        backend=embedding_backend,
    )
    try:
        memory_id = await asyncio.to_thread(
            db.add,
            content=content,
            category=category or "general",
            tags=tags,
            embedding=embedding,
        )
    except ValueError as e:
        msg = str(e)
        if "exceeds limit" not in msg:
            logger.exception("Validation failed in _handle_add")
            msg = "validation failed"
        return {
            "error": msg,
            "suggestion": "Ensure input parameters meet validation rules.",
        }
    except Exception:
        logger.exception("Unexpected error in _handle_add")
        return {
            "error": "Internal error while adding memory",
            "suggestion": "Check server logs for tracebacks or verify database permissions.",
        }

    result: dict = {
        "id": memory_id,
        "status": "saved",
        "category": category or "general",
        "semantic": embedding is not None,
    }
    if dedup_warning:
        result["dedup_warning"] = dedup_warning

    # Background: score importance + extract entities (non-blocking)
    asyncio.create_task(_enrich_memory(db, memory_id, content))

    return result


async def _enrich_memory(db: MemoryDB, memory_id: str, content: str) -> None:
    """Background task: score importance and extract entities.

    Phase 3 KG_AUTO_ENABLED path: when ``settings.kg_auto_enabled`` is
    True, route extraction through the new
    :mod:`mnemo_mcp.temporal.extract` + :mod:`mnemo_mcp.temporal.store`
    pipeline (records ``memory_edges.memory_id`` + ``valid_from`` for
    bitemporal traceability). Otherwise keeps the Phase 1 legacy path
    (calls graph.extract_entities + graph.upsert/link helpers directly)
    so callers pre-Phase-3 see no behavioural change.
    """
    from mnemo_mcp.graph import (
        create_relations,
        extract_entities,
        link_memory_entities,
        score_importance,
        upsert_entities,
    )

    try:
        importance = await score_importance(content)
        if importance != 0.5:
            await asyncio.to_thread(db.update_importance, memory_id, importance)
    except Exception as e:
        logger.debug(f"Importance scoring background error: {e}")

    # Phase 3 KG_AUTO_ENABLED path: temporal.extract + temporal.store with
    # bitemporal bookkeeping. Falls back to legacy on import failure so a
    # broken Phase 3 install never blocks captures.
    if settings.kg_auto_enabled:
        try:
            from mnemo_mcp.temporal.extract import extract_entities as t_extract
            from mnemo_mcp.temporal.store import store_kg_with_memory_id

            graph_data = await t_extract(content)
            if graph_data and graph_data.get("entities"):
                await asyncio.to_thread(
                    store_kg_with_memory_id, db._conn, memory_id, graph_data
                )
            return
        except Exception as e:
            logger.debug(f"Phase 3 KG extraction failed, falling back to legacy: {e}")

    # Legacy Phase 1 path (default).
    try:
        graph_data = await extract_entities(content)
        if graph_data and graph_data.get("entities"):
            conn = db._conn
            entity_ids = upsert_entities(conn, graph_data["entities"])
            name_to_id = {}
            for ent, eid in zip(graph_data["entities"], entity_ids, strict=False):
                ent_name = ent.get("name", "").strip()
                if ent_name:
                    name_to_id[ent_name] = eid
            if graph_data.get("relations"):
                create_relations(conn, graph_data["relations"], name_to_id)
            link_memory_entities(conn, memory_id, entity_ids)
            conn.commit()
    except Exception as e:
        logger.debug(f"Entity extraction background error: {e}")


async def _handle_search(
    ctx: Context | None,
    query: str | None,
    category: str | None = None,
    tags: list[str] | None = None,
    limit: int = 5,
    *,
    context_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    min_importance: float = 0.0,
    include_archived: bool = False,
) -> dict[str, typing.Any]:
    db, embedding_model, embedding_dims = _get_ctx(ctx)

    if not query:
        return {
            "error": "query is required for search",
            "example": "action='search', query='user preferences for UI theme'",
            "suggestion": "Provide the 'query' parameter to perform a search.",
        }

    if isinstance(limit, int):
        limit = max(1, min(limit, 100))

    from mnemo_mcp.embedder import get_backend

    embedding_backend = get_backend()
    embedding = await _embed(
        query,
        embedding_model,
        embedding_dims,
        is_query=True,
        backend=embedding_backend,
    )

    # Spec section 4.2: rerank operates on a wider candidate pool
    # (top-50 -> top-N) so we ask db.search for ``max(50, limit*5)`` rows
    # when a reranker is active and otherwise stay at the LLM-requested limit.
    from mnemo_mcp.reranker import get_reranker

    reranker = get_reranker()
    from mnemo_mcp.reranker import describe_reranker, rerank_with_identity

    reranker_backend, reranker_model = describe_reranker(reranker)
    reranker_fallback = "not_configured" if reranker is None else "not_needed"
    rerank_pool = max(50, limit * 5) if reranker else None

    results = await asyncio.to_thread(
        db.search,
        query=query,
        embedding=embedding,
        category=category,
        tags=tags,
        limit=limit,
        context_type=context_type,
        since=since,
        until=until,
        min_importance=min_importance,
        include_archived=include_archived,
        candidate_pool=rerank_pool,
    )

    reranked = False
    if reranker and len(results) > 1:
        reranker_fallback = "none"
        documents = [r["content"] for r in results]
        try:
            outcome = await asyncio.to_thread(
                rerank_with_identity, reranker, query, documents, limit
            )
            ranked = outcome.results
            if outcome.backend_name is not None:
                reranker_backend = outcome.backend_name
            if outcome.model_name is not None:
                reranker_model = outcome.model_name
            if ranked:
                reranked_results = []
                for idx, score in ranked:
                    r = results[idx].copy()
                    r["rerank_score"] = round(score, 4)
                    reranked_results.append(r)
                results = reranked_results
                reranked = True
            else:
                reranker_fallback = "original_order_after_empty_result"
                # No reranker output -> fall back to top-``limit`` of the
                # hybrid-scored pool so the response still respects ``limit``.
                results = results[:limit]
        except Exception as e:
            reranker_fallback = "original_order_after_error"
            logger.debug(f"Reranking failed, using original order: {e}")
            results = results[:limit]
    else:
        results = results[:limit]

    # Graph boost: find related memories via entity graph
    if results:
        try:
            from mnemo_mcp.graph import find_related_memory_ids

            top_id = results[0]["id"]
            related_ids = await asyncio.to_thread(
                find_related_memory_ids, db._conn, top_id
            )
            if related_ids:
                related_set = set(related_ids)
                for r in results:
                    if r["id"] in related_set:
                        r["graph_related"] = True
        except Exception as e:
            logger.warning(f"Graph boost failed (non-blocking): {e}")

    response: dict = {
        "count": len(results),
        "results": [_format_memory(r) for r in results],
        "semantic": embedding is not None,
        "reranked": reranked,
        "reranker": {
            "backend": reranker_backend,
            "model": reranker_model,
            "fallback": reranker_fallback,
        },
    }

    if len(results) == 0:
        response["suggestion"] = (
            "No results found. Try broader terms, different keywords, "
            "or use action='list' to browse all memories."
        )

    return response
    return response


async def _handle_list(
    ctx: Context | None,
    category: str | None = None,
    limit: int = 5,
) -> dict[str, typing.Any]:
    db, _, _ = _get_ctx(ctx)

    if isinstance(limit, int):
        limit = max(1, min(limit, 100))

    results = await asyncio.to_thread(
        db.list_memories,
        category=category,
        limit=limit,
    )
    response: dict = {
        "count": len(results),
        "results": [_format_memory(r) for r in results],
    }
    if len(results) == 0:
        if category:
            response["suggestion"] = (
                f"No memories found in category '{category}'. Use action='list' without a category to see all, or action='add' to create some!"
            )
        else:
            response["suggestion"] = (
                "No memories found. Use action='add' to create some!"
            )
    return response


async def _handle_update(
    ctx: Context | None,
    memory_id: str | None,
    content: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    source: str | None = None,
    importance: float | None = None,
) -> dict[str, typing.Any]:

    db, embedding_model, embedding_dims = _get_ctx(ctx)
    from mnemo_mcp.embedder import get_backend

    embedding_backend = get_backend()

    if not memory_id:
        return {
            "error": "memory_id is required for update. Use action='search' or action='list' first to find the memory ID.",
            "example": "action='update', memory_id='abc123', content='updated content'",
            "suggestion": "Provide the 'memory_id' parameter to update a specific memory.",
        }

    embedding = None
    if content:
        embedding = await _embed(
            content,
            embedding_model,
            embedding_dims,
            backend=embedding_backend,
        )

    try:
        new_id = await asyncio.to_thread(
            db.update,
            memory_id=memory_id,
            content=content,
            category=category,
            tags=tags,
            source=source,
            importance=importance,
            embedding=embedding,
        )
    except ValueError as e:
        msg = str(e)
        if "exceeds limit" not in msg:
            logger.exception("Validation failed in _handle_update")
            msg = "validation failed"
        return {
            "error": msg,
            "suggestion": "Check input parameters for invalid types or values.",
        }
    except Exception:
        logger.exception("Unexpected error in _handle_update")
        return {
            "error": "Internal error while updating memory",
            "suggestion": "Check server logs for tracebacks or verify database connection.",
        }
    if new_id:
        # Background: re-extract entities if content changed. Bitemporal
        # supersession (mem_003) means memory_id no longer resolves after
        # this update -- enrichment must target the new row.
        if content:
            asyncio.create_task(_enrich_memory(db, new_id, content))
        return {"status": "updated", "id": new_id}
    return {
        "error": f"Memory {memory_id} not found",
        "suggestion": "Verify the memory_id using action='search' or action='list'.",
    }


async def _handle_delete(
    ctx: Context | None,
    memory_id: str | None,
) -> dict[str, typing.Any]:

    db, _, _ = _get_ctx(ctx)

    if not memory_id:
        return {
            "error": "memory_id is required for delete. Use action='search' or action='list' first to find the memory ID.",
            "example": "action='delete', memory_id='abc123'",
            "suggestion": "Provide the 'memory_id' parameter to delete a specific memory.",
        }

    ok = await asyncio.to_thread(db.delete, memory_id)
    if ok:
        return {"status": "deleted", "id": memory_id}
    return {
        "error": f"Memory {memory_id} not found",
        "suggestion": "Verify the memory_id using action='search' or action='list'.",
    }


async def _handle_export(ctx: Context | None) -> dict[str, typing.Any]:
    db, _, _ = _get_ctx(ctx)
    jsonl, count = await asyncio.to_thread(db.export_jsonl)
    return {
        "format": "jsonl",
        "data": jsonl,
        "count": count,
    }


async def _handle_import(
    ctx: Context | None,
    data: str | list | None,
    mode: str = "merge",
) -> dict[str, typing.Any]:
    db, _, _ = _get_ctx(ctx)

    if not data:
        return {
            "error": "data (JSONL string or list of objects) is required for import",
            "suggestion": "Provide the 'data' parameter containing the JSONL data or a list of JSON objects to import.",
        }

    _VALID_MODES = ["merge", "replace"]
    if mode is not None and mode not in _VALID_MODES:
        closest = difflib.get_close_matches(str(mode), _VALID_MODES, n=1)
        resp = {
            "error": f"Invalid mode '{mode}'.",
            "valid_modes": _VALID_MODES,
        }
        if closest:
            resp["suggestion"] = f"Did you mean '{closest[0]}'?"
        else:
            resp["suggestion"] = f"Pick a mode from {_VALID_MODES}."
        return resp

    # Bolt Performance Optimization: Pass raw list/dict directly to database layer.
    # Avoids unnecessary JSON serialization and deserialization cycles for parsed inputs.
    if data is None:
        raise ValueError("data is required")
    result = await asyncio.to_thread(db.import_jsonl, data, mode=mode)
    return {
        "status": "imported",
        **result,
    }


async def _handle_stats(ctx: Context | None) -> dict[str, typing.Any]:
    db, embedding_model, embedding_dims = _get_ctx(ctx)
    s = await asyncio.to_thread(db.stats)
    s["embedding_model"] = embedding_model
    s["embedding_dims"] = embedding_dims
    return s


async def _handle_restore(
    ctx: Context | None,
    memory_id: str | None,
) -> dict[str, typing.Any]:

    db, _, _ = _get_ctx(ctx)

    if not memory_id:
        return {
            "error": "memory_id is required for restore. Use action='archived' first to find archived memory IDs.",
            "example": "action='restore', memory_id='abc123'",
            "suggestion": "Provide the 'memory_id' parameter to restore a specific memory.",
        }

    ok = await asyncio.to_thread(db.restore_memory, memory_id)
    if ok:
        return {"status": "restored", "id": memory_id}
    return {
        "error": f"Archived memory {memory_id} not found",
        "suggestion": "Verify the memory_id using action='archived'.",
    }


async def _handle_archived(
    ctx: Context | None,
    limit: int = 5,
) -> dict[str, typing.Any]:
    db, _, _ = _get_ctx(ctx)

    if isinstance(limit, int):
        limit = max(1, min(limit, 100))

    results = await asyncio.to_thread(db.list_archived, limit)
    response: dict = {
        "count": len(results),
        "results": results,
    }
    if len(results) == 0:
        response["suggestion"] = (
            "No archived memories found. Use action='list' to view active memories."
        )
    return response


_CAPTURE_COUNTER: dict[str, int] = {"calls": 0}


def _archive_trigger_interval() -> int:
    """Read ``ARCHIVE_TRIGGER_EVERY`` env var (default 100) for capture-driven
    background archive runs.
    """
    raw = os.environ.get("ARCHIVE_TRIGGER_EVERY", "100")
    try:
        value = int(raw)
    except ValueError:
        return 100
    return max(1, value)


async def _handle_capture(
    ctx: Context | None,
    text: str | None,
    context_type: str = "conversation",
    category: str | None = None,
    tags: list[str] | None = None,
    source: str | None = None,
    importance: float | None = None,
    auto: bool = False,
) -> dict[str, typing.Any]:
    """Handle ``memory(action="capture")`` -- typed capture with dedup.

    Wraps :func:`mnemo_mcp.capture.capture` with the shared lifespan ctx so
    the capture pipeline can reuse the configured embedding backend without
    reaching into module-level globals.
    """
    db, embedding_model, embedding_dims = _get_ctx(ctx)
    from mnemo_mcp.embedder import get_backend

    embedding_backend = get_backend()

    if not text:
        return {
            "error": "text is required for capture",
            "example": (
                "action='capture', text='User prefers dark mode', "
                "context_type='preference'"
            ),
            "suggestion": ("Provide the 'text' parameter to capture a typed memory."),
        }

    embedding = await _embed(
        text,
        embedding_model,
        embedding_dims,
        backend=embedding_backend,
    )

    from mnemo_mcp.capture import CONTEXT_TYPES
    from mnemo_mcp.capture import capture as _capture

    try:
        result = await _capture(
            db,
            text=text,
            context_type=context_type,
            category=category or "general",
            tags=tags,
            source=source,
            embedding=embedding,
            importance=importance,
            auto=auto,
        )
    except ValueError as e:
        msg = str(e)
        if "context_type" in msg:
            closest = (
                difflib.get_close_matches(str(context_type), list(CONTEXT_TYPES), n=1)
                if context_type is not None
                else []
            )
            resp = {
                "error": msg,
                "valid_context_types": sorted(CONTEXT_TYPES),
            }
            if closest:
                resp["suggestion"] = f"Did you mean '{closest[0]}'?"
            else:
                resp["suggestion"] = (
                    f"Pick a context_type from {sorted(CONTEXT_TYPES)}."
                )
            return resp
        if "exceeds limit" not in msg:
            logger.exception("Validation failed in _handle_capture")
            msg = "validation failed"
        return {"error": msg, "suggestion": "Check payload length and constraints."}
    except Exception:
        logger.exception("Unexpected error in _handle_capture")
        return {
            "error": "Internal error while capturing memory",
            "suggestion": "Check server logs for tracebacks.",
        }

    # Background enrichment only when we actually inserted a new row.
    if not result.get("deduplicated"):
        asyncio.create_task(_enrich_memory(db, result["memory_id"], text))

    # Archive policy auto-trigger: every Nth capture (default 100), run a
    # background archive_by_score sweep so old low-importance rows soft-archive
    # without requiring a manual ``archive_now`` call.
    if settings.archive_enabled:
        _CAPTURE_COUNTER["calls"] += 1
        interval = _archive_trigger_interval()
        if _CAPTURE_COUNTER["calls"] % interval == 0:
            asyncio.create_task(
                asyncio.to_thread(
                    db.archive_by_score,
                    archive_after_days=int(settings.archive_after_days),
                )
            )

    return {
        "status": "deduplicated" if result.get("deduplicated") else "captured",
        "id": result["memory_id"],
        "context_type": result.get("context_type", context_type),
        "deduplicated": bool(result.get("deduplicated")),
        "auto": bool(result.get("auto")),
        "semantic": embedding is not None,
        **(
            {
                "similarity": result["similarity"],
                "existing_content": result.get("existing_content"),
            }
            if result.get("deduplicated")
            else {}
        ),
    }


async def _handle_archive_now(
    ctx: Context | None,
) -> dict[str, typing.Any]:
    """Trigger ``archive_by_score`` on demand using current settings."""
    db, _, _ = _get_ctx(ctx)
    archive_after_days = int(settings.archive_after_days)
    count = await asyncio.to_thread(
        db.archive_by_score, archive_after_days=archive_after_days
    )
    return {
        "status": "archived",
        "count": count,
        "archive_after_days": archive_after_days,
        "scoring": "recency_factor * (1 - importance) > 1.0",
    }


# ---------------------------------------------------------------------------
# Phase 3 KG actions: entity_search / entity_graph / history / as_of.
# ---------------------------------------------------------------------------


async def _handle_entity_search(
    ctx: Context | None,
    name: str | None,
    entity_type: str | None,
    limit: int = 20,
) -> dict[str, typing.Any]:
    """``memory(action="entity_search")`` -- find memories by entity name."""
    db, _, _ = _get_ctx(ctx)
    if not name:
        return {
            "error": "name is required for entity_search",
            "example": "action='entity_search', name='FastAPI'",
            "suggestion": (
                "Pass 'name' (entity name, case-insensitive) and "
                "optionally 'entity_type' (person/project/tool/concept/"
                "org/location/event)."
            ),
        }

    _VALID_ENTITY_TYPES = [
        "person",
        "project",
        "tool",
        "concept",
        "org",
        "location",
        "event",
    ]
    if entity_type is not None and entity_type not in _VALID_ENTITY_TYPES:
        closest = difflib.get_close_matches(str(entity_type), _VALID_ENTITY_TYPES, n=1)
        resp = {
            "error": f"Invalid entity_type '{entity_type}'.",
            "valid_entity_types": _VALID_ENTITY_TYPES,
        }
        if closest:
            resp["suggestion"] = f"Did you mean '{closest[0]}'?"
        else:
            resp["suggestion"] = f"Pick an entity_type from {_VALID_ENTITY_TYPES}."
        return resp

    from mnemo_mcp.temporal.queries import entity_search

    rows = await asyncio.to_thread(
        entity_search, db, name=name, entity_type=entity_type, limit=limit
    )
    return {
        "count": len(rows),
        "results": [_format_memory(r) for r in rows],
        "matched_name": name,
    }


async def _handle_entity_graph(
    ctx: Context | None,
    entity_id: str | None,
    name: str | None,
    depth: int = 2,
    limit: int = 50,
) -> dict[str, typing.Any]:
    """``memory(action="entity_graph")`` -- KG neighbourhood subgraph."""
    db, _, _ = _get_ctx(ctx)
    if not entity_id and not name:
        return {
            "error": "entity_id or name required for entity_graph",
            "example": "action='entity_graph', name='Python', depth=2",
            "suggestion": "Provide either 'entity_id' or 'name' to specify the root of the graph.",
        }
    from mnemo_mcp.temporal.queries import entity_graph

    result = await asyncio.to_thread(
        entity_graph, db, entity_id=entity_id, name=name, depth=depth, limit=limit
    )
    return result


async def _handle_as_of(
    ctx: Context | None,
    as_of: str | None,
    limit: int = 5,
) -> dict[str, typing.Any]:
    """``memory(action="as_of")`` -- point-in-time view of memories valid at
    ``as_of`` (ISO timestamp). Delegates to ``temporal.queries.memories_as_of``.
    """
    db, _, _ = _get_ctx(ctx)

    if not as_of:
        return {
            "error": "as_of is required for action='as_of'",
            "example": "action='as_of', as_of='2026-01-15T00:00:00'",
            "suggestion": "Provide the 'as_of' parameter as an ISO timestamp.",
        }

    if isinstance(limit, int):
        limit = max(1, min(limit, 100))

    from mnemo_mcp.temporal.queries import memories_as_of

    rows = await asyncio.to_thread(memories_as_of, db, as_of, limit)
    return {
        "memories": [_format_memory(m) for m in rows],
        "count": len(rows),
        "as_of": as_of,
    }


async def _handle_history(
    ctx: Context | None,
    entity_id: str | None,
) -> dict[str, typing.Any]:
    """``memory(action="history")`` -- timeline of memories linked to an entity."""
    db, _, _ = _get_ctx(ctx)
    if not entity_id:
        return {
            "error": "entity_id required for history",
            "example": "action='history', entity_id='<uuid>'",
            "suggestion": (
                "Get an entity_id from entity_graph or entity_search results."
            ),
        }
    from mnemo_mcp.temporal.queries import history_for_entity

    timeline = await asyncio.to_thread(history_for_entity, db, entity_id)
    return {
        "entity_id": entity_id,
        "count": len(timeline),
        "timeline": [_format_memory(m) for m in timeline],
    }


async def _handle_consolidate(
    ctx: Context | None,
    category: str | None = None,
) -> dict[str, typing.Any]:
    """Consolidate similar memories in a category using LLM summarization."""
    db, _, _ = _get_ctx(ctx)
    from mnemo_mcp.graph import _cell_ready

    if not _cell_ready("chat"):
        return {
            "error": "Consolidation requires the [models.chat] provider cell",
            "suggestion": "Configure the cell (base_url/api_key/model) in ~/.mnemo/config.toml.",
        }

    if not category:
        return {
            "error": "category is required for consolidate",
            "suggestion": "Provide the 'category' parameter to specify which memories to consolidate.",
        }

    memories = await asyncio.to_thread(db.list_memories, category=category, limit=50)
    if len(memories) < 2:
        return {
            "error": f"Need at least 2 memories in '{category}' to consolidate",
            "suggestion": f"Use action='list' with category='{category}' to see existing memories.",
        }

    try:
        from mnemo_mcp.graph import _cell_completion

        content_list = "\n---\n".join(
            f"[{m['id'][:8]}] {m['content']}" for m in memories[:20]
        )

        summary = await _cell_completion(
            "chat",
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Summarize these related memories into a single consolidated memory. "
                        "Preserve key facts and remove redundancy. Return ONLY the consolidated text.\n\n"
                        f"{content_list}"
                    ),
                }
            ],
            temperature=0,
            max_tokens=1000,
        )

        return {
            "status": "consolidated",
            "category": category,
            "original_count": len(memories),
            "summary": summary.strip(),
            "note": "Review the summary and use add/delete to apply changes.",
        }
    except Exception:
        logger.exception("Consolidation failed")
        return {
            "error": "Consolidation failed: internal error",
            "suggestion": "Check LLM provider configuration and network connectivity.",
        }


# --- Tools ---


@mcp.tool(
    description=(
        "Store NEW information. Use for preferences, decisions, facts.\n"
        "\n"
        "ACTION GUIDE — when to use:\n"
        "- Use when saving new information for the first time.\n"
        "  Example: content='User prefers dark mode', category='preference', tags=['ui']"
    ),
    annotations=ToolAnnotations(
        title="Add Memory",
        readOnlyHint=False,
        destructiveHint=False,
    ),
)
async def add_memory(
    content: str,
    category: str | None = None,
    tags: list[str] | None = None,
    ctx: Context | None = None,
) -> dict[str, typing.Any]:
    return await _handle_add(ctx, content, category, tags)


@mcp.tool(
    description=(
        "Find existing memories by natural language query. Always search before adding.\n"
        "\n"
        "ACTION GUIDE — when to use:\n"
        "- Use BEFORE adding new information to avoid duplicates.\n"
        "  Example: query='dark mode preference'"
    ),
    annotations=ToolAnnotations(
        title="Search Memory",
        readOnlyHint=True,
        destructiveHint=False,
    ),
)
async def search_memory(
    query: str,
    category: str | None = None,
    tags: list[str] | None = None,
    limit: int = 5,
    ctx: Context | None = None,
) -> dict[str, typing.Any]:
    return await _handle_search(ctx, query, category, tags, limit)


@mcp.tool(
    description=(
        "Browse all memories, optionally filtered by category.\n"
        "\n"
        "ACTION GUIDE — when to use:\n"
        "- Use when you want to view a broad set of memories, or see what's in a specific category.\n"
        "  Example: category='preference', limit=10"
    ),
    annotations=ToolAnnotations(
        title="List Memories",
        readOnlyHint=True,
        destructiveHint=False,
    ),
)
async def list_memories(
    category: str | None = None, limit: int = 5, ctx: Context | None = None
) -> dict[str, typing.Any]:
    return await _handle_list(ctx, category, limit)


@mcp.tool(
    description=(
        "Modify an EXISTING memory by ID. Get memory_id from search results.\n"
        "\n"
        "ACTION GUIDE — when to use:\n"
        "- Use when an existing fact or preference changes.\n"
        "  Example: memory_id='abc123', content='User now prefers light mode'"
    ),
    annotations=ToolAnnotations(
        title="Update Memory",
        readOnlyHint=False,
        destructiveHint=False,
    ),
)
async def update_memory(
    memory_id: str,
    content: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    source: str | None = None,
    importance: float | None = None,
    ctx: Context | None = None,
) -> dict[str, typing.Any]:
    return await _handle_update(
        ctx, memory_id, content, category, tags, source, importance
    )


@mcp.tool(
    description=(
        "Remove a memory by ID.\n"
        "\n"
        "ACTION GUIDE — when to use:\n"
        "- Use when a memory is completely outdated, incorrect, or explicitly requested to be forgotten.\n"
        "  Example: memory_id='abc123'"
    ),
    annotations=ToolAnnotations(
        title="Delete Memory",
        readOnlyHint=False,
        destructiveHint=True,
    ),
)
async def delete_memory(
    memory_id: str, ctx: Context | None = None
) -> dict[str, typing.Any]:
    return await _handle_delete(ctx, memory_id)


@mcp.tool(
    description=(
        "Export all memories as JSONL.\n"
        "\n"
        "ACTION GUIDE — when to use:\n"
        "- Use when the user requests a backup or raw dump of their memory database."
    ),
    annotations=ToolAnnotations(
        title="Export Memories",
        readOnlyHint=False,
        destructiveHint=False,
    ),
)
async def export_memories(ctx: Context | None = None) -> dict[str, typing.Any]:
    return await _handle_export(ctx)


@mcp.tool(
    description=(
        "Import memories from JSONL data or a list of objects.\n"
        "\n"
        "ACTION GUIDE — when to use:\n"
        "- Use when restoring from a backup or migrating data into the memory system.\n"
        "  Example: data='[{\"content\": \"example\"}]', mode='merge'"
    ),
    annotations=ToolAnnotations(
        title="Import Memories",
        readOnlyHint=False,
        destructiveHint=False,
    ),
)
async def import_memories(
    data: str | list, mode: str = "merge", ctx: Context | None = None
) -> dict[str, typing.Any]:
    return await _handle_import(ctx, data, mode)


@mcp.tool(
    description=(
        "Show database statistics (total memories, categories, embedding status).\n"
        "\n"
        "ACTION GUIDE — when to use:\n"
        "- Use when you need to understand the scale or health of the memory database, or check if embeddings are enabled."
    ),
    annotations=ToolAnnotations(
        title="Memory Stats",
        readOnlyHint=True,
        destructiveHint=False,
    ),
)
async def memory_stats(ctx: Context | None = None) -> dict[str, typing.Any]:
    return await _handle_stats(ctx)


@mcp.tool(
    description=(
        "Restore an archived memory by ID.\n"
        "\n"
        "ACTION GUIDE — when to use:\n"
        "- Use to bring a previously archived memory back into the active search pool.\n"
        "  Example: memory_id='abc123'"
    ),
    annotations=ToolAnnotations(
        title="Restore Memory",
        readOnlyHint=False,
        destructiveHint=False,
    ),
)
async def restore_memory(
    memory_id: str, ctx: Context | None = None
) -> dict[str, typing.Any]:
    return await _handle_restore(ctx, memory_id)


@mcp.tool(
    description=(
        "List archived memories.\n"
        "\n"
        "ACTION GUIDE — when to use:\n"
        "- Use to view memories that have been soft-deleted or automatically archived due to low importance/recency."
    ),
    annotations=ToolAnnotations(
        title="Archived Memories",
        readOnlyHint=False,
        destructiveHint=False,
    ),
)
async def archived_memories(
    limit: int = 5, ctx: Context | None = None
) -> dict[str, typing.Any]:
    return await _handle_archived(ctx, limit)


@mcp.tool(
    description=(
        "Summarize similar memories in a category (requires LLM API keys).\n"
        "\n"
        "ACTION GUIDE — when to use:\n"
        "- Use when a category has too many redundant or closely related memories and needs cleanup.\n"
        "  Example: category='preference'"
    ),
    annotations=ToolAnnotations(
        title="Consolidate Memories",
        readOnlyHint=False,
        destructiveHint=False,
    ),
)
async def consolidate_memories(
    category: str, ctx: Context | None = None
) -> dict[str, typing.Any]:
    return await _handle_consolidate(ctx, category)


@mcp.tool(
    description=(
        "[DEPRECATED — use the granular tools (add_memory, search_memory, ...) "
        "instead; this composite tool will be removed in a future release]\n\n"
        "Legacy dispatcher for backward compatibility. Use specialized tools (add_memory, search_memory, etc.) instead.\n\nPersistent memory store. Actions: add|search|list|update|delete|export|import|stats|restore|archived|consolidate.\n"
        "\n"
        "ACTION GUIDE — when to use each:\n"
        "- add: Store NEW information. Requires 'content'. Use when saving preferences, decisions, facts for the first time.\n"
        "  Example: action='add', content='User prefers dark mode', category='preference', tags=['ui']\n"
        "- search: Find existing memories by natural language query. Requires 'query'. Use BEFORE add to avoid duplicates.\n"
        "  Example: action='search', query='dark mode preference'\n"
        "- update: Modify an EXISTING memory by ID. Requires 'memory_id' (from search/list results). Use when a fact changes.\n"
        "  Example: action='update', memory_id='abc123', content='User now prefers light mode'\n"
        "- list: Browse all memories, optionally filtered by category. No query needed.\n"
        "- delete: Remove a memory by ID. Requires 'memory_id'.\n"
        "- stats: Show database statistics (total memories, categories, embedding status).\n"
        "- export: Export all memories to JSONL format.\n"
        "- import: Import memories from JSONL data. Requires 'data'.\n"
        "- archived: List archived memories. Optionally filter by limit.\n"
        "- restore: Restore an archived memory by ID. Requires 'memory_id'.\n"
        "- consolidate: Summarize and consolidate similar memories in a category using LLM. Requires 'category'.\n"
        "\n"
        "WORKFLOW: search -> not found? -> add. Found outdated? -> update (with memory_id from results).\n"
        "PROACTIVE: save user preferences, decisions, corrections, project conventions."
    ),
    annotations=ToolAnnotations(
        title="Memory",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def memory(
    action: str,
    content: str | None = None,
    query: str | None = None,
    memory_id: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    source: str | None = None,
    importance: float | None = None,
    limit: int = 5,
    data: str | list | None = None,
    mode: str = "merge",
    text: str | None = None,
    context_type: str = "conversation",
    auto: bool = False,
    since: str | None = None,
    until: str | None = None,
    min_importance: float = 0.0,
    include_archived: bool = False,
    name: str | None = None,
    entity_id: str | None = None,
    depth: int = 2,
    as_of: str | None = None,
    ctx: Context | None = None,
) -> dict[str, typing.Any]:
    """Execute a memory action.

    Actions:
    - add: Store NEW information (content required, category/tags optional).
      Use for first-time storage of preferences, decisions, facts.
    - search: Find memories by natural language (query required, category/tags/limit optional).
      Always search before adding to avoid duplicates.
    - list: Browse all memories (category/limit optional). No query needed.
    - update: Modify EXISTING memory (memory_id required, content/category/tags/source/importance optional).
      Get memory_id from search or list results first.
    - delete: Remove memory (memory_id required)
    - export: Export all as JSONL
    - import: Import from JSONL (data required, mode: merge|replace)
    - stats: Database statistics
    - restore: Restore archived memory (memory_id required)
    - archived: List archived memories (limit optional)
    - consolidate: LLM summarize similar memories (category required)
    - as_of: Point-in-time view of memories valid at a given ISO timestamp
      (as_of required, limit optional). Only combinable with action='as_of';
      passing as_of with any other action is an error, not a silent no-op.
    """
    # Clamp limit to reasonable bounds to prevent DoS

    if isinstance(limit, int):
        limit = max(1, min(limit, 100))

    if as_of is not None and action != "as_of":
        result: dict[str, typing.Any] = {
            "error": (
                f"as_of is only supported with action='as_of' (got action={action!r}). "
                "Point-in-time filtering for search/list is not implemented; "
                "refusing to silently return current-state results."
            ),
            "suggestion": "Use action='as_of' with the as_of parameter, or drop as_of for current-state results.",
        }
        result["_deprecation"] = _deprecation_notice(action)
        return result

    match action:
        case "add":
            result = await _handle_add(ctx, content, category, tags)
        case "capture":
            result = await _handle_capture(
                ctx,
                text or content,
                context_type=context_type,
                category=category,
                tags=tags,
                source=source,
                importance=importance,
                auto=auto,
            )
        case "search":
            # Phase 1 filter passthrough — context_type is also accepted by
            # the capture branch above; here we treat it as a search filter
            # only when caller did not leave it at the conversation default.
            ctype_filter = context_type if context_type != "conversation" else None
            result = await _handle_search(
                ctx,
                query,
                category,
                tags,
                limit,
                context_type=ctype_filter,
                since=since,
                until=until,
                min_importance=min_importance,
                include_archived=include_archived,
            )
        case "list":
            result = await _handle_list(ctx, category, limit)
        case "as_of":
            result = await _handle_as_of(ctx, as_of, limit)
        case "update":
            result = await _handle_update(
                ctx, memory_id, content, category, tags, source, importance
            )
        case "delete":
            result = await _handle_delete(ctx, memory_id)
        case "export":
            result = await _handle_export(ctx)
        case "import":
            result = await _handle_import(ctx, data, mode)
        case "stats":
            result = await _handle_stats(ctx)
        case "restore":
            result = await _handle_restore(ctx, memory_id)
        case "archived":
            result = await _handle_archived(ctx, limit)
        case "archive_now":
            result = await _handle_archive_now(ctx)
        case "consolidate":
            result = await _handle_consolidate(ctx, category)
        case "compress":
            result = await _handle_memory_compress(ctx, memory_id)
        case "entity_search":
            ent_type = context_type if context_type != "conversation" else None
            result = await _handle_entity_search(
                ctx, name=name or query, entity_type=ent_type, limit=limit
            )
        case "entity_graph":
            result = await _handle_entity_graph(
                ctx,
                entity_id=entity_id,
                name=name or query,
                depth=depth,
                limit=limit,
            )
        case "history":
            result = await _handle_history(ctx, entity_id=entity_id or memory_id)
        case _:
            valid_actions = [
                "add",
                "archive_now",
                "archived",
                "as_of",
                "capture",
                "compress",
                "consolidate",
                "delete",
                "entity_graph",
                "entity_search",
                "export",
                "history",
                "import",
                "list",
                "restore",
                "search",
                "stats",
                "update",
            ]
            closest = (
                difflib.get_close_matches(str(action), valid_actions, n=1)
                if action is not None
                else []
            )
            resp: dict[str, typing.Any] = {
                "error": f"Unknown action '{action}'.",
                "valid_actions": valid_actions,
                "hint": "Common actions: 'add' to store new info, 'search' to find existing, 'update' to modify by ID.",
            }
            if closest:
                resp["suggestion"] = f"Did you mean '{closest[0]}'?"
            else:
                resp["suggestion"] = (
                    f"Available actions are: {', '.join(valid_actions)}."
                )
            result = resp

    result["_deprecation"] = _deprecation_notice(action)
    return result


@mcp.tool(
    description=(
        "Server configuration. Actions: status | set | warmup | "
        "backfill_embeddings.\n"
        "\n"
        "ACTION GUIDE — when to use each:\n"
        "- status: Show current configuration, provider cells, auth mode, and "
        "database stats.\n"
        "- set: Update a setting. Requires 'key' and 'value'. Valid key: "
        "'log_level' (str).\n"
        "- warmup: Pre-download local embedding model (~570 MB) / probe the "
        "embed cell.\n"
        "- backfill_embeddings: Embed active rows missing a vector; optional "
        "batch_size is bounded to 100."
    ),
    annotations=ToolAnnotations(
        title="Config",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)
async def config(
    action: str,
    key: str | None = None,
    value: str | None = None,
    batch_size: int | None = None,
    ctx: Context | None = None,
) -> dict[str, typing.Any]:
    """Server configuration and bounded vector backfill.

    Actions:
    - status: Show current config
    - set: Update setting (key + value required)
    - warmup: Pre-download local embedding model / probe the embed cell
    - backfill_embeddings: Embed active rows missing a vector
    """
    match action:
        case "status":
            return await _handle_config_status(ctx)
        case "set":
            return await _handle_config_set(key, value)
        case "warmup":
            return await _handle_config_warmup()
        case "backfill_embeddings":
            return await _handle_config_backfill(ctx, batch_size)
        case _:
            valid_actions = [
                "backfill_embeddings",
                "set",
                "status",
                "warmup",
            ]
            closest = (
                difflib.get_close_matches(str(action), valid_actions, n=1)
                if action is not None
                else []
            )
            resp: dict[str, typing.Any] = {
                "error": f"Unknown action '{action}'.",
                "valid_actions": valid_actions,
                "hint": "Common actions: 'status' to view config, 'set' to update settings.",
            }
            if closest:
                resp["suggestion"] = f"Did you mean '{closest[0]}'?"
            else:
                resp["suggestion"] = (
                    f"Available actions are: {', '.join(valid_actions)}."
                )
            return resp


async def _handle_memory_compress(
    ctx: Context | None, memory_id: str | None
) -> dict[str, typing.Any]:
    """``memory(action="compress", memory_id=...)`` - manual compression.

    Reruns the LLM compression pipeline against an existing row whose
    ``content`` is currently uncompressed. Updates ``content`` +
    ``text_raw`` + ``compressed`` + ``compression_provider`` in place.
    Useful for back-filling rows captured before COMPRESSION_ENABLED
    was true.
    """
    db, _, _ = _get_ctx(ctx)
    if not memory_id:
        return {
            "error": "memory_id required for compress",
            "suggestion": "Pass memory_id from search/list results.",
        }

    row = await asyncio.to_thread(db.get, memory_id)
    if not row:
        return {
            "error": f"Memory {memory_id} not found",
            "suggestion": "Verify the memory_id using action='search' or action='list'.",
        }
    if row.get("compressed"):
        return {
            "status": "already_compressed",
            "id": memory_id,
            "compression_provider": row.get("compression_provider"),
        }

    from mnemo_mcp.compression import compress

    result = await compress(row["content"])
    if not result["compressed"]:
        return {
            "status": "skipped",
            "id": memory_id,
            "reason": "no LLM provider available or compression disabled",
        }

    from datetime import UTC, datetime

    cursor = db._conn.cursor()
    cursor.execute(
        "UPDATE memories SET content = ?, text_raw = ?, compressed = 1, "
        "compression_provider = ?, updated_at = ? WHERE id = ?",
        (
            result["text"],
            result["text_raw"],
            result["compression_provider"],
            datetime.now(UTC).isoformat(),
            memory_id,
        ),
    )
    db._conn.commit()
    return {
        "status": "compressed",
        "id": memory_id,
        "compression_provider": result["compression_provider"],
        "tokens_in": result["tokens_in"],
        "tokens_out": result["tokens_out"],
    }


async def _handle_config_backfill(
    ctx: Context | None,
    batch_size: int | None,
) -> dict[str, typing.Any]:
    """Backfill active rows through the request-scoped store and embedder.

    This is intentionally a bounded MCP operation rather than a laptop-side
    D1 shortcut: the D1 and Vectorize transports are only available inside the
    deployed container. The migration-0003 ledger makes each page idempotent,
    while the authenticated subject selects the model, endpoint, and key.
    """
    if batch_size is None:
        batch_size = 32
    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or not 1 <= batch_size <= 100
    ):
        return {
            "error": "batch_size must be an integer between 1 and 100",
            "suggestion": "Use a bounded batch_size such as 32.",
        }

    db, embedding_model, embedding_dims = _get_ctx(ctx)
    from mnemo_mcp.embedder import get_backend

    backend = get_backend()
    if not embedding_model or backend is None:
        return {
            "status": "unavailable",
            "error": "No embedding backend is configured for the current subject.",
            "suggestion": "Verify embedding configuration or run the setup flow.",
            "scanned": 0,
            "embedded": 0,
            "skipped": 0,
            "failed": 0,
        }

    scanned = embedded = skipped = failed = 0
    seen_ids: set[str] = set()
    while True:
        try:
            rows = await asyncio.to_thread(
                db.rows_without_vectors,
                batch_size,
                exclude_ids=seen_ids,
            )
        except TypeError as exc:
            if "exclude_ids" not in str(exc):
                raise
            rows = await asyncio.to_thread(db.rows_without_vectors, batch_size)

        fresh_rows = [
            dict(row) for row in rows if str(row.get("id", "")) not in seen_ids
        ]
        if not fresh_rows:
            break
        seen_ids.update(str(row.get("id", "")) for row in fresh_rows)
        scanned += len(fresh_rows)

        usable = [row for row in fresh_rows if str(row.get("content") or "").strip()]
        skipped += len(fresh_rows) - len(usable)
        if not usable:
            if len(rows) < batch_size:
                break
            continue

        try:
            vectors = await backend.embed_texts(
                [str(row["content"]) for row in usable],
                embedding_dims,
                role="document",
            )
        except Exception as exc:
            logger.warning(f"Embedding backfill batch failed: {exc}")
            failed += len(usable)
            break

        if len(vectors) != len(usable):
            failed += len(usable)
            break

        batch_failed = False
        for row, vector in zip(usable, vectors, strict=True):
            if not vector:
                failed += 1
                batch_failed = True
                continue
            try:
                await asyncio.to_thread(db.write_vector, row["id"], list(vector))
            except Exception as exc:
                logger.warning(
                    f"Embedding backfill write failed for {row['id']}: {exc}"
                )
                failed += 1
                batch_failed = True
                continue
            embedded += 1

        if batch_failed or len(rows) < batch_size:
            break

    return {
        "status": "completed" if failed == 0 else "partial",
        "model": embedding_model,
        "dimensions": embedding_dims,
        "scanned": scanned,
        "embedded": embedded,
        "skipped": skipped,
        "failed": failed,
    }


async def _handle_config_status(ctx: Context | None) -> dict[str, typing.Any]:
    db, embedding_model, embedding_dims = _get_ctx(ctx)
    s = await asyncio.to_thread(db.stats)
    return {
        "database": {
            "path": s["db_path"],
            "total_memories": s["total_memories"],
            "categories": s["categories"],
            "vec_enabled": s["vec_enabled"],
        },
        "embedding": {
            "model": embedding_model,
            "dims": embedding_dims,
            "available": embedding_model is not None,
        },
        "provider_cells": {
            task: cell_configured(task)
            for task in ("embed", "rerank", "chat", "jev_score")
        },
        "auth_mode": hull_settings().server.auth,
    }


async def _handle_config_set(
    key: str | None, value: str | None
) -> dict[str, typing.Any]:
    if not key or value is None:
        return {
            "error": "key and value are required for set",
            "suggestion": "Provide both 'key' and 'value' parameters to update a configuration setting.",
        }

    valid_keys = {
        "log_level",
    }
    if key not in valid_keys:
        closest = (
            difflib.get_close_matches(str(key), list(valid_keys), n=1)
            if key is not None
            else []
        )
        resp: dict[str, typing.Any] = {
            "error": f"Invalid key: {key}",
            "valid_keys": sorted(valid_keys),
        }
        if closest:
            resp["suggestion"] = f"Did you mean '{closest[0]}'?"
        else:
            resp["suggestion"] = f"Available keys are: {', '.join(sorted(valid_keys))}."
        return resp

    # Apply setting
    if key == "log_level":
        level = value.upper()
        valid_levels = {
            "TRACE",
            "DEBUG",
            "INFO",
            "SUCCESS",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }
        if level not in valid_levels:
            closest = (
                difflib.get_close_matches(str(level), list(valid_levels), n=1)
                if level is not None
                else []
            )
            resp = {
                "error": f"Invalid log level: {value}",
                "valid_levels": sorted(valid_levels),
            }
            if closest:
                resp["suggestion"] = f"Did you mean '{closest[0]}'?"
            else:
                resp["suggestion"] = (
                    f"Available log levels are: {', '.join(sorted(valid_levels))}."
                )
            return resp

        settings.log_level = level
        logger.remove()
        logger.add(
            sys.stderr,
            level=settings.log_level,
        )

    return {
        "status": "updated",
        "key": key,
        "value": getattr(settings, key),
    }


async def _handle_config_warmup() -> dict[str, typing.Any]:
    from mnemo_mcp.setup_tool import run_warmup

    result = await run_warmup()
    return result


# --- Resources ---


@mcp.resource("mnemo://stats")
async def stats_resource(ctx: Context | None = None) -> str:
    """Database statistics and server status."""
    return _json(await _handle_stats(ctx))


# --- Prompts ---


@mcp.prompt()
def save_summary(summary: str) -> str:
    """Generate a prompt to save a conversation summary as memory.

    ACTION GUIDE — when to use:
    - Use when a conversation is concluding or shifting topics to persist key takeaways.
    - Parameters: 'summary' (the consolidated text to save).
    """
    if not summary or not summary.strip():
        return _json(
            {
                "error": "Summary cannot be empty",
                "suggestion": "Provide a concise summary of the conversation to save as memory.",
            }
        )

    return (
        f"Save this conversation summary as a memory:\n\n{summary}\n\n"
        "Use the memory tool with action='add', category='context', "
        "and appropriate tags."
    )


@mcp.prompt()
def recall_context(topic: str) -> str:
    """Generate a prompt to recall relevant memories about a topic.

    ACTION GUIDE — when to use:
    - Use when starting a new task or answering a question to retrieve prior context.
    - Parameters: 'topic' (the specific subject or keywords to search for).
    """
    if not topic or not topic.strip():
        return _json(
            {
                "error": "Topic cannot be empty",
                "suggestion": "Provide a specific topic or keyword to search for in your memories.",
            }
        )

    return (
        f"Search your memories for relevant context about: {topic}\n\n"
        "Use the memory tool with action='search' and this query. "
        "Include any relevant findings in your response."
    )


# --- Entrypoint ---


def build_http_app(settings=None):
    """Build the authenticated HTTP MCP app (Starlette), no port bind.

    Composition (de-host): the MCP SDK's ``streamable_http_app()`` carries
    only the session-manager lifespan, so this outer Starlette app runs BOTH
    lifespans — mnemo's own (store init, embedding/rerank warmup) and the
    session manager's — via an AsyncExitStack. :class:`HullAuthMiddleware`
    (pure ASGI) authenticates every request BEFORE the MCP handler and binds
    the identity to a contextvar that tools read with
    :func:`mnemo_mcp.runtime.current_sub`.
    """
    from contextlib import AsyncExitStack, asynccontextmanager

    from hull_core.auth.asgi import HullAuthMiddleware
    from starlette.applications import Starlette
    from starlette.routing import Mount

    inner = mcp.streamable_http_app()
    authenticator = build_authenticator(settings)

    @asynccontextmanager
    async def _combined_lifespan(app):  # noqa: ANN001, ANN202
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(lifespan(mcp))
            await stack.enter_async_context(inner.router.lifespan_context(inner))
            yield

    app = HullAuthMiddleware(inner, authenticator)
    return Starlette(lifespan=_combined_lifespan, routes=[Mount("/", app=app)])


def _is_loopback_host(host: str) -> bool:
    if host in ("localhost", "::1", "[::1]"):
        return True
    try:
        return int(socket.inet_aton(host).hex(), 16) & 0xFF000000 == 0x7F000000
    except OSError:
        return False


class ServerConfigError(ValueError):
    """Invalid server start configuration."""


def run_server_blocking(
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Blocking entry point: acquire the lifecycle lock, serve until stopped.

    The ONLY way mnemo-mcp runs (spec §3): one HTTP process, MCP endpoint at
    ``http://host:port/mcp``, auth per ``~/.mnemo/config.toml`` ([server]
    auth = no-auth | token | multi). In open mode a non-loopback bind is
    refused — an unauthenticated listener must never leave localhost.
    """
    import uvicorn
    from hull_core.lifecycle.lock import LifecycleLock

    from mnemo_mcp.runtime import hull_settings

    hs = hull_settings()
    bind_host = host or os.getenv("MNEMO_HOST") or hs.server.host
    bind_port = int(
        port if port is not None else (os.getenv("MNEMO_PORT") or hs.server.port)
    )

    if hs.server.auth == "open" and not _is_loopback_host(bind_host):
        raise ServerConfigError(
            f"auth = 'open' only permits loopback binds, refusing host "
            f"{bind_host!r} (set [server] auth to 'token' or 'multi' in "
            "~/.mnemo/config.toml for a shared listener)"
        )

    lock = LifecycleLock("mnemo", bind_port)
    with lock:
        app = build_http_app(hs)
        logger.info(
            f"mnemo-mcp MCP endpoint: http://{bind_host}:{bind_port}/mcp "
            f"(auth mode: {hs.server.auth})"
        )
        uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")


def main() -> None:
    """Blocking server entry.

    De-host: there is no stdio spawn mode and no ``--oauth`` flag anymore —
    the server is always the HTTP MCP endpoint. Bind host/port come from
    ``~/.mnemo/config.toml`` ([server] host/port), overridable via
    MNEMO_HOST / MNEMO_PORT env for container deployments.
    """
    host = os.environ.get("MNEMO_HOST") or None
    port_env = os.environ.get("MNEMO_PORT")
    port = int(port_env) if port_env else None
    run_server_blocking(host=host, port=port)


if __name__ == "__main__":
    main()
