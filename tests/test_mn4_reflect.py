"""MN-4: bounded cited reflect unit tests (dry — zero model calls)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from mnemo_core import operations, results
from mnemo_mcp.db import MemoryDB


@pytest.fixture()
def store(tmp_path: Path) -> Iterator[MemoryDB]:
    db = MemoryDB(tmp_path / "reflect.db", embedding_dims=0)
    yield db
    db.close()


def test_reflect_answers_with_citation_only(store: MemoryDB) -> None:
    operations.capture(store, "alice", "deploy checklist for pilot")
    envelope = operations.reflect(store, "alice", "deploy checklist")
    assert envelope["ok"] is True
    data = envelope["data"]
    assert data["abstained"] is False
    assert data["citations"], "reflect must cite retrieval results"
    assert data["answer"] == data["citations"][0]["content"]
    # Extractive contract: the answer is a stored content verbatim.
    stored = operations.recall(store, "alice", "deploy")["data"]["matches"][0][
        "content"
    ]
    assert data["answer"] == stored
    assert data["cost"] == {
        "model_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }


def test_reflect_abstains_without_retrieval_support(store: MemoryDB) -> None:
    envelope = operations.reflect(store, "alice", "unheard question")
    assert envelope["ok"] is True
    data = envelope["data"]
    assert data["abstained"] is True
    assert data["reason"] == "no_retrieval_support"
    assert data["answer"] is None
    assert data["citations"] == []
    assert data["cost"]["model_calls"] == 0


def test_reflect_never_writes_back(store: MemoryDB) -> None:
    operations.capture(store, "alice", "deploy checklist for pilot")
    before = operations.recall(store, "alice", "deploy", k=10)["data"]["matches"]
    operations.reflect(store, "alice", "deploy checklist")
    after = operations.recall(store, "alice", "deploy", k=10)["data"]["matches"]
    assert len(after) == len(before)
    assert [m["id"] for m in after] == [m["id"] for m in before]


def test_reflect_validates_inputs(store: MemoryDB) -> None:
    empty_query = operations.reflect(store, "alice", "   ")
    assert empty_query["error"]["code"] == results.VALIDATION
    bad_k = operations.reflect(store, "alice", "query", k=0)
    assert bad_k["error"]["code"] == results.VALIDATION


def test_reflect_k_is_clamped(store: MemoryDB) -> None:
    for i in range(15):
        operations.capture(store, "alice", f"note number {i} about deploy")
    envelope = operations.reflect(store, "alice", "deploy", k=50)
    assert envelope["ok"] is True
    assert len(envelope["data"]["citations"]) <= 10


def test_reflect_never_emits_raw_secret(store: MemoryDB) -> None:
    token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
    captured = operations.capture(store, "alice", f"token {token} leaked")
    assert captured["data"]["redactions"] == ["github_pat"]
    envelope = operations.reflect(store, "alice", "token")
    assert envelope["ok"] is True
    data = envelope["data"]
    assert "ghp_" not in (data["answer"] or "")
    assert all("ghp_" not in c["content"] for c in data["citations"])


def test_reflect_respects_subject_scope(store: MemoryDB) -> None:
    operations.capture(store, "alice", "alice deploy checklist")
    bob = operations.reflect(store, "bob", "deploy checklist")
    assert bob["ok"] is True
    assert bob["data"]["abstained"] is True
    alice = operations.reflect(store, "alice", "deploy checklist")
    assert alice["data"]["abstained"] is False
