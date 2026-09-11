"""MN-3 wave 1: per-subject recall enforcement at the storage tier."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from mnemo_core import operations, results
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


class TestScopedFetch:
    """Wave 2: fetch joins the subject contract (same semantics as search).

    A named subject can only fetch its own rows; rows captured with a NULL
    subject (legacy / unattributed) are invisible to a scoped fetch and
    remain reachable only through the unfiltered (subject=None) view.
    """

    def test_scoped_fetch_returns_own_row(self, store: MemoryDB) -> None:
        operations.capture(store, "alice", "alice note")
        mid = self._last_id(store)
        env = operations.fetch(store, "alice", mid)
        assert env["ok"] is True
        assert env["data"]["memory"]["id"] == mid

    def test_scoped_fetch_hides_other_subject_row(self, store: MemoryDB) -> None:
        operations.capture(store, "alice", "alice secret note")
        mid = self._last_id(store)
        env = operations.fetch(store, "bob", mid)
        assert env == {
            "ok": False,
            "error": {
                "code": results.NOT_FOUND,
                "message": f"memory {mid!r} not found",
            },
        }

    def test_scoped_fetch_hides_legacy_null_subject_row(self, store: MemoryDB) -> None:
        store.add(content="legacy blob", category="general")
        mid = self._last_id(store)
        assert operations.fetch(store, "alice", mid)["error"]["code"] == (
            results.NOT_FOUND
        )
        legacy_view = operations.fetch(store, None, mid)
        assert legacy_view["ok"] is True
        assert legacy_view["data"]["memory"]["content"] == "legacy blob"

    def test_fetch_egress_redaction_fires_on_owned_raw_rows(
        self, store: MemoryDB
    ) -> None:
        # Planted via store.add (bypasses capture-time redaction) so the
        # fetch egress path itself must redact.
        store.add(
            content="note with ghp_abcdefghijklmnopqrstuvwxyzabcdefghij",
            category="general",
            subject="alice",
        )
        mid = self._last_id(store)
        env = operations.fetch(store, "alice", mid)
        assert env["ok"] is True
        assert env["data"]["redactions"] == ["github_pat"]
        assert "ghp_" not in env["data"]["memory"]["content"]

    @staticmethod
    def _last_id(store: MemoryDB) -> str:
        row = store._conn.execute(
            "SELECT id FROM memories ORDER BY created_at DESC, id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        return row["id"]
