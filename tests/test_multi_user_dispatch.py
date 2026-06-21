"""Dispatch-level multi-user credential isolation tests.

The accessor-level tests in ``test_multi_user.py`` prove that
``credentials_for_current_request()`` returns the right per-``sub`` dict. They
do NOT prove that the per-``sub`` key actually reaches the live litellm call
during embed / rerank / LLM dispatch -- which is the crg-class bug this module
guards: the embed / rerank backends were module-level singletons created at
startup with ``api_key=None`` (litellm read the process env), and ``acomplete``
called ``acompletion`` with no ``api_key``, so a relay-submitted per-``sub`` key
(``store_for_sub``) never reached embed / rerank / LLM in multi-user mode.

These tests mock the lowest litellm passthrough (``mcp_core.llm.aembedding`` /
``acompletion`` / ``rerank``) and assert the ``api_key=`` kwarg equals the per-
``sub`` value -- and that a second ``sub`` driving the SAME process does not see
the first ``sub``'s key.

Spec: ``~/.claude/skills/mcp-dev/references/multi-user-pattern.md`` +
``2026-05-01-stdio-pure-http-multiuser.md`` §4.2.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _credential_secret(monkeypatch):
    """Per-sub config routes through PerPluginStore, whose multi-user key
    derivation requires CREDENTIAL_SECRET. Real deployments always set it."""
    monkeypatch.setenv("CREDENTIAL_SECRET", "test-secret")


@pytest.fixture(autouse=True)
def _reset_current_sub():
    """Guarantee ``_current_sub`` is ``None`` before/after every test so a sub
    cannot leak across tests and mask an isolation bug."""
    from mnemo_mcp.credential_state import _current_sub

    token = _current_sub.set(None)
    try:
        yield
    finally:
        _current_sub.reset(token)


@pytest.fixture(autouse=True)
def _clean_cloud_env(monkeypatch):
    """Clear all cloud keys from the process env so a leaked env value cannot
    accidentally satisfy an assertion (the whole point is that multi-user
    dispatch must NOT read process env)."""
    from mnemo_mcp.credential_state import CLOUD_KEYS

    for key in CLOUD_KEYS:
        monkeypatch.delenv(key, raising=False)


def _embed_resp(*vectors):
    return SimpleNamespace(
        data=[
            SimpleNamespace(index=i, embedding=list(v)) for i, v in enumerate(vectors)
        ]
    )


# ---------------------------------------------------------------------------
# api_key_for_model helper
# ---------------------------------------------------------------------------


def test_api_key_for_model_single_user_returns_none(monkeypatch):
    """Single-user (no ``_current_sub``): helper returns ``None`` so litellm
    keeps reading the key from env (singleton behaviour unchanged)."""
    monkeypatch.setenv("JINA_AI_API_KEY", "env-key")
    from mnemo_mcp.credential_state import api_key_for_model

    assert api_key_for_model("jina_ai/jina-embeddings-v5-text-small") is None


def test_api_key_for_model_resolves_per_sub(tmp_path, monkeypatch):
    """Multi-user: helper maps model -> key env var -> per-sub value."""
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import (
        _current_sub,
        api_key_for_model,
        store_for_sub,
    )

    store_for_sub("alice", {"JINA_AI_API_KEY": "alice-jina"})
    token = _current_sub.set("alice")
    try:
        assert (
            api_key_for_model("jina_ai/jina-embeddings-v5-text-small") == "alice-jina"
        )
        # A provider Alice did not configure resolves to None, not a crash.
        assert api_key_for_model("cohere/rerank-v3.5") is None
    finally:
        _current_sub.reset(token)


# ---------------------------------------------------------------------------
# embed dispatch
# ---------------------------------------------------------------------------


async def test_embed_passes_per_sub_key_to_litellm(tmp_path, monkeypatch):
    """``_embed`` under an active sub must pass that sub's key to ``aembedding``,
    NOT ``None`` (which would let litellm fall back to the process env)."""
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import _current_sub, store_for_sub
    from mnemo_mcp.server import _embed

    store_for_sub("alice", {"JINA_AI_API_KEY": "alice-embed-key"})

    mock = AsyncMock(return_value=_embed_resp([0.1, 0.2, 0.3]))
    token = _current_sub.set("alice")
    try:
        with patch("mcp_core.llm.aembedding", mock):
            result = await _embed("hello", "jina_ai/jina-embeddings-v5-text-small", 3)
    finally:
        _current_sub.reset(token)

    assert result == [0.1, 0.2, 0.3]
    mock.assert_awaited_once()
    assert mock.call_args.kwargs.get("api_key") == "alice-embed-key"


async def test_embed_second_sub_does_not_see_first_sub_key(tmp_path, monkeypatch):
    """Two subs drive ``_embed`` in the same process; each litellm call must
    carry only its own sub's key (no bleed via a cached singleton)."""
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import _current_sub, store_for_sub
    from mnemo_mcp.server import _embed

    store_for_sub("alice", {"JINA_AI_API_KEY": "alice-embed-key"})
    store_for_sub("bob", {"JINA_AI_API_KEY": "bob-embed-key"})

    mock = AsyncMock(return_value=_embed_resp([0.1]))

    # Alice's request first.
    token = _current_sub.set("alice")
    try:
        with patch("mcp_core.llm.aembedding", mock):
            await _embed("q", "jina_ai/jina-embeddings-v5-text-small", 1)
    finally:
        _current_sub.reset(token)
    assert mock.call_args.kwargs.get("api_key") == "alice-embed-key"

    # Bob's request second -- must NOT inherit Alice's key.
    token = _current_sub.set("bob")
    try:
        with patch("mcp_core.llm.aembedding", mock):
            await _embed("q", "jina_ai/jina-embeddings-v5-text-small", 1)
    finally:
        _current_sub.reset(token)
    assert mock.call_args.kwargs.get("api_key") == "bob-embed-key"


# ---------------------------------------------------------------------------
# rerank dispatch
# ---------------------------------------------------------------------------


async def test_rerank_passes_per_sub_key_to_litellm(tmp_path, monkeypatch):
    """The reranker invoked from ``_handle_search`` under an active sub must
    pass that sub's key to ``mcp_core.llm.rerank``."""
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    # A cloud rerank chain is forced so the request-scoped CloudReranker path
    # is exercised regardless of which provider keys exist in the process env.
    monkeypatch.setattr("mnemo_mcp.config.settings.rerank_models", "cohere/rerank-v3.5")
    from mnemo_mcp.credential_state import _current_sub, store_for_sub
    from mnemo_mcp.server import _resolve_request_reranker

    store_for_sub("alice", {"COHERE_API_KEY": "alice-rerank-key"})

    rerank_resp = SimpleNamespace(
        results=[SimpleNamespace(index=0, relevance_score=0.9)]
    )
    mock = MagicMock(return_value=rerank_resp)

    token = _current_sub.set("alice")
    try:
        reranker = _resolve_request_reranker(MagicMock(name="startup_singleton"))
        with patch("mcp_core.llm.rerank", mock):
            ranked = reranker.rerank("q", ["doc one", "doc two"], top_n=1)
    finally:
        _current_sub.reset(token)

    assert ranked == [(0, 0.9)]
    mock.assert_called_once()
    assert mock.call_args.kwargs.get("api_key") == "alice-rerank-key"


async def test_rerank_second_sub_does_not_see_first_sub_key(tmp_path, monkeypatch):
    """Two subs rerank in the same process; no key bleed via singleton."""
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("mnemo_mcp.config.settings.rerank_models", "cohere/rerank-v3.5")
    from mnemo_mcp.credential_state import _current_sub, store_for_sub
    from mnemo_mcp.server import _resolve_request_reranker

    store_for_sub("alice", {"COHERE_API_KEY": "alice-rerank-key"})
    store_for_sub("bob", {"COHERE_API_KEY": "bob-rerank-key"})

    rerank_resp = SimpleNamespace(
        results=[SimpleNamespace(index=0, relevance_score=0.9)]
    )
    mock = MagicMock(return_value=rerank_resp)
    startup_singleton = MagicMock(name="startup_singleton")

    token = _current_sub.set("alice")
    try:
        with patch("mcp_core.llm.rerank", mock):
            _resolve_request_reranker(startup_singleton).rerank("q", ["a", "b"], 1)
    finally:
        _current_sub.reset(token)
    assert mock.call_args.kwargs.get("api_key") == "alice-rerank-key"

    token = _current_sub.set("bob")
    try:
        with patch("mcp_core.llm.rerank", mock):
            _resolve_request_reranker(startup_singleton).rerank("q", ["a", "b"], 1)
    finally:
        _current_sub.reset(token)
    assert mock.call_args.kwargs.get("api_key") == "bob-rerank-key"


# ---------------------------------------------------------------------------
# LLM dispatch (acomplete)
# ---------------------------------------------------------------------------


async def test_acomplete_passes_per_sub_key_to_litellm(tmp_path, monkeypatch):
    """``acomplete`` under an active sub must pass that sub's key for the
    resolved chain model to ``acompletion``."""
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import _current_sub, store_for_sub
    from mnemo_mcp.llm import acomplete

    store_for_sub("alice", {"GEMINI_API_KEY": "alice-gemini-key"})

    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))]
    )
    mock = AsyncMock(return_value=resp)

    token = _current_sub.set("alice")
    try:
        with patch("mcp_core.llm.acompletion", mock):
            out = await acomplete(
                [{"role": "user", "content": "ping"}],
                models=["gemini/gemini-3-flash-preview"],
            )
    finally:
        _current_sub.reset(token)

    assert out == "hi"
    mock.assert_awaited_once()
    assert mock.call_args.kwargs.get("api_key") == "alice-gemini-key"


async def test_acomplete_second_sub_does_not_see_first_sub_key(tmp_path, monkeypatch):
    """Two subs drive ``acomplete`` in the same process; no key bleed."""
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import _current_sub, store_for_sub
    from mnemo_mcp.llm import acomplete

    store_for_sub("alice", {"GEMINI_API_KEY": "alice-gemini-key"})
    store_for_sub("bob", {"GEMINI_API_KEY": "bob-gemini-key"})

    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
    )
    mock = AsyncMock(return_value=resp)

    token = _current_sub.set("alice")
    try:
        with patch("mcp_core.llm.acompletion", mock):
            await acomplete(
                [{"role": "user", "content": "x"}],
                models=["gemini/gemini-3-flash-preview"],
            )
    finally:
        _current_sub.reset(token)
    assert mock.call_args.kwargs.get("api_key") == "alice-gemini-key"

    token = _current_sub.set("bob")
    try:
        with patch("mcp_core.llm.acompletion", mock):
            await acomplete(
                [{"role": "user", "content": "x"}],
                models=["gemini/gemini-3-flash-preview"],
            )
    finally:
        _current_sub.reset(token)
    assert mock.call_args.kwargs.get("api_key") == "bob-gemini-key"


async def test_acomplete_single_user_omits_api_key(monkeypatch):
    """Single-user (no sub): ``acomplete`` must NOT inject api_key so litellm
    keeps reading from env (existing behaviour preserved)."""
    monkeypatch.setenv("GEMINI_API_KEY", "env-gemini")
    from mnemo_mcp.llm import acomplete

    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
    )
    mock = AsyncMock(return_value=resp)
    with patch("mcp_core.llm.acompletion", mock):
        await acomplete(
            [{"role": "user", "content": "x"}],
            models=["gemini/gemini-3-flash-preview"],
        )
    # api_key omitted (None) -> litellm resolves from env.
    assert mock.call_args.kwargs.get("api_key") is None
