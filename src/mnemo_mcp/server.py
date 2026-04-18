"""Mnemo MCP Server - Persistent AI memory with embedded sync.

MCP Interface:
- memory tool: add/search/list/update/delete/export/import/stats
- config tool: status/sync/set/warmup/setup_sync
- help tool: full documentation on demand
- Resources: mnemo://stats, mnemo://recent
- Prompts: save_summary, recall_context
"""

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import resources as pkg_resources

from loguru import logger
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from mnemo_mcp.config import _EMBEDDING_CANDIDATES, settings
from mnemo_mcp.db import MemoryDB

# Constant embedding dimensions for sqlite-vec.
# All embeddings are truncated to this size so switching models never
# breaks the vector table. Override via EMBEDDING_DIMS env var.
_DEFAULT_EMBEDDING_DIMS = 768

# --- Lifespan ---


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

    embedding_model = settings.resolve_embedding_model()
    embedding_dims = settings.resolve_embedding_dims()
    embedding_backend_type = settings.resolve_embedding_backend()

    if cred_state == CredentialState.LOCAL or embedding_backend_type == "local":
        # Local-only path
        local_model = settings.resolve_local_embedding_model()
        try:
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

    # CONFIGURED + cloud backend -- no local fallback
    if embedding_model:
        # Explicit model -- validate it
        try:
            backend = await asyncio.to_thread(init_backend, "cloud", embedding_model)
            native_dims = await asyncio.to_thread(backend.check_available)
            if native_dims > 0:
                if embedding_dims == 0:
                    embedding_dims = _DEFAULT_EMBEDDING_DIMS
                logger.info(
                    f"Embedding: {embedding_model} "
                    f"(native={native_dims}, stored={embedding_dims})"
                )
                ctx["embedding_model"] = embedding_model
                ctx["embedding_dims"] = embedding_dims
                return
            else:
                logger.warning(f"Embedding model {embedding_model} not available")
        except Exception as e:
            logger.warning(f"Embedding model {embedding_model} not available: {e}")
    elif mode == "sdk":
        # Auto-detect: try candidate models
        for candidate in _EMBEDDING_CANDIDATES:
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
            except Exception:
                continue

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
            backend = await asyncio.to_thread(init_reranker, "local", local_model)
            available = await asyncio.to_thread(backend.check_available)
            if available:
                logger.info(f"Reranker: local {local_model}")
            else:
                logger.error("Local reranker not available")
        except Exception as e:
            logger.error(f"Local reranker init failed: {e}")
        return

    # CONFIGURED + cloud backend -- no local fallback
    if backend_type in ("cloud", "litellm"):
        model = settings.resolve_rerank_model()
        if model:
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
    db_path = settings.get_db_path()
    db = MemoryDB(
        db_path,
        embedding_dims=embedding_dims,
        recency_half_life_days=settings.recency_half_life_days,
    )
    stats = db.stats()
    logger.info(
        f"Database: {db_path} ({stats['total_memories']} memories, "
        f"vec={'on' if db.vec_enabled else 'off'})"
    )

    # 4. Start auto-sync if configured (requires Google Drive client ID)
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


# --- Helper ---


def _get_ctx(ctx: Context | None) -> tuple[MemoryDB, str | None, int]:
    """Extract db, model, dims from context."""
    lc = ctx.request_context.lifespan_context
    return lc["db"], lc["embedding_model"], lc["embedding_dims"]


def _json(obj: object) -> str:
    """Serialize to readable JSON."""
    return json.dumps(obj, indent=2)


async def _maybe_include_setup_hint(result: dict) -> dict:
    """If in awaiting_setup, trigger lazy relay and add hint to response."""
    from mnemo_mcp.credential_state import (
        CredentialState,
        get_state,
        trigger_relay_setup,
    )

    if get_state() == CredentialState.AWAITING_SETUP:
        url = await trigger_relay_setup()
        if url:
            result["_setup_hint"] = (
                f"Cloud features available. Configure API keys: {url}"
            )
    return result


def _format_memory(mem: dict) -> dict:
    """Format a raw memory dict for tool output.

    - Parse ``tags`` from JSON string to list
    - Round ``score`` to 3 decimal places
    """
    if isinstance(mem.get("tags"), str):
        try:
            mem["tags"] = json.loads(mem["tags"])
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
    db: MemoryDB,
    content: str | None,
    category: str | None,
    tags: list[str] | None,
    embedding_model: str | None,
    embedding_dims: int,
) -> str:
    if not content:
        return _json(
            {
                "error": "content is required for add",
                "example": "action='add', content='User prefers Python for data tasks', category='preference', tags=['python']",
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
        return _json({"error": str(e)})
    except Exception:
        logger.exception("Unexpected error in _handle_add")
        return _json({"error": "Internal error while adding memory"})

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
    """Background task: score importance and extract entities."""
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

    try:
        graph_data = await extract_entities(content)
        if graph_data and graph_data.get("entities"):
            conn = db._conn
            entity_ids = upsert_entities(conn, graph_data["entities"])
            name_to_id = {}
            for ent, eid in zip(graph_data["entities"], entity_ids, strict=False):
                name = ent.get("name", "").strip()
                if name:
                    name_to_id[name] = eid
            if graph_data.get("relations"):
                create_relations(conn, graph_data["relations"], name_to_id)
            link_memory_entities(conn, memory_id, entity_ids)
            conn.commit()
    except Exception as e:
        logger.debug(f"Entity extraction background error: {e}")


async def _handle_search(
    db: MemoryDB,
    query: str | None,
    category: str | None,
    tags: list[str] | None,
    limit: int,
    embedding_model: str | None,
    embedding_dims: int,
) -> str:
    if not query:
        return _json(
            {
                "error": "query is required for search",
                "example": "action='search', query='user preferences for UI theme'",
            }
        )

    if isinstance(limit, int):
        limit = max(1, min(limit, 100))

    embedding = await _embed(query, embedding_model, embedding_dims, is_query=True)
    results = await asyncio.to_thread(
        db.search,
        query=query,
        embedding=embedding,
        category=category,
        tags=tags,
        limit=limit,
    )

    # Rerank results for better precision (best-effort)
    from mnemo_mcp.reranker import get_reranker

    reranker = get_reranker()
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
        except Exception as e:
            logger.debug(f"Reranking failed, using original order: {e}")

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
    db: MemoryDB,
    category: str | None,
    limit: int,
) -> str:
    if isinstance(limit, int):
        limit = max(1, min(limit, 100))

    results = await asyncio.to_thread(
        db.list_memories,
        category=category,
        limit=limit,
    )
    return _json(
        {
            "count": len(results),
            "results": [_format_memory(r) for r in results],
        }
    )


async def _handle_update(
    db: MemoryDB,
    memory_id: str | None,
    content: str | None,
    category: str | None,
    tags: list[str] | None,
    source: str | None,
    importance: float | None,
    embedding_model: str | None,
    embedding_dims: int,
) -> str:
    if not memory_id:
        return _json(
            {
                "error": "memory_id is required for update. Use action='search' or action='list' first to find the memory ID.",
                "example": "action='update', memory_id='abc123', content='updated content'",
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
        return _json({"error": str(e)})
    except Exception:
        logger.exception("Unexpected error in _handle_update")
        return _json({"error": "Internal error while updating memory"})
    if ok:
        # Background: re-extract entities if content changed
        if content:
            asyncio.create_task(_enrich_memory(db, memory_id, content))
        return _json({"status": "updated", "id": memory_id})
    return _json({"error": f"Memory {memory_id} not found"})


async def _handle_delete(
    db: MemoryDB,
    memory_id: str | None,
) -> str:
    if not memory_id:
        return _json(
            {
                "error": "memory_id is required for delete. Use action='search' or action='list' first to find the memory ID.",
                "example": "action='delete', memory_id='abc123'",
            }
        )

    ok = await asyncio.to_thread(db.delete, memory_id)
    if ok:
        return _json({"status": "deleted", "id": memory_id})
    return _json({"error": f"Memory {memory_id} not found"})


async def _handle_export(
    db: MemoryDB,
) -> str:
    jsonl, count = await asyncio.to_thread(db.export_jsonl)
    return _json(
        {
            "format": "jsonl",
            "data": jsonl,
            "count": count,
        }
    )


async def _handle_import(
    db: MemoryDB,
    data: str | list | None,
    mode: str,
) -> str:
    if not data:
        return _json(
            {"error": "data (JSONL string or list of objects) is required for import"}
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


async def _handle_stats(
    db: MemoryDB,
    embedding_model: str | None,
    embedding_dims: int,
) -> str:
    s = await asyncio.to_thread(db.stats)
    s["embedding_model"] = embedding_model
    s["embedding_dims"] = embedding_dims
    s["sync_enabled"] = settings.sync_enabled
    s["sync_folder"] = settings.sync_folder
    return _json(s)


async def _handle_restore(
    db: MemoryDB,
    memory_id: str | None,
) -> str:
    if not memory_id:
        return _json(
            {
                "error": "memory_id is required for restore. Use action='archived' first to find archived memory IDs.",
                "example": "action='restore', memory_id='abc123'",
            }
        )

    ok = await asyncio.to_thread(db.restore_memory, memory_id)
    if ok:
        return _json({"status": "restored", "id": memory_id})
    return _json({"error": f"Archived memory {memory_id} not found"})


async def _handle_archived(
    db: MemoryDB,
    limit: int,
) -> str:
    if isinstance(limit, int):
        limit = max(1, min(limit, 100))

    results = await asyncio.to_thread(db.list_archived, limit)
    return _json(
        {
            "count": len(results),
            "results": results,
        }
    )


async def _handle_consolidate(
    db: MemoryDB,
    category: str | None,
) -> str:
    """Consolidate similar memories in a category using LLM summarization."""
    from mnemo_mcp.graph import _has_llm_provider

    mode = settings.resolve_provider_mode()
    if mode == "local" and not _has_llm_provider():
        return _json({"error": "Consolidation requires LLM (SDK mode with API keys)"})

    if not category:
        return _json({"error": "category is required for consolidate"})

    memories = await asyncio.to_thread(db.list_memories, category=category, limit=50)
    if len(memories) < 2:
        return _json(
            {"error": f"Need at least 2 memories in '{category}' to consolidate"}
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
        return _json({"error": f"Consolidation failed: {e}"})


# --- Tools ---


@mcp.tool(
    description=(
        "Persistent memory store. Actions: add|search|list|update|delete|export|import|stats|restore|archived|consolidate.\n"
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
    db, embedding_model, embedding_dims = _get_ctx(ctx)

    # Clamp limit to reasonable bounds to prevent DoS
    if isinstance(limit, int):
        limit = max(1, min(limit, 100))

    match action:
        case "add":
            return await _handle_add(
                db, content, category, tags, embedding_model, embedding_dims
            )
        case "search":
            return await _handle_search(
                db, query, category, tags, limit, embedding_model, embedding_dims
            )
        case "list":
            return await _handle_list(db, category, limit)
        case "update":
            return await _handle_update(
                db,
                memory_id,
                content,
                category,
                tags,
                source,
                importance,
                embedding_model,
                embedding_dims,
            )
        case "delete":
            return await _handle_delete(db, memory_id)
        case "export":
            return await _handle_export(db)
        case "import":
            return await _handle_import(db, data, mode)
        case "stats":
            return await _handle_stats(db, embedding_model, embedding_dims)
        case "restore":
            return await _handle_restore(db, memory_id)
        case "archived":
            return await _handle_archived(db, limit)
        case "consolidate":
            return await _handle_consolidate(db, category)
        case _:
            import difflib

            valid_actions = [
                "add",
                "archived",
                "consolidate",
                "delete",
                "export",
                "import",
                "list",
                "restore",
                "search",
                "stats",
                "update",
            ]
            closest = difflib.get_close_matches(action, valid_actions, n=1)
            suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
            return _json(
                {
                    "error": f"Unknown action '{action}'.{suggestion}",
                    "valid_actions": valid_actions,
                    "hint": "Common actions: 'add' to store new info, 'search' to find existing, 'update' to modify by ID.",
                }
            )


@mcp.tool(
    description=(
        "Server config, sync, and setup. Actions: status|sync|set|warmup|setup_sync. "
        "status: show config. sync: manual sync. set: change setting. "
        "warmup: pre-download embedding model (~570 MB). "
        "setup_sync: authenticate Google Drive via Device Code OAuth."
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
    db, embedding_model, embedding_dims = _get_ctx(ctx)

    match action:
        case "status":
            return await _handle_config_status(db, embedding_model, embedding_dims)
        case "sync":
            return await _handle_config_sync(db)
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
        case _:
            import difflib

            valid_actions = [
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
                "warmup",
            ]
            closest = difflib.get_close_matches(action, valid_actions, n=1)
            suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
            return _json(
                {
                    "error": f"Unknown action '{action}'.{suggestion}",
                    "valid_actions": valid_actions,
                }
            )


async def _handle_config_status(
    db: MemoryDB, embedding_model: str | None, embedding_dims: int
) -> str:
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


async def _handle_config_sync(db: MemoryDB) -> str:
    from mnemo_mcp.sync import sync_full

    result = await sync_full(db)
    return _json(result)


async def _handle_config_set(key: str | None, value: str | None) -> str:
    if not key or value is None:
        return _json({"error": "key and value are required for set"})

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
    from mnemo_mcp.credential_state import get_setup_url, get_state

    state = get_state()
    return _json(
        {
            "state": state.value,
            "setup_url": get_setup_url(),
            "cloud_keys_in_env": [
                k
                for k in (
                    "JINA_AI_API_KEY",
                    "GEMINI_API_KEY",
                    "OPENAI_API_KEY",
                    "COHERE_API_KEY",
                )
                if os.environ.get(k)
            ],
        }
    )


async def _handle_config_setup_start(key: str | None) -> str:
    from mnemo_mcp.credential_state import (
        CredentialState,
        get_state,
        trigger_relay_setup,
    )

    if get_state() == CredentialState.CONFIGURED and not (
        key and key.lower() == "force"
    ):
        return _json(
            {
                "status": "already_configured",
                "message": "Already configured. Use key='force' to reconfigure.",
            }
        )
    url = await trigger_relay_setup(force=True)
    if url:
        return _json(
            {
                "status": "setup_started",
                "setup_url": url,
                "message": "Open this URL to configure API keys.",
            }
        )
    return _json({"status": "error", "message": "Failed to start relay session."})


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
    # Backward compat alias for setup_start
    from mnemo_mcp.credential_state import trigger_relay_setup

    url = await trigger_relay_setup(force=True)
    if url:
        return _json({"status": "setup_started", "setup_url": url})
    return _json({"status": "error", "message": "Relay setup failed."})


@mcp.tool(
    description="Full documentation for memory and config tools. topic: 'memory' | 'config'",
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

        closest = difflib.get_close_matches(topic, list(valid_topics.keys()), n=1)
        suggestion = f" Did you mean '{closest[0]}'?" if closest else ""
        return _json(
            {
                "error": f"Unknown topic '{topic}'.{suggestion}",
                "valid_topics": list(valid_topics.keys()),
            }
        )

    doc_file = docs_package / filename
    content = await asyncio.to_thread(doc_file.read_text, encoding="utf-8")
    return content


# --- Resources ---


@mcp.resource("mnemo://stats")
async def stats_resource(ctx: Context | None = None) -> str:
    """Database statistics and server status."""
    db, embedding_model, embedding_dims = _get_ctx(ctx)
    s = await asyncio.to_thread(db.stats)
    s["embedding_model"] = embedding_model
    s["sync_enabled"] = settings.sync_enabled
    return _json(s)


@mcp.resource("mnemo://recent")
async def recent_resource(ctx: Context | None = None) -> str:
    """10 most recently updated memories."""
    db, _, _ = _get_ctx(ctx)
    results = await asyncio.to_thread(db.list_memories, limit=10)
    return _json(results)


# --- Prompts ---


@mcp.prompt()
def save_summary(summary: str) -> str:
    """Generate a prompt to save a conversation summary as memory."""
    return (
        f"Save this conversation summary as a memory:\n\n{summary}\n\n"
        "Use the memory tool with action='add', category='context', "
        "and appropriate tags."
    )


@mcp.prompt()
def recall_context(topic: str) -> str:
    """Generate a prompt to recall relevant memories about a topic."""
    return (
        f"Search your memories for relevant context about: {topic}\n\n"
        "Use the memory tool with action='search' and this query. "
        "Include any relevant findings in your response."
    )


# --- Entrypoint ---


async def run_http(port: int = 0) -> None:
    """Run as HTTP server with local OAuth 2.1 AS."""
    from mcp_core.transport.local_server import run_local_server

    from mnemo_mcp.credential_state import (
        save_credentials,
        set_gdrive_complete_callback,
    )
    from mnemo_mcp.relay_schema import RELAY_SCHEMA

    await run_local_server(
        mcp,  # ty: ignore[invalid-argument-type]
        server_name="mnemo-mcp",
        relay_schema=RELAY_SCHEMA,
        port=port,
        on_credentials_saved=save_credentials,
        setup_complete_hook=set_gdrive_complete_callback,
    )


def main() -> None:
    """Run the MCP server. Defaults to HTTP, --stdio for backward compat."""
    logger.remove()
    valid_levels = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}
    level = settings.log_level.upper() if settings.log_level else "WARNING"
    if level not in valid_levels:
        level = "WARNING"
    logger.add(sys.stderr, level=level)
    logger.info("Starting Mnemo MCP Server...")

    if "--stdio" in sys.argv or os.environ.get("MCP_TRANSPORT") == "stdio":
        mcp.run()
    else:
        asyncio.run(run_http())
