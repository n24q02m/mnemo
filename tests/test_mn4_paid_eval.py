"""MN-4 paid-path tests: bounded provider, no network, no spend.

The provider transport is faked, so every assertion here exercises the real
core/adapter contracts (redaction-before-provider, cap enforcement, receipt
fields, abstention-without-call, dry-path compatibility) at zero cost.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from mnemo_core import operations
from mnemo_core.ports import ProviderAnswer
from mnemo_mcp.db import MemoryDB


class FakeTransport:
    """Records requests; returns canned completions. Never touches network."""

    def __init__(self, prompt_tokens: int = 800, completion_tokens: int = 300) -> None:
        self.requests: list[tuple[str, str, int]] = []
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens

    def __call__(
        self, model: str, prompt: str, max_tokens: int
    ) -> tuple[str, int, int]:
        self.requests.append((model, prompt, max_tokens))
        return ("synthesized answer", self.prompt_tokens, self.completion_tokens)


@pytest.fixture()
def db(tmp_path: pathlib.Path) -> MemoryDB:
    return MemoryDB(tmp_path / "t.db", embedding_dims=0)


def _provider(transport: FakeTransport, cap: float = 5.00):
    from mnemo_mcp.providers import BoundedReflectProvider

    return BoundedReflectProvider(
        model="cohere/command-r7b-12-2024",
        api_key="test-key-not-real",
        cap_usd=cap,
        transport=transport,
    )


def test_dry_path_default_unchanged(db: MemoryDB) -> None:
    operations.capture(db, "alice", "deploy checklist for pilot")
    out = operations.reflect(db, "alice", "deploy checklist")
    assert out["ok"] is True
    assert out["data"]["answer"] == "deploy checklist for pilot"
    assert out["data"]["cost"] == {
        "model_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }


def test_abstention_makes_no_provider_call(db: MemoryDB) -> None:
    transport = FakeTransport()
    out = operations.reflect(db, "alice", "nothing here", provider=_provider(transport))
    assert out["ok"] is True
    assert out["data"]["abstained"] is True
    assert out["data"]["cost"]["model_calls"] == 0
    assert transport.requests == []


def test_paid_path_receipt_and_answer(db: MemoryDB) -> None:
    operations.capture(db, "alice", "deploy checklist for pilot")
    transport = FakeTransport()
    provider = _provider(transport)
    out = operations.reflect(db, "alice", "deploy checklist", provider=provider)
    assert out["ok"] is True
    assert out["data"]["answer"] == "synthesized answer"
    cost = out["data"]["cost"]
    assert cost["model_calls"] == 1
    assert cost["prompt_tokens"] == 800
    assert cost["completion_tokens"] == 300
    assert cost["model"] == "cohere/command-r7b-12-2024"
    # 800 in @ $0.0375/M + 300 out @ $0.15/M
    assert cost["est_cost_usd"] == round(800 / 1e6 * 0.0375 + 300 / 1e6 * 0.15, 6)
    assert cost["session_spent_usd"] == cost["est_cost_usd"]
    assert provider.spent_usd == pytest.approx(cost["est_cost_usd"])
    # prompt carries citations, never raw subject-scoped rows beyond them
    assert "deploy checklist for pilot" in transport.requests[0][1]


def test_redaction_before_provider(db: MemoryDB) -> None:
    transport = FakeTransport()
    provider = _provider(transport)
    operations.capture(
        db, "alice", "github token ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa and note"
    )
    out = operations.reflect(db, "alice", "github token", provider=provider)
    assert out["ok"] is True
    sent_prompt = transport.requests[0][1]
    assert ("ghp_" + "a" * 36) not in sent_prompt
    assert "[REDACTED:github_pat]" in sent_prompt


def test_cap_refuses_before_call(db: MemoryDB) -> None:
    operations.capture(db, "alice", "deploy checklist for pilot")
    # Pre-call projection bounds the call at max_tokens=400/400 (~$0.000075
    # at r7b prices); a cap below that means no call is ever affordable.
    transport = FakeTransport(prompt_tokens=15_000_000, completion_tokens=3_000_000)
    provider = _provider(transport, cap=0.00001)
    out = operations.reflect(db, "alice", "deploy checklist", provider=provider)
    assert out["ok"] is False
    assert out["error"]["code"] == "CAP"
    assert "cap exhausted" in out["error"]["message"]
    assert transport.requests == []
    assert provider.spent_usd == 0.0


def test_cap_stops_after_accumulation(db: MemoryDB) -> None:
    operations.capture(db, "alice", "deploy checklist for pilot")
    # 800/300 at r7b prices ~ $0.000075/call; cap after first real call
    transport = FakeTransport()
    provider = _provider(transport, cap=0.00008)
    first = operations.reflect(db, "alice", "deploy checklist", provider=provider)
    assert first["ok"] is True  # pre-call projection uses max_tokens bounds
    second = operations.reflect(db, "alice", "deploy checklist", provider=provider)
    assert second["ok"] is False
    assert second["error"]["code"] == "CAP"


def test_provider_error_maps_internal(db: MemoryDB) -> None:
    operations.capture(db, "alice", "deploy checklist for pilot")

    class Boom:
        def synthesize(self, query: str, citations: list[dict]) -> ProviderAnswer:
            raise RuntimeError("boom")

    out = operations.reflect(db, "alice", "deploy checklist", provider=Boom())
    assert out["ok"] is False
    assert out["error"]["code"] == "INTERNAL"


def test_corpus_baseline_file_untouched() -> None:
    corpus = json.loads(
        (
            pathlib.Path(__file__).parents[1] / "evals" / "mn4_reflect_corpus.json"
        ).read_text(encoding="utf-8")
    )
    assert corpus["cases"]
