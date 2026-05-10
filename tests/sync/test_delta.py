"""Tests for the Phase 2 delta-sync orchestrator + LWW conflict resolver.

Covers:
- ``build_delta_bundle`` only includes rows newer than ``since``.
- ``build_full_bundle`` includes every row regardless of ``since``.
- ``apply_bundle`` inserts new rows from a remote bundle.
- LWW per row: local newer -> skip + audit row; remote newer -> update.
- ``sync_now`` delta path: pushes bundle at cursor + 1, advances state.
- ``sync_now`` full-pull-push path: triggered when remote_seq > local + 1;
  merges remote rows then pushes a new full bundle at remote_seq + 1.
- Empty-remote -> empty-merge path (cursor still advances).

Uses the moto S3 backend so the orchestrator end-to-end loop runs
deterministic + offline.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from mnemo_mcp import sync as sync_pkg
from mnemo_mcp.db import MemoryDB
from mnemo_mcp.sync.bundle import decode_bundle
from mnemo_mcp.sync.delta import (
    apply_bundle,
    build_delta_bundle,
    build_full_bundle,
    sync_now,
)
from mnemo_mcp.sync.s3 import S3Backend

_BUCKET = "mnemo-test-delta"
_PASS = "delta-test-passphrase"


@pytest.fixture(autouse=True)
def _isolated_registry() -> Iterator[None]:
    sync_pkg.reset_registry()
    yield
    sync_pkg.reset_registry()


@pytest.fixture
def isolated_db(tmp_path: Path) -> Iterator[MemoryDB]:
    db = MemoryDB(tmp_path / "memories.db", embedding_dims=0)
    yield db
    db.close()


@pytest.fixture
def s3_backend() -> Iterator[S3Backend]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=_BUCKET)
        backend = S3Backend(
            bucket=_BUCKET,
            region="us-east-1",
            access_key_id="testing",
            secret_access_key="testing",
        )
        sync_pkg.register("s3", backend)
        yield backend


# ---------------------------------------------------------------------------
# build_delta_bundle / build_full_bundle
# ---------------------------------------------------------------------------


async def test_build_delta_includes_only_rows_after_since(
    isolated_db: MemoryDB,
) -> None:
    # Seed two rows with a known timestamp gap.
    isolated_db._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('old', 'old content', ?, ?, ?)",
        (
            datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
            datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
            datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        ),
    )
    isolated_db._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('new', 'new content', ?, ?, ?)",
        (
            datetime(2026, 5, 1, tzinfo=UTC).isoformat(),
            datetime(2026, 5, 1, tzinfo=UTC).isoformat(),
            datetime(2026, 5, 1, tzinfo=UTC).isoformat(),
        ),
    )
    isolated_db._conn.commit()

    # since = mid-2026-03 -> only 'new' should land in the bundle.
    cutoff = datetime(2026, 3, 1, tzinfo=UTC).timestamp()
    bundle = await build_delta_bundle(isolated_db, since=cutoff, passphrase=_PASS)
    payload = decode_bundle(bundle, _PASS)

    rows = [
        json.loads(line)
        for line in payload["memories.jsonl"].decode().splitlines()
        if line
    ]
    assert {r["id"] for r in rows} == {"new"}

    manifest = json.loads(payload["manifest.json"])
    assert manifest["row_count"] == 1
    assert manifest["since"] == cutoff


async def test_build_full_includes_all_rows(isolated_db: MemoryDB) -> None:
    for i in range(3):
        isolated_db._conn.execute(
            "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
            "VALUES (?, ?, '2026-01-01', '2026-01-01', '2026-01-01')",
            (f"row-{i}", f"content-{i}"),
        )
    isolated_db._conn.commit()

    bundle = await build_full_bundle(isolated_db, passphrase=_PASS)
    payload = decode_bundle(bundle, _PASS)
    rows = [
        json.loads(line)
        for line in payload["memories.jsonl"].decode().splitlines()
        if line
    ]
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# apply_bundle: LWW per row
# ---------------------------------------------------------------------------


async def test_apply_bundle_inserts_new_rows(
    isolated_db: MemoryDB, tmp_path: Path
) -> None:
    # Build a bundle on a separate DB then apply to isolated_db.
    other = MemoryDB(tmp_path / "other.db", embedding_dims=0)
    other._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('a', 'remote', '2026-05-01', '2026-05-01', '2026-05-01')"
    )
    other._conn.commit()
    bundle = await build_full_bundle(other, passphrase=_PASS)
    other.close()

    counts = await apply_bundle(isolated_db, bundle, _PASS)
    assert counts["inserted"] == 1
    assert counts["updated"] == 0
    assert counts["skipped"] == 0

    row = isolated_db._conn.execute(
        "SELECT content FROM memories WHERE id = 'a'"
    ).fetchone()
    assert row["content"] == "remote"


async def test_apply_bundle_lww_local_wins(
    isolated_db: MemoryDB, tmp_path: Path
) -> None:
    # Local row: updated_at=2026-06-01 (newer).
    isolated_db._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('a', 'local-newer', '2026-01-01', '2026-06-01', '2026-06-01')"
    )
    isolated_db._conn.commit()

    # Remote bundle row: updated_at=2026-05-01 (older).
    other = MemoryDB(tmp_path / "other.db", embedding_dims=0)
    other._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('a', 'remote-older', '2026-01-01', '2026-05-01', '2026-05-01')"
    )
    other._conn.commit()
    bundle = await build_full_bundle(other, passphrase=_PASS)
    other.close()

    counts = await apply_bundle(isolated_db, bundle, _PASS)
    assert counts["skipped"] == 1, counts
    assert counts["updated"] == 0
    assert counts["inserted"] == 0

    # Local row preserved.
    row = isolated_db._conn.execute(
        "SELECT content FROM memories WHERE id = 'a'"
    ).fetchone()
    assert row["content"] == "local-newer"

    # Audit row exists.
    audit = isolated_db._conn.execute(
        "SELECT memory_id, local_content, remote_content FROM sync_overrides"
    ).fetchall()
    assert len(audit) == 1
    assert audit[0]["memory_id"] == "a"
    assert audit[0]["local_content"] == "local-newer"
    assert audit[0]["remote_content"] == "remote-older"


async def test_apply_bundle_lww_remote_wins(
    isolated_db: MemoryDB, tmp_path: Path
) -> None:
    # Local row: updated_at=2026-04-01 (older).
    isolated_db._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('a', 'local-older', '2026-01-01', '2026-04-01', '2026-04-01')"
    )
    isolated_db._conn.commit()

    # Remote bundle row: updated_at=2026-06-01 (newer).
    other = MemoryDB(tmp_path / "other.db", embedding_dims=0)
    other._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('a', 'remote-newer', '2026-01-01', '2026-06-01', '2026-06-01')"
    )
    other._conn.commit()
    bundle = await build_full_bundle(other, passphrase=_PASS)
    other.close()

    counts = await apply_bundle(isolated_db, bundle, _PASS)
    assert counts["updated"] == 1, counts
    assert counts["skipped"] == 0

    row = isolated_db._conn.execute(
        "SELECT content FROM memories WHERE id = 'a'"
    ).fetchone()
    assert row["content"] == "remote-newer"


# ---------------------------------------------------------------------------
# sync_now orchestrator
# ---------------------------------------------------------------------------


async def test_sync_now_delta_push_advances_cursor(
    isolated_db: MemoryDB, s3_backend: S3Backend
) -> None:
    isolated_db._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('a', 'first', '2026-05-01', '2026-05-01', '2026-05-01')"
    )
    isolated_db._conn.commit()

    result = await sync_now(isolated_db, "s3", _PASS)
    assert result["mode"] == "delta"
    assert result["cursor"] == 1
    assert result["rows"] == 1

    state = isolated_db.get_sync_state("s3")
    assert state is not None
    assert state["upload_cursor"] == 1
    assert state["last_sync_at"] is not None


async def test_sync_now_full_pull_push_on_sequence_gap(
    isolated_db: MemoryDB, s3_backend: S3Backend, tmp_path: Path
) -> None:
    """Another machine pushed seq=1+2 while we sat at 0 -> full pull + merge."""
    # Build a remote bundle from a different DB to simulate "other machine".
    other = MemoryDB(tmp_path / "other.db", embedding_dims=0)
    other._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('remote-only', 'from other', '2026-05-02', '2026-05-02', '2026-05-02')"
    )
    other._conn.commit()
    remote_bundle_1 = await build_full_bundle(other, passphrase=_PASS)
    other.close()

    # Push two bundles to S3 directly (simulating the other machine).
    await s3_backend.push(remote_bundle_1, sequence=1)
    await s3_backend.push(remote_bundle_1, sequence=2)

    # Local has its own row and cursor=0.
    isolated_db._conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES ('local', 'local-row', '2026-05-03', '2026-05-03', '2026-05-03')"
    )
    isolated_db._conn.commit()

    result = await sync_now(isolated_db, "s3", _PASS)
    assert result["mode"] == "full-pull-push"
    # Cursor = remote_seq + 1 = 3
    assert result["cursor"] == 3
    # Merge applied the remote-only row into local.
    assert result["merge"]["inserted"] == 1

    rows = isolated_db._conn.execute("SELECT id FROM memories ORDER BY id").fetchall()
    assert {r["id"] for r in rows} == {"local", "remote-only"}


async def test_sync_now_handles_empty_local_db(
    isolated_db: MemoryDB, s3_backend: S3Backend
) -> None:
    """Empty local DB still pushes a (zero-row) delta bundle and advances."""
    result = await sync_now(isolated_db, "s3", _PASS)
    assert result["mode"] == "delta"
    assert result["cursor"] == 1
    assert result["rows"] == 0
