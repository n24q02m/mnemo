"""Configuration settings for Mnemo MCP Server."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings


def _default_data_dir() -> Path:
    """Get default data directory (~/.mnemo-mcp/)."""
    return Path.home() / ".mnemo-mcp"


class Settings(BaseSettings):
    """Mnemo MCP Server configuration.

    Environment variables:
    - DB_PATH: Path to SQLite database (default: ~/.mnemo-mcp/memories.db)
    - API_KEYS: Provider API keys (format: ENV_VAR:key,ENV_VAR:key)
    - EMBEDDING_MODEL: LiteLLM embedding model (auto-detected if not set)
    - EMBEDDING_DIMS: Embedding dimensions (auto-detected)
    - SYNC_ENABLED: Enable rclone sync (default: false)
    - SYNC_REMOTE: Rclone remote name (e.g., "gdrive")
    - SYNC_FOLDER: Remote folder name (default: "mnemo-mcp")
    - SYNC_INTERVAL: Auto-sync interval in seconds (0 = manual only)
    """

    # Database
    db_path: str = ""

    # LLM API Keys: "ENV_VAR:key,ENV_VAR:key,..."
    api_keys: str | None = None

    # Embedding model (LiteLLM format, auto-detected from API_KEYS if not set)
    embedding_model: str = ""
    embedding_dims: int = 0  # 0 = use server default (768)
    embedding_backend: str = ""  # "litellm" | "local" | "" (auto-detect)

    # Sync (rclone)
    sync_enabled: bool = False
    sync_remote: str = ""  # rclone remote name
    sync_folder: str = "mnemo-mcp"
    sync_interval: int = 0  # seconds, 0 = manual only

    # Logging
    log_level: str = "INFO"

    model_config = {"env_prefix": "", "case_sensitive": False}

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

    def resolve_embedding_model(self) -> str | None:
        """Return explicit EMBEDDING_MODEL or None for auto-detect.

        If EMBEDDING_MODEL is set explicitly, return it.
        Otherwise return None — auto-detection happens in server lifespan
        by trying candidate models via LiteLLM.
        """
        if self.embedding_model:
            return self.embedding_model
        return None

    def resolve_embedding_dims(self) -> int:
        """Return explicit EMBEDDING_DIMS or 0 for auto-detect."""
        return self.embedding_dims

    def resolve_embedding_backend(self) -> str:
        """Resolve embedding backend: 'local', 'litellm', or ''.

        Auto-detect order:
        1. Explicit EMBEDDING_BACKEND setting
        2. 'litellm' if API keys are configured (cloud first)
        3. 'local' if qwen3-embed is available (built-in fallback)
        4. '' (no embedding, FTS5-only)
        """
        if self.embedding_backend:
            return self.embedding_backend

        # Auto-detect: prefer cloud if API keys available
        if self.api_keys:
            return "litellm"

        try:
            import qwen3_embed  # noqa: F401

            return "local"
        except ImportError:
            pass

        return ""


settings = Settings()
