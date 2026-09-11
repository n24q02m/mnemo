"""MN-3 wave 1: per-subject recall enforcement at the storage tier."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from mnemo_core import operations
from mnemo_mcp.db import MemoryDB


@pytest.fixture
def store(tmp_path: Path) -> Generator[MemoryDB]:
    db = MemoryDB(tmp_path / "subject.db", embedding_dims=0)
    yield db
    db.close()


def _cap(db: MemoryDB, subject: str | None, content: str) -> dict:
    return operations.capture(db, subject, content)


def test_scoped_recall_returns_only_own_subject(store: MemoryDB) -> None:
    _cap(store, "alice", "alice prefers the us-east-1 region")
    _cap(store, "carol", "carol prefers the eu-central-1 region")

    env = operations.recall(store, "carol", "region", k=5)
    assert env["ok"] is True
    contents = [m["content"] for m in env["data"]["matches"]]
    assert any("eu-central-1" in c for c in contents)
    assert all("us-east-1" not in c for c in contents)


def test_legacy_null_subject_rows_invisible_to_scoped_probe(store: MemoryDB) -> None:
    _cap(store, "alice", "alice note about clickhouse")
    # Legacy path: raw add without subject -> NULL row.
    store.add(content="legacy blob about clickhouse", category="general")

    env = operations.recall(store, "alice", "clickhouse", k=5)
    contents = [m["content"] for m in env["data"]["matches"]]
    assert any("alice note" in c for c in contents)
    assert all("legacy blob" not in c for c in contents)


def test_none_subject_recall_keeps_unfiltered_legacy_view(store: MemoryDB) -> None:
    _cap(store, "alice", "alice note about clickhouse")
    store.add(content="legacy blob about clickhouse", category="general")

    env = operations.recall(store, None, "clickhouse", k=5)
    contents = [m["content"] for m in env["data"]["matches"]]
    assert any("alice note" in c for c in contents)
    assert any("legacy blob" in c for c in contents)


def test_capture_persists_subject_column(store: MemoryDB) -> None:
    env = _cap(store, "binh", "ghi chu cua binh")
    row = store._conn.execute(
        "SELECT subject FROM memories WHERE id = ?", (env["data"]["id"],)
    ).fetchone()
    assert row is not None and row["subject"] == "binh"
