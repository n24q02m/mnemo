"""Mnemo MCP Server - Persistent AI memory with embedded sync.

MCP Interface:
- memory tool: add/search/list/update/delete/export/import/stats
- config tool: status/sync/set
- help tool: full documentation on demand
- Resources: mnemo://stats, mnemo://recent
- Prompts: save_summary, recall_context
"""

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import resources as pkg_resources

from loguru import logger
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from mnemo_mcp.config import settings
from mnemo_mcp.db import MemoryDB

# Embedding models to try during auto-detection (in priority order).
# LiteLLM validates each against its API key — first success wins.
_EMBEDDING_CANDIDATES = [
    "gemini/gemini-embedding-001",
    "text-embedding-3-small",
    "mistral/mistral-embed",
    "embed-english-v3.0",
]

# Fixed embedding dimensions for sqlite-vec.
# All embeddings are truncated to this size so switching models never
# breaks the vector table. Override via EMBEDDING_DIMS env var.
_DEFAULT_EMBEDDING_DIMS = 768

# --- Lifespan ---


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Initialize DB, embeddings, and sync on startup."""
    # 1. Setup API keys (+ aliases like GOOGLE_API_KEY -> GEMINI_API_KEY)
    keys = settings.setup_api_keys()
    if keys:
        logger.info(f"API keys configured: {', '.join(keys.keys())}")

    # 2. Resolve embedding backend + model + dims
    embedding_model = settings.resolve_embedding_model()
    embedding_dims = settings.resolve_embedding_dims()
    embedding_backend_type = settings.resolve_embedding_backend()

    if embedding_backend_type == "local":
        # Local ONNX backend (qwen3-embed) — no API keys needed
        from mnemo_mcp.embedder import init_backend

        backend = init_backend("local", embedding_model or None)
        native_dims = backend.check_available()
        if native_dims > 0:
            if embedding_dims == 0:
                embedding_dims = _DEFAULT_EMBEDDING_DIMS
            embedding_model = "__local__"
            logger.info(
                f"Embedding: local ONNX (native={native_dims}, stored={embedding_dims})"
            )
        else:
            logger.warning("Local embedding not available, trying LiteLLM...")
            embedding_backend_type = "litellm" if keys else ""

    if embedding_backend_type == "litellm":
        from mnemo_mcp.embedder import check_embedding_available, init_backend

        if embedding_model and embedding_model != "__local__":
            # Explicit model — validate it
            native_dims = check_embedding_available(embedding_model)
            if native_dims > 0:
                init_backend("litellm", embedding_model)
                if embedding_dims == 0:
                    embedding_dims = _DEFAULT_EMBEDDING_DIMS
                logger.info(
                    f"Embedding: {embedding_model} "
                    f"(native={native_dims}, stored={embedding_dims})"
                )
            else:
                logger.warning(
                    f"Embedding model {embedding_model} not available, using FTS5-only"
                )
                embedding_model = None
        elif keys:
            # Auto-detect: try candidate models
            for candidate in _EMBEDDING_CANDIDATES:
                native_dims = check_embedding_available(candidate)
                if native_dims > 0:
                    embedding_model = candidate
                    init_backend("litellm", candidate)
                    if embedding_dims == 0:
                        embedding_dims = _DEFAULT_EMBEDDING_DIMS
                    logger.info(
                        f"Embedding: {embedding_model} "
                        f"(native={native_dims}, stored={embedding_dims})"
                    )
                    break
            if not embedding_model:
                logger.warning("No embedding model available, using FTS5-only")
        else:
            embedding_model = None

    if not embedding_backend_type:
        logger.info("No embedding backend available, using FTS5-only search")

    # 3. Initialize database
    db_path = settings.get_db_path()
    db = MemoryDB(db_path, embedding_dims=embedding_dims)
    stats = db.stats()
    logger.info(
        f"Database: {db_path} ({stats['total_memories']} memories, "
        f"vec={'on' if db.vec_enabled else 'off'})"
    )

    # 4. Start auto-sync if configured
    if settings.sync_enabled:
        from mnemo_mcp.sync import start_auto_sync

        start_auto_sync(db)
        logger.info(
            f"Sync: {settings.sync_remote}:{settings.sync_folder} "
            f"(interval={settings.sync_interval}s)"
        )

    ctx = {
        "db": db,
        "embedding_model": embedding_model,
        "embedding_dims": embedding_dims,
    }

    try:
        yield ctx
    finally:
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


def _get_ctx(ctx: Context) -> tuple[MemoryDB, str | None, int]:
    """Extract db, model, dims from context."""
    lc = ctx.request_context.lifespan_context
    return lc["db"], lc["embedding_model"], lc["embedding_dims"]


def _json(obj: object) -> str:
    """Serialize to readable JSON."""
    return json.dumps(obj, indent=2)


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
    if backend is not None:
        try:
            if is_query and isinstance(backend, Qwen3EmbedBackend):
                return await backend.embed_single_query(text, dims)
            return await backend.embed_single(text, dims)
        except Exception as e:
            logger.debug(f"Embedding failed: {e}")
            return None

    # Legacy path: no backend initialized but model is set
    from mnemo_mcp.embedder import embed_single

    try:
        return await embed_single(text, model, dims)
    except Exception as e:
        logger.debug(f"Embedding failed: {e}")
        return None


# --- Tools ---


@mcp.tool(
    description=(
        "Persistent memory store. Actions: add|search|list|update|delete|export|import|stats. "
        "PROACTIVE: save user preferences, decisions, corrections, project conventions. "
        "Search before recommending. Use help tool for full docs."
    ),
    annotations=ToolAnnotations(
        title="Memory",
        readOnlyHint=False,
        destructiveHint=False,
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
    limit: int = 5,
    data: str | list | None = None,
    mode: str = "merge",
    ctx: Context = None,  # type: ignore[assignment]
) -> str:
    """Execute a memory action.

    Actions:
    - add: Save memory (content required, category/tags optional)
    - search: Hybrid search (query required, category/tags/limit optional)
    - list: Browse memories (category/limit optional)
    - update: Modify memory (memory_id required, content/category/tags optional)
    - delete: Remove memory (memory_id required)
    - export: Export all as JSONL
    - import: Import from JSONL (data required, mode: merge|replace)
    - stats: Database statistics
    """
    db, embedding_model, embedding_dims = _get_ctx(ctx)

    match action:
        case "add":
            if not content:
                return _json({"error": "content is required for add"})

            embedding = await _embed(content, embedding_model, embedding_dims)
            memory_id = await asyncio.to_thread(
                db.add,
                content=content,
                category=category or "general",
                tags=tags,
                embedding=embedding,
            )
            return _json(
                {
                    "id": memory_id,
                    "status": "saved",
                    "category": category or "general",
                    "semantic": embedding is not None,
                }
            )

        case "search":
            if not query:
                return _json({"error": "query is required for search"})

            embedding = await _embed(
                query, embedding_model, embedding_dims, is_query=True
            )
            results = await asyncio.to_thread(
                db.search,
                query=query,
                embedding=embedding,
                category=category,
                tags=tags,
                limit=limit,
            )
            return _json(
                {
                    "count": len(results),
                    "results": [_format_memory(r) for r in results],
                    "semantic": embedding is not None,
                }
            )

        case "list":
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

        case "update":
            if not memory_id:
                return _json({"error": "memory_id is required for update"})

            embedding = None
            if content:
                embedding = await _embed(content, embedding_model, embedding_dims)

            ok = await asyncio.to_thread(
                db.update,
                memory_id=memory_id,
                content=content,
                category=category,
                tags=tags,
                embedding=embedding,
            )
            if ok:
                return _json({"status": "updated", "id": memory_id})
            return _json({"error": f"Memory {memory_id} not found"})

        case "delete":
            if not memory_id:
                return _json({"error": "memory_id is required for delete"})

            ok = await asyncio.to_thread(db.delete, memory_id)
            if ok:
                return _json({"status": "deleted", "id": memory_id})
            return _json({"error": f"Memory {memory_id} not found"})

        case "export":
            jsonl = await asyncio.to_thread(db.export_jsonl)
            return _json(
                {
                    "format": "jsonl",
                    "data": jsonl,
                    "count": len(jsonl.strip().split("\n")) if jsonl.strip() else 0,
                }
            )

        case "import":
            if not data:
                return _json(
                    {
                        "error": "data (JSONL string or list of objects) is required for import"
                    }
                )

            # Normalize: accept both JSONL string and parsed list/dict from MCP clients
            if isinstance(data, list):
                import_data = "\n".join(
                    json.dumps(item, ensure_ascii=False) for item in data
                )
            elif isinstance(data, dict):
                import_data = json.dumps(data, ensure_ascii=False)
            else:
                import_data = data

            result = await asyncio.to_thread(db.import_jsonl, import_data, mode=mode)
            return _json(
                {
                    "status": "imported",
                    **result,
                }
            )

        case "stats":
            s = await asyncio.to_thread(db.stats)
            s["embedding_model"] = embedding_model
            s["embedding_dims"] = embedding_dims
            s["sync_enabled"] = settings.sync_enabled
            s["sync_remote"] = settings.sync_remote
            return _json(s)

        case _:
            return _json(
                {
                    "error": f"Unknown action: {action}",
                    "valid_actions": [
                        "add",
                        "search",
                        "list",
                        "update",
                        "delete",
                        "export",
                        "import",
                        "stats",
                    ],
                }
            )


@mcp.tool(
    description=(
        "Server config and sync. Actions: status|sync|set. "
        "status: show config. sync: manual sync. set: change setting."
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
    ctx: Context = None,  # type: ignore[assignment]
) -> str:
    """Server configuration and sync control.

    Actions:
    - status: Show current config
    - sync: Trigger manual sync (requires sync_enabled + sync_remote)
    - set: Update setting (key + value required)
    """
    db, embedding_model, embedding_dims = _get_ctx(ctx)

    match action:
        case "status":
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
                        "remote": settings.sync_remote,
                        "folder": settings.sync_folder,
                        "interval": settings.sync_interval,
                    },
                }
            )

        case "sync":
            from mnemo_mcp.sync import sync_full

            result = await sync_full(db)
            return _json(result)

        case "set":
            if not key or value is None:
                return _json({"error": "key and value are required for set"})

            valid_keys = {
                "sync_enabled",
                "sync_remote",
                "sync_folder",
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
                settings.log_level = value.upper()
                logger.remove()
                logger.add(
                    sys.stderr,
                    level=settings.log_level,
                )
            else:
                setattr(settings, key, value)

            return _json(
                {
                    "status": "updated",
                    "key": key,
                    "value": getattr(settings, key),
                }
            )

        case _:
            return _json(
                {
                    "error": f"Unknown action: {action}",
                    "valid_actions": ["status", "sync", "set"],
                }
            )


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

    filename = valid_topics.get(topic)
    if not filename:
        return _json(
            {
                "error": f"Unknown topic: {topic}",
                "valid_topics": list(valid_topics.keys()),
            }
        )

    doc_file = docs_package / filename
    content = doc_file.read_text(encoding="utf-8")
    return content


# --- Resources ---


@mcp.resource("mnemo://stats")
async def stats_resource(ctx: Context = None) -> str:  # type: ignore[assignment]
    """Database statistics and server status."""
    db, embedding_model, embedding_dims = _get_ctx(ctx)
    s = await asyncio.to_thread(db.stats)
    s["embedding_model"] = embedding_model
    s["sync_enabled"] = settings.sync_enabled
    return _json(s)


@mcp.resource("mnemo://recent")
async def recent_resource(ctx: Context = None) -> str:  # type: ignore[assignment]
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


def main() -> None:
    """Run the MCP server."""
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)
    logger.info("Starting Mnemo MCP Server...")

    mcp.run()
