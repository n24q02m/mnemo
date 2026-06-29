"""Mnemo MCP Server - Persistent AI memory with embedded sync.

MCP Interface:
- memory tool: add/search/list/update/delete/export/import/stats
- config tool: status/sync/set/warmup/setup_sync
- help tool: full documentation on demand
- Resources: mnemo://stats
- Prompts: save_summary, recall_context
"""

import asyncio
import json
import os
import sys
import typing
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib import resources as pkg_resources
from importlib.metadata import version as _pkgver

from loguru import logger
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from mnemo_mcp.config import settings
from mnemo_mcp.db import MemoryDB

# Resolved via importlib.metadata (not ``from mnemo_mcp import __version__``)
# to avoid a circular import: ``mnemo_mcp/__init__`` imports ``server.main``.
__version__ = _pkgver("mnemo-mcp")

# Constant embedding dimensions for sqlite-vec.
# All embeddings are truncated to this size so switching models never
# breaks the vector table. Override via EMBEDDING_DIMS env var.
_DEFAULT_EMBEDDING_DIMS = 768

# --- Lifespan ---


def _maybe_register_custom_embed(model_id: str) -> None:
    """Register a BYO local embedding model with qwen3-embed.

    Built-in ``n24q02m/Qwen3-*`` ids are already known to qwen3-embed, so
    they are skipped. Any other id (set via ``LOCAL_EMBEDDING_MODEL``) is
    registered via ``CustomModelSpec`` using the companion ``LOCAL_EMBEDDING_*``
    settings, so ``TextEmbedding(model_id)`` can load it.
    """
    if model_id.startswith("n24q02m/Qwen3-"):
        return

    from qwen3_embed import CustomModelSpec

    dim = settings.local_embedding_dim or settings.resolve_embedding_dims()
    if dim <= 0:
        dim = _DEFAULT_EMBEDDING_DIMS

    try:
        CustomModelSpec(
            model_id=model_id,
            hf=model_id,
            model_file=settings.local_embedding_model_file,
            dim=dim,
            pooling=settings.local_embedding_pooling,
            normalization=settings.local_embedding_normalize,
        ).register()
        logger.info(f"Registered custom local embedding model: {model_id}")
    except ValueError as e:
        # Already registered (embedding backend re-init) or invalid spec --
        # non-fatal; the existing registration is reused.
        logger.debug(f"Custom embedding registration skipped: {e}")


def _maybe_register_custom_rerank(model_id: str) -> None:
    """Register a BYO local reranker with qwen3-embed.

    Built-in ``n24q02m/Qwen3-Reranker-*`` ids are already known to qwen3-embed,
    so they are skipped. Any other id (set via ``LOCAL_RERANK_MODEL``) is
    registered via ``CustomRerankerSpec`` using ``LOCAL_RERANK_MODEL_FILE``, so
    ``TextCrossEncoder(model_id)`` can load it. A cross-encoder needs no
    dim/pooling.
    """
    if model_id.startswith("n24q02m/Qwen3-Reranker-"):
        return

    from qwen3_embed import CustomRerankerSpec

    try:
        CustomRerankerSpec(
            model_id=model_id,
            hf=model_id,
            model_file=settings.local_rerank_model_file,
        ).register()
        logger.info(f"Registered custom local reranker: {model_id}")
    except ValueError as e:
        # Already registered (reranker backend re-init) or invalid spec --
        # non-fatal; the existing registration is reused.
        logger.debug(f"Custom reranker registration skipped: {e}")


async def _init_embedding_backend(
    mode: str,
    ctx: dict,
) -> None:
    """Initialize embedding backend based on credential state.

    AWAITING_SETUP: skip (FTS5-only mode until user configures credentials).
    LOCAL: local-only path (qwen3-embed ONNX).
    CONFIGURED: cloud-only path -- no silent local fallback.

    Running this as a background task lets the MCP server accept connections
    immediately instead of blocking on model download or cloud API validation.
    """
    from mnemo_mcp.credential_state import CredentialState, get_state
    from mnemo_mcp.embedder import init_backend

    cred_state = get_state()

    if cred_state == CredentialState.AWAITING_SETUP:
        logger.info("Embedding: skipped (credentials not configured, FTS5 mode)")
        return

    embedding_chain = settings.embedding_chain()
    embedding_dims = settings.resolve_embedding_dims()
    embedding_backend_type = settings.resolve_embedding_backend()

    if cred_state == CredentialState.LOCAL or embedding_backend_type == "local":
        # Local-only path
        local_model = settings.resolve_local_embedding_model()
        try:
            await asyncio.to_thread(_maybe_register_custom_embed, local_model)
            backend = await asyncio.to_thread(init_backend, "local", local_model)
            native_dims = await asyncio.to_thread(backend.check_available)
            if native_dims > 0:
                if embedding_dims == 0:
                    embedding_dims = _DEFAULT_EMBEDDING_DIMS
                logger.info(
                    f"Embedding: local {local_model} "
                    f"(native={native_dims}, stored={embedding_dims})"
                )
                ctx["embedding_model"] = "__local__"
                ctx["embedding_dims"] = embedding_dims
            else:
                logger.error("Local embedding model not available")
        except Exception as e:
            logger.error(f"Local embedding init failed: {e}")
        return

    # CONFIGURED + cloud backend -- no local fallback.
    # Try each model in the chain (litellm fallback order) until one validates.
    for candidate in embedding_chain:
        try:
            backend = await asyncio.to_thread(init_backend, "cloud", candidate)
            native_dims = await asyncio.to_thread(backend.check_available)
            if native_dims > 0:
                if embedding_dims == 0:
                    embedding_dims = _DEFAULT_EMBEDDING_DIMS
                logger.info(
                    f"Embedding: {candidate} "
                    f"(native={native_dims}, stored={embedding_dims})"
                )
                ctx["embedding_model"] = candidate
                ctx["embedding_dims"] = embedding_dims
                return
            else:
                logger.warning(f"Embedding model {candidate} not available")
        except Exception as e:
            logger.warning(f"Embedding model {candidate} not available: {e}")

    logger.error("Cloud embedding not available and local fallback is disabled")


async def _init_reranker_backend(mode: str) -> None:
    """Initialize reranker backend based on credential state.

    AWAITING_SETUP: skip (search works without reranking).
    LOCAL: local-only path.
    CONFIGURED: cloud-only path -- no silent local fallback.
    """
    from mnemo_mcp.credential_state import CredentialState, get_state
    from mnemo_mcp.reranker import init_reranker

    backend_type = settings.resolve_rerank_backend()
    if not backend_type:
        logger.debug("Reranking disabled")
        return

    cred_state = get_state()

    if cred_state == CredentialState.AWAITING_SETUP:
        logger.info("Reranker: skipped (credentials not configured)")
        return

    if cred_state == CredentialState.LOCAL or backend_type == "local":
        # Local-only path
        local_model = settings.resolve_local_rerank_model()
        try:
            await asyncio.to_thread(_maybe_register_custom_rerank, local_model)
            backend = await asyncio.to_thread(init_reranker, "local", local_model)
            available = await asyncio.to_thread(backend.check_available)
            if available:
                logger.info(f"Reranker: local {local_model}")
            else:
                logger.error("Local reranker not available")
        except Exception as e:
            logger.error(f"Local reranker init failed: {e}")
        return

    # CONFIGURED + cloud backend -- no local fallback.
    # Try each model in the chain (litellm fallback order) until one validates.
    if backend_type in ("cloud", "litellm"):
        for model in settings.rerank_chain():
            try:
                backend = await asyncio.to_thread(init_reranker, "cloud", model)
                available = await asyncio.to_thread(backend.check_available)
                if available:
                    logger.info(f"Reranker: {model}")
                    return
            except Exception as e:
                logger.warning(f"Reranker {model} not available: {e}")
        logger.error("Cloud reranker not available and local fallback is disabled")


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Initialize DB, embeddings, and sync on startup.

    Embedding backend init runs as a background task so the server accepts
    connections immediately. Tools gracefully degrade to FTS5-only search
    until the embedding model is ready.
    """
    # 0. Non-blocking credential resolution (fast, <10ms)
    # Replaces the old blocking ensure_config() which waited 300s for relay.
    # Relay is now triggered lazily on first tool call via _maybe_include_setup_hint().
    try:
        from mnemo_mcp.credential_state import resolve_credential_state

        resolve_credential_state()
    except Exception as e:
        logger.debug(f"Credential resolution not available: {e}")

    # 1. Setup provider mode (sdk/local)
    mode = settings.setup_providers()

    # 2. Resolve initial embedding dims (may be refined by background task)
    embedding_dims = settings.resolve_embedding_dims()
    if embedding_dims == 0:
        embedding_dims = _DEFAULT_EMBEDDING_DIMS

    # 3. Initialize database (fast, no network)
    # Resolve the active embedding-model identity synchronously so the vector
    # store can guard against silent corruption when the model changes. The
    # background _init_embedding_backend task only refines availability; the
    # configured identity (local resolved id, or cloud chain head) is already
    # known here. dims is the primary guard; the model id is a secondary tag.
    if settings.resolve_embedding_backend() == "local":
        embedding_model_identity = settings.resolve_local_embedding_model()
    else:
        embedding_model_identity = settings.embedding_primary() or ""

    db_path = settings.get_db_path()
    db = MemoryDB(
        db_path,
        embedding_dims=embedding_dims,
        recency_half_life_days=settings.recency_half_life_days,
        embedding_model=embedding_model_identity,
        reindex_on_model_change=settings.reindex_on_model_change,
    )
    stats = db.stats()
    logger.info(
        f"Database: {db_path} ({stats['total_memories']} memories, "
        f"vec={'on' if db.vec_enabled else 'off'})"
    )

    # 4. Resolve sync mode (XOR per deployment) + start backend-specific init.
    #
    # Per the 2026-05-14 Test B design: operator picks ONE backend at deploy
    # time. SYNC_S3_BUCKET set -> S3 (Method 2/3 docker); otherwise -> GDrive
    # (Method 1 local-relay). See ``docs/passport.md``.
    from mnemo_mcp.sync import resolve_active_backend

    sync_mode = resolve_active_backend()
    if sync_mode == "s3":
        logger.info("Sync mode: s3 (S3 operator-config) — GDrive auto-init skipped")
    else:
        logger.info("Sync mode: gdrive (GDrive user OAuth via relay)")
        # Legacy GDrive DB-file copy path (Phase 1) — kept for backward compat
        # with existing GDrive users. Phase 2 passport bundles still flow
        # through the scheduler regardless of this background task.
        if settings.google_drive_client_id:
            from mnemo_mcp.sync import start_auto_sync

            start_auto_sync(db)
            logger.info(
                f"Sync: Google Drive/{settings.sync_folder} "
                f"(interval={settings.sync_interval}s)"
            )

    # Shared context -- embedding_model starts as None (not ready yet).
    # Background task updates it in-place once the backend is validated.
    ctx = {
        "db": db,
        "embedding_model": None,
        "embedding_dims": embedding_dims,
    }

    # 5. Initialize embedding backend in background (non-blocking).
    # This avoids blocking the server start on model download (~570 MB)
    # or cloud API validation. Tools degrade to FTS5-only until ready.
    embedding_task = asyncio.create_task(_init_embedding_backend(mode, ctx))

    # 6. Initialize reranker backend in background (non-blocking).
    reranker_task = asyncio.create_task(_init_reranker_backend(mode))

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

        # Cleanup
        from mnemo_mcp.sync import stop_auto_sync

        stop_auto_sync()
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


def _get_ctx(ctx: Context | None) -> tuple[MemoryDB, str | None, int]:
    """Extract db, model, dims from context."""
    lc = ctx.request_context.lifespan_context
    return lc["db"], lc["embedding_model"], lc["embedding_dims"]


def _json(obj: object) -> str:
    """Serialize to readable JSON."""
    return json.dumps(obj, indent=2)


async def _maybe_include_setup_hint(result: dict) -> dict:
    """If in awaiting_setup, surface a hint pointing the user at HTTP setup.

    Stdio mode reads creds from env vars; missing creds is non-fatal because
    mnemo-mcp falls back to local Qwen3-Embedding ONNX. The hint nudges users
    toward the optional HTTP setup form for cloud providers / GDrive sync.
    """
    from mnemo_mcp.credential_state import CredentialState, get_state

    if get_state() == CredentialState.AWAITING_SETUP:
        result["_setup_hint"] = (
            "Cloud features (Jina/Gemini/OpenAI/Cohere) and GDrive sync are "
            "optional. Set API keys via env vars (stdio mode) or run with "
            "--http and visit /authorize to configure via browser form."
        )
    return result


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
    text: str, model: str | None, dims: int, is_query: bool = False
) -> list[float] | None:
    """Embed text if embedding is available.

    Args:
        text: Text to embed.
        model: Embedding model name.
        dims: Target dimensions (MRL truncation).
        is_query: If True, use query_embed for instruction-aware asymmetric
            retrieval (Qwen3). Document embeddings stay raw.
    """
    if not model:
        return None

    from mnemo_mcp.embedder import Qwen3EmbedBackend, get_backend

    backend = get_backend()
    if backend is None:
        # Should not happen if model is set (implies init succeeded), but safe guard.
        logger.warning(f"Embedding backend not initialized despite model={model}")
        return None

    try:
        if is_query and isinstance(backend, Qwen3EmbedBackend):
            return await backend.embed_single_query(text, dims)
        return await backend.embed_single(text, dims)
    except Exception as e:
        logger.debug(f"Embedding failed: {e}")
        return None


async def _handle_add(
    ctx: Context | None,
    content: str | None,
    category: str | None = None,
    tags: list[str] | None = None,
) -> str:
    db, embedding_model, embedding_dims = _get_ctx(ctx)

    if not content:
        return _json(
            {
                "error": "content is required for add",
                "example": "action='add', content='User prefers Python for data tasks', category='preference', tags=['python']",
                "suggestion": "Provide the 'content' parameter to save a new memory.",
            }
        )

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

    embedding = await _embed(content, embedding_model, embedding_dims)
    try:
        memory_id = await asyncio.to_thread(
            db.add,
            content=content,
            category=category or "general",
            tags=tags,
            embedding=embedding,
        )
    except ValueError as e:
        return _json(
            {
                "error": str(e),
                "suggestion": "Ensure input parameters meet validation rules.",
            }
        )
    except Exception:
        logger.exception("Unexpected error in _handle_add")
        return _json(
            {
                "error": "Internal error while adding memory",
                "suggestion": "Check server logs for tracebacks or verify database permissions.",
            }
        )

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

    return _json(result)


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
) -> str:
    db, embedding_model, embedding_dims = _get_ctx(ctx)

    if not query:
        return _json(
            {
                "error": "query is required for search",
                "example": "action='search', query='user preferences for UI theme'",
                "suggestion": "Provide the 'query' parameter to perform a search.",
            }
        )

    db, _, _ = _get_ctx(ctx)

    if isinstance(limit, int):
        limit = max(1, min(limit, 100))

    embedding = await _embed(query, embedding_model, embedding_dims, is_query=True)

    # Spec section 4.2: rerank operates on a wider candidate pool
    # (top-50 -> top-N) so we ask db.search for ``max(50, limit*5)`` rows
    # when a reranker is active and otherwise stay at the LLM-requested limit.
    from mnemo_mcp.reranker import get_reranker

    reranker = get_reranker()
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
        documents = [r["content"] for r in results]
        try:
            ranked = await asyncio.to_thread(
                reranker.rerank, query, documents, top_n=limit
            )
            if ranked:
                reranked_results = []
                for idx, score in ranked:
                    r = results[idx].copy()
                    r["rerank_score"] = round(score, 4)
                    reranked_results.append(r)
                results = reranked_results
                reranked = True
            else:
                # No reranker output -> fall back to top-``limit`` of the
                # hybrid-scored pool so the response still respects ``limit``.
                results = results[:limit]
        except Exception as e:
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
    }

    if len(results) == 0:
        response["suggestion"] = (
            "No results found. Try broader terms, different keywords, "
            "or use action='list' to browse all memories."
        )

    response = await _maybe_include_setup_hint(response)
    return _json(response)


async def _handle_list(
    ctx: Context | None,
    category: str | None = None,
    limit: int = 5,
) -> str:
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
    return _json(response)


async def _handle_update(
    ctx: Context | None,
    memory_id: str | None,
    content: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    source: str | None = None,
    importance: float | None = None,
) -> str:

    db, _, _ = _get_ctx(ctx)
    db, embedding_model, embedding_dims = _get_ctx(ctx)

    if not memory_id:
        return _json(
            {
                "error": "memory_id is required for update. Use action='search' or action='list' first to find the memory ID.",
                "example": "action='update', memory_id='abc123', content='updated content'",
                "suggestion": "Provide the 'memory_id' parameter to update a specific memory.",
            }
        )

    embedding = None
    if content:
        embedding = await _embed(content, embedding_model, embedding_dims)

    try:
        ok = await asyncio.to_thread(
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
        return _json(
            {
                "error": str(e),
                "suggestion": "Check input parameters for invalid types or values.",
            }
        )
    except Exception:
        logger.exception("Unexpected error in _handle_update")
        return _json(
            {
                "error": "Internal error while updating memory",
                "suggestion": "Check server logs for tracebacks or verify database connection.",
            }
        )
    if ok:
        # Background: re-extract entities if content changed
        if content:
            asyncio.create_task(_enrich_memory(db, memory_id, content))
        return _json({"status": "updated", "id": memory_id})
    return _json(
        {
            "error": f"Memory {memory_id} not found",
            "suggestion": "Verify the memory_id using action='search' or action='list'.",
        }
    )


async def _handle_delete(
    ctx: Context | None,
    memory_id: str | None,
) -> str:

    db, _, _ = _get_ctx(ctx)

    if not memory_id:
        return _json(
            {
                "error": "memory_id is required for delete. Use action='search' or action='list' first to find the memory ID.",
                "example": "action='delete', memory_id='abc123'",
                "suggestion": "Provide the 'memory_id' parameter to delete a specific memory.",
            }
        )

    ok = await asyncio.to_thread(db.delete, memory_id)
    if ok:
        return _json({"status": "deleted", "id": memory_id})
    return _json(
        {
            "error": f"Memory {memory_id} not found",
            "suggestion": "Verify the memory_id using action='search' or action='list'.",
        }
    )


async def _handle_export(ctx: Context | None) -> str:
    db, _, _ = _get_ctx(ctx)
    jsonl, count = await asyncio.to_thread(db.export_jsonl)
    return _json(
        {
            "format": "jsonl",
            "data": jsonl,
            "count": count,
        }
    )


async def _handle_import(
    ctx: Context | None,
    data: str | list | None,
    mode: str = "merge",
) -> str:
    db, _, _ = _get_ctx(ctx)

    if not data:
        return _json(
            {
                "error": "data (JSONL string or list of objects) is required for import",
                "suggestion": "Provide the 'data' parameter containing the JSONL data or a list of JSON objects to import.",
            }
        )

    # Bolt Performance Optimization: Pass raw list/dict directly to database layer.
    # Avoids unnecessary JSON serialization and deserialization cycles for parsed inputs.
    assert data is not None  # guarded above
    result = await asyncio.to_thread(db.import_jsonl, data, mode=mode)
    return _json(
        {
            "status": "imported",
            **result,
        }
    )


async def _handle_stats(ctx: Context | None) -> str:
    db, embedding_model, embedding_dims = _get_ctx(ctx)
    s = await asyncio.to_thread(db.stats)
    s["embedding_model"] = embedding_model
    s["embedding_dims"] = embedding_dims
    s["sync_enabled"] = settings.sync_enabled
    s["sync_folder"] = settings.sync_folder
    return _json(s)


async def _handle_restore(
    ctx: Context | None,
    memory_id: str | None,
) -> str:

    db, _, _ = _get_ctx(ctx)

    if not memory_id:
        return _json(
            {
                "error": "memory_id is required for restore. Use action='archived' first to find archived memory IDs.",
                "example": "action='restore', memory_id='abc123'",
                "suggestion": "Provide the 'memory_id' parameter to restore a specific memory.",
            }
        )

    ok = await asyncio.to_thread(db.restore_memory, memory_id)
    if ok:
        return _json({"status": "restored", "id": memory_id})
    return _json(
        {
            "error": f"Archived memory {memory_id} not found",
            "suggestion": "Verify the memory_id using action='archived'.",
        }
    )


async def _handle_archived(
    ctx: Context | None,
    limit: int = 5,
) -> str:
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
    return _json(response)


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
) -> str:
    """Handle ``memory(action="capture")`` -- typed capture with dedup.

    Wraps :func:`mnemo_mcp.capture.capture` with the shared lifespan ctx so
    the capture pipeline can reuse the configured embedding backend without
    reaching into module-level globals.
    """
    db, embedding_model, embedding_dims = _get_ctx(ctx)

    if not text:
        return _json(
            {
                "error": "text is required for capture",
                "example": (
                    "action='capture', text='User prefers dark mode', "
                    "context_type='preference'"
                ),
                "suggestion": (
                    "Provide the 'text' parameter to capture a typed memory."
                ),
            }
        )

    embedding = await _embed(text, embedding_model, embedding_dims)

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
            return _json(
                {
                    "error": msg,
                    "valid_context_types": sorted(CONTEXT_TYPES),
                    "suggestion": (
                        f"Pick a context_type from {sorted(CONTEXT_TYPES)}."
                    ),
                }
            )
        return _json(
            {"error": msg, "suggestion": "Check payload length and constraints."}
        )
    except Exception:
        logger.exception("Unexpected error in _handle_capture")
        return _json(
            {
                "error": "Internal error while capturing memory",
                "suggestion": "Check server logs for tracebacks.",
            }
        )

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

    return _json(
        {
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
    )


async def _handle_archive_now(
    ctx: Context | None,
) -> str:
    """Trigger ``archive_by_score`` on demand using current settings."""
    db, _, _ = _get_ctx(ctx)
    archive_after_days = int(settings.archive_after_days)
    count = await asyncio.to_thread(
        db.archive_by_score, archive_after_days=archive_after_days
    )
    return _json(
        {
            "status": "archived",
            "count": count,
            "archive_after_days": archive_after_days,
            "scoring": "recency_factor * (1 - importance) > 1.0",
        }
    )


# ---------------------------------------------------------------------------
# Phase 3 KG actions: entity_search / entity_graph / history / as_of.
# ---------------------------------------------------------------------------


async def _handle_entity_search(
    ctx: Context | None,
    name: str | None,
    entity_type: str | None,
    limit: int = 20,
) -> str:
    """``memory(action="entity_search")`` -- find memories by entity name."""
    db, _, _ = _get_ctx(ctx)
    if not name:
        return _json(
            {
                "error": "name is required for entity_search",
                "example": "action='entity_search', name='FastAPI'",
                "suggestion": (
                    "Pass 'name' (entity name, case-insensitive) and "
                    "optionally 'entity_type' (person/project/tool/concept/"
                    "org/location/event)."
                ),
            }
        )
    from mnemo_mcp.temporal.queries import entity_search

    rows = await asyncio.to_thread(
        entity_search, db, name=name, entity_type=entity_type, limit=limit
    )
    return _json(
        {
            "count": len(rows),
            "results": [_format_memory(r) for r in rows],
            "matched_name": name,
        }
    )


async def _handle_entity_graph(
    ctx: Context | None,
    entity_id: str | None,
    name: str | None,
    depth: int = 2,
    limit: int = 50,
) -> str:
    """``memory(action="entity_graph")`` -- KG neighbourhood subgraph."""
    db, _, _ = _get_ctx(ctx)
    if not entity_id and not name:
        return _json(
            {
                "error": "entity_id or name required for entity_graph",
                "example": "action='entity_graph', name='Python', depth=2",
                "suggestion": "Provide either 'entity_id' or 'name' to specify the root of the graph.",
            }
        )
    from mnemo_mcp.temporal.queries import entity_graph

    result = await asyncio.to_thread(
        entity_graph, db, entity_id=entity_id, name=name, depth=depth, limit=limit
    )
    return _json(result)


async def _handle_history(
    ctx: Context | None,
    entity_id: str | None,
) -> str:
    """``memory(action="history")`` -- timeline of memories linked to an entity."""
    db, _, _ = _get_ctx(ctx)
    if not entity_id:
        return _json(
            {
                "error": "entity_id required for history",
                "example": "action='history', entity_id='<uuid>'",
                "suggestion": (
                    "Get an entity_id from entity_graph or entity_search results."
                ),
            }
        )
    from mnemo_mcp.temporal.queries import history_for_entity

    timeline = await asyncio.to_thread(history_for_entity, db, entity_id)
    return _json(
        {
            "entity_id": entity_id,
            "count": len(timeline),
            "timeline": [_format_memory(m) for m in timeline],
        }
    )


async def _handle_consolidate(
    ctx: Context | None,
    category: str | None = None,
) -> str:
    """Consolidate similar memories in a category using LLM summarization."""
    db, _, _ = _get_ctx(ctx)
    from mnemo_mcp.graph import _has_llm_provider

    mode = settings.resolve_provider_mode()
    if mode == "local" and not _has_llm_provider():
        return _json(
            {
                "error": "Consolidation requires LLM (SDK mode with API keys)",
                "suggestion": "Run the setup flow or provide API keys via environment variables (e.g. GEMINI_API_KEY).",
            }
        )

    if not category:
        return _json(
            {
                "error": "category is required for consolidate",
                "suggestion": "Provide the 'category' parameter to specify which memories to consolidate.",
            }
        )

    memories = await asyncio.to_thread(db.list_memories, category=category, limit=50)
    if len(memories) < 2:
        return _json(
            {
                "error": f"Need at least 2 memories in '{category}' to consolidate",
                "suggestion": f"Use action='list' with category='{category}' to see existing memories.",
            }
        )

    try:
        from mnemo_mcp.graph import _llm_completion, _resolve_llm_model

        model = _resolve_llm_model(settings)

        content_list = "\n---\n".join(
            f"[{m['id'][:8]}] {m['content']}" for m in memories[:20]
        )

        summary = await _llm_completion(
            model=model,
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

        return _json(
            {
                "status": "consolidated",
                "category": category,
                "original_count": len(memories),
                "summary": summary.strip(),
                "note": "Review the summary and use add/delete to apply changes.",
            }
        )
    except Exception as e:
        return _json(
            {
                "error": f"Consolidation failed: {e}",
                "suggestion": "Check LLM provider configuration and network connectivity.",
            }
        )


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
) -> str:
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
) -> str:
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
) -> str:
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
) -> str:
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
async def delete_memory(memory_id: str, ctx: Context | None = None) -> str:
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
async def export_memories(ctx: Context | None = None) -> str:
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
) -> str:
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
async def memory_stats(ctx: Context | None = None) -> str:
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
async def restore_memory(memory_id: str, ctx: Context | None = None) -> str:
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
async def archived_memories(limit: int = 5, ctx: Context | None = None) -> str:
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
async def consolidate_memories(category: str, ctx: Context | None = None) -> str:
    return await _handle_consolidate(ctx, category)


@mcp.tool(
    description=(
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
) -> str:
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
    """
    # Clamp limit to reasonable bounds to prevent DoS

    if isinstance(limit, int):
        limit = max(1, min(limit, 100))

    match action:
        case "add":
            return await _handle_add(ctx, content, category, tags)
        case "capture":
            return await _handle_capture(
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
            return await _handle_search(
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
            return await _handle_list(ctx, category, limit)
        case "update":
            return await _handle_update(
                ctx, memory_id, content, category, tags, source, importance
            )
        case "delete":
            return await _handle_delete(ctx, memory_id)
        case "export":
            return await _handle_export(ctx)
        case "import":
            return await _handle_import(ctx, data, mode)
        case "stats":
            return await _handle_stats(ctx)
        case "restore":
            return await _handle_restore(ctx, memory_id)
        case "archived":
            return await _handle_archived(ctx, limit)
        case "archive_now":
            return await _handle_archive_now(ctx)
        case "consolidate":
            return await _handle_consolidate(ctx, category)
        case "compress":
            return await _handle_memory_compress(ctx, memory_id)
        case "entity_search":
            ent_type = context_type if context_type != "conversation" else None
            return await _handle_entity_search(
                ctx, name=name or query, entity_type=ent_type, limit=limit
            )
        case "entity_graph":
            return await _handle_entity_graph(
                ctx,
                entity_id=entity_id,
                name=name or query,
                depth=depth,
                limit=limit,
            )
        case "history":
            return await _handle_history(ctx, entity_id=entity_id or memory_id)
        case _:
            import difflib

            valid_actions = [
                "add",
                "archive_now",
                "archived",
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
                difflib.get_close_matches(action, valid_actions, n=1) if action else []
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
            return _json(resp)


@mcp.tool(
    description=(
        "Server config, sync, and setup. Actions: status|sync|set|warmup|setup_sync.\n"
        "\n"
        "ACTION GUIDE — when to use each:\n"
        "- status: Show current configuration, setup status, and database stats.\n"
        "- sync: Trigger manual sync (requires sync_enabled=true + google_drive_client_id).\n"
        "- set: Update a setting. Requires 'key' and 'value'.\n"
        "  Valid keys: 'sync_enabled' (true/false), 'sync_interval' (int), 'log_level' (str).\n"
        "  Example: action='set', key='sync_enabled', value='true'\n"
        "- warmup: Pre-download embedding model (~570 MB) to avoid delays later.\n"
        "- setup_sync: Authenticate Google Drive via Device Code OAuth flow."
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
    ctx: Context | None = None,
) -> str:
    """Server configuration, sync control, and setup.

    Actions:
    - status: Show current config
    - sync: Trigger manual Google Drive sync (requires sync_enabled + google_drive_client_id)
    - set: Update setting (key + value required)
    - warmup: Pre-download embedding model (~570 MB) to avoid first-run delays
    - setup_sync: Authenticate Google Drive via Device Code OAuth flow
    """
    match action:
        case "status":
            return await _handle_config_status(ctx)
        case "sync":
            return await _handle_config_sync(ctx)
        case "set":
            return await _handle_config_set(key, value)
        case "warmup":
            return await _handle_config_warmup()
        case "setup_sync":
            return await _handle_config_setup_sync()
        case "setup_status":
            return await _handle_config_setup_status()
        case "setup_start":
            return await _handle_config_setup_start(key)
        case "setup_skip":
            return await _handle_config_setup_skip()
        case "setup_reset":
            return await _handle_config_setup_reset()
        case "setup_complete":
            return await _handle_config_setup_complete(ctx)
        case "setup_relay":
            return await _handle_config_setup_relay()
        case "sync_now":
            return await _handle_config_sync_now(ctx, key)
        case "export_passport":
            return await _handle_config_export_passport(ctx)
        case "import_passport":
            return await _handle_config_import_passport(ctx, key)
        case _:
            import difflib

            valid_actions = [
                "export_passport",
                "import_passport",
                "set",
                "setup_complete",
                "setup_relay",
                "setup_reset",
                "setup_skip",
                "setup_start",
                "setup_status",
                "setup_sync",
                "status",
                "sync",
                "sync_now",
                "warmup",
            ]
            closest = (
                difflib.get_close_matches(action, valid_actions, n=1) if action else []
            )
            resp: dict[str, typing.Any] = {
                "error": f"Unknown action '{action}'.",
                "valid_actions": valid_actions,
                "hint": "Common actions: 'status' to view config, 'set' to update settings, 'sync' to manual sync.",
            }
            if closest:
                resp["suggestion"] = f"Did you mean '{closest[0]}'?"
            else:
                resp["suggestion"] = (
                    f"Available actions are: {', '.join(valid_actions)}."
                )
            return _json(resp)


async def _handle_config_status(ctx: Context | None) -> str:
    db, embedding_model, embedding_dims = _get_ctx(ctx)
    s = await asyncio.to_thread(db.stats)
    return _json(
        {
            "database": {
                "path": str(settings.get_db_path()),
                "total_memories": s["total_memories"],
                "categories": s["categories"],
                "vec_enabled": s["vec_enabled"],
            },
            "embedding": {
                "model": embedding_model,
                "dims": embedding_dims,
                "available": embedding_model is not None,
            },
            "sync": {
                "enabled": settings.sync_enabled,
                "provider": "google_drive",
                "folder": settings.sync_folder,
                "interval": settings.sync_interval,
            },
        }
    )


async def _handle_config_sync(ctx: Context | None) -> str:
    db, _, _ = _get_ctx(ctx)
    from mnemo_mcp.sync import sync_full

    result = await sync_full(db)
    return _json(result)


async def _handle_config_set(key: str | None, value: str | None) -> str:
    if not key or value is None:
        return _json(
            {
                "error": "key and value are required for set",
                "suggestion": "Provide both 'key' and 'value' parameters to update a configuration setting.",
            }
        )

    valid_keys = {
        "sync_enabled",
        "sync_interval",
        "log_level",
    }
    if key not in valid_keys:
        return _json(
            {
                "error": f"Invalid key: {key}",
                "valid_keys": sorted(valid_keys),
            }
        )

    # Apply setting
    if key == "sync_enabled":
        settings.sync_enabled = value.lower() in ("true", "1", "yes")
    elif key == "sync_interval":
        settings.sync_interval = int(value)
    elif key == "log_level":
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
            return _json(
                {
                    "error": f"Invalid log level: {value}",
                    "valid_levels": sorted(valid_levels),
                }
            )

        settings.log_level = level
        logger.remove()
        logger.add(
            sys.stderr,
            level=settings.log_level,
        )

    return _json(
        {
            "status": "updated",
            "key": key,
            "value": getattr(settings, key),
        }
    )


async def _handle_config_warmup() -> str:
    from mnemo_mcp.setup_tool import run_warmup

    result = await run_warmup()
    return _json(result)


async def _handle_config_setup_sync() -> str:
    from mnemo_mcp.setup_tool import run_setup_sync

    result = await run_setup_sync()
    return _json(result)


async def _handle_config_setup_status() -> str:
    from mcp_core.storage.per_plugin_store import PerPluginStore

    from mnemo_mcp.credential_state import (
        ALL_CONFIG_KEYS,
        CLOUD_KEYS,
        CredentialState,
        credentials_for_current_request,
        get_current_sub,
        get_setup_url,
        get_state,
    )

    # In HTTP multi-user remote mode the per-request JWT sub is set; resolve
    # cred providers from the per-sub config so status reflects the *caller*,
    # not the shared host process env. Stdio + single-user HTTP keep the
    # legacy env + PerPluginStore derivation.
    if get_current_sub() is not None:
        _per_sub = credentials_for_current_request()
        _env_keys: list[str] = []
        _store_keys = [k for k in ALL_CONFIG_KEYS if _per_sub.get(k)]
    else:
        # Derive providers_configured from live PerPluginStore load + env
        # so status is accurate even if module-level _state is stale.
        _saved = PerPluginStore("mnemo").load() or {}
        _env_keys = [k for k in ALL_CONFIG_KEYS if os.environ.get(k)]
        _store_keys = [k for k in ALL_CONFIG_KEYS if _saved.get(k)]
    _providers = list(dict.fromkeys(_env_keys + _store_keys))
    _state = get_state()

    if _providers:
        _derived_state = "configured"
    elif _state == CredentialState.LOCAL:
        _derived_state = "local"
    elif _state == CredentialState.SETUP_IN_PROGRESS:
        _derived_state = "setup_in_progress"
    else:
        _derived_state = "awaiting_setup"
    return _json(
        {
            "state": _derived_state,
            "setup_url": get_setup_url(),
            "cloud_keys_in_env": [k for k in _env_keys if k in CLOUD_KEYS],
            "providers_configured": _providers,
        }
    )


async def _handle_config_setup_start(key: str | None) -> str:
    from mnemo_mcp.credential_state import CredentialState, get_state

    if get_state() == CredentialState.CONFIGURED and not (
        key and key.lower() == "force"
    ):
        return _json(
            {
                "status": "already_configured",
                "message": "Already configured. Use key='force' to reconfigure.",
            }
        )
    return _json(
        {
            "status": "stdio_unsupported",
            "message": (
                "Setup form is only available in HTTP mode. Run mnemo-mcp "
                "with --http (or MCP_TRANSPORT=http) and visit /authorize to "
                "configure API keys via browser. In stdio mode, set env vars "
                "directly (JINA_AI_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, "
                "COHERE_API_KEY, GOOGLE_DRIVE_CLIENT_ID)."
            ),
        }
    )


async def _handle_config_setup_skip() -> str:
    from mcp_core import set_local_mode

    from mnemo_mcp.credential_state import CredentialState, set_state

    set_local_mode("mnemo-mcp")
    set_state(CredentialState.LOCAL)
    return _json(
        {
            "status": "ok",
            "message": "Local mode set. Relay will not trigger on restart.",
        }
    )


async def _handle_config_setup_reset() -> str:
    from mnemo_mcp.credential_state import reset_state

    reset_state()
    return _json(
        {
            "status": "ok",
            "message": "Credentials cleared. Next tool call will offer setup.",
        }
    )


async def _handle_config_setup_complete(
    ctx: Context | None,
) -> str:
    from mnemo_mcp.credential_state import (
        CredentialState,
        get_state,
        resolve_credential_state,
    )

    resolve_credential_state()
    state = get_state()
    settings.setup_providers()

    # Re-init embedding backend when configured (always, in case
    # credentials changed or backend was cleared by reset)
    if state == CredentialState.CONFIGURED and ctx is not None:
        lc = ctx.request_context.lifespan_context
        mode = settings.setup_providers()
        await _init_embedding_backend(mode, lc)

    return _json(
        {
            "status": "ok",
            "state": state.value,
            "message": "Credential state refreshed.",
        }
    )


async def _handle_config_setup_relay() -> str:
    # Backward compat alias for setup_start.
    return await _handle_config_setup_start(key="force")


# ---------------------------------------------------------------------------
# Phase 2: passport sync MCP actions
# ---------------------------------------------------------------------------


def _resolve_sync_passphrase() -> str | None:
    """Resolve the passport bundle passphrase from env or persisted store.

    Order:
    1. ``SYNC_PASSPHRASE`` env var (in-process override, never persisted).
    2. ``settings.sync_passphrase`` Pydantic value (env-driven).

    Note: we deliberately do NOT load the Argon2id-derived hash from
    ``config.enc`` here - that hash is for verification only, never
    decryption. The user must supply the raw passphrase per session
    (HTTP relay form keeps the raw value in process memory only) so a
    leaked ``config.enc`` cannot decrypt past bundles.
    """
    raw = os.environ.get("SYNC_PASSPHRASE", "").strip()
    if raw:
        return raw
    if settings.sync_passphrase:
        return settings.sync_passphrase.strip() or None
    return None


def _resolve_default_backend() -> str:
    """Return the active sync backend per the deployment-mode XOR.

    Delegates to :func:`mnemo_mcp.sync.resolve_active_backend` which checks
    ``SYNC_S3_BUCKET`` (env > pydantic field). The legacy
    ``settings.sync_backend`` comma-separated multi-backend value is
    ignored — operator picks ONE backend at deploy time (Method 1 GDrive
    via relay vs Method 2/3 S3 via docker env). See ``docs/passport.md``.
    """
    from mnemo_mcp.sync import resolve_active_backend

    return resolve_active_backend()


async def _handle_config_sync_now(ctx: Context | None, backend: str | None) -> str:
    """``config(action="sync_now")`` - delta push (or full-pull-push on gap)."""
    db, _, _ = _get_ctx(ctx)
    passphrase = _resolve_sync_passphrase()
    if not passphrase:
        return _json(
            {
                "error": "SYNC_PASSPHRASE not set",
                "hint": (
                    "Set SYNC_PASSPHRASE env var (stdio mode) or submit "
                    "the relay form passphrase field (HTTP mode) before "
                    "triggering passport sync."
                ),
                "suggestion": "Provide the SYNC_PASSPHRASE environment variable or use the HTTP setup form.",
            }
        )

    target = (backend or _resolve_default_backend()).strip()
    try:
        from mnemo_mcp.sync.delta import sync_now

        result = await sync_now(db, target, passphrase)
        return _json({"backend": target, **result})
    except KeyError as e:
        return _json(
            {
                "error": str(e),
                "suggestion": "Check if backend configuration is complete.",
            }
        )
    except Exception as e:
        logger.exception("sync_now failed")
        return _json(
            {
                "error": f"sync_now failed: {e}",
                "suggestion": "Check network connectivity and provider credentials.",
            }
        )


async def _handle_config_export_passport(ctx: Context | None) -> str:
    """``config(action="export_passport")`` - write encrypted passport file."""
    db, _, _ = _get_ctx(ctx)
    passphrase = _resolve_sync_passphrase()
    if not passphrase:
        return _json(
            {
                "error": "SYNC_PASSPHRASE not set",
                "hint": (
                    "Set SYNC_PASSPHRASE env var or submit the relay form "
                    "passphrase before exporting a passport."
                ),
                "suggestion": "Provide the SYNC_PASSPHRASE environment variable or use the HTTP setup form.",
            }
        )

    from mnemo_mcp.sync.delta import build_full_bundle

    bundle = await build_full_bundle(db, passphrase)
    out_dir = settings.get_data_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"passport-{int(__import__('time').time())}.mnemo"
    await asyncio.to_thread(path.write_bytes, bundle)
    return _json({"status": "exported", "path": str(path), "size": len(bundle)})


async def _handle_config_import_passport(
    ctx: Context | None, source: str | None
) -> str:
    """``config(action="import_passport", from="s3"|"gdrive")``."""
    db, _, _ = _get_ctx(ctx)
    passphrase = _resolve_sync_passphrase()
    if not passphrase:
        return _json(
            {
                "error": "SYNC_PASSPHRASE not set",
                "hint": (
                    "Set SYNC_PASSPHRASE env var or submit the relay form "
                    "passphrase before importing a passport."
                ),
                "suggestion": "Provide the SYNC_PASSPHRASE environment variable or use the HTTP setup form.",
            }
        )

    target = (source or _resolve_default_backend()).strip()
    try:
        from mnemo_mcp.sync import get as get_backend
        from mnemo_mcp.sync.delta import apply_bundle

        backend = get_backend(target)
        bundle = await backend.pull(sequence=None)
    except KeyError as e:
        return _json(
            {
                "error": str(e),
                "suggestion": "Ensure the specified backend is properly configured.",
            }
        )
    except Exception as e:
        logger.exception("import_passport: backend pull failed")
        return _json(
            {
                "error": f"backend pull failed: {e}",
                "suggestion": "Verify remote backend access and network connectivity.",
            }
        )

    if not bundle:
        return _json(
            {
                "status": "no_passport",
                "backend": target,
                "message": "No passport bundle found on backend.",
            }
        )

    try:
        result = await apply_bundle(db, bundle, passphrase)
    except Exception as e:
        logger.exception("import_passport: apply_bundle failed")
        return _json(
            {
                "error": "Passphrase mismatch or tampered bundle",
                "detail": f"{type(e).__name__}: {e}",
                "backend": target,
            }
        )

    return _json({"status": "imported", "backend": target, **result})


async def _handle_memory_compress(ctx: Context | None, memory_id: str | None) -> str:
    """``memory(action="compress", memory_id=...)`` - manual compression.

    Reruns the LLM compression pipeline against an existing row whose
    ``content`` is currently uncompressed. Updates ``content`` +
    ``text_raw`` + ``compressed`` + ``compression_provider`` in place.
    Useful for back-filling rows captured before COMPRESSION_ENABLED
    was true.
    """
    db, _, _ = _get_ctx(ctx)
    if not memory_id:
        return _json(
            {
                "error": "memory_id required for compress",
                "suggestion": "Pass memory_id from search/list results.",
            }
        )

    row = await asyncio.to_thread(db.get, memory_id)
    if not row:
        return _json(
            {
                "error": f"Memory {memory_id} not found",
                "suggestion": "Verify the memory_id using action='search' or action='list'.",
            }
        )
    if row.get("compressed"):
        return _json(
            {
                "status": "already_compressed",
                "id": memory_id,
                "compression_provider": row.get("compression_provider"),
            }
        )

    from mnemo_mcp.compression import compress

    result = await compress(row["content"])
    if not result["compressed"]:
        return _json(
            {
                "status": "skipped",
                "id": memory_id,
                "reason": "no LLM provider available or compression disabled",
            }
        )

    cursor = db._conn.cursor()
    cursor.execute(
        "UPDATE memories SET content = ?, text_raw = ?, compressed = 1, "
        "compression_provider = ?, updated_at = ? WHERE id = ?",
        (
            result["text"],
            result["text_raw"],
            result["compression_provider"],
            __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
            memory_id,
        ),
    )
    db._conn.commit()
    return _json(
        {
            "status": "compressed",
            "id": memory_id,
            "compression_provider": result["compression_provider"],
            "tokens_in": result["tokens_in"],
            "tokens_out": result["tokens_out"],
        }
    )


@mcp.tool(
    description=(
        "Full documentation for memory and config tools. topic: 'memory' | 'config'\n"
        "\n"
        "ACTION GUIDE — when to use:\n"
        "- Use when you need detailed instructions on how to use specific server tools or features."
    ),
    annotations=ToolAnnotations(
        title="Help",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def help(topic: str = "memory") -> str:
    """Load full documentation for a tool."""
    docs_package = pkg_resources.files("mnemo_mcp.docs")
    valid_topics = {"memory": "memory.md", "config": "config.md"}

    # Backward compatibility: redirect "setup" to "config"
    if topic == "setup":
        topic = "config"

    filename = valid_topics.get(topic)
    if not filename:
        import difflib

        closest = (
            difflib.get_close_matches(topic, list(valid_topics.keys()), n=1)
            if topic
            else []
        )
        resp: dict[str, typing.Any] = {
            "error": f"Unknown topic '{topic}'.",
            "valid_topics": list(valid_topics.keys()),
        }
        if closest:
            resp["suggestion"] = f"Did you mean '{closest[0]}'?"
        else:
            resp["suggestion"] = (
                f"Available topics are: {', '.join(valid_topics.keys())}."
            )
        return _json(resp)

    doc_file = docs_package / filename
    content = await asyncio.to_thread(doc_file.read_text, encoding="utf-8")
    return content


# --- Re-trigger relay form ---
#
# Registers ``config__open_relay`` so the LLM can surface the HTTP setup
# form URL on demand. In stdio mode (no PUBLIC_URL), the tool returns
# ``stdio_unsupported`` -- users must run with --http to use the form.
from mcp_core.relay.tool_helpers import register_open_relay_tool  # noqa: E402

register_open_relay_tool(mcp, "mnemo-mcp", os.environ.get("PUBLIC_URL"))


# --- Resources ---


@mcp.resource("mnemo://stats")
async def stats_resource(ctx: Context | None = None) -> str:
    """Database statistics and server status."""
    return await _handle_stats(ctx)


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


async def run_http(port: int = 0) -> None:
    """Run as HTTP server with local OAuth 2.1 AS.

    Single-user mode (default): bind ``127.0.0.1`` and persist credentials
    to one shared ``config.enc`` on the host.

    Multi-user remote mode (``PUBLIC_URL`` set): bind ``0.0.0.0:8080`` (or
    ``MCP_PORT``) and scope credential storage per-JWT-sub via
    ``save_credentials``. The ``MCP_DCR_SERVER_SECRET`` env var is required
    as proof of intentional multi-user deployment -- without it, refuse to
    start so a misconfigured single-user instance never accidentally
    accepts other users' OAuth flows into the same shared ``config.enc``.
    """
    from mcp_core.transport.local_server import run_http_server

    from mnemo_mcp.credential_state import (
        _current_sub,
        save_credentials,
        wire_gdrive_callbacks,
    )
    from mnemo_mcp.relay_schema import RELAY_SCHEMA

    public_url = os.environ.get("PUBLIC_URL")
    if public_url:
        if not os.environ.get("MCP_DCR_SERVER_SECRET"):
            raise SystemExit(
                "mnemo-mcp refuses to start: PUBLIC_URL set but "
                "MCP_DCR_SERVER_SECRET missing. Multi-user remote mode "
                "requires the DCR secret as proof of intentional multi-user "
                "deployment (prevents accidental single-user credential leak)."
            )
        host = "0.0.0.0"
        port = int(os.environ.get("MCP_PORT", "8080"))
    else:
        host = "127.0.0.1"

    # HTTP multi-user remote mode (PUBLIC_URL set) wires an auth_scope
    # middleware that pins the decoded JWT ``sub`` into a contextvar for the
    # duration of the request so per-tool-call credential lookups can resolve
    # against ``$MNEMO_DATA_DIR/subs/<sub>/config.json`` instead of process
    # environment. Single-user HTTP (PUBLIC_URL unset) keeps the existing
    # env-driven flow untouched.
    async def _per_request_sub_scope(
        claims: dict, next_: Callable[[], Awaitable[None]]
    ) -> None:
        token = _current_sub.set(claims.get("sub"))
        try:
            await next_()
        finally:
            _current_sub.reset(token)

    # MCP_AUTH_DISABLE=1 skips Bearer JWT verification on /mcp -- for
    # deployments behind an external auth boundary (reverse proxy / API
    # gateway). See mcp-core BearerMCPApp.auth_disabled (>=1.15.0-beta.3).
    auth_disabled = os.environ.get("MCP_AUTH_DISABLE") == "1"

    await run_http_server(
        mcp,  # ty: ignore[invalid-argument-type]
        server_name="mnemo-mcp",
        relay_schema=RELAY_SCHEMA,
        auth_disabled=auth_disabled,
        port=port,
        host=host,
        on_credentials_saved=save_credentials,
        # Use wire_gdrive_callbacks so terminal OAuth errors (invalid_grant,
        # expired_token, save_token failures) surface to the browser's
        # /setup-status poll instead of leaving the form stuck on
        # "Waiting for authorization..." forever. Accepts legacy 1-arg core.
        setup_complete_hook=wire_gdrive_callbacks,
        auth_scope=_per_request_sub_scope if public_url else None,
    )


def main() -> None:
    """Run the MCP server.

    Transport selection (stdio default, HTTP opt-in):
      - stdio (default): pure stdio, env var creds only, single-user
      - http (opt-in via --http or MCP_TRANSPORT=http or TRANSPORT_MODE=http):
        runHttpServer with delegated OAuth (always multi-user when
        PUBLIC_URL set + MCP_DCR_SERVER_SECRET).
    """
    logger.remove()
    valid_levels = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}
    level = settings.log_level.upper() if settings.log_level else "WARNING"
    if level not in valid_levels:
        level = "WARNING"
    logger.add(sys.stderr, level=level)
    logger.info("Starting Mnemo MCP Server...")

    is_http = (
        "--http" in sys.argv
        or os.environ.get("MCP_TRANSPORT") == "http"
        or os.environ.get("TRANSPORT_MODE") == "http"
    )

    if is_http:
        asyncio.run(run_http())
        return

    # Stdio mode (default): run FastMCP stdio server directly. No bridge layer.
    # Universal MCP client compatibility (Claude Code, Cursor, VS Code Copilot, etc.).
    # See: ~/projects/.superpower/mcp-core/specs/2026-05-01-stdio-pure-http-multiuser.md
    mcp.run(transport="stdio")
