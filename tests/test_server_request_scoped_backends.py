from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from mcp.server.fastmcp import Context

from mnemo_mcp.credential_state import _current_sub, store_for_sub
from mnemo_mcp.server import (
    _backend_cache_key,
    _get_request_embedding,
    _get_request_reranker,
    _request_backend_cache,
)


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(request_context=SimpleNamespace(lifespan_context={}))


def _typed_ctx() -> Context:
    return cast(Context, _ctx())


def test_backend_cache_key_is_subject_scoped_without_secret():
    key = _backend_cache_key("embedding", "cohere/embed-v4.0", None, "alice")

    assert key == ("embedding", "cohere/embed-v4.0", None, "alice")
    assert "api-key" not in repr(key)
    assert key != _backend_cache_key("embedding", "cohere/embed-v4.0", None, "bob")


def test_embedding_backend_is_scoped_to_current_sub(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    store_for_sub(
        "alice",
        {
            "EMBEDDING_MODELS": "cohere/embed-v4.0",
            "EMBEDDING_API_BASE": "https://alice.example/embed",
            "COHERE_API_KEY": "alice-key",
        },
    )

    token = _current_sub.set("alice")
    try:
        model, backend = _get_request_embedding(_typed_ctx(), "global-model", 768)
    finally:
        _current_sub.reset(token)

    assert model == "cohere/embed-v4.0"
    assert backend is not None
    assert backend.model == "cohere/embed-v4.0"
    assert backend.api_base == "https://alice.example/embed"
    assert backend.api_key == "alice-key"


def test_embedding_backend_does_not_fall_back_to_global_sub_config(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))

    token = _current_sub.set("missing-sub")
    try:
        model, backend = _get_request_embedding(_typed_ctx(), "global-model", 768)
    finally:
        _current_sub.reset(token)

    assert model is None
    assert backend is None


def test_embedding_backend_refreshes_after_credential_rotation(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    store_for_sub(
        "alice",
        {
            "EMBEDDING_MODELS": "cohere/embed-v4.0",
            "EMBEDDING_API_BASE": "https://alice.example/embed",
            "COHERE_API_KEY": "old-key",
        },
    )

    ctx = _typed_ctx()
    token = _current_sub.set("alice")
    try:
        _, first = _get_request_embedding(ctx, "global-model", 768)
        store_for_sub(
            "alice",
            {
                "EMBEDDING_MODELS": "cohere/embed-v4.0",
                "EMBEDDING_API_BASE": "https://alice.example/embed",
                "COHERE_API_KEY": "rotated-key",
            },
        )
        _, second = _get_request_embedding(ctx, "global-model", 768)
    finally:
        _current_sub.reset(token)

    assert first is not second
    assert second is not None
    assert second.api_key == "rotated-key"


def test_request_backend_cache_is_empty_without_context():
    assert _request_backend_cache(None, "request_embedding_backends") == {}


def test_embedding_backend_reuses_cache_for_unchanged_credentials(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    store_for_sub(
        "alice",
        {
            "EMBEDDING_MODELS": "cohere/embed-v4.0",
            "COHERE_API_KEY": "stable-key",
        },
    )

    ctx = _typed_ctx()
    token = _current_sub.set("alice")
    try:
        _, first = _get_request_embedding(ctx, "global-model", 768)
        _, second = _get_request_embedding(ctx, "global-model", 768)
    finally:
        _current_sub.reset(token)

    assert second is first


def test_embedding_backend_is_unavailable_without_subject_key(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    store_for_sub("alice", {"EMBEDDING_MODELS": "cohere/embed-v4.0"})

    token = _current_sub.set("alice")
    try:
        assert _get_request_embedding(_typed_ctx(), "global-model", 768) == (None, None)
    finally:
        _current_sub.reset(token)


def test_reranker_backend_is_scoped_to_current_sub(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    store_for_sub(
        "bob",
        {
            "RERANK_MODELS": "cohere/rerank-v4.0-fast",
            "RERANK_API_BASE": "https://bob.example/rerank",
            "COHERE_API_KEY": "bob-key",
        },
    )

    token = _current_sub.set("bob")
    try:
        backend = _get_request_reranker(_typed_ctx())
    finally:
        _current_sub.reset(token)

    assert backend is not None
    assert backend.model == "cohere/rerank-v4.0-fast"
    assert backend.api_base == "https://bob.example/rerank"
    assert backend.api_key == "bob-key"


def test_reranker_is_unavailable_without_model_or_key(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    store_for_sub("no-model", {})
    store_for_sub("no-key", {"RERANK_MODELS": "cohere/rerank-v4.0-fast"})

    no_model_token = _current_sub.set("no-model")
    try:
        assert _get_request_reranker(_typed_ctx()) is None
    finally:
        _current_sub.reset(no_model_token)

    no_key_token = _current_sub.set("no-key")
    try:
        assert _get_request_reranker(_typed_ctx()) is None
    finally:
        _current_sub.reset(no_key_token)


def test_reranker_reuses_cache_for_unchanged_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    store_for_sub(
        "bob",
        {
            "RERANK_MODELS": "cohere/rerank-v4.0-fast",
            "COHERE_API_KEY": "stable-key",
        },
    )

    ctx = _typed_ctx()
    token = _current_sub.set("bob")
    try:
        first = _get_request_reranker(ctx)
        second = _get_request_reranker(ctx)
    finally:
        _current_sub.reset(token)

    assert second is first
