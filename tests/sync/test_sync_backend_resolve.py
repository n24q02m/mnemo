"""Tests for the XOR sync-backend resolver (2026-05-14 design).

Covers:
- :func:`resolve_active_backend` returns ``"s3"`` when ``SYNC_S3_BUCKET``
  env var is set.
- Returns ``"s3"`` when only the pydantic ``settings.sync_s3_bucket``
  field is populated (no env).
- Env var takes precedence over the pydantic field (operator override).
- Returns ``"gdrive"`` when neither env nor field is set (default,
  Method 1 local-relay).
- :func:`get` with ``name="auto"`` dispatches via the resolver.
- Empty / whitespace-only values are treated as unset.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from mnemo_mcp import sync as sync_pkg
from mnemo_mcp.sync import (
    GDriveBackend,
    resolve_active_backend,
)


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    sync_pkg.reset_registry()
    yield
    sync_pkg.reset_registry()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate deployment selection from the runner's environment."""
    monkeypatch.delenv("SYNC_S3_BUCKET", raising=False)
    monkeypatch.delenv("MEMORY_DB_BACKEND", raising=False)
    monkeypatch.setenv("SYNC_ENABLED", "true")

    from mnemo_mcp.config import settings

    monkeypatch.setattr(settings, "sync_enabled", True)
    monkeypatch.setattr(settings, "sync_s3_bucket", "")


# ---------------------------------------------------------------------------
# resolve_active_backend
# ---------------------------------------------------------------------------


def test_s3_env_returns_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNC_S3_BUCKET", "my-bucket")
    assert resolve_active_backend() == "s3"


def test_no_env_no_setting_returns_gdrive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default deployment (Method 1 local-relay / uvx) -> GDrive."""
    import mnemo_mcp.config as config_mod
    from mnemo_mcp.config import Settings

    # Fresh Settings with no S3 config.
    monkeypatch.setattr(config_mod, "settings", Settings(sync_s3_bucket=""))
    assert resolve_active_backend() == "gdrive"


def test_settings_field_alone_returns_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings-only (no env) still selects S3 — covers config.enc-persisted
    bucket case where the operator wrote SYNC_S3_BUCKET via the relay form
    before the XOR refactor."""
    import mnemo_mcp.config as config_mod
    from mnemo_mcp.config import Settings

    persisted = Settings(sync_s3_bucket="persisted-bucket")
    monkeypatch.setattr(config_mod, "settings", persisted)
    monkeypatch.setattr("mnemo_mcp.sync.gdrive.settings", persisted)
    assert resolve_active_backend() == "s3"


def test_env_priority_over_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env var wins even when settings.sync_s3_bucket is empty — and the
    inverse: env=set still wins over a non-empty settings (idempotent S3)."""
    import mnemo_mcp.config as config_mod
    from mnemo_mcp.config import Settings

    monkeypatch.setattr(config_mod, "settings", Settings(sync_s3_bucket=""))
    monkeypatch.setenv("SYNC_S3_BUCKET", "env-bucket")
    assert resolve_active_backend() == "s3"

    # Both set — still s3, env value takes precedence semantically (the
    # function only needs to return "s3"; downstream s3 backend wiring
    # reads the env value via S3Backend init).
    monkeypatch.setattr(
        config_mod, "settings", Settings(sync_s3_bucket="settings-bucket")
    )
    assert resolve_active_backend() == "s3"


def test_whitespace_env_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operators sometimes set SYNC_S3_BUCKET=" " by mistake; treat as unset."""
    import mnemo_mcp.config as config_mod
    from mnemo_mcp.config import Settings

    monkeypatch.setattr(config_mod, "settings", Settings(sync_s3_bucket=""))
    monkeypatch.setenv("SYNC_S3_BUCKET", "   ")
    assert resolve_active_backend() == "gdrive"


def test_whitespace_settings_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    import mnemo_mcp.config as config_mod
    from mnemo_mcp.config import Settings

    monkeypatch.setattr(config_mod, "settings", Settings(sync_s3_bucket="   "))
    assert resolve_active_backend() == "gdrive"


# ---------------------------------------------------------------------------
# get("auto") dispatch
# ---------------------------------------------------------------------------


def test_get_auto_dispatches_to_gdrive(monkeypatch: pytest.MonkeyPatch) -> None:
    import mnemo_mcp.config as config_mod
    from mnemo_mcp.config import Settings

    monkeypatch.setattr(config_mod, "settings", Settings(sync_s3_bucket=""))
    backend = sync_pkg.get("auto")
    assert isinstance(backend, GDriveBackend)


def test_get_auto_dispatches_to_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    import mnemo_mcp.config as config_mod
    from mnemo_mcp.config import Settings

    monkeypatch.setattr(
        config_mod,
        "settings",
        Settings(
            sync_s3_bucket="auto-bucket",
            sync_s3_region="us-east-1",
            sync_s3_access_key_id="t",
            sync_s3_secret_access_key="t",
        ),
    )
    monkeypatch.setenv("SYNC_S3_BUCKET", "auto-bucket")
    backend = sync_pkg.get("auto")
    # S3Backend has name="s3" attribute per the base contract.
    assert backend.name == "s3"


async def test_cf_d1_suppresses_google_setup_sync_and_scheduling(monkeypatch):
    from mnemo_mcp import credential_state, relay_setup, setup_tool
    from mnemo_mcp.config import settings
    from mnemo_mcp.server import (
        _handle_config_import_passport,
        _handle_config_sync_now,
    )

    monkeypatch.setenv("MEMORY_DB_BACKEND", " CF-D1 ")
    monkeypatch.setenv("SYNC_S3_BUCKET", "stale-bucket")
    monkeypatch.setattr(settings, "google_drive_client_id", "fixture-client")
    monkeypatch.setattr(settings, "google_drive_client_secret", "fixture-secret")

    def forbidden(*args, **kwargs):
        pytest.fail("A disabled sync path touched Google or scheduled background work")

    monkeypatch.setattr("httpx.post", forbidden)
    monkeypatch.setattr(sync_pkg.asyncio, "create_task", forbidden)
    assert resolve_active_backend() == "disabled"
    assert credential_state._trigger_gdrive_flow(sub="fixture-sub") is None
    assert await relay_setup._setup_gdrive_sync("https://relay.example", "fixture")
    assert await sync_pkg.setup_google_auth() is False
    assert (await setup_tool.run_setup_sync())["status"] == "disabled"
    assert (await sync_pkg.sync_full(None))["status"] == "disabled"
    sync_pkg.start_auto_sync(None)
    assert sync_pkg.start_passport_scheduler(None) is False
    assert (await _handle_config_sync_now(None, "gdrive"))["status"] == "disabled"
    assert (await _handle_config_import_passport(None, "gdrive"))[
        "status"
    ] == "disabled"
    for backend in ("auto", "gdrive", "s3"):
        with pytest.raises(KeyError):
            sync_pkg.get(backend)


async def test_non_cf_google_setup_remains_available(monkeypatch):
    from mnemo_mcp import credential_state, relay_setup
    from mnemo_mcp.config import settings

    monkeypatch.setenv("MEMORY_DB_BACKEND", "sqlite")
    monkeypatch.setattr(settings, "google_drive_client_id", "fixture-client")
    monkeypatch.setattr(settings, "google_drive_client_secret", "fixture-secret")
    requests = []

    def reject_device_code(url, **kwargs):
        from types import SimpleNamespace

        requests.append(url)
        return SimpleNamespace(status_code=400)

    async def reject_async_device_code(client_id):
        requests.append("async-device-code")
        return None

    monkeypatch.setattr("httpx.post", reject_device_code)
    monkeypatch.setattr(sync_pkg, "_request_device_code", reject_async_device_code)
    assert resolve_active_backend() == "gdrive"
    assert credential_state._trigger_gdrive_flow() is None
    assert (
        await relay_setup._setup_gdrive_sync("https://relay.example", "fixture")
        is False
    )
    assert requests == [
        "https://oauth2.googleapis.com/device/code",
        "async-device-code",
    ]


def test_disabled_sync_blocks_explicit_backend_and_scheduler(monkeypatch):
    from mnemo_mcp.config import settings

    monkeypatch.setenv("SYNC_S3_BUCKET", "configured-bucket")
    monkeypatch.setattr(settings, "sync_enabled", False)
    assert resolve_active_backend() == "disabled"
    with pytest.raises(KeyError):
        sync_pkg.get("s3")
    assert sync_pkg.start_passport_scheduler(None) is False
