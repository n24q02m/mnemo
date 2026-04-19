"""Configuration settings for Mnemo MCP Server."""

import os
from pathlib import Path

from loguru import logger
from pydantic_settings import BaseSettings


def _default_data_dir() -> Path:
    """Get default data directory (~/.mnemo-mcp/)."""
    return Path.home() / ".mnemo-mcp"


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


def _has_gguf_support() -> bool:
    """Check if llama-cpp-python is installed for GGUF models."""
    try:
        import llama_cpp  # noqa: F401

        return True
    except ImportError:
        return False


def _resolve_local_model(onnx_name: str, gguf_name: str) -> str:
    """Choose local model variant: GGUF if GPU + llama-cpp, else ONNX."""
    if _detect_gpu() and _has_gguf_support():
        return gguf_name
    return onnx_name


_EMBEDDING_PROVIDERS: dict[str, str] = {
    "JINA_AI_API_KEY": "jina_ai/jina-embeddings-v5-text-small",
    "GEMINI_API_KEY": "gemini/gemini-embedding-001",
    "GOOGLE_API_KEY": "gemini/gemini-embedding-001",
    "OPENAI_API_KEY": "text-embedding-3-large",
    "COHERE_API_KEY": "embed-multilingual-v3.0",
}

_RERANK_PROVIDERS: dict[str, str] = {
    "JINA_AI_API_KEY": "jina_ai/jina-reranker-v3",
    "COHERE_API_KEY": "rerank-v4.0-pro",
    "CO_API_KEY": "rerank-v4.0-pro",
}


class Settings(BaseSettings):
    """Mnemo MCP Server configuration.

    Environment variables:
    - DB_PATH: Path to SQLite database (default: ~/.mnemo-mcp/memories.db)
    - API_KEYS: Provider API keys, supports multiple providers
        Format: "ENV_VAR:key,ENV_VAR:key,..."
        Example: "COHERE_API_KEY:co-...,GEMINI_API_KEY:AIza..."
        Embedding: Jina > Gemini > OpenAI > Cohere. LLM: Gemini, OpenAI, xAI.
    - EMBEDDING_MODEL: Embedding model (auto-detected if not set)
    - EMBEDDING_DIMS: Embedding dimensions (0 = auto-detect, default 768)
    - EMBEDDING_BACKEND: "cloud" | "local" (auto: API_KEYS -> cloud, else local)
    - SYNC_ENABLED: Enable Google Drive sync (default: true)
    - SYNC_FOLDER: Google Drive folder name (default: "mnemo-mcp")
    - SYNC_INTERVAL: Auto-sync interval in seconds (default: 300)
    - GOOGLE_DRIVE_CLIENT_ID: OAuth client ID for Google Drive sync
    - GOOGLE_DRIVE_CLIENT_SECRET: OAuth client secret for Google Drive sync
    """

    # Database
    db_path: str = ""

    # Provider API Keys: "ENV_VAR:key,ENV_VAR:key,..."
    api_keys: str | None = None

    # Embedding model (auto-detected from API_KEYS if not set)
    embedding_model: str = ""
    embedding_dims: int = 0  # 0 = use server default (768)
    embedding_backend: str = (
        ""  # "cloud" | "local" | "" (auto: API_KEYS->cloud, else local)
    )

    # Reranking
    rerank_enabled: bool = True
    rerank_backend: str = ""  # "cloud" | "local" | "" (auto)
    rerank_model: str = ""
    rerank_top_n: int = 10
    # Sync (Google Drive API)
    # GDrive Desktop OAuth client — Google explicitly treats the Desktop/Installed
    # app client_secret as PUBLIC (per https://developers.google.com/identity/protocols/oauth2#installed).
    # Hardcoding default keeps parity with wet-mcp so end-users get zero-config sync after relay submit.
    sync_enabled: bool = True
    sync_folder: str = "mnemo-mcp"  # Google Drive folder name
    sync_interval: int = 300  # seconds, 0 = manual only
    google_drive_client_id: str = (
        "147668446467-olf2cf6e49rshqv9quvhq639110oc6hc.apps.googleusercontent.com"
    )
    google_drive_client_secret: str = "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"

    # Archive
    archive_enabled: bool = True
    archive_after_days: int = 90
    archive_importance_threshold: float = 0.3

    # Dedup
    dedup_threshold: float = 0.9
    dedup_warn_threshold: float = 0.7

    # Temporal decay
    recency_half_life_days: int = 7

    # LLM for graph/importance (reuse existing SDK config)
    llm_models: str = "gemini/gemini-3-flash-preview,openai/gpt-5.4-mini-2026-03-17"

    # Logging
    log_level: str = "INFO"

    model_config = {
        "env_prefix": "",
        "case_sensitive": False,
        "validate_assignment": True,
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

    def resolve_embedding_model(self) -> str | None:
        """Return explicit EMBEDDING_MODEL or None for auto-detect."""
        if self.embedding_model:
            return self.embedding_model
        return None

    def resolve_embedding_dims(self) -> int:
        """Return explicit EMBEDDING_DIMS or 0 for auto-detect."""
        return self.embedding_dims

    def resolve_local_embedding_model(self) -> str:
        """Resolve local embedding model: GGUF if GPU + llama-cpp, else ONNX."""
        return _resolve_local_model(
            "n24q02m/Qwen3-Embedding-0.6B-ONNX",
            "n24q02m/Qwen3-Embedding-0.6B-GGUF",
        )

    def resolve_embedding_backend(self) -> str:
        """Resolve embedding backend: 'local' or 'cloud'.

        Always returns a valid backend (never empty).

        Auto-detect order:
        1. Explicit EMBEDDING_BACKEND setting
        2. 'cloud' if in sdk mode (API keys configured)
        3. 'local' (qwen3-embed built-in, always available)
        """
        if self.embedding_backend:
            # Backward compat: 'litellm' maps to 'cloud'
            if self.embedding_backend == "litellm":
                return "cloud"
            return self.embedding_backend
        mode = self.resolve_provider_mode()
        if mode == "sdk":
            return "cloud"
        return "local"

    def resolve_rerank_backend(self) -> str:
        """Resolve reranker backend: 'cloud', 'local', or '' (disabled).

        Auto-detect order:
        1. Disabled if rerank_enabled is False
        2. Explicit rerank_backend setting
        3. 'cloud' if rerank_model set
        4. 'cloud' if a known rerank provider key is in env or API_KEYS
        5. 'local' (qwen3-embed cross-encoder, always available)
        """
        if not self.rerank_enabled:
            return ""
        if self.rerank_backend:
            # Backward compat: 'litellm' maps to 'cloud'
            if self.rerank_backend == "litellm":
                return "cloud"
            return self.rerank_backend
        if self.rerank_model:
            return "cloud"
        for key in _RERANK_PROVIDERS:
            if os.environ.get(key):
                return "cloud"
        if self.api_keys:
            for key in _RERANK_PROVIDERS:
                if key in self.api_keys:
                    return "cloud"
        return "local"

    def resolve_rerank_model(self) -> str | None:
        """Resolve reranker model name from config or env.

        Returns None if no known provider key is found.
        """
        if self.rerank_model:
            return self.rerank_model
        for key, model in _RERANK_PROVIDERS.items():
            if os.environ.get(key):
                return model
        if self.api_keys:
            for key, model in _RERANK_PROVIDERS.items():
                if key in self.api_keys:
                    return model
        return None

    def resolve_local_rerank_model(self) -> str:
        """Resolve local reranker model: GGUF if GPU + llama-cpp, else ONNX."""
        return _resolve_local_model(
            "n24q02m/Qwen3-Reranker-0.6B-ONNX",
            "n24q02m/Qwen3-Reranker-0.6B-GGUF",
        )


# Embedding models to try during auto-detection (in priority order).
# Cloud backend validates each against its API key -- first success wins.
_EMBEDDING_CANDIDATES = [
    "jina_ai/jina-embeddings-v5-text-small",
    "gemini/gemini-embedding-001",
    "text-embedding-3-large",
    "embed-multilingual-v3.0",
]

settings = Settings()
