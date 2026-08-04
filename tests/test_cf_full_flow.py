from __future__ import annotations

import json
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


class _FakeSession:
    def __init__(self, *, duplicate_warning: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.next_id = 0
        self.memories: dict[str, str] = {}
        self.duplicate_warning = duplicate_warning

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
