"""Tests for the Phase 2 passport sync scheduler (XOR backend selection).

Covers:
- ``start_passport_scheduler`` returns False when interval <= 0.
- Returns False when already running (no double-spawn).
- Returns True when spawning + ``stop_passport_scheduler`` cancels cleanly.
- Loop calls sync_now with the SINGLE active backend resolved via
  :func:`resolve_active_backend` (S3 when SYNC_S3_BUCKET set, else GDrive).
- Loop swallows per-backend exceptions and continues.
- Loop exits cleanly on cancellation via stop helper.

XOR semantics (2026-05-14 Test B design): the legacy comma-separated
multi-backend mirror was dropped — operator picks ONE deployment mode.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mnemo_mcp import sync as sync_pkg
from mnemo_mcp.db import MemoryDB


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    sync_pkg.reset_registry()
    sync_pkg.stop_passport_scheduler()
    yield
    sync_pkg.stop_passport_scheduler()
    sync_pkg.reset_registry()


@pytest.fixture
def isolated_db(tmp_path: Path) -> Iterator[MemoryDB]:
    db = MemoryDB(tmp_path / "memories.db", embedding_dims=0)
    yield db
    db.close()


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------


async def test_start_returns_false_when_interval_zero(
    isolated_db: MemoryDB,
) -> None:
    assert sync_pkg.start_passport_scheduler(isolated_db, interval=0) is False


async def test_start_returns_false_when_interval_negative(
    isolated_db: MemoryDB,
) -> None:
    assert sync_pkg.start_passport_scheduler(isolated_db, interval=-5) is False


async def test_start_returns_true_then_stop(isolated_db: MemoryDB) -> None:
    spawned = sync_pkg.start_passport_scheduler(isolated_db, interval=60)
    assert spawned is True

    # Second call must NOT spawn a new task.
    spawned_again = sync_pkg.start_passport_scheduler(isolated_db, interval=60)
    assert spawned_again is False

    sync_pkg.stop_passport_scheduler()
    # Yield once so the cancellation propagates before the test exits.
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Loop behaviour
# ---------------------------------------------------------------------------


async def test_loop_calls_sync_now_with_s3_when_bucket_set(
    isolated_db: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SYNC_S3_BUCKET set -> resolve_active_backend() == 's3' -> sync_now('s3')."""
    monkeypatch.setenv("SYNC_PASSPHRASE", "test-pass")
    monkeypatch.setenv("SYNC_S3_BUCKET", "test-bucket")

    import mnemo_mcp.config as config_mod
    from mnemo_mcp.config import Settings

    monkeypatch.setattr(
        config_mod,
        "settings",
        Settings(sync_s3_bucket="test-bucket", sync_interval=1),
    )

    fake_sync = AsyncMock(return_value={"mode": "delta", "cursor": 1})
    with patch("mnemo_mcp.sync.delta.sync_now", side_effect=fake_sync):
        # Patch sleep so the first loop tick fires immediately.
        original_sleep = asyncio.sleep

        async def _fast_sleep(_t: float) -> None:
            await original_sleep(0)

        with patch("mnemo_mcp.sync.asyncio.sleep", side_effect=_fast_sleep):
            spawned = sync_pkg.start_passport_scheduler(isolated_db, interval=1)
            assert spawned is True
            # Let the loop run a few ticks.
            await original_sleep(0.05)
            sync_pkg.stop_passport_scheduler()
            # Yield so cancellation lands.
            await original_sleep(0)

    backends_called = {call.args[1] for call in fake_sync.call_args_list}
    # XOR: only s3 is exercised; gdrive is NOT called when SYNC_S3_BUCKET is set.
    assert backends_called == {"s3"}


async def test_loop_calls_sync_now_with_gdrive_by_default(
    isolated_db: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No SYNC_S3_BUCKET -> resolve_active_backend() == 'gdrive' -> sync_now('gdrive')."""
    monkeypatch.setenv("SYNC_PASSPHRASE", "test-pass")
    monkeypatch.delenv("SYNC_S3_BUCKET", raising=False)

    import mnemo_mcp.config as config_mod
    from mnemo_mcp.config import Settings

    monkeypatch.setattr(
        config_mod, "settings", Settings(sync_s3_bucket="", sync_interval=1)
    )

    fake_sync = AsyncMock(return_value={"mode": "delta", "cursor": 1})
    with patch("mnemo_mcp.sync.delta.sync_now", side_effect=fake_sync):
        original_sleep = asyncio.sleep

        async def _fast_sleep(_t: float) -> None:
            await original_sleep(0)

        with patch("mnemo_mcp.sync.asyncio.sleep", side_effect=_fast_sleep):
            spawned = sync_pkg.start_passport_scheduler(isolated_db, interval=1)
            assert spawned is True
            await original_sleep(0.05)
            sync_pkg.stop_passport_scheduler()
            await original_sleep(0)

    backends_called = {call.args[1] for call in fake_sync.call_args_list}
    assert backends_called == {"gdrive"}


async def test_loop_swallows_per_backend_errors(
    isolated_db: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNC_PASSPHRASE", "test-pass")
    monkeypatch.setenv("SYNC_S3_BUCKET", "test-bucket")

    import mnemo_mcp.config as config_mod
    from mnemo_mcp.config import Settings

    monkeypatch.setattr(
        config_mod,
        "settings",
        Settings(sync_s3_bucket="test-bucket", sync_interval=1),
    )

    fake_sync = AsyncMock(side_effect=RuntimeError("backend offline"))
    with patch("mnemo_mcp.sync.delta.sync_now", side_effect=fake_sync):
        original_sleep = asyncio.sleep

        async def _fast_sleep(_t: float) -> None:
            await original_sleep(0)

        with patch("mnemo_mcp.sync.asyncio.sleep", side_effect=_fast_sleep):
            spawned = sync_pkg.start_passport_scheduler(isolated_db, interval=1)
            assert spawned is True
            await original_sleep(0.05)
            sync_pkg.stop_passport_scheduler()
            await original_sleep(0)

    # The error did not kill the loop -- sync_now was attempted.
    assert fake_sync.call_count >= 1


async def test_loop_skips_when_no_passphrase(
    isolated_db: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No SYNC_PASSPHRASE -> tick logs + skips, sync_now never invoked."""
    monkeypatch.delenv("SYNC_PASSPHRASE", raising=False)
    monkeypatch.setenv("SYNC_S3_BUCKET", "test-bucket")

    import mnemo_mcp.config as config_mod
    from mnemo_mcp.config import Settings

    monkeypatch.setattr(
        config_mod,
        "settings",
        Settings(sync_s3_bucket="test-bucket", sync_interval=1),
    )

    fake_sync = AsyncMock()
    with patch("mnemo_mcp.sync.delta.sync_now", side_effect=fake_sync):
        original_sleep = asyncio.sleep

        async def _fast_sleep(_t: float) -> None:
            await original_sleep(0)

        with patch("mnemo_mcp.sync.asyncio.sleep", side_effect=_fast_sleep):
            spawned = sync_pkg.start_passport_scheduler(isolated_db, interval=1)
            assert spawned is True
            await original_sleep(0.05)
            sync_pkg.stop_passport_scheduler()
            await original_sleep(0)

    fake_sync.assert_not_called()


# ---------------------------------------------------------------------------
# Skill file existence (passport-bootstrap)
# ---------------------------------------------------------------------------


def test_passport_bootstrap_skill_file_exists() -> None:
    skill_path = (
        Path(__file__).resolve().parent.parent.parent
        / "skills"
        / "passport-bootstrap"
        / "SKILL.md"
    )
    assert skill_path.exists(), f"missing {skill_path}"
    text = skill_path.read_text(encoding="utf-8")
    assert "name: passport-bootstrap" in text
    # Skill must reference the import_passport action.
    assert "import_passport" in text
