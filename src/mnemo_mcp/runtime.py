"""Runtime bridge between mnemo-mcp and hull-core (de-host 2026-09).

One place wires the shared-core seams together:

- instance settings: ``~/.mnemo/config.toml`` (auth mode + bind + per-task
  provider cells), loaded via :func:`hull_core.config.settings.load_settings`
  with mnemo's config dir;
- identity: the request-scoped :class:`hull_core.auth.context.AuthContext`
  published by :class:`hull_core.auth.asgi.HullAuthMiddleware`;
- per-sub storage roots: each namespace gets its own
  ``~/.mnemo/subs/<namespace>/memories.db`` so mode-3 users on one process
  can never read each other's memories (spec §4 Q2). The host-root store
  ``~/.mnemo/memories.db`` serves the shared ``default`` namespace;
- provider clients: one :class:`hull_core.providers.openai_spec.
  OpenAICompatClient` per task cell (embed / rerank / chat / jev_score),
  built with the mode-derived SSRF policy (loopback self-hosted providers are
  a no-auth single-instance feature only).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from hull_core.auth.context import AuthContext, current_user
from hull_core.auth.middleware import Authenticator
from hull_core.auth.users import User, load_users
from hull_core.config.models import ModelCell, resolve_model_cells
from hull_core.config.settings import CONFIG_TEMPLATE, HullSettings, load_settings
from hull_core.providers.openai_spec import OpenAICompatClient

# Default storage width for sqlite-vec when EMBEDDING_DIMS is unset: the
# native width of the default [models.embed] cell (voyage-4-lite, 1024d,
# probed live 2026-09-26). Embeddings are requested at this width (MRL) and
# truncated to it, so a same-dim model swap keeps the vector space
# comparable -- MemoryDB's store_meta identity guard catches the rest.
DEFAULT_EMBEDDING_DIMS = 1024

# Namespace used by mode 1/2 (no-auth / shared token): one shared namespace.
DEFAULT_NAMESPACE = "default"

# Mode-3 namespaces become path segments under ~/.mnemo/subs/; keep them
# filesystem-safe so one user can never escape their own store.
_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def mnemo_config_dir() -> Path:
    """mnemo's instance-config + data root: ``~/.mnemo/``."""
    return Path.home() / ".mnemo"


def mnemo_config_path() -> Path:
    return mnemo_config_dir() / "config.toml"


@lru_cache(maxsize=4)
def _cached_settings(config_dir: Path, mtime: float) -> HullSettings:
    return load_settings(config_dir)


def hull_settings() -> HullSettings:
    """Load ``~/.mnemo/config.toml`` (cached per file mtime; tests can reset)."""
    config_dir = mnemo_config_dir()
    path = config_dir / "config.toml"
    return _cached_settings(
        config_dir, path.stat().st_mtime if path.is_file() else 0.0
    )


def reset_settings_cache() -> None:
    """Drop the cached instance settings (config edited, tests)."""
    _cached_settings.cache_clear()


def load_users_for(settings: HullSettings) -> dict[str, User] | None:
    """Load users.toml for multi mode; None otherwise."""
    if settings.server.auth != "multi":
        return None
    if settings.server.users_file is None:
        raise RuntimeError(
            "auth = 'multi' requires [server] users_file (default ~/.mnemo/users.toml)"
        )
    return load_users(settings.server.users_file)


def build_authenticator(
    settings: HullSettings | None = None,
    *,
    limiter: object | None = None,
) -> Authenticator:
    """Assemble the hull Authenticator from mnemo's instance config."""
    from hull_core.limits.limiter import SlidingWindowLimiter

    settings = settings if settings is not None else hull_settings()
    users = load_users_for(settings)
    return Authenticator(
        settings,
        users=users,
        limiter=limiter if limiter is not None else SlidingWindowLimiter(),
    )


def current_sub() -> str:
    """The authenticated caller's namespace (isolates every read/write)."""
    user = current_user()
    return user.namespace


def validate_namespace(namespace: str) -> str:
    """Reject namespaces that could escape ``~/.mnemo/subs/``."""
    if not _NAMESPACE_RE.match(namespace):
        raise ValueError(f"invalid namespace {namespace!r}")
    return namespace


def db_path_for_namespace(namespace: str | None = None) -> Path:
    """Per-namespace store path (spec §4 Q2).

    ``default`` -> ``~/.mnemo/memories.db`` (host root, shared namespace);
    anything else -> ``~/.mnemo/subs/<namespace>/memories.db`` (isolated).
    """
    ns = DEFAULT_NAMESPACE if namespace is None else namespace
    if ns == DEFAULT_NAMESPACE:
        return mnemo_config_dir() / "memories.db"
    validate_namespace(ns)
    return mnemo_config_dir() / "subs" / ns / "memories.db"


def model_cell(task: str, settings: HullSettings | None = None) -> ModelCell:
    """Resolve one per-task provider cell (embed/rerank/chat/jev_score)."""
    settings = settings if settings is not None else hull_settings()
    return resolve_model_cells(settings.models)[task]


def provider_client(
    task: str,
    settings: HullSettings | None = None,
    *,
    timeout: float = 60.0,
) -> OpenAICompatClient:
    """Build an OpenAI-spec client for one task cell (SSRF policy by mode)."""
    settings = settings if settings is not None else hull_settings()
    return OpenAICompatClient(
        model_cell(task, settings),
        auth_mode=settings.server.auth,
        timeout=timeout,
    )


def cell_configured(task: str, settings: HullSettings | None = None) -> bool:
    """True when the host configured a key for the task's cell."""
    return model_cell(task, settings).configured


def write_default_config(*, force: bool = False) -> Path:
    """Write mnemo's config template; refuse to clobber unless ``force``."""
    config_path = mnemo_config_path()
    if config_path.exists() and not force:
        raise FileExistsError(
            f"config already exists: {config_path} (use --force to overwrite)"
        )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return config_path


__all__ = [
    "CONFIG_TEMPLATE",
    "DEFAULT_EMBEDDING_DIMS",
    "DEFAULT_NAMESPACE",
    "AuthContext",
    "current_user",
    "mnemo_config_dir",
    "mnemo_config_path",
    "hull_settings",
    "reset_settings_cache",
    "load_users_for",
    "build_authenticator",
    "current_sub",
    "validate_namespace",
    "db_path_for_namespace",
    "model_cell",
    "provider_client",
    "cell_configured",
    "write_default_config",
]
