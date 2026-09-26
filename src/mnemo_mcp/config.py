"""Instance configuration for product-local settings (de-host 2026-09).

Env-driven (pydantic-settings) product fields only: storage path, local ONNX
fallbacks, retrieval/consolidation knobs, logging. Everything the HOST owns —
auth mode + bind + per-task provider cells (embed/rerank/chat/jev_score) —
lives in ``~/.mnemo/config.toml`` via :mod:`hull_core.config.settings`
(see :mod:`mnemo_mcp.runtime`).
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from loguru import logger


def _default_data_dir() -> Path:
    """Get default data directory (~/.mnemo/)."""
    return Path.home() / ".mnemo"


@functools.lru_cache(maxsize=1)
def _detect_gpu() -> bool:
    """Detect GPU availability once (cross-platform, no hard deps)."""
    try:  # NVIDIA first: pynvml is cheap if present, absent otherwise.
        import pynvml  # type: ignore[import-not-found]

        pynvml.nvmlInit()
        return pynvml.nvmlDeviceGetCount() > 0
    except Exception:
        pass
    try:  # Apple Silicon: MPS via torch when installed.
        import torch  # type: ignore[import-not-found]

        return bool(getattr(torch.backends, "mps", None)) and torch.backends.mps.is_available()
    except Exception:
        return False


def _has_gguf_support() -> bool:
    try:
        import llama_cpp  # type: ignore[import-not-found]

        return True
    except ImportError:
        return False


def _resolve_local_model(onnx_name: str, gguf_name: str) -> str:
    """Pick GGUF on GPU+llama-cpp, else the ONNX default."""
    if _detect_gpu() and _has_gguf_support():
        return gguf_name
    return onnx_name


class Settings(BaseSettings):
    """Mnemo MCP Server configuration (product-local fields).

    Environment variables:
    - DB_PATH (or MNEMO_DB_PATH): Path to SQLite database
        (default: ~/.mnemo/memories.db). Both names are accepted;
        MNEMO_DB_PATH matches the name used by alembic migrations.
    - EMBEDDING_DIMS: Embedding storage width (0 = runtime default,
        1024 -- the native width of the default [models.embed] cell).
    - DISABLE_LOCAL_EMBED / DISABLE_LOCAL_RERANK: kill the local ONNX
        fallback legs (embedding/reranking degrade instead of downloading).
    - COMPRESSION_ENABLED: toggle the LLM compression pipeline.
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        validate_assignment=True,
        populate_by_name=True,
    )

    # Database. Accepts either DB_PATH (runtime, backward-compat) or
    # MNEMO_DB_PATH (the name alembic migrations read in alembic/env.py),
    # so a single env var aligns runtime and migrations.
    db_path: str = Field("", validation_alias=AliasChoices("DB_PATH", "MNEMO_DB_PATH"))

    # Embedding storage width; 0 = use the runtime default.
    embedding_dims: int = 0
    reindex_on_model_change: bool = False

    # Local ONNX fallback legs.
    disable_local_embed: bool = False  # env DISABLE_LOCAL_EMBED
    disable_local_rerank: bool = False  # env DISABLE_LOCAL_RERANK
    local_embedding_model: str = ""
    local_rerank_model: str = ""
    local_embedding_pooling: str = "MEAN"
    local_embedding_dim: int = 0  # 0 = use EMBEDDING_DIMS / runtime default
    local_embedding_normalize: bool = True
    local_embedding_model_file: str = "onnx/model.onnx"
    local_rerank_model_file: str = "onnx/model.onnx"

    # Reranker.
    rerank_enabled: bool = True
    rerank_top_n: int = 10

    # Archive / decay.
    archive_enabled: bool = True
    archive_after_days: int = 90
    archive_importance_threshold: float = 0.3

    # Dedup.
    dedup_threshold: float = 0.9
    dedup_warn_threshold: float = 0.7

    # Recency decay half-life (days) for hybrid scoring.
    recency_half_life_days: int = 7

    # LLM compression pipeline (chat cell).
    compression_enabled: bool = True

    # Knowledge graph + temporal.
    kg_auto_enabled: bool = False
    temporal_entity_resolution_threshold: float = 0.85
    temporal_supersession_threshold: float = 0.85
    temporal_supersession_enabled: bool = True

    log_level: str = "INFO"

    def get_db_path(self) -> Path:
        """Get resolved database path."""
        if self.db_path:
            return Path(self.db_path).expanduser()
        return _default_data_dir() / "memories.db"

    def get_data_dir(self) -> Path:
        """Get data directory (parent of db file)."""
        return self.get_db_path().parent

    def resolve_embedding_dims(self) -> int:
        """Return explicit EMBEDDING_DIMS or 0 for the runtime default."""
        return self.embedding_dims

    def resolve_local_embedding_model(self) -> str:
        """Resolve local embedding model: BYO override, else GGUF/ONNX default."""
        if self.local_embedding_model:
            return self.local_embedding_model
        return _resolve_local_model(
            "n24q02m/Qwen3-Embedding-0.6B-ONNX",
            "n24q02m/Qwen3-Embedding-0.6B-GGUF",
        )

    def resolve_local_rerank_model(self) -> str:
        """Resolve local reranker model: GGUF if GPU + llama-cpp, else ONNX.

        The ONNX default is the YesNo variant (~598 MB at inference vs ~12 GB
        for the full-vocab build); it is mathematically equivalent and, since
        fastretrieval's local runtime, produces batch-invariant scores.
        A BYO ``LOCAL_RERANK_MODEL`` override takes precedence when set.
        """
        if self.local_rerank_model:
            return self.local_rerank_model
        return _resolve_local_model(
            "n24q02m/Qwen3-Reranker-0.6B-ONNX-YesNo",
            "n24q02m/Qwen3-Reranker-0.6B-GGUF",
        )


settings = Settings()
