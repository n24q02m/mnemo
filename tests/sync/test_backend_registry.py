"""Tests for the Phase 2 sync backend registry.

Covers:
- :func:`register` accepts SyncBackend instances and rejects non-subclasses.
- :func:`get` returns the registered backend or raises KeyError with a
  helpful message listing the registered names.
- :func:`get("gdrive")` lazily registers :class:`GDriveBackend` on first call.
- :class:`GDriveBackend` is a :class:`SyncBackend` subclass and exposes
  the four-method contract.
- :func:`reset_registry` clears state (test helper).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import pytest

from mnemo_mcp import sync as sync_pkg
from mnemo_mcp.sync import (
    GDriveBackend,
    SyncBackend,
    get,
    list_backends,
    register,
    reset_registry,
)


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    reset_registry()
    yield
    reset_registry()


class _Mock(SyncBackend):
    name = "mock"

    async def push(self, bundle: bytes, sequence: int) -> None:
        return None

    async def pull(self, sequence: int | None = None) -> bytes | None:
        return b"mock-bundle"

    async def last_remote_sequence(self) -> int:
        return 0

    async def health_check(self) -> bool:
        return True


def test_register_accepts_sync_backend_instance() -> None:
    backend = _Mock()
    register("mock", backend)
    assert get("mock") is backend


def test_register_rejects_non_sync_backend() -> None:
    with pytest.raises(TypeError, match="SyncBackend instance"):
        register("bad", cast(SyncBackend, "not-a-backend"))


def test_get_unknown_backend_raises_keyerror_listing_names() -> None:
    register("mock", _Mock())
    with pytest.raises(KeyError) as exc:
        get("does-not-exist")
    assert "does-not-exist" in str(exc.value)
    assert "mock" in str(exc.value)


def test_get_gdrive_lazy_registers() -> None:
    assert "gdrive" not in list_backends()
    backend = get("gdrive")
    assert isinstance(backend, GDriveBackend)
    assert "gdrive" in list_backends()
    # Second call returns the same instance.
    assert get("gdrive") is backend


def test_gdrive_backend_subclasses_sync_backend() -> None:
    assert issubclass(GDriveBackend, SyncBackend)
    inst = GDriveBackend()
    # Four contract methods are present and async-callable signatures.
    assert callable(inst.push)
    assert callable(inst.pull)
    assert callable(inst.last_remote_sequence)
    assert callable(inst.health_check)


def test_list_backends_returns_sorted_names() -> None:
    register("zeta", _Mock())
    register("alpha", _Mock())
    assert list_backends() == ["alpha", "zeta"]


def test_legacy_function_imports_still_work() -> None:
    """Phase 1 callers do ``from mnemo_mcp.sync import sync_full`` etc.

    Confirm those names remain importable AND callable post-refactor.
    """
    from mnemo_mcp.sync import (  # noqa: F401 - import is the test
        setup_google_auth,
        start_auto_sync,
        stop_auto_sync,
        sync_full,
        sync_pull,
        sync_push,
    )

    assert callable(sync_full)
    assert callable(setup_google_auth)


def test_sync_module_setattr_propagates_to_gdrive(monkeypatch) -> None:
    """``patch("mnemo_mcp.sync._refresh_token", mock)`` MUST also be the
    name resolved inside ``gdrive.py`` so the production code call hits the
    mock instead of the original function.
    """
    from mnemo_mcp.sync import gdrive

    sentinel = object()
    monkeypatch.setattr("mnemo_mcp.sync._refresh_token", sentinel)
    assert gdrive._refresh_token is sentinel

    # Cleanup is automatic via monkeypatch.
    assert sync_pkg._refresh_token is sentinel
