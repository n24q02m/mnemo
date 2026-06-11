"""Tests for embedder.py -- cloud provider-specific backends and detection.

Targets: _detect_embedding_provider (env var fallback), _strip_provider,
Jina embed backend, Gemini embed backend, OpenAI embed backend,
_embed_batch_inner no-retry RuntimeError path, CloudEmbeddingBackend routing.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from mnemo_mcp.embedder import (
    CloudEmbeddingBackend,
    _detect_embedding_provider,
    _is_unsupported_param,
    _parse_embeddings,
    _strip_provider,
)


def _embedding_response(*vectors, indexed=True):
    """Build a litellm-shaped embedding response (resp.data list)."""
    data = [SimpleNamespace(index=i, embedding=list(v)) for i, v in enumerate(vectors)]
    return SimpleNamespace(data=data if indexed else list(vectors))


# ---------------------------------------------------------------------------
# _detect_embedding_provider
# ---------------------------------------------------------------------------


class TestDetectEmbeddingProvider:
    def test_jina_model_prefix(self):
        assert _detect_embedding_provider("jina_ai/jina-embeddings-v5") == "jina"

    def test_jina_short_prefix(self):
        assert _detect_embedding_provider("jina-embeddings-v5") == "jina"

    def test_gemini_model_prefix(self):
        assert _detect_embedding_provider("gemini/gemini-embedding-001") == "gemini"

    def test_gemini_in_name(self):
        assert _detect_embedding_provider("my-gemini-model") == "gemini"

    def test_cohere_embed_prefix(self):
        assert _detect_embedding_provider("embed-multilingual-v3.0") == "cohere"

    def test_cohere_provider_prefix(self):
        assert _detect_embedding_provider("cohere/embed-english-v3.0") == "cohere"

    def test_openai_text_embedding(self):
        assert _detect_embedding_provider("text-embedding-3-large") == "openai"

    def test_openai_provider_prefix(self):
        assert _detect_embedding_provider("openai/text-embedding-ada-002") == "openai"

    def test_fallback_jina_env(self, monkeypatch):
        """Falls back to jina when JINA_AI_API_KEY is set."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("JINA_AI_API_KEY", "jina_test")
        assert _detect_embedding_provider("unknown-model") == "jina"

    def test_fallback_gemini_env(self, monkeypatch):
        """Falls back to gemini when GEMINI_API_KEY is set."""
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "AIza_test")
        assert _detect_embedding_provider("unknown-model") == "gemini"

    def test_fallback_google_api_key_env(self, monkeypatch):
        """Falls back to gemini when GOOGLE_API_KEY is set."""
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "AIza_google")
        assert _detect_embedding_provider("unknown-model") == "gemini"

    def test_fallback_openai_env(self, monkeypatch):
        """Falls back to openai when OPENAI_API_KEY is set."""
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")
        assert _detect_embedding_provider("unknown-model") == "openai"

    def test_fallback_cohere_default(self, monkeypatch):
        """Falls back to cohere when no env vars are set."""
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert _detect_embedding_provider("unknown-model") == "cohere"


class TestStripProvider:
    def test_with_prefix(self):
        assert _strip_provider("gemini/gemini-embedding-001") == "gemini-embedding-001"

    def test_without_prefix(self):
        assert _strip_provider("embed-multilingual-v3.0") == "embed-multilingual-v3.0"

    def test_multiple_slashes(self):
        assert _strip_provider("a/b/c") == "b/c"


# ---------------------------------------------------------------------------
# _is_unsupported_param
# ---------------------------------------------------------------------------


class TestIsUnsupportedParam:
    def test_unsupported_dimensions(self):
        exc = Exception("does not support parameters: {'dimensions': 768}")
        assert _is_unsupported_param(exc, "dimensions") is True

    def test_output_dimension_not_supported(self):
        exc = Exception("output_dimension is not supported for this model")
        assert _is_unsupported_param(exc, "dimensions") is True

    def test_not_a_valid_param(self):
        exc = Exception("dimension is not a valid parameter")
        assert _is_unsupported_param(exc, "dimensions") is True

    def test_unrelated_error(self):
        exc = Exception("Invalid API key")
        assert _is_unsupported_param(exc, "dimensions") is False


# ---------------------------------------------------------------------------
# _litellm_model mapping (provider -> litellm 'provider/model')
# ---------------------------------------------------------------------------


class TestLitellmModelMapping:
    def test_jina_bare_name_prefixed(self):
        backend = CloudEmbeddingBackend(model="jina-embeddings-v5", api_key="key")
        assert backend._litellm_model() == "jina_ai/jina-embeddings-v5"

    def test_gemini_bare_name_prefixed(self):
        backend = CloudEmbeddingBackend(model="gemini-embedding-001", api_key="key")
        assert backend._litellm_model() == "gemini/gemini-embedding-001"

    def test_cohere_bare_name_prefixed(self):
        backend = CloudEmbeddingBackend(model="embed-multilingual-v3.0", api_key="key")
        assert backend._litellm_model() == "cohere/embed-multilingual-v3.0"

    def test_openai_bare_name_passthrough(self):
        backend = CloudEmbeddingBackend(model="text-embedding-3-large", api_key="key")
        assert backend._litellm_model() == "text-embedding-3-large"

    def test_slash_form_passthrough(self):
        backend = CloudEmbeddingBackend(
            model="jina_ai/jina-embeddings-v5", api_key="key"
        )
        assert backend._litellm_model() == "jina_ai/jina-embeddings-v5"


# ---------------------------------------------------------------------------
# CloudEmbeddingBackend -- litellm passthrough (aembedding)
# ---------------------------------------------------------------------------


class TestCloudEmbeddingPassthrough:
    async def test_jina_embed(self):
        """Embeds via aembedding and returns sorted vectors."""
        mock = AsyncMock(
            return_value=_embedding_response([0.1, 0.2, 0.3], [0.4, 0.5, 0.6])
        )
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(
                model="jina_ai/jina-embeddings-v5-text-small", api_key="jina_test"
            )
            result = await backend.embed_texts(["hello", "world"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]
        assert mock.call_args.kwargs["model"] == "jina_ai/jina-embeddings-v5-text-small"

    async def test_dimensions_forwarded(self):
        """dimensions is forwarded to aembedding."""
        mock = AsyncMock(return_value=_embedding_response([0.1]))
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(
                model="jina_ai/jina-embeddings-v5-text-small", api_key="jina_test"
            )
            await backend.embed_texts(["test"], dimensions=512)

        assert mock.call_args.kwargs["dimensions"] == 512

    async def test_results_sorted_by_index(self):
        """Out-of-order embedding data is sorted by index."""
        resp = SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.4]),
                SimpleNamespace(index=0, embedding=[0.1]),
            ]
        )
        mock = AsyncMock(return_value=resp)
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(model="jina_ai/test", api_key="key")
            result = await backend.embed_texts(["a", "b"])
        assert result[0] == [0.1]
        assert result[1] == [0.4]

    async def test_cohere_input_type_forwarded(self):
        """Cohere provider passes input_type='search_document'."""
        mock = AsyncMock(return_value=_embedding_response([0.1]))
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(
                model="embed-multilingual-v3.0", api_key="key"
            )
            await backend.embed_texts(["test"])
        assert mock.call_args.kwargs["input_type"] == "search_document"
        assert mock.call_args.kwargs["model"] == "cohere/embed-multilingual-v3.0"

    async def test_none_data_returns_empty(self):
        """resp.data=None is guarded and yields []."""
        mock = AsyncMock(return_value=SimpleNamespace(data=None))
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(
                model="gemini/gemini-embedding-001", api_key="AIza_test"
            )
            result = await backend.embed_texts(["test"])
        assert result == []

    async def test_dict_items_parsed(self):
        """Embedding items may be plain dicts."""
        resp = SimpleNamespace(
            data=[{"index": 0, "embedding": [0.7, 0.8]}],
        )
        mock = AsyncMock(return_value=resp)
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(
                model="text-embedding-3-large", api_key="sk_test"
            )
            result = await backend.embed_texts(["x"])
        assert result == [[0.7, 0.8]]

    async def test_api_base_forwarded(self):
        """Custom api_base flows through to aembedding."""
        mock = AsyncMock(return_value=_embedding_response([0.1]))
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(
                model="openai/text-embedding-3-large",
                api_key="sk_test",
                api_base="https://proxy.example.com/v1",
            )
            await backend.embed_texts(["test"])
        assert mock.call_args.kwargs["api_base"] == "https://proxy.example.com/v1"
        assert mock.call_args.kwargs["api_key"] == "sk_test"


# ---------------------------------------------------------------------------
# _parse_embeddings shape handling
# ---------------------------------------------------------------------------


class TestParseEmbeddings:
    def test_pydantic_items(self):
        resp = SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.4]),
                SimpleNamespace(index=0, embedding=[0.1]),
            ]
        )
        assert _parse_embeddings(resp) == [[0.1], [0.4]]

    def test_dict_items(self):
        resp = SimpleNamespace(
            data=[{"index": 0, "embedding": [0.1]}, {"index": 1, "embedding": [0.2]}]
        )
        assert _parse_embeddings(resp) == [[0.1], [0.2]]

    def test_none_data(self):
        assert _parse_embeddings(SimpleNamespace(data=None)) == []


# ---------------------------------------------------------------------------
# CloudEmbeddingBackend -- _call_provider routing
# ---------------------------------------------------------------------------


class TestCallProviderRouting:
    def test_routes_to_jina(self):
        backend = CloudEmbeddingBackend(model="jina_ai/test", api_key="key")
        assert backend._provider == "jina"

    def test_routes_to_gemini(self):
        backend = CloudEmbeddingBackend(model="gemini/test", api_key="key")
        assert backend._provider == "gemini"

    def test_routes_to_openai(self):
        backend = CloudEmbeddingBackend(model="text-embedding-3-large", api_key="key")
        assert backend._provider == "openai"

    def test_routes_to_cohere(self):
        backend = CloudEmbeddingBackend(model="embed-multilingual-v3.0", api_key="key")
        assert backend._provider == "cohere"


# ---------------------------------------------------------------------------
# CloudEmbeddingBackend -- _embed_batch_inner no retries RuntimeError
# ---------------------------------------------------------------------------


class TestEmbedBatchInnerEdge:
    async def test_no_retries_runtime_error(self):
        """Raises RuntimeError when no retries were attempted (last_exc is None).

        This path is technically unreachable but is a defensive safeguard.
        We test it by mocking MAX_RETRIES to 0.
        """
        backend = CloudEmbeddingBackend(model="embed-multilingual-v3.0", api_key="key")

        with patch("mnemo_mcp.embedder.MAX_RETRIES", 0):
            with pytest.raises(RuntimeError, match="no retries attempted"):
                await backend._embed_batch_inner(["test"])
