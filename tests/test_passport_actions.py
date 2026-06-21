"""Tests for the Phase 2 passport sync MCP actions + memory(action='compress').

Covers:
- ``config(action='sync_now')`` returns error when SYNC_PASSPHRASE missing.
- ``config(action='sync_now', backend='s3')`` runs delta push end-to-end.
- ``config(action='export_passport')`` writes a `.mnemo` file at the data
  directory.
- ``config(action='import_passport', from='s3')`` errors when no bundle
  exists; restores rows when bundle present.
- ``memory(action='compress', memory_id=...)`` rewrites stored content +
  flips compressed flag when LLM available.
- ``compress`` action no-ops when memory already compressed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from mnemo_mcp import sync as sync_pkg
from mnemo_mcp.db import MemoryDB
from mnemo_mcp.server import (
    _handle_config_export_passport,
    _handle_config_import_passport,
    _handle_config_sync_now,
    _handle_memory_compress,
)
from mnemo_mcp.sync.s3 import S3Backend

_BUCKET = "mnemo-test-passport-actions"


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    sync_pkg.reset_registry()
    yield
    sync_pkg.reset_registry()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "SYNC_PASSPHRASE",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
        "COMPRESSION_ENABLED",
        "COMPRESSION_PROVIDER",
        "COMPRESSION_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[MemoryDB]:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "memories.db"))
    db = MemoryDB(tmp_path / "memories.db", embedding_dims=0)
    yield db
    db.close()


def _make_ctx(db: MemoryDB) -> MagicMock:
    """Build a stub ``ctx`` matching ``_get_ctx`` extraction shape."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "db": db,
        "embedding_model": None,
        "embedding_dims": 0,
    }
    return ctx


# ---------------------------------------------------------------------------
# config(action='sync_now')
# ---------------------------------------------------------------------------


async def test_sync_now_returns_error_without_passphrase(
    isolated_db: MemoryDB,
) -> None:
    ctx = _make_ctx(isolated_db)
    raw = await _handle_config_sync_now(ctx, backend="s3")
    payload = json.loads(raw)
    assert "error" in payload
    assert "SYNC_PASSPHRASE" in payload["error"]


async def test_sync_now_delta_push_end_to_end(
    isolated_db: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNC_PASSPHRASE", "test-pass")
    isolated_db._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('a', 'hi', '2026-05-01', '2026-05-01', '2026-05-01')"
    )
    isolated_db._conn.commit()

    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=_BUCKET)
        backend = S3Backend(
            bucket=_BUCKET,
            region="us-east-1",
            access_key_id="t",
            secret_access_key="t",
        )
        sync_pkg.register("s3", backend)

        ctx = _make_ctx(isolated_db)
        raw = await _handle_config_sync_now(ctx, backend="s3")
        payload = json.loads(raw)

    assert payload["backend"] == "s3"
    assert payload["mode"] == "delta"
    assert payload["cursor"] == 1
    assert payload["rows"] == 1


async def test_sync_now_unknown_backend(
    isolated_db: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNC_PASSPHRASE", "test-pass")
    ctx = _make_ctx(isolated_db)
    raw = await _handle_config_sync_now(ctx, backend="nonexistent")
    payload = json.loads(raw)
    assert "error" in payload
    assert "nonexistent" in payload["error"]


# ---------------------------------------------------------------------------
# config(action='export_passport')
# ---------------------------------------------------------------------------


async def test_export_passport_writes_file(
    isolated_db: MemoryDB, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SYNC_PASSPHRASE", "test-pass")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "memories.db"))
    # Reload settings so DB_PATH override takes effect for export dir.
    import mnemo_mcp.config as config_mod
    from mnemo_mcp.config import Settings

    monkeypatch.setattr(config_mod, "settings", Settings())

    isolated_db._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('a', 'hi', '2026-05-01', '2026-05-01', '2026-05-01')"
    )
    isolated_db._conn.commit()

    ctx = _make_ctx(isolated_db)
    raw = await _handle_config_export_passport(ctx)
    payload = json.loads(raw)

    assert payload["status"] == "exported"
    assert payload["size"] > 0
    assert Path(payload["path"]).exists()
    assert Path(payload["path"]).name.startswith("passport-")
    assert Path(payload["path"]).suffix == ".mnemo"


async def test_export_passport_requires_passphrase(
    isolated_db: MemoryDB,
) -> None:
    ctx = _make_ctx(isolated_db)
    raw = await _handle_config_export_passport(ctx)
    payload = json.loads(raw)
    assert "error" in payload
    assert "SYNC_PASSPHRASE" in payload["error"]


# ---------------------------------------------------------------------------
# config(action='import_passport')
# ---------------------------------------------------------------------------


async def test_import_passport_requires_passphrase(
    isolated_db: MemoryDB,
) -> None:
    ctx = _make_ctx(isolated_db)
    raw = await _handle_config_import_passport(ctx, source="s3")
    payload = json.loads(raw)
    assert "error" in payload
    assert "SYNC_PASSPHRASE" in payload["error"]


async def test_import_passport_no_bundle_returns_status(
    isolated_db: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNC_PASSPHRASE", "test-pass")

    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=_BUCKET)
        backend = S3Backend(
            bucket=_BUCKET,
            region="us-east-1",
            access_key_id="t",
            secret_access_key="t",
        )
        sync_pkg.register("s3", backend)

        ctx = _make_ctx(isolated_db)
        raw = await _handle_config_import_passport(ctx, source="s3")
        payload = json.loads(raw)

    assert payload["status"] == "no_passport"
    assert payload["backend"] == "s3"


async def test_import_passport_round_trip(
    isolated_db: MemoryDB,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Push from a remote source DB then import back into local DB."""
    monkeypatch.setenv("SYNC_PASSPHRASE", "test-pass")

    other = MemoryDB(tmp_path / "other.db", embedding_dims=0)
    other._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('remote', 'from-other', '2026-05-02', '2026-05-02', '2026-05-02')"
    )
    other._conn.commit()

    from mnemo_mcp.sync.delta import build_full_bundle

    bundle = await build_full_bundle(other, passphrase="test-pass")
    other.close()

    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=_BUCKET)
        backend = S3Backend(
            bucket=_BUCKET,
            region="us-east-1",
            access_key_id="t",
            secret_access_key="t",
        )
        await backend.push(bundle, sequence=1)
        sync_pkg.register("s3", backend)

        ctx = _make_ctx(isolated_db)
        raw = await _handle_config_import_passport(ctx, source="s3")
        payload = json.loads(raw)

    assert payload["status"] == "imported"
    assert payload["inserted"] == 1
    rows = isolated_db._conn.execute(
        "SELECT content FROM memories WHERE id = 'remote'"
    ).fetchone()
    assert rows["content"] == "from-other"


# ---------------------------------------------------------------------------
# memory(action='compress')
# ---------------------------------------------------------------------------


async def test_memory_compress_rewrites_existing_row(
    isolated_db: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    isolated_db._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('a', 'long verbose original', '2026-05-01', '2026-05-01', '2026-05-01')"
    )
    isolated_db._conn.commit()

    async def _fake_call(prompt, *, models, temperature, max_tokens):
        return "tight summary"

    ctx = _make_ctx(isolated_db)
    with patch("mnemo_mcp.compression.call_llm", side_effect=_fake_call):
        raw = await _handle_memory_compress(ctx, memory_id="a")

    payload = json.loads(raw)
    assert payload["status"] == "compressed"
    assert payload["compression_provider"] == "gemini"

    row = isolated_db._conn.execute(
        "SELECT content, text_raw, compressed, compression_provider FROM memories "
        "WHERE id = 'a'"
    ).fetchone()
    assert row["content"] == "tight summary"
    assert row["text_raw"] == "long verbose original"
    assert row["compressed"] == 1
    assert row["compression_provider"] == "gemini"


async def test_memory_compress_no_provider_returns_skipped(
    isolated_db: MemoryDB,
) -> None:
    isolated_db._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('a', 'content', '2026-05-01', '2026-05-01', '2026-05-01')"
    )
    isolated_db._conn.commit()

    ctx = _make_ctx(isolated_db)
    raw = await _handle_memory_compress(ctx, memory_id="a")
    payload = json.loads(raw)
    assert payload["status"] == "skipped"


async def test_memory_compress_already_compressed_noops(
    isolated_db: MemoryDB,
) -> None:
    isolated_db._conn.execute(
        "INSERT INTO memories (id, content, text_raw, compressed, compression_provider, "
        "created_at, updated_at, last_accessed) "
        "VALUES ('a', 'short', 'long original', 1, 'gemini', "
        "'2026-05-01', '2026-05-01', '2026-05-01')"
    )
    isolated_db._conn.commit()

    ctx = _make_ctx(isolated_db)
    raw = await _handle_memory_compress(ctx, memory_id="a")
    payload = json.loads(raw)
    assert payload["status"] == "already_compressed"
    assert payload["compression_provider"] == "gemini"


async def test_memory_compress_missing_id_errors(isolated_db: MemoryDB) -> None:
    ctx = _make_ctx(isolated_db)
    raw = await _handle_memory_compress(ctx, memory_id=None)
    payload = json.loads(raw)
    assert "error" in payload
    assert "memory_id" in payload["error"]


async def test_memory_compress_unknown_id_errors(isolated_db: MemoryDB) -> None:
    ctx = _make_ctx(isolated_db)
    raw = await _handle_memory_compress(ctx, memory_id="nonexistent")
    payload = json.loads(raw)
    assert "error" in payload
    assert "not found" in payload["error"]


# ---------------------------------------------------------------------------
# Error path coverage: sync_now / import_passport unexpected exceptions
# ---------------------------------------------------------------------------


async def test_sync_now_propagates_unexpected_error(
    isolated_db: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNC_PASSPHRASE", "test-pass")

    fake = MagicMock(side_effect=RuntimeError("backend offline"))
    with patch("mnemo_mcp.sync.delta.sync_now", side_effect=fake):
        ctx = _make_ctx(isolated_db)
        raw = await _handle_config_sync_now(ctx, backend="gdrive")

    payload = json.loads(raw)
    assert "error" in payload
    assert "sync_now failed" in payload["error"]


async def test_import_passport_decryption_failure(
    isolated_db: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wrong passphrase -> generic 'Passphrase mismatch' message."""
    monkeypatch.setenv("SYNC_PASSPHRASE", "wrong-pass")

    # Build a bundle with a different passphrase.
    from mnemo_mcp.sync.delta import build_full_bundle

    other = MemoryDB(isolated_db._db_path.parent / "other.db", embedding_dims=0)
    other._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('a', 'x', '2026-05-01', '2026-05-01', '2026-05-01')"
    )
    other._conn.commit()
    bundle = await build_full_bundle(other, passphrase="real-pass")
    other.close()

    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=_BUCKET)
        backend = S3Backend(
            bucket=_BUCKET,
            region="us-east-1",
            access_key_id="t",
            secret_access_key="t",
        )
        await backend.push(bundle, sequence=1)
        sync_pkg.register("s3", backend)

        ctx = _make_ctx(isolated_db)
        raw = await _handle_config_import_passport(ctx, source="s3")
        payload = json.loads(raw)

    assert "error" in payload
    assert "Passphrase mismatch" in payload["error"]


async def test_import_passport_pull_exception(
    isolated_db: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backend pull raising -> caller sees clear error message."""
    monkeypatch.setenv("SYNC_PASSPHRASE", "x")

    from mnemo_mcp.sync.base import SyncBackend

    class _BadBackend(SyncBackend):
        name = "bad"

        async def push(self, bundle: bytes, sequence: int) -> None:
            return None

        async def pull(self, sequence=None):
            raise RuntimeError("pull boom")

        async def last_remote_sequence(self) -> int:
            return 0

        async def health_check(self) -> bool:
            return True

    sync_pkg.register("s3", _BadBackend())

    ctx = _make_ctx(isolated_db)
    raw = await _handle_config_import_passport(ctx, source="s3")
    payload = json.loads(raw)

    assert "error" in payload
    assert "backend pull failed" in payload["error"]
