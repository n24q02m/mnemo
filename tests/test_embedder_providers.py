"""Tests for embedder.py -- cloud provider-specific backends and detection.

Targets: _detect_embedding_provider (env var fallback), _strip_provider,
Jina embed backend, Gemini embed backend, OpenAI embed backend,
_embed_batch_inner no-retry RuntimeError path, CloudEmbeddingBackend routing.
"""

from unittest.mock import MagicMock, patch

import pytest

from mnemo_mcp.embedder import (
    CloudEmbeddingBackend,
    _detect_embedding_provider,
    _is_unsupported_param,
    _strip_provider,
)

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
# CloudEmbeddingBackend -- Jina provider
# ---------------------------------------------------------------------------


class TestJinaEmbedding:
    @patch("httpx.post")
    async def test_jina_embed(self, mock_post):
        """Jina embedding via REST API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                {"index": 1, "embedding": [0.4, 0.5, 0.6]},
            ]
        }
        mock_post.return_value = mock_response

        backend = CloudEmbeddingBackend(
            model="jina_ai/jina-embeddings-v5-text-small",
            api_key="jina_test",
        )
        result = await backend.embed_texts(["hello", "world"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]

    @patch("httpx.post")
    async def test_jina_embed_with_dimensions(self, mock_post):
        """Jina embedding passes dimensions param."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"data": [{"index": 0, "embedding": [0.1]}]}
        mock_post.return_value = mock_response

        backend = CloudEmbeddingBackend(
            model="jina_ai/jina-embeddings-v5-text-small",
            api_key="jina_test",
        )
        await backend.embed_texts(["test"], dimensions=512)

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["dimensions"] == 512

    @patch("httpx.post")
    async def test_jina_embed_unsorted_data(self, mock_post):
        """Jina results are sorted by index."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"index": 1, "embedding": [0.4]},
                {"index": 0, "embedding": [0.1]},
            ]
        }
        mock_post.return_value = mock_response

        backend = CloudEmbeddingBackend(
            model="jina_ai/test",
            api_key="key",
        )
        result = await backend.embed_texts(["a", "b"])
        assert result[0] == [0.1]
        assert result[1] == [0.4]


# ---------------------------------------------------------------------------
# CloudEmbeddingBackend -- Gemini provider
# ---------------------------------------------------------------------------


class TestGeminiEmbedding:
    @patch("google.genai.Client")
    async def test_gemini_embed(self, mock_client_cls):
        """Gemini embedding via google-genai SDK."""
        mock_embedding = MagicMock()
        mock_embedding.values = [0.1, 0.2, 0.3]

        mock_result = MagicMock()
        mock_result.embeddings = [mock_embedding]

        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = mock_result
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(
            model="gemini/gemini-embedding-001",
            api_key="AIza_test",
        )
        result = await backend.embed_texts(["hello"])

        assert len(result) == 1
        assert result[0] == [0.1, 0.2, 0.3]

    @patch("google.genai.Client")
    async def test_gemini_embed_with_dimensions(self, mock_client_cls):
        """Gemini passes output_dimensionality in config."""
        mock_embedding = MagicMock()
        mock_embedding.values = [0.1]

        mock_result = MagicMock()
        mock_result.embeddings = [mock_embedding]

        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = mock_result
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(
            model="gemini/gemini-embedding-001",
            api_key="AIza_test",
        )
        await backend.embed_texts(["test"], dimensions=768)

        call_kwargs = mock_client.models.embed_content.call_args
        config = call_kwargs.kwargs.get("config")
        assert config is not None

    @patch("google.genai.Client")
    async def test_gemini_embed_empty_embeddings(self, mock_client_cls):
        """Gemini handles empty embeddings list."""
        mock_result = MagicMock()
        mock_result.embeddings = None

        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = mock_result
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(
            model="gemini/gemini-embedding-001",
            api_key="AIza_test",
        )
        result = await backend.embed_texts(["test"])
        assert result == []


# ---------------------------------------------------------------------------
# CloudEmbeddingBackend -- OpenAI provider
# ---------------------------------------------------------------------------


class TestOpenAIEmbedding:
    @patch("openai.OpenAI")
    async def test_openai_embed(self, mock_client_cls):
        """OpenAI embedding via SDK."""
        mock_data_0 = MagicMock()
        mock_data_0.index = 0
        mock_data_0.embedding = [0.1, 0.2]

        mock_data_1 = MagicMock()
        mock_data_1.index = 1
        mock_data_1.embedding = [0.3, 0.4]

        mock_response = MagicMock()
        mock_response.data = [mock_data_1, mock_data_0]  # Out of order

        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = mock_response
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(
            model="text-embedding-3-large",
            api_key="sk_test",
        )
        result = await backend.embed_texts(["hello", "world"])

        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]

    @patch("openai.OpenAI")
    async def test_openai_embed_with_dimensions(self, mock_client_cls):
        """OpenAI passes dimensions param."""
        mock_data = MagicMock()
        mock_data.index = 0
        mock_data.embedding = [0.1]

        mock_response = MagicMock()
        mock_response.data = [mock_data]

        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = mock_response
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(
            model="text-embedding-3-large",
            api_key="sk_test",
        )
        await backend.embed_texts(["test"], dimensions=512)

        call_kwargs = mock_client.embeddings.create.call_args
        assert call_kwargs.kwargs.get("dimensions") == 512

    @patch("openai.OpenAI")
    async def test_openai_embed_with_api_base(self, mock_client_cls):
        """OpenAI respects custom api_base."""
        mock_data = MagicMock()
        mock_data.index = 0
        mock_data.embedding = [0.1]

        mock_response = MagicMock()
        mock_response.data = [mock_data]

        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = mock_response
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(
            model="openai/text-embedding-3-large",
            api_key="sk_test",
            api_base="https://proxy.example.com/v1",
        )
        await backend.embed_texts(["test"])

        mock_client_cls.assert_called_with(
            api_key="sk_test",
            base_url="https://proxy.example.com/v1",
        )


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
