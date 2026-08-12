from __future__ import annotations

import json
import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest

_HARNESS_SPEC = spec_from_file_location(
    "cf_full_flow",
    Path(__file__).parents[1] / "scripts" / "cf_full_flow.py",
)
assert _HARNESS_SPEC is not None and _HARNESS_SPEC.loader is not None
_HARNESS = module_from_spec(_HARNESS_SPEC)
sys.modules[_HARNESS_SPEC.name] = _HARNESS
_HARNESS_SPEC.loader.exec_module(_HARNESS)


def test_configure_cohere_cf_gateway_uses_existing_gateway_token(monkeypatch):
    for name in (
        "JINA_AI_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "XAI_API_KEY",
        "COHERE_API_KEY",
        "EMBEDDING_MODELS",
        "EMBEDDING_API_BASE",
        "RERANK_MODELS",
        "RERANK_API_BASE",
        "LLM_MODELS",
        "LLM_API_BASE",
    ):
        monkeypatch.setenv(name, "stale")
    monkeypatch.setenv(
        "CF_AIG_BASE",
        "https://gateway.example/v1/account/llm-main/",
    )
    monkeypatch.setenv("CF_AIG_TOKEN", "gateway-token")

    _HARNESS._configure_cohere_cf_gateway()

    assert os.environ["COHERE_API_KEY"] == "gateway-token"
    assert os.environ["EMBEDDING_MODELS"] == "cohere/embed-v4.0"
    assert (
        os.environ["EMBEDDING_API_BASE"]
        == "https://gateway.example/v1/account/llm-main/cohere/v2/embed"
    )
    assert os.environ["RERANK_MODELS"] == "cohere/rerank-v4.0-fast"
    assert (
        os.environ["RERANK_API_BASE"]
        == "https://gateway.example/v1/account/llm-main/cohere"
    )
    assert not os.environ.get("JINA_AI_API_KEY")


def test_assert_rerank_payload_requires_semantic_and_reranked_flags():
    payload = {
        "semantic": True,
        "reranked": True,
        "count": 3,
        "results": [
            {"id": "memory-1"},
            {"id": "memory-2"},
            {"id": "memory-3"},
        ],
    }

    _HARNESS._assert_rerank_payload(
        json.dumps(payload),
        ["memory-1", "memory-2", "memory-3"],
    )

    payload["reranked"] = False
    with pytest.raises(AssertionError, match="reranked"):
        _HARNESS._assert_rerank_payload(
            json.dumps(payload),
            ["memory-1", "memory-2", "memory-3"],
        )


class _FakeSession:
    def __init__(self, *, duplicate_warning: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.next_id = 0
        self.memories: dict[str, str] = {}
        self.duplicate_warning = duplicate_warning
        self.backfill_payload = {
            "status": "completed",
            "model": "cohere/embed-v4.0",
            "dimensions": 1536,
            "scanned": 267,
            "embedded": 267,
            "skipped": 0,
            "failed": 0,
        }

    async def initialize(self) -> None:
        return None

    async def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        if name == "add_memory":
            self.next_id += 1
            memory_id = f"memory-{self.next_id}"
            marker = arguments["content"].rsplit(" ", 1)[-1]
            self.memories[memory_id] = marker
            payload = {
                "id": memory_id,
                "status": "created",
                "category": "test",
                "semantic": "test",
            }
            if self.duplicate_warning:
                payload["dedup_warning"] = "duplicate"
            return SimpleNamespace(
                content=[SimpleNamespace(text=json.dumps(payload))],
            )

        if name == "search_memory":
            marker = arguments["query"]
            results = [
                {"id": memory_id, "content": stored_marker}
                for memory_id, stored_marker in self.memories.items()
                if stored_marker == marker
            ]
            payload = {"count": len(results), "results": results}
            return SimpleNamespace(
                content=[SimpleNamespace(text=json.dumps(payload))],
            )

        if name == "delete_memory":
            memory_id = arguments["memory_id"]
            self.memories.pop(memory_id, None)
            payload = {"status": "deleted", "id": memory_id}
            return SimpleNamespace(
                content=[SimpleNamespace(text=json.dumps(payload))],
            )

        if name == "config":
            assert arguments == {"action": "backfill_embeddings", "batch_size": 32}
            return SimpleNamespace(
                content=[SimpleNamespace(text=json.dumps(self.backfill_payload))],
            )

        raise AssertionError(f"unexpected tool: {name}")


class _FakeTransport:
    async def __aenter__(self):
        return None, None, None

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _FakeClientSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.mark.asyncio
async def test_run_search_uses_unique_marker_and_deletes_exact_memory():
    session = _FakeSession()

    first = await _HARNESS._run_search(session)
    second = await _HARNESS._run_search(session)

    assert first.marker != second.marker
    assert first.memory_id == "memory-1"
    assert second.memory_id == "memory-2"
    assert [name for name, _ in session.calls] == [
        "add_memory",
        "search_memory",
        "delete_memory",
        "add_memory",
        "search_memory",
        "delete_memory",
    ]
    assert [
        arguments["memory_id"]
        for name, arguments in session.calls
        if name == "delete_memory"
    ] == [
        "memory-1",
        "memory-2",
    ]


@pytest.mark.asyncio
async def test_run_search_rejects_duplicate_warning_and_cleans_up_exact_memory():
    session = _FakeSession(duplicate_warning=True)

    with pytest.raises(AssertionError, match="duplicate warning"):
        await _HARNESS._run_search(session)

    assert [name for name, _ in session.calls] == [
        "add_memory",
        "delete_memory",
    ]
    assert session.calls[-1][1]["memory_id"] == "memory-1"


@pytest.mark.asyncio
async def test_run_backfill_uses_config_action_and_requires_zero_failures(monkeypatch):
    session = _FakeSession()

    monkeypatch.setattr(_HARNESS, "_creds", lambda: {"COHERE_API_KEY": "gateway"})
    monkeypatch.setattr(_HARNESS, "get_token", lambda endpoint, creds: "token")
    monkeypatch.setattr(_HARNESS, "_sub_of", lambda token: "sub-a")

    async def fake_session(endpoint: str, token: str):
        return _FakeTransport(), lambda read, write: _FakeClientSessionContext(session)

    monkeypatch.setattr(_HARNESS, "_session", fake_session)

    await _HARNESS.run_backfill("https://mnemo.test")

    assert session.calls == [
        ("config", {"action": "backfill_embeddings", "batch_size": 32}),
    ]


@pytest.mark.asyncio
async def test_run_backfill_rejects_failures(monkeypatch):
    session = _FakeSession()
    session.backfill_payload["failed"] = 1

    monkeypatch.setattr(_HARNESS, "_creds", lambda: {"COHERE_API_KEY": "gateway"})
    monkeypatch.setattr(_HARNESS, "get_token", lambda endpoint, creds: "token")
    monkeypatch.setattr(_HARNESS, "_sub_of", lambda token: "sub-a")

    async def fake_session(endpoint: str, token: str):
        return _FakeTransport(), lambda read, write: _FakeClientSessionContext(session)

    monkeypatch.setattr(_HARNESS, "_session", fake_session)

    with pytest.raises(AssertionError, match="failed"):
        await _HARNESS.run_backfill("https://mnemo.test")


def test_assert_search_absent_rejects_leaked_marker():
    _HARNESS._assert_search_absent(
        json.dumps({"count": 0, "results": []}),
        "marker",
    )

    with pytest.raises(AssertionError, match="isolation failure"):
        _HARNESS._assert_search_absent(
            json.dumps({"count": 1, "results": [{"content": "marker"}]}),
            "marker",
        )


@pytest.mark.asyncio
async def test_run_two_sub_isolation_uses_distinct_markers_and_exact_cleanup(
    monkeypatch,
):
    session_a = _FakeSession()
    session_b = _FakeSession()
    sessions = {"token-a": session_a, "token-b": session_b}
    tokens = iter(("token-a", "token-b"))

    monkeypatch.setattr(_HARNESS, "_creds", lambda: {"JINA_API_KEY": "jina"})
    monkeypatch.setattr(
        _HARNESS,
        "get_token",
        lambda endpoint, creds: next(tokens),
    )
    monkeypatch.setattr(
        _HARNESS,
        "_sub_of",
        lambda token: {"token-a": "sub-a", "token-b": "sub-b"}[token],
    )

    async def fake_session(endpoint: str, token: str):
        return _FakeTransport(), lambda read, write: _FakeClientSessionContext(
            sessions[token]
        )

    monkeypatch.setattr(_HARNESS, "_session", fake_session)

    await _HARNESS.run_two_sub_isolation("https://mnemo.test")

    assert [name for name, _ in session_a.calls] == [
        "add_memory",
        "search_memory",
        "delete_memory",
    ]
    assert [name for name, _ in session_b.calls] == [
        "search_memory",
        "add_memory",
        "search_memory",
        "delete_memory",
    ]
    marker_a = session_a.calls[0][1]["content"].rsplit(" ", 1)[-1]
    marker_b = session_b.calls[1][1]["content"].rsplit(" ", 1)[-1]
    assert "-isolation-a-" in marker_a
    assert "-isolation-b-" in marker_b
    assert marker_a != marker_b
    assert session_b.calls[-1][1]["memory_id"] == "memory-1"
