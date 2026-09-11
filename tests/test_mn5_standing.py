"""MN-5: standing questions / knowledge pages unit tests (dry)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from mnemo_core import results, standing
from mnemo_mcp.db import MemoryDB


@pytest.fixture()
def store(tmp_path: Path) -> Iterator[MemoryDB]:
    db = MemoryDB(tmp_path / "standing.db", embedding_dims=0)
    yield db
    db.close()


def test_refresh_materializes_extractive_page(store: MemoryDB) -> None:
    from mnemo_core import operations

    operations.capture(store, "alice", "deploy checklist for pilot")
    env = standing.standing_refresh(store, "alice", "deploy-page", "deploy checklist")
    assert env["ok"] is True
    assert env["data"]["abstained"] is False
    assert env["data"]["cost"]["model_calls"] == 0
    assert env["data"]["sources"], "page must pin source versions"

    read = standing.standing_read(store, "alice", "deploy-page")
    assert read["ok"] is True
    data = read["data"]
    assert data["tombstone"] is False
    assert data["staleness"] == "fresh"
    assert data["answer"] == "deploy checklist for pilot"
    assert data["cost"] == {
        "model_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }


def test_read_is_cheap_and_reports_missing_page(store: MemoryDB) -> None:
    missing = standing.standing_read(store, "alice", "nope")
    assert missing["ok"] is False
    assert missing["error"]["code"] == results.NOT_FOUND


def test_source_missing_marks_page_stale(store: MemoryDB, tmp_path: Path) -> None:
    from mnemo_core import operations

    operations.capture(store, "alice", "oncall rotation alice monday")
    standing.standing_refresh(store, "alice", "oncall-page", "oncall rotation")
    # The pilot tier has no delete op, but the DB layer is still SQLite:
    # hard-delete the source row behind the store's back and the next
    # cheap read must verdict the page stale instead of crashing.
    conn = __import__("sqlite3").connect(tmp_path / "standing.db")
    conn.execute("DELETE FROM memories WHERE category != '_standing'")
    conn.commit()
    conn.close()
    read = standing.standing_read(store, "alice", "oncall-page")
    assert read["ok"] is True
    assert read["data"]["staleness"] == "stale:source_missing"
    assert read["data"]["answer"] is not None


def test_refresh_supersedes_older_page_newest_wins(store: MemoryDB) -> None:
    from mnemo_core import operations

    operations.capture(store, "alice", "deploy checklist v1")
    operations.capture(store, "alice", "deploy checklist v2 rollout")
    standing.standing_refresh(store, "alice", "deploy-page", "deploy checklist v1")
    env = standing.standing_refresh(
        store, "alice", "deploy-page", "checklist v2 rollout"
    )
    assert env["ok"] is True
    read = standing.standing_read(store, "alice", "deploy-page")
    assert read["ok"] is True
    assert read["data"]["answer"] == "deploy checklist v2 rollout"


def test_invalidate_writes_tombstone_and_read_reports_it(store: MemoryDB) -> None:
    from mnemo_core import operations

    operations.capture(store, "alice", "deploy checklist for pilot")
    standing.standing_refresh(store, "alice", "deploy-page", "deploy checklist")
    inv = standing.standing_invalidate(
        store, "alice", "deploy-page", "deploy checklist"
    )
    assert inv["ok"] is True
    read = standing.standing_read(store, "alice", "deploy-page")
    assert read["ok"] is True
    assert read["data"]["tombstone"] is True
    assert read["data"]["staleness"] == "invalidated"
    assert read["data"]["answer"] is None


def test_standing_pages_respect_subject_scope(store: MemoryDB) -> None:
    from mnemo_core import operations

    operations.capture(store, "alice", "alice deploy checklist")
    standing.standing_refresh(store, "alice", "deploy-page", "deploy checklist")
    bob = standing.standing_read(store, "bob", "deploy-page")
    assert bob["ok"] is False
    assert bob["error"]["code"] == results.NOT_FOUND


def test_standing_validates_inputs(store: MemoryDB) -> None:
    no_key = standing.standing_refresh(store, "alice", "  ", "question")
    assert no_key["error"]["code"] == results.VALIDATION
    no_question = standing.standing_refresh(store, "alice", "key", "  ")
    assert no_question["error"]["code"] == results.VALIDATION
    no_key_read = standing.standing_read(store, "alice", "")
    assert no_key_read["error"]["code"] == results.VALIDATION
    no_key_inv = standing.standing_invalidate(store, "alice", "")
    assert no_key_inv["error"]["code"] == results.VALIDATION


def test_refresh_abstaining_question_materializes_empty_page(store: MemoryDB) -> None:
    env = standing.standing_refresh(store, "alice", "empty-page", "nothing known")
    assert env["ok"] is True
    assert env["data"]["abstained"] is True
    assert env["data"]["sources"] == []
    read = standing.standing_read(store, "alice", "empty-page")
    assert read["ok"] is True
    assert read["data"]["staleness"] == "fresh"
    assert read["data"]["answer"] is None
