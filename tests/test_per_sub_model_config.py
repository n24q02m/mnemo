"""Regression tests for request-scoped relay model, key, and endpoint config."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from mnemo_mcp.credential_state import (
    _current_sub,
    api_base_for_task,
    api_key_for_model,
    detect_llm_provider_key,
    has_llm_provider,
    model_chain_for_task,
    model_for_task,
    store_for_sub,
)
from mnemo_mcp.embedder import CloudEmbeddingBackend
from mnemo_mcp.graph import _has_llm_provider, _llm_completion, _resolve_llm_model
from mnemo_mcp.llm import call_llm
from mnemo_mcp.relay_schema import RELAY_SCHEMA
from mnemo_mcp.reranker import CloudReranker


@pytest.fixture(autouse=True)
def _reset_current_sub():
    token = _current_sub.set(None)
    try:
        yield
    finally:
        _current_sub.reset(token)


def test_per_sub_resolver_isolates_models_keys_and_api_bases(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_MODELS", "openai/global-embedding")
    monkeypatch.setenv("EMBEDDING_API_BASE", "https://env.example/embed")
    monkeypatch.setenv("COHERE_API_KEY", "env-cohere-key")

    store_for_sub(
        "alice",
        {
            "EMBEDDING_MODELS": "cohere/embed-v4.0",
            "EMBEDDING_API_BASE": "https://alice.example/embed",
            "COHERE_API_KEY": "alice-cohere-key",
        },
    )
    store_for_sub(
        "bob",
        {
            "EMBEDDING_MODELS": "jina_ai/jina-embeddings-v5-text-small",
            "EMBEDDING_API_BASE": "https://bob.example/embed",
            "JINA_AI_API_KEY": "bob-jina-key",
        },
    )

    alice_token = _current_sub.set("alice")
    try:
        assert model_chain_for_task("embedding") == ["cohere/embed-v4.0"]
        assert api_base_for_task("EMBEDDING_API_BASE") == (
            "https://alice.example/embed"
        )
        assert api_key_for_model("cohere/embed-v4.0") == "alice-cohere-key"
        assert api_key_for_model("jina_ai/jina-embeddings-v5-text-small") is None
    finally:
        _current_sub.reset(alice_token)

    bob_token = _current_sub.set("bob")
    try:
        assert model_chain_for_task("embedding") == [
            "jina_ai/jina-embeddings-v5-text-small"
        ]
        assert api_base_for_task("EMBEDDING_API_BASE") == ("https://bob.example/embed")
        assert api_key_for_model("jina_ai/jina-embeddings-v5-text-small") == (
            "bob-jina-key"
        )
        assert api_key_for_model("cohere/embed-v4.0") is None
    finally:
        _current_sub.reset(bob_token)


def test_single_user_endpoint_uses_env_but_key_stays_litellm_managed(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDING_API_BASE", "https://env.example/embed")
    monkeypatch.setenv("COHERE_API_KEY", "env-cohere-key")

    assert api_base_for_task("EMBEDDING_API_BASE") == "https://env.example/embed"
    assert api_key_for_model("cohere/embed-v4.0") is None


def test_model_chain_parser_supports_alias_list_and_fallback(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODELS", " first , ,second ")
    assert model_chain_for_task("embedding") == ["first", "second"]
    assert model_for_task("EMBEDDING_MODELS") == "first"

    monkeypatch.delenv("EMBEDDING_MODELS")
    assert model_chain_for_task("embedding", fallback="fallback") == ["fallback"]


def test_model_chain_parser_handles_sequence_invalid_task_and_non_string_value(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    token = _current_sub.set("alice")
    try:
        store_for_sub(
            "alice",
            cast(dict[str, str], {"EMBEDDING_MODELS": ["one", "", 2]}),
        )
        assert model_chain_for_task("embedding") == ["one", "2"]
        store_for_sub(
            "alice",
            cast(dict[str, str], {"EMBEDDING_MODELS": 42}),
        )
        assert model_chain_for_task("embedding") == []
    finally:
        _current_sub.reset(token)

    with pytest.raises(ValueError, match="Unknown model-chain task"):
        model_chain_for_task("unknown")


def test_llm_provider_detection_and_gemini_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    for key in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
        "GOOGLE_VERTEX_EXPRESS_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "global-google-key")
    assert detect_llm_provider_key() == "GOOGLE_API_KEY"
    assert has_llm_provider() is True

    store_for_sub(
        "alice",
        {
            "LLM_MODELS": "gemini/gemini-2.5-flash",
            "GOOGLE_API_KEY": "alice-google-key",
        },
    )
    token = _current_sub.set("alice")
    try:
        assert detect_llm_provider_key() == "GOOGLE_API_KEY"
        assert api_key_for_model("gemini/gemini-2.5-flash") == "alice-google-key"
    finally:
        _current_sub.reset(token)


async def test_embedder_forwards_current_sub_key_and_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COHERE_API_KEY", "env-cohere-key")
    store_for_sub(
        "alice",
        {
            "COHERE_API_KEY": "alice-cohere-key",
            "EMBEDDING_API_BASE": "https://alice.example/embed",
        },
    )
    store_for_sub(
        "bob",
        {
            "COHERE_API_KEY": "bob-cohere-key",
            "EMBEDDING_API_BASE": "https://bob.example/embed",
        },
    )

    calls: list[dict] = []

    async def fake_aembedding(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.1, 0.2])])

    monkeypatch.setattr("mcp_core.llm.aembedding", fake_aembedding)

    for sub, text in (("alice", "a"), ("bob", "b")):
        token = _current_sub.set(sub)
        try:
            await CloudEmbeddingBackend("cohere/embed-v4.0").embed_single(text)
        finally:
            _current_sub.reset(token)

    assert [(call["api_key"], call["api_base"]) for call in calls] == [
        ("alice-cohere-key", "https://alice.example/embed"),
        ("bob-cohere-key", "https://bob.example/embed"),
    ]


def test_reranker_forwards_current_sub_key_and_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COHERE_API_KEY", "env-cohere-key")
    store_for_sub(
        "alice",
        {
            "COHERE_API_KEY": "alice-cohere-key",
            "RERANK_API_BASE": "https://alice.example/rerank",
        },
    )
    store_for_sub(
        "bob",
        {
            "COHERE_API_KEY": "bob-cohere-key",
            "RERANK_API_BASE": "https://bob.example/rerank",
        },
    )

    calls: list[dict] = []

    def fake_rerank(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(results=[SimpleNamespace(index=0, relevance_score=0.9)])

    monkeypatch.setattr("mcp_core.llm.rerank", fake_rerank)

    for sub in ("alice", "bob"):
        token = _current_sub.set(sub)
        try:
            assert CloudReranker("cohere/rerank-v4.0-fast").rerank(
                "query", ["document"], top_n=1
            ) == [(0, 0.9)]
        finally:
            _current_sub.reset(token)

    assert [(call["api_key"], call["api_base"]) for call in calls] == [
        ("alice-cohere-key", "https://alice.example/rerank"),
        ("bob-cohere-key", "https://bob.example/rerank"),
    ]


async def test_llm_dispatch_uses_current_sub_model_key_and_endpoint(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai-key")
    monkeypatch.setenv("LLM_API_BASE", "https://env.example/llm")
    monkeypatch.setenv("LLM_MODELS", "openai=global-model")
    store_for_sub(
        "alice",
        {
            "OPENAI_API_KEY": "alice-openai-key",
            "LLM_API_BASE": "https://alice.example/llm",
            "LLM_MODELS": "openai=alice-model",
        },
    )

    captured: dict = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )

    monkeypatch.setattr("mcp_core.llm.acompletion", fake_acompletion)
    token = _current_sub.set("alice")
    try:
        assert await call_llm("hello") == "ok"
    finally:
        _current_sub.reset(token)

    assert captured["model"] == "openai/alice-model"
    assert captured["api_key"] == "alice-openai-key"
    assert captured["api_base"] == "https://alice.example/llm"


async def test_graph_uses_current_sub_model_key_and_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai-key")
    monkeypatch.setenv("LLM_API_BASE", "https://env.example/llm")
    store_for_sub(
        "alice",
        {
            "OPENAI_API_KEY": "alice-openai-key",
            "LLM_API_BASE": "https://alice.example/llm",
            "LLM_MODELS": "openai=alice-model",
        },
    )

    captured: dict = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )

    class Settings:
        llm_models = "gemini=global-model"

    monkeypatch.setattr("mcp_core.llm.acompletion", fake_acompletion)
    token = _current_sub.set("alice")
    try:
        assert _has_llm_provider() is True
        assert _resolve_llm_model(Settings()) == "openai/alice-model"
        assert (
            await _llm_completion(
                "openai/alice-model", [{"role": "user", "content": "hello"}]
            )
            == "ok"
        )
    finally:
        _current_sub.reset(token)

    assert captured["model"] == "openai/alice-model"
    assert captured["api_key"] == "alice-openai-key"
    assert captured["api_base"] == "https://alice.example/llm"


def test_relay_schema_exposes_per_task_endpoints_and_vertex_key():
    fields = {field["key"]: field for field in RELAY_SCHEMA["fields"]}

    for key in ("EMBEDDING_API_BASE", "RERANK_API_BASE", "LLM_API_BASE"):
        assert fields[key]["type"] == "url"
        assert fields[key]["required"] is False

    assert fields["GOOGLE_VERTEX_EXPRESS_API_KEY"]["type"] == "password"
    assert fields["GOOGLE_VERTEX_EXPRESS_API_KEY"]["derived"] is True
