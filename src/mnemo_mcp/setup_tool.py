"""Setup tool -- warmup and setup-sync logic as MCP-callable functions.

Extracted from __main__.py CLI commands and server.py config tool into
async functions that return structured dicts for MCP tool responses.
"""

import asyncio
import json as json_mod
import os
import shutil
import tempfile
from pathlib import Path

from loguru import logger

from mnemo_mcp.config import _EMBEDDING_CANDIDATES, settings


def clear_model_cache(model_name: str) -> str | None:
    """Remove corrupted HuggingFace cache for a model so it re-downloads.

    Returns the path that was cleared, or None if no cache existed.
    """
    cache_dir = Path(
        os.getenv(
            "QWEN3_EMBED_CACHE_PATH",
            os.path.join(tempfile.gettempdir(), "qwen3_embed_cache"),
        )
    )
    safe_name = model_name.replace("/", "--")
    model_cache = cache_dir / f"models--{safe_name}"
    if model_cache.exists():
        shutil.rmtree(model_cache)
        return str(model_cache)
    return None


def _validate_cloud_models(settings_obj) -> dict:
    """Check if cloud embedding models are valid."""
    from mnemo_mcp.embedder import init_backend

    model = settings_obj.resolve_embedding_model()
    candidates = [model] if model else _EMBEDDING_CANDIDATES

    for candidate in candidates:
        try:
            backend = init_backend("cloud", candidate)
            dims = backend.check_available()
            if dims > 0:
                return {
                    "cloud_ready": True,
                    "model": candidate,
                    "dims": dims,
                }
        except Exception:
            continue

    return {"cloud_ready": False}


def _download_local_embedding(settings_obj) -> dict:
    """Download and validate local embedding model."""
    from qwen3_embed import TextEmbedding

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
    """Pre-download embedding model and validate setup to avoid first-run delays.

    Returns a structured dict with warmup results:
    {
        "status": "ok" | "error",
        "mode": "cloud" | "local",
        "steps": [{"step": str, "status": str, ...}, ...],
    }
    """
    steps = []

    # 1. Check cloud models if API keys are available
    keys = settings.setup_api_keys()
    if keys:
        cloud_result = await asyncio.to_thread(_validate_cloud_models, settings)
        if cloud_result["cloud_ready"]:
            steps.append(
                {
                    "step": "cloud_embedding",
                    "status": "ok",
                    "model": cloud_result["model"],
                    "dims": cloud_result["dims"],
                }
            )
            return {
                "status": "ok",
                "mode": "cloud",
                "steps": steps,
                "embedding": {
                    "model": cloud_result["model"],
                    "dims": cloud_result["dims"],
                },
            }
        steps.append(
            {
                "step": "cloud_embedding",
                "status": "fallback",
                "message": "Cloud models not available, falling back to local",
            }
        )

    # 2. Download local embedding model
    embed_result = await asyncio.to_thread(_download_local_embedding, settings)
    steps.append(embed_result)

    return {
        "status": "ok",
        "mode": "local",
        "steps": steps,
    }


async def run_setup_sync(provider: str = "drive") -> dict:
    """Authenticate sync provider via rclone (opens browser for OAuth).

    Returns a structured dict with setup results.
    """
    from mnemo_mcp.sync import _download_rclone, _extract_token, _get_rclone_path
    from mnemo_mcp.token_store import get_token_path, save_token

    rclone_path = _get_rclone_path()
    if not rclone_path:
        rclone_path = await _download_rclone()
        if not rclone_path:
            return {"status": "error", "error": "Failed to download rclone"}

    import subprocess

    result = await asyncio.to_thread(
        lambda: subprocess.run(
            [str(rclone_path), "authorize", "--", provider],
            stdout=subprocess.PIPE,
            text=True,
            timeout=300,
        )
    )

    if result.returncode != 0:
        return {
            "status": "error",
            "error": f"rclone authorize failed (exit {result.returncode})",
        }

    token_json = _extract_token(result.stdout or "")
    if not token_json:
        return {
            "status": "error",
            "error": "Could not extract token from rclone output",
            "hint": "Try with SYNC_ENABLED=true -- the server will auto-authenticate",
        }

    try:
        token_dict = json_mod.loads(token_json)
    except json_mod.JSONDecodeError:
        return {"status": "error", "error": "Invalid token JSON from rclone"}

    save_token(provider, token_dict)
    remote_name = "gdrive" if provider == "drive" else provider
    token_path = get_token_path(provider)

    return {
        "status": "authenticated",
        "provider": provider,
        "remote_name": remote_name,
        "token_path": str(token_path),
        "next_steps": {
            "SYNC_ENABLED": "true",
            **({"SYNC_PROVIDER": provider} if provider != "drive" else {}),
            **({"SYNC_REMOTE": remote_name} if remote_name != "gdrive" else {}),
        },
    }
