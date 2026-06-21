"""Configuration settings for Mnemo MCP Server."""

import functools
import importlib.util
import os
from pathlib import Path

from loguru import logger
from mcp_core.chains import resolve_backend
from mcp_core.llm.providers import key_env_for_model
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


def _default_data_dir() -> Path:
    """Get default data directory (~/.mnemo-mcp/)."""
    return Path.home() / ".mnemo-mcp"


@functools.lru_cache(maxsize=1)
def _detect_gpu() -> bool:
    """Check if GPU is available via onnxruntime providers."""
    try:
        import onnxruntime as ort

        providers = ort.get_available_providers()
        return (
            "CUDAExecutionProvider" in providers or "DmlExecutionProvider" in providers
        )
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def _has_gguf_support() -> bool:
    """Check if llama-cpp-python is installed for GGUF models."""
    return importlib.util.find_spec("llama_cpp") is not None


def _resolve_local_model(onnx_name: str, gguf_name: str) -> str:
    """Choose local model variant: GGUF if GPU + llama-cpp, else ONNX."""
    if _detect_gpu() and _has_gguf_support():
        return gguf_name
    return onnx_name


class Settings(BaseSettings):
    """Mnemo MCP Server configuration.

    Environment variables:
    - DB_PATH (or MNEMO_DB_PATH): Path to SQLite database
        (default: ~/.mnemo-mcp/memories.db). Both names are accepted;
        MNEMO_DB_PATH matches the name used by alembic migrations.
    - API_KEYS: Provider API keys, supports multiple providers
        Format: "ENV_VAR:key,ENV_VAR:key,..."
        Example: "COHERE_API_KEY:co-...,GEMINI_API_KEY:AIza..."
        Provider is implied by the model prefix; key per litellm convention.
    - EMBEDDING_MODELS / RERANK_MODELS / LLM_MODELS: ordered chains
        "provider/model,provider/model" (order = litellm fallback). Empty
        embedding/rerank -> local ONNX; empty LLM -> feature off.
    - EMBEDDING_DIMS: Embedding dimensions (0 = auto-detect, default 768)
    - EMBEDDING_MODEL / EMBEDDING_BACKEND: DEPRECATED (folded into the
        *_MODELS chains; backend inferred). Honored one release with a warning.
    - SYNC_ENABLED: Enable Google Drive sync (default: true)
    - SYNC_FOLDER: Google Drive folder name (default: "mnemo-mcp")
    - SYNC_INTERVAL: Auto-sync interval in seconds (default: 300)
    - GOOGLE_DRIVE_CLIENT_ID: OAuth client ID for Google Drive sync
    - GOOGLE_DRIVE_CLIENT_SECRET: OAuth client secret for Google Drive sync
    """

    # Database. Accepts either DB_PATH (runtime, backward-compat) or
    # MNEMO_DB_PATH (the name alembic migrations read in alembic/env.py),
    # so a single env var aligns runtime and migrations.
    db_path: str = Field("", validation_alias=AliasChoices("DB_PATH", "MNEMO_DB_PATH"))

    # Provider API Keys: "ENV_VAR:key,ENV_VAR:key,..."
    api_keys: str | None = None

    # Per-task model chains "provider/model,provider/model" (order = litellm
    # fallback). Empty -> local ONNX. Replaces the priority-router auto-detect
    # and the singular EMBEDDING_MODEL/EMBEDDING_BACKEND (deprecated shims).
    embedding_models: str = ""
    rerank_models: str = ""

    # DEPRECATED (2026-06-11, removed next release): singular model + backend
    # env vars. Folded into the plural *_MODELS chain (with a deprecation
    # warning); backend is now inferred from the chain (non-empty -> cloud).
    embedding_model: str = ""
    embedding_dims: int = 0  # 0 = use server default (768)

    # Safe-by-default vector-store guard. When the active embedding model /
    # dims differ from what produced the stored vectors, the DB raises
    # EmbeddingModelMismatch (touching no data). Set this True to instead DROP
    # the stored vectors + rebuild on the next embed pass (destructive, opt-in).
    reindex_on_model_change: bool = False
    embedding_backend: str = (
        ""  # "cloud" | "local" | "" (auto: API_KEYS->cloud, else local)
    )

    # Per-capability disable-local toggles (cross-cutting; see mcp_core.chains).
    # Turn OFF the heavy local qwen3 ONNX fallback (~570MB) WITHOUT pinning a
    # cloud model. Toggle on + no cloud chain => feature gracefully UNAVAILABLE
    # (clear status), never silently forced to a provider. Independent per task.
    disable_local_embed: bool = False  # env DISABLE_LOCAL_EMBED
    disable_local_rerank: bool = False  # env DISABLE_LOCAL_RERANK

    # BYO (bring-your-own) LOCAL model override. When set, the local
    # embed/rerank backend loads this model id instead of the bundled
    # Qwen3 default. A non-built-in id is registered with qwen3-embed via
    # CustomModelSpec / CustomRerankerSpec (server.py) using the companion
    # vars below.
    local_embedding_model: str = ""
    local_rerank_model: str = ""

    # Companion vars for registering a custom LOCAL embedding model.
    local_embedding_pooling: str = "MEAN"
    local_embedding_dim: int = 0  # 0 = use EMBEDDING_DIMS / server default
    local_embedding_normalize: bool = True
    local_embedding_model_file: str = "onnx/model.onnx"
    # Companion var for registering a custom LOCAL reranker (BYO ONNX cross-
    # encoder). A cross-encoder needs no dim/pooling -- just the ONNX file path.
    local_rerank_model_file: str = "onnx/model.onnx"

    # Reranking
    rerank_enabled: bool = True
    # DEPRECATED (2026-06-11, removed next release): see embedding_* above.
    rerank_backend: str = ""  # "cloud" | "local" | "" (auto)
    rerank_model: str = ""
    rerank_top_n: int = 10
    # Sync (Google Drive API)
    sync_enabled: bool = True
    sync_folder: str = "mnemo-mcp"  # Google Drive folder name
    sync_interval: int = 300  # seconds, 0 = manual only
    google_drive_client_id: str = ""
    google_drive_client_secret: str = ""

    # Archive
    archive_enabled: bool = True
    archive_after_days: int = 90
    archive_importance_threshold: float = 0.3

    # Dedup
    dedup_threshold: float = 0.9
    dedup_warn_threshold: float = 0.7

    # Temporal decay
    recency_half_life_days: int = 7

    # LLM chain (graph/importance/compression). Empty -> the key-gated default
    # chain (only default models whose provider key is configured); if none ->
    # empty -> LLM feature gracefully unavailable. Explicit LLM_MODELS is honored
    # verbatim (not key-filtered), matching EMBEDDING_MODELS / RERANK_MODELS.
    llm_models: str = ""

    # Phase 2: LLM compression
    compression_enabled: bool = True
    # "" = use the resolved llm_chain(); set to pin a single model (provider
    # derived from its prefix). compression_provider is kept for backward
    # compat with persisted config.enc but is no longer consulted by dispatch.
    compression_provider: str = ""
    compression_model: str = ""

    # DEPRECATED (2026-05-14): backend is auto-resolved from SYNC_S3_BUCKET
    # presence via :func:`mnemo_mcp.sync.resolve_active_backend` (XOR
    # between S3 and GDrive per deployment mode). Field kept for backward
    # compatibility with older ``config.enc`` files / external scripts that
    # may still set the env var; the value is no longer consulted by the
    # scheduler / sync_now handlers. Slated for removal post-v2.x.
    sync_backend: str = "gdrive"
    sync_s3_bucket: str = ""
    sync_s3_region: str = "us-east-1"
    sync_s3_endpoint: str = ""  # custom endpoint for R2 / B2 / MinIO
    sync_s3_access_key_id: str = ""
    sync_s3_secret_access_key: str = ""
    sync_s3_prefix: str = "passport/"

    # Phase 2: passport bundle passphrase (Argon2id-derived hash stored
    # in encrypted config.json; raw passphrase NEVER written to disk).
    sync_passphrase: str = ""  # set ONLY for in-process derivation

    # Phase 3: temporal KG.
    # KG_AUTO_ENABLED: when True, capture pipeline auto-extracts entities +
    #   relations via the LLM and persists them via temporal.store.
    #   Default False so Phase 1/2 callers don't pay the LLM round-trip
    #   without opt-in. The legacy add()/_enrich_memory background path
    #   still runs unchanged for backward compat.
    kg_auto_enabled: bool = False
    # Entity-resolution cosine threshold (0.85 default per spec §3).
    temporal_entity_resolution_threshold: float = 0.85
    # Supersession min confidence -- LLM emits {old_fact_id, confidence};
    # only apply when confidence >= this gate (0.85 default).
    temporal_supersession_threshold: float = 0.85
    temporal_supersession_enabled: bool = True

    # Logging
    log_level: str = "INFO"

    model_config = {
        "env_prefix": "",
        "case_sensitive": False,
        "validate_assignment": True,
        # Allow init by field name (e.g. Settings(db_path=...)) in addition
        # to the env aliases declared via validation_alias on db_path.
        "populate_by_name": True,
    }

    def get_db_path(self) -> Path:
        """Get resolved database path."""
        if self.db_path:
            return Path(self.db_path).expanduser()
        return _default_data_dir() / "memories.db"

    def get_data_dir(self) -> Path:
        """Get data directory (parent of db file)."""
        return self.get_db_path().parent

    # Env var aliases for provider SDKs
    _ENV_ALIASES: dict[str, str] = {
        "GOOGLE_API_KEY": "GEMINI_API_KEY",
    }

    def setup_api_keys(self) -> dict[str, list[str]]:
        """Parse API_KEYS and set env vars for provider SDKs.

        Format: "GOOGLE_API_KEY:AIza...,OPENAI_API_KEY:sk-..."

        Also sets aliases (e.g., GOOGLE_API_KEY -> GEMINI_API_KEY)
        because Gemini SDK uses GEMINI_API_KEY for gemini/ models.

        Returns:
            Dict mapping env var name to list of API keys.
        """
        if not self.api_keys:
            return {}

        keys_by_env: dict[str, list[str]] = {}

        for pair in self.api_keys.split(","):
            pair = pair.strip()
            if ":" not in pair:
                continue

            env_var, key = pair.split(":", 1)
            env_var = env_var.strip()
            key = key.strip()

            if not key:
                continue

            keys_by_env.setdefault(env_var, []).append(key)

        # Set first key of each env var (provider SDKs read from env)
        for env_var, keys in keys_by_env.items():
            os.environ[env_var] = keys[0]
            # Set alias if defined (e.g., GOOGLE_API_KEY -> GEMINI_API_KEY)
            alias = self._ENV_ALIASES.get(env_var)
            if alias and alias not in os.environ:
                os.environ[alias] = keys[0]

        return keys_by_env

    def resolve_provider_mode(self) -> str:
        """Detect provider mode: 'sdk' or 'local'."""
        if self.api_keys:
            return "sdk"
        if any(
            os.getenv(k)
            for k in (
                "JINA_AI_API_KEY",
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
                "OPENAI_API_KEY",
                "COHERE_API_KEY",
                "CO_API_KEY",
                "XAI_API_KEY",
            )
        ):
            return "sdk"
        return "local"

    def setup_providers(self) -> str:
        """One-time provider configuration. Call once during lifespan startup.

        Returns mode string: 'sdk' or 'local'.
        """
        mode = self.resolve_provider_mode()

        if mode == "sdk":
            self.setup_api_keys()
            logger.info("SDK direct mode (native provider SDKs)")
        else:
            logger.info("Local mode (no cloud API)")

        return mode

    # Explicit provider prefixes so key-availability filtering + litellm
    # routing are unambiguous (cohere/openai bare names would mis-detect).
    _DEFAULT_EMBEDDING_CHAIN = (
        "jina_ai/jina-embeddings-v5-text-small",
        "gemini/gemini-embedding-001",
        "openai/text-embedding-3-large",
        "cohere/embed-multilingual-v3.0",
    )
    _DEFAULT_RERANK_CHAIN = (
        "jina_ai/jina-reranker-v3",
        "cohere/rerank-v3.5",
    )
    _DEFAULT_LLM_CHAIN = (
        "gemini/gemini-3-flash-preview",
        "openai/gpt-5.4-mini-2026-03-17",
    )

    def _chain(self, primary: str, legacy: str, default: tuple[str, ...]) -> list[str]:
        if primary:
            return [m.strip() for m in primary.split(",") if m.strip()]
        if legacy:
            logger.warning(
                "Deprecated singular model env honored; migrate to the plural "
                "<TASK>_MODELS chain (removed next release): {!r}",
                legacy,
            )
            return [legacy.strip()]
        # No explicit chain: fall back to the curated default, but ONLY the
        # models whose provider key is actually configured. If none are (e.g.
        # an OpenAI-only key with a Jina/Cohere rerank default), the chain is
        # empty -> the task falls to local ONNX. This keeps "no usable key ->
        # local-core still runs" (spec §5.4) without a priority-router.
        return [m for m in default if self._key_available(key_env_for_model(m))]

    def _key_available(self, env_var: str) -> bool:
        """Whether a provider key is configured via env, bundled api_keys, or alias.

        Mirrors the resolution that ``setup_api_keys`` performs at startup so
        chain filtering is correct before the env export (and in tests that
        pass ``api_keys=`` without calling setup).
        """
        bundled = self.api_keys or ""
        if os.getenv(env_var) or env_var in bundled:
            return True
        # An alias (e.g. GOOGLE_API_KEY) satisfies its canonical key (GEMINI).
        for alias, canonical in self._ENV_ALIASES.items():
            if canonical == env_var and (os.getenv(alias) or alias in bundled):
                return True
        return False

    def embedding_chain(self) -> list[str]:
        return self._chain(
            self.embedding_models, self.embedding_model, self._DEFAULT_EMBEDDING_CHAIN
        )

    def rerank_chain(self) -> list[str]:
        if not self.rerank_enabled:
            return []
        return self._chain(
            self.rerank_models, self.rerank_model, self._DEFAULT_RERANK_CHAIN
        )

    def embedding_primary(self) -> str | None:
        chain = self.embedding_chain()
        return chain[0] if chain else None

    def rerank_primary(self) -> str | None:
        chain = self.rerank_chain()
        return chain[0] if chain else None

    def llm_chain(self) -> list[str]:
        """Resolve the LLM model chain.

        Explicit ``LLM_MODELS`` is honored verbatim. When unset, the curated
        default chain is key-gated: only default models whose provider key is
        configured survive (reusing the same ``_key_available`` /
        ``key_env_for_model`` filter as the embedding/rerank defaults). If no
        default model has a configured key, the chain is empty and the LLM
        feature is gracefully unavailable -- no keyless cloud model is emitted.
        """
        # No legacy singular LLM env var; pass "" so _chain skips to the
        # key-gated default when llm_models is empty.
        return self._chain(self.llm_models, "", self._DEFAULT_LLM_CHAIN)

    def llm_primary(self) -> str | None:
        chain = self.llm_chain()
        return chain[0] if chain else None

    def resolve_llm_backend(self) -> str:
        """Resolve the LLM backend: 'cloud' (non-empty chain) or 'unavailable'.

        The LLM feature has no local fallback: an empty chain (no LLM_MODELS and
        no default-model provider key) means the feature is off, reported as
        'unavailable' so ``config(action="status")`` can show it cleanly.
        """
        return "cloud" if self.llm_chain() else "unavailable"

    def resolve_embedding_dims(self) -> int:
        """Return explicit EMBEDDING_DIMS or 0 for auto-detect."""
        return self.embedding_dims

    def resolve_local_embedding_model(self) -> str:
        """Resolve local embedding model: BYO override, else GGUF/ONNX default."""
        if self.local_embedding_model:
            return self.local_embedding_model
        return _resolve_local_model(
            "n24q02m/Qwen3-Embedding-0.6B-ONNX",
            "n24q02m/Qwen3-Embedding-0.6B-GGUF",
        )

    def resolve_embedding_backend(self) -> str:
        """Resolve embedding backend: 'cloud', 'local', or 'unavailable'.

        3-way resolution via the shared mcp-core primitive: 'cloud' (non-empty
        EMBEDDING_MODELS chain), 'local' (empty chain + local leg enabled), or
        'unavailable' (empty chain + DISABLE_LOCAL_EMBED set -> no local download
        and no cloud, so embedding is gracefully unavailable, NOT forced). The
        deprecated EMBEDDING_BACKEND env var is honored for one release.

        Cloudflare serverless sets a cloud EMBEDDING_MODELS chain (or
        DISABLE_LOCAL_EMBED) via wrangler vars so the 570MB qwen3-embed ONNX
        model is never instantiated in the container.
        """
        if self.embedding_backend:
            logger.warning(
                "Deprecated EMBEDDING_BACKEND honored; backend is now "
                "inferred from EMBEDDING_MODELS."
            )
            return (
                "cloud"
                if self.embedding_backend in ("cloud", "litellm")
                else self.embedding_backend
            )
        return resolve_backend(
            has_cloud_chain=bool(self.embedding_chain()),
            local_enabled=not self.disable_local_embed,
        ).value

    def resolve_rerank_backend(self) -> str:
        """Resolve reranker backend: 'cloud', 'local', 'unavailable', or '' (disabled).

        '' when rerank_enabled is False. Otherwise 3-way via the shared mcp-core
        primitive (keyed on RERANK_MODELS + DISABLE_LOCAL_RERANK); the deprecated
        RERANK_BACKEND env var is honored for one release.
        """
        if not self.rerank_enabled:
            return ""
        if self.rerank_backend:
            logger.warning(
                "Deprecated RERANK_BACKEND honored; backend is now "
                "inferred from RERANK_MODELS."
            )
            return (
                "cloud"
                if self.rerank_backend in ("cloud", "litellm")
                else self.rerank_backend
            )
        return resolve_backend(
            has_cloud_chain=bool(self.rerank_chain()),
            local_enabled=not self.disable_local_rerank,
        ).value

    def resolve_local_rerank_model(self) -> str:
        """Resolve local reranker model: GGUF if GPU + llama-cpp, else ONNX.

        The ONNX default is the YesNo variant (~598 MB at inference vs ~12 GB
        for the full-vocab build); it is mathematically equivalent and, since
        qwen3-embed 1.11.2b3, produces batch-invariant scores (issue #725).
        A BYO ``LOCAL_RERANK_MODEL`` override takes precedence when set.
        """
        if self.local_rerank_model:
            return self.local_rerank_model
        return _resolve_local_model(
            "n24q02m/Qwen3-Reranker-0.6B-ONNX-YesNo",
            "n24q02m/Qwen3-Reranker-0.6B-GGUF",
        )


settings = Settings()
