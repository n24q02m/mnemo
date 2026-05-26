"""Backend-pluggable sync package (Phase 2 refactor).

This package replaces the single-file ``sync.py`` from Phase 1. It still
exports every public + private symbol the existing call sites + tests
import (so ``from mnemo_mcp.sync import sync_full`` and
``patch("mnemo_mcp.sync._refresh_token", ...)`` keep working) while also
exposing a backend registry so the Phase 2 passport sync orchestrator can
choose between Google Drive and S3 (and any future backend) uniformly.

Layout:

* :mod:`mnemo_mcp.sync.base` - :class:`SyncBackend` abstract contract.
* :mod:`mnemo_mcp.sync.gdrive` - legacy DB-file sync helpers + new
  :class:`GDriveBackend` adapter for opaque-bundle passport sync.
* :mod:`mnemo_mcp.sync.s3` - new S3 / R2 / B2 / MinIO backend (Task 5).
* :mod:`mnemo_mcp.sync.bundle` - AES-256-GCM + Argon2id bundle codec (Task 6).
* :mod:`mnemo_mcp.sync.delta` - delta-sync orchestrator with LWW conflict
  resolution (Task 8).

To preserve the Phase 1 monkeypatching pattern (``patch("mnemo_mcp.sync.X")``)
this ``__init__`` mirrors the gdrive submodule's ``__dict__`` into its own
namespace AND wires the gdrive module's globals so a patch on either
namespace propagates to the actual call site. Tests written against the
single-file ``sync.py`` continue to pass without modification.
"""

from __future__ import annotations

import sys
import types

from mnemo_mcp.sync import gdrive as _gdrive_module
from mnemo_mcp.sync.base import SyncBackend
from mnemo_mcp.sync.gdrive import GDriveBackend

# Mirror every public + private name exported by gdrive.py into this
# package's namespace. Tests that do ``patch("mnemo_mcp.sync._refresh_token",
# mock)`` set the attribute here; the production code inside gdrive.py looks
# up names in its OWN globals, so we additionally proxy attribute mutations
# from this module into the gdrive module via __setattr__ at the module
# class level (see _SyncModuleProxy below).

_DELEGATE_NAMES = [name for name in dir(_gdrive_module) if not name.startswith("__")]

#: Names representing mutable module-level state inside gdrive.py. We do
#: NOT copy these into the package globals so a fresh ``getattr`` always
#: lands on the live gdrive value (via ``_SyncModuleProxy.__getattr__``).
#: Other names (functions, classes) ARE copied so ``from mnemo_mcp.sync
#: import sync_full`` keeps yielding the actual function object instead of
#: triggering descriptor lookup on every import.
_LIVE_PROXY_NAMES = {"_sync_task", "_folder_id_cache"}

for _name in _DELEGATE_NAMES:
    if _name in _LIVE_PROXY_NAMES:
        continue
    globals()[_name] = getattr(_gdrive_module, _name)


class _SyncModuleProxy(types.ModuleType):
    """Module subclass that mirrors writes -> gdrive AND reads <- gdrive.

    Tests do ``patch("mnemo_mcp.sync._foo", mock)`` which calls
    ``sys.modules["mnemo_mcp.sync"].__setattr__("_foo", mock)``. The patched
    attribute MUST also become visible inside ``gdrive.py``'s globals so the
    function calls there resolve to the mock. Conversely, tests assert
    ``mnemo_mcp.sync._sync_task == ...`` AFTER ``start_auto_sync`` mutated
    the gdrive global; we mirror reads back so the assertion sees the live
    gdrive value.
    """

    def __setattr__(self, name: str, value: object) -> None:
        if name in _LIVE_PROXY_NAMES:
            # Live state -> only mutate gdrive globals so subsequent
            # ``getattr`` falls through to the live value via __getattr__.
            setattr(_gdrive_module, name, value)
            return
        super().__setattr__(name, value)
        if name in _DELEGATE_NAMES:
            setattr(_gdrive_module, name, value)

    def __getattr__(self, name: str) -> object:
        if name in _DELEGATE_NAMES or hasattr(_gdrive_module, name):
            return getattr(_gdrive_module, name)
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


sys.modules[__name__].__class__ = _SyncModuleProxy


# ---------------------------------------------------------------------------
# Backend registry (Phase 2 NEW)
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, SyncBackend] = {}


def register(name: str, backend: SyncBackend) -> None:
    """Register ``backend`` under ``name`` so :func:`get` can resolve it."""
    if not isinstance(backend, SyncBackend):
        raise TypeError(
            f"register: expected SyncBackend instance, got {type(backend).__name__}"
        )
    _REGISTRY[name] = backend


def resolve_active_backend() -> str:
    """Return the active sync backend (``"s3"`` or ``"gdrive"``) per deployment.

    XOR selection per the 2026-05-14 Test B clarification:

    * **S3** when ``SYNC_S3_BUCKET`` is set via env var OR via the pydantic
      ``settings.sync_s3_bucket`` field. Indicates Method 2/3 (HTTP / Docker
      deploy) where the operator wires S3 credentials at container spawn.
    * **GDrive** otherwise. Indicates Method 1 (local-relay / uvx) where
      end-users authorise their Google account via the relay form.

    Pure function — no side effects, safe to call from lifespan startup,
    scheduler loop, MCP tool handlers, anywhere. The env var takes
    precedence over the pydantic field so an operator can override a
    persisted setting without rewriting ``config.enc``.
    """
    import os as _os

    if _os.environ.get("SYNC_S3_BUCKET", "").strip():
        return "s3"
    try:
        from mnemo_mcp.config import settings as _settings

        if (_settings.sync_s3_bucket or "").strip():
            return "s3"
    except Exception:
        # Settings import / instantiation failure is non-fatal — fall
        # through to the gdrive default so the server still starts.
        pass
    return "gdrive"


def get(name: str) -> SyncBackend:
    """Return the registered backend for ``name`` or raise ``KeyError``.

    Lazily registers default backends on first lookup so importing the
    package does not immediately touch httpx / boto3 / OAuth state:

    * ``"auto"`` -> dispatches via :func:`resolve_active_backend` (XOR
      between S3 and GDrive per deployment env). Use this from generic
      callers that should respect the deployment mode without hardcoding.
    * ``"gdrive"`` -> :class:`GDriveBackend` (uses Phase 1 OAuth token).
    * ``"s3"`` -> :class:`S3Backend` configured from ``settings.sync_s3_*``.
      Raises ``KeyError`` if ``SYNC_S3_BUCKET`` is unset (so the caller
      sees a helpful "configure SYNC_S3_BUCKET" message instead of a
      cryptic boto3 NoCredentialsError later).
    """
    if name == "auto":
        name = resolve_active_backend()
    if name == "gdrive" and "gdrive" not in _REGISTRY:
        _REGISTRY["gdrive"] = GDriveBackend()
    if name == "s3" and "s3" not in _REGISTRY:
        from mnemo_mcp.config import settings
        from mnemo_mcp.sync.s3 import S3Backend

        if not settings.sync_s3_bucket:
            raise KeyError(
                "Cannot get('s3'): SYNC_S3_BUCKET is empty. Set the bucket "
                "name (and SYNC_S3_REGION / SYNC_S3_ENDPOINT for R2 / B2 / "
                "MinIO) before requesting the S3 backend."
            )
        _REGISTRY["s3"] = S3Backend(
            bucket=settings.sync_s3_bucket,
            region=settings.sync_s3_region or "us-east-1",
            access_key_id=settings.sync_s3_access_key_id or None,
            secret_access_key=settings.sync_s3_secret_access_key or None,
            endpoint_url=settings.sync_s3_endpoint or None,
            prefix=settings.sync_s3_prefix or "passport/",
        )
    if name not in _REGISTRY:
        raise KeyError(
            f"Unknown sync backend {name!r}; "
            f"registered backends: {sorted(_REGISTRY.keys())}"
        )
    return _REGISTRY[name]


def list_backends() -> list[str]:
    """Return the list of registered backend names sorted alphabetically."""
    return sorted(_REGISTRY.keys())


def reset_registry() -> None:
    """Clear the registry (test helper - do not call in production)."""
    _REGISTRY.clear()


# ---------------------------------------------------------------------------
# Phase 2 passport-sync scheduler (lock-protected, runs sync_now per backend)
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402

_PASSPORT_SYNC_LOCK = asyncio.Lock()
_PASSPORT_SYNC_TASK: asyncio.Task | None = None


async def _passport_sync_loop(db, interval: int) -> None:
    """Background loop calling sync_now for the SINGLE active backend.

    Runs every ``interval`` seconds. Exits cleanly on cancellation.
    Errors are logged and swallowed so a transient backend failure does
    not kill the loop.

    Backend selection per :func:`resolve_active_backend` — XOR between
    S3 (when ``SYNC_S3_BUCKET`` is set, Method 2/3 docker deploy) and
    GDrive (otherwise, Method 1 local-relay). The legacy comma-separated
    multi-backend mirror semantics were dropped per the 2026-05-14 Test B
    design clarification: operator picks ONE deployment mode.
    """
    from loguru import logger

    from mnemo_mcp.config import settings as _settings
    from mnemo_mcp.sync.delta import sync_now

    logger.info(f"Passport sync scheduler started (interval={interval}s)")
    while True:
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("Passport sync scheduler stopped")
            return

        passphrase = (_settings.sync_passphrase or "").strip()
        import os as _os

        env_pass = _os.environ.get("SYNC_PASSPHRASE", "").strip()
        if env_pass:
            passphrase = env_pass
        if not passphrase:
            logger.debug("scheduler tick skipped: SYNC_PASSPHRASE not set")
            continue

        backend_name = resolve_active_backend()

        async with _PASSPORT_SYNC_LOCK:
            try:
                await sync_now(db, backend_name, passphrase)
                logger.debug(f"scheduler tick ok backend={backend_name}")
            except Exception as e:
                logger.warning(f"scheduler tick failed backend={backend_name} err={e}")


def start_passport_scheduler(db, interval: int | None = None) -> bool:
    """Start the background passport sync loop.

    Returns True if a task was spawned, False when the loop is disabled
    (interval <= 0) or already running.
    """
    global _PASSPORT_SYNC_TASK
    from mnemo_mcp.config import settings as _settings

    if interval is None:
        interval = int(_settings.sync_interval or 0)
    if interval <= 0:
        return False
    if _PASSPORT_SYNC_TASK is not None and not _PASSPORT_SYNC_TASK.done():
        return False

    try:
        _PASSPORT_SYNC_TASK = asyncio.create_task(_passport_sync_loop(db, interval))
        return True
    except RuntimeError:
        return False


def stop_passport_scheduler() -> None:
    """Cancel the background passport sync loop if running."""
    global _PASSPORT_SYNC_TASK
    if _PASSPORT_SYNC_TASK is not None and not _PASSPORT_SYNC_TASK.done():
        _PASSPORT_SYNC_TASK.cancel()
    _PASSPORT_SYNC_TASK = None
