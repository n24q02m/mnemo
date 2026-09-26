"""Setup tool -- warmup and setup-sync logic as MCP-callable functions.

Extracted from __main__.py CLI commands and server.py config tool into
async functions that return structured dicts for MCP tool responses.
"""

import asyncio
import os
import shutil
from pathlib import Path

from loguru import logger

from mnemo_mcp.config import settings


def clear_model_cache(model_name: str) -> str | None:
    """Remove corrupted HuggingFace cache for a model so it re-downloads.

    Returns the path that was cleared, or None if no cache existed.
    """
    cache_dir = _resolve_cache_dir()
    safe_name = model_name.replace("/", "--")
    model_cache = cache_dir / f"models--{safe_name}"
    if model_cache.exists():
        shutil.rmtree(model_cache)
        return str(model_cache)
    return None


def _resolve_cache_dir() -> Path:
    """Resolve the local model cache using fastretrieval's public API."""
    new = os.getenv("FASTRETRIEVAL_CACHE_PATH")
    if new:
        return Path(new)

    from fastretrieval import define_cache_dir

    # Keep cache recovery aligned with fastretrieval's public API and default path.
    return define_cache_dir()


def _download_local_embedding(settings_obj) -> dict:
    """Download and validate the local embedding model."""
    from fastretrieval import TextEmbedding

    local_model = settings_obj.resolve_local_embedding_model()
    try:
        embed_model = TextEmbedding(model_name=local_model)
        result = list(embed_model.embed(["warmup test"]))
        if result:
            return {
                "step": "local_embedding",
                "status": "ok",
                "model": local_model,
                "dims": len(result[0]),
            }
        return {
            "step": "local_embedding",
            "status": "warning",
            "message": "Embedding test returned empty result",
        }
    except Exception as exc:
        if "NO_SUCHFILE" in str(exc) or "doesn't exist" in str(exc):
            cleared = clear_model_cache(local_model)
            logger.info(f"Cleared corrupted cache: {cleared}")
            embed_model = TextEmbedding(model_name=local_model)
            result = list(embed_model.embed(["warmup test"]))
            if result:
                return {
                    "step": "local_embedding",
                    "status": "ok",
                    "model": local_model,
                    "dims": len(result[0]),
                    "retried": True,
                }
            return {
                "step": "local_embedding",
                "status": "warning",
                "message": "Embedding test failed after cache clear",
            }
        raise


async def run_warmup() -> dict:
    """Pre-download/validate the embedding backend to avoid first-run delays.

    Cloud first: when the ``[models.embed]`` cell has a key, probe it with one
    ping embed. Otherwise fall back to the local ONNX model (unless
    ``DISABLE_LOCAL_EMBED`` is set). Returns a structured dict:
    ``{"status": "ok"|"error", "mode": "cloud"|"local"|"unavailable", "steps": [...]}``.
    """
    from mnemo_mcp.embedder import init_backend
    from mnemo_mcp.runtime import cell_configured, model_cell

    if cell_configured("embed"):
        try:
            backend = init_backend("cloud")
            native_dims = await backend.check_available()
            if native_dims > 0:
                return {
                    "status": "ok",
                    "mode": "cloud",
                    "steps": [
                        {
                            "step": "cloud_embedding",
                            "status": "ok",
                            "model": model_cell("embed").model,
                            "dims": native_dims,
                        }
                    ],
                    "embedding": {
                        "model": model_cell("embed").model,
                        "dims": native_dims,
                    },
                }
        except Exception as exc:
            logger.warning(f"Cloud embed probe failed: {exc}")
        return {
            "status": "error",
            "mode": "unavailable",
            "steps": [{"step": "cloud_embedding", "status": "error"}],
        }

    if settings.disable_local_embed:
        return {
            "status": "ok",
            "mode": "unavailable",
            "steps": [
                {
                    "step": "local_embedding",
                    "status": "skipped",
                    "message": "Local embedding disabled; embedding is unavailable",
                }
            ],
        }

    embed_result = await asyncio.to_thread(_download_local_embedding, settings)
    return {"status": "ok", "mode": "local", "steps": [embed_result]}
