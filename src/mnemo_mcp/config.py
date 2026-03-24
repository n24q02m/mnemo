"""Configuration settings for Mnemo MCP Server."""

import os
import re
from pathlib import Path

from loguru import logger
from pydantic import field_validator
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


_RERANK_PROVIDERS: dict[str, str] = {
    "COHERE_API_KEY": "rerank-v4.0-pro",
    "CO_API_KEY": "rerank-v4.0-pro",
}

RCLONE_PROVIDERS = {
    "drive",
    "dropbox",
    "s3",
    "b2",
    "onedrive",
    "box",
    "ftp",
    "sftp",
    "webdav",
    "local",
    "azureblob",
    "jottacloud",
    "mega",
    "pcloud",
    "smb",
    "koofr",
    "yandex",
    "hidrive",
    "mailru",
    "putio",
    "premiumizeme",
    "seafile",
    "sugar",
    "uptobox",
}


class Settings(BaseSettings):
    """Mnemo MCP Server configuration.

    Environment variables:
    - DB_PATH: Path to SQLite database (default: ~/.mnemo-mcp/memories.db)
    - API_KEYS: Provider API keys, supports multiple providers
        Format: "ENV_VAR:key,ENV_VAR:key,..."
        Example: "COHERE_API_KEY:co-...,GEMINI_API_KEY:AIza..."
        Embedding/rerank: Cohere. LLM: Gemini, OpenAI, xAI.
    - LITELLM_PROXY_URL: Proxy URL (legacy, kept for backward compat)
    - LITELLM_PROXY_KEY: Proxy virtual key (legacy)
    - EMBEDDING_MODEL: Embedding model (auto-detected if not set)
    - EMBEDDING_DIMS: Embedding dimensions (0 = auto-detect, default 768)
    - EMBEDDING_BACKEND: "cloud" | "local" (auto: API_KEYS -> cloud, else local)
        Local: GGUF if GPU + llama-cpp-python, else ONNX
    - SYNC_ENABLED: Enable rclone sync (default: false)
    - SYNC_PROVIDER: rclone provider type (default: "drive" for Google Drive)
    - SYNC_REMOTE: Rclone remote name (default: "gdrive")
    - SYNC_FOLDER: Remote folder name (default: "mnemo-mcp")
    - SYNC_INTERVAL: Auto-sync interval in seconds (default: 300)
    """

    # Database
    db_path: str = ""

    # LLM API Keys: "ENV_VAR:key,ENV_VAR:key,..."
    api_keys: str | None = None

    # LiteLLM Proxy (selfhosted gateway)
    litellm_proxy_url: str = ""  # e.g. http://10.0.0.20:4000
    litellm_proxy_key: str = ""

    # Embedding model (LiteLLM format, auto-detected from API_KEYS if not set)
    embedding_model: str = ""
    embedding_dims: int = 0  # 0 = use server default (768)
    embedding_backend: str = (
        ""  # "litellm" | "local" | "" (auto: API_KEYS->litellm, else local)
    )

    # Reranking
    rerank_enabled: bool = True
    rerank_backend: str = ""  # "litellm" | "local" | "" (auto)
    rerank_model: str = ""
    rerank_top_n: int = 10
    # Sync (rclone)
    sync_enabled: bool = False
    sync_provider: str = "drive"  # rclone provider type (drive, dropbox, s3, etc.)
    sync_remote: str = "gdrive"  # rclone remote name
    sync_folder: str = "mnemo-mcp"
    sync_interval: int = 300  # seconds, 0 = manual only
    rclone_version: str = "v1.68.2"

    # Archive
    archive_enabled: bool = True
    archive_after_days: int = 90
    archive_importance_threshold: float = 0.3

    # Dedup
    dedup_threshold: float = 0.9
    dedup_warn_threshold: float = 0.7

    # Temporal decay
    recency_half_life_days: int = 7

    # LLM for graph/importance (reuse existing proxy/SDK config)
    llm_models: str = "gemini/gemini-3-flash-preview"

    # Logging
    log_level: str = "INFO"

    model_config = {
        "env_prefix": "",
        "case_sensitive": False,
        "validate_assignment": True,
    }

    @field_validator("sync_provider")
    @classmethod
    def validate_sync_provider(cls, v: str) -> str:
        """Validate sync_provider against allowlist to prevent argument injection."""
        if not v:
            return v
        if v not in RCLONE_PROVIDERS:
            raise ValueError(
                f"Invalid sync_provider '{v}'. Must be one of: {', '.join(sorted(RCLONE_PROVIDERS))}"
            )
        return v

    @field_validator("sync_folder")
    @classmethod
    def validate_sync_folder(cls, v: str) -> str:
        """Validate sync_folder to prevent path traversal in rclone args."""
        if not v:
            return v
        if ".." in v or v.startswith("/"):
            raise ValueError("sync_folder must not contain '..' or start with '/'")
        if not re.match(r"^[a-zA-Z0-9_./\- ]*$", v):
            raise ValueError(
                "sync_folder can only contain alphanumeric characters, dashes, underscores, dots, slashes, and spaces"
            )
        return v

    @field_validator("sync_remote")
    @classmethod
    def validate_sync_remote(cls, v: str) -> str:
        """Validate sync_remote to prevent argument injection."""
        if not v:
            return v
        if v.startswith("-"):
            raise ValueError("sync_remote must not start with a hyphen (-)")
        if not re.match(r"^[a-zA-Z0-9_.-]*$", v):
            raise ValueError(
                "sync_remote can only contain alphanumeric characters, dashes, underscores, and dots"
            )
        return v

    def get_db_path(self) -> Path:
        """Get resolved database path."""
        if self.db_path:
            return Path(self.db_path).expanduser()
        return _default_data_dir() / "memories.db"

    def get_data_dir(self) -> Path:
        """Get data directory (parent of db file)."""
        return self.get_db_path().parent

    # LiteLLM uses different env vars for embeddings vs completions
    _ENV_ALIASES: dict[str, str] = {
        "GOOGLE_API_KEY": "GEMINI_API_KEY",
    }

    def setup_api_keys(self) -> dict[str, list[str]]:
        """Parse API_KEYS and set env vars for LiteLLM.

        Format: "GOOGLE_API_KEY:AIza...,OPENAI_API_KEY:sk-..."

        Also sets aliases (e.g., GOOGLE_API_KEY → GEMINI_API_KEY)
        because LiteLLM embedding uses GEMINI_API_KEY for gemini/ models.

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

        # Set first key of each env var (LiteLLM reads from env)
        for env_var, keys in keys_by_env.items():
            if keys:
                os.environ[env_var] = keys[0]
                # Set alias if defined (e.g., GOOGLE_API_KEY → GEMINI_API_KEY)
                alias = self._ENV_ALIASES.get(env_var)
                if alias and alias not in os.environ:
                    os.environ[alias] = keys[0]

        return keys_by_env

    def resolve_litellm_mode(self) -> str:
        """Detect LiteLLM mode: 'proxy', 'sdk', or 'local'."""
        if self.litellm_proxy_url:
            return "proxy"
        if self.api_keys:
            return "sdk"
        return "local"

    def setup_litellm(self) -> str:
        """One-time provider configuration. Call once during lifespan startup.

        Returns mode string: 'proxy', 'sdk', or 'local'.
        Kept method name for backward compatibility.
        """
        mode = self.resolve_litellm_mode()

        if mode == "proxy":
            logger.info(f"Proxy mode: {self.litellm_proxy_url}")
        elif mode == "sdk":
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
        Returns 'litellm' for backward compat when explicitly set.

        Auto-detect order:
        1. Explicit EMBEDDING_BACKEND setting
        2. 'cloud' if in proxy/sdk mode (API keys or proxy configured)
        3. 'local' (qwen3-embed built-in, always available)
        """
        if self.embedding_backend:
            return self.embedding_backend
        mode = self.resolve_litellm_mode()
        if mode in ("proxy", "sdk"):
            return "cloud"
        return "local"

    def resolve_rerank_backend(self) -> str:
        """Resolve reranker backend: 'cloud', 'local', or '' (disabled).

        Returns 'litellm' for backward compat when explicitly set.

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
    "embed-multilingual-v3.0",
]

settings = Settings()
