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
    """Ensure SYNC_S3_BUCKET is unset at the start of every test."""
    monkeypatch.delenv("SYNC_S3_BUCKET", raising=False)


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

    monkeypatch.setattr(
        config_mod, "settings", Settings(sync_s3_bucket="persisted-bucket")
    )
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
