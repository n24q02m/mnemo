"""Core operation tests for the mnemo pilot (P0)."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from mnemo_core import operations, results
from mnemo_mcp.db import MemoryDB


@pytest.fixture
def store(tmp_path: Path) -> Generator[MemoryDB]:
    db = MemoryDB(tmp_path / "pilot.db", embedding_dims=0)
    yield db
    db.close()


def test_capture_returns_id_and_subject(store: MemoryDB) -> None:
    env = operations.capture(store, "alice", "deploy checklist", tags=["ops"])
    assert env["ok"] is True
    assert env["data"]["id"]
    assert env["data"]["subject"] == "alice"
    assert env["data"]["tags"] == ["ops"]


def test_capture_empty_content_is_validation(store: MemoryDB) -> None:
    env = operations.capture(store, "alice", "   ")
    assert env == {
        "ok": False,
        "error": {"code": "VALIDATION", "message": "content is required"},
    }


def test_capture_oversized_content_maps_to_validation(store: MemoryDB) -> None:
    env = operations.capture(store, "alice", "x" * 20_001)
    assert env["ok"] is False
    assert env["error"]["code"] == results.VALIDATION


def test_recall_matches_captured_memory(store: MemoryDB) -> None:
    operations.capture(store, "alice", "mnemo pilot uses sqlite FTS5")
    env = operations.recall(store, "alice", "FTS5")
    assert env["ok"] is True
    assert any("FTS5" in m["content"] for m in env["data"]["matches"])


def test_recall_empty_query_is_validation(store: MemoryDB) -> None:
    env = operations.recall(store, "alice", "  ")
    assert env["error"]["code"] == results.VALIDATION


def test_fetch_missing_id_is_not_found(store: MemoryDB) -> None:
    env = operations.fetch(store, "alice", "deadbeef")
    assert env["ok"] is False
    assert env["error"]["code"] == results.NOT_FOUND


def test_fetch_existing_id_round_trips(store: MemoryDB) -> None:
    captured = operations.capture(store, "alice", "round trip")
    env = operations.fetch(store, "alice", captured["data"]["id"])
    assert env["ok"] is True
    assert env["data"]["memory"]["content"] == "round trip"


def test_storage_failure_maps_to_storage_code(
    store: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: object, **kw: object) -> str:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(store, "add", boom)
    env = operations.capture(store, "alice", "anything")
    assert env["ok"] is False
    assert env["error"]["code"] == results.STORAGE


def test_subject_isolation_between_stores(tmp_path: Path) -> None:
    alice = MemoryDB(tmp_path / "alice.db", embedding_dims=0)
    bob = MemoryDB(tmp_path / "bob.db", embedding_dims=0)
    try:
        operations.capture(alice, "alice", "alice private note")
        env_bob = operations.recall(bob, "bob", "alice private note")
        assert env_bob["ok"] is True
        assert env_bob["data"]["matches"] == []
    finally:
        alice.close()
        bob.close()


def test_exit_code_mapping() -> None:
    assert results.exit_code(results.ok({})) == 0
    assert results.exit_code(results.err(results.VALIDATION, "m")) == 2
    assert results.exit_code(results.err(results.NOT_FOUND, "m")) == 3
    assert results.exit_code(results.err(results.AUTH_DENIED, "m")) == 4
    assert results.exit_code(results.err(results.STORAGE, "m")) == 5
    assert results.exit_code(results.err(results.INTERNAL, "m")) == 1


def test_core_operations_never_read_environ() -> None:
    """Spec invariant: the domain layer never reads the process environment.

    AST-based so docstrings/comments mentioning the rule don't trip it.
    """
    import ast

    tree = ast.parse(Path(operations.__file__).read_text(encoding="utf-8"))
    banned: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "environ"
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        ):
            banned.append("os.environ")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getenv"
        ):
            banned.append("getenv()")
    assert banned == [], f"domain layer reads environment: {banned}"
