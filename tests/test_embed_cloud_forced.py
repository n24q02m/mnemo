"""On Cloudflare the embedding/rerank backend MUST be cloud (no 570MB ONNX).

The container forces cloud by setting EMBEDDING_MODELS / RERANK_MODELS (Jina) via
wrangler vars; config.py infers cloud from a non-empty chain. This is the
regression gate proving that lever is honoured.

Note on the "empty -> local" fallback: an EMPTY *_MODELS chain does NOT mean
local unconditionally -- config._chain() falls back to a curated default chain
filtered to whichever provider keys are actually configured. So local only
results when there is no usable provider key. These tests clear the deprecated
backend levers + every provider key so the assertions are deterministic
regardless of the ambient process env (which other tests populate).
"""

from mnemo_mcp.config import Settings

_DEPRECATED_LEVERS = (
    "EMBEDDING_BACKEND",
    "RERANK_BACKEND",
    "EMBEDDING_MODEL",
    "RERANK_MODEL",
)
_PROVIDER_KEYS = (
    "JINA_AI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
)


def test_cloud_chain_forces_cloud_backend(monkeypatch):
    for var in _DEPRECATED_LEVERS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("JINA_AI_API_KEY", "jina_xxx")
    s = Settings(
        embedding_models="jina_ai/jina-embeddings-v5-text-small",
        rerank_models="jina_ai/jina-reranker-v3",
    )
    assert s.resolve_embedding_backend() == "cloud"
    assert s.resolve_rerank_backend() == "cloud"


def test_empty_chain_falls_to_local(monkeypatch):
    # local only when no model chain AND no provider key makes the curated
    # default chain usable -- clear every lever + key for a deterministic assert.
    for var in (*_DEPRECATED_LEVERS, *_PROVIDER_KEYS):
        monkeypatch.delenv(var, raising=False)
    s = Settings(
        embedding_models="",
        embedding_model="",
        rerank_models="",
        rerank_model="",
        rerank_enabled=True,
        api_keys="",
    )
    assert s.resolve_embedding_backend() == "local"
    assert s.resolve_rerank_backend() == "local"
