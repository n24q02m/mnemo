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


class _SyncModuleProxy(type(sys.modules[__name__])):
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


def get(name: str) -> SyncBackend:
    """Return the registered backend for ``name`` or raise ``KeyError``.

    Lazily registers the default ``GDriveBackend`` on first ``get("gdrive")``
    so importing the package does not immediately touch httpx / OAuth state.
    """
    if name == "gdrive" and "gdrive" not in _REGISTRY:
        _REGISTRY["gdrive"] = GDriveBackend()
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
