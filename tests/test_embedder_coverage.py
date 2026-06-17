import os
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from mnemo_mcp.embedder import (
    CloudEmbeddingBackend,
    Qwen3EmbedBackend,
    _detect_embedding_provider,
    _strip_provider,
)


class TestQwen3EmbedBackendCoverage:
    @patch("mnemo_mcp.embedder.Qwen3EmbedBackend._get_model")
    async def test_embed_single_query(self, mock_get_model):
        mock_model = MagicMock()
        mock_model.query_embed.side_effect = lambda text, **kwargs: iter(
            [np.array([0.1, 0.2])]
        )
        mock_get_model.return_value = mock_model

        backend = Qwen3EmbedBackend()
        # Test with dimensions
        result = await backend.embed_single_query("query", dimensions=2)
        assert result == [0.1, 0.2]
        mock_model.query_embed.assert_called_with("query", dim=2)

        # Test without dimensions to cover 472->474 branch
        result = await backend.embed_single_query("query")
        assert result == [0.1, 0.2]
        mock_model.query_embed.assert_called_with("query")

    @patch("mnemo_mcp.embedder.Qwen3EmbedBackend._get_model")
    async def test_embed_texts_inner(self, mock_get_model):
        mock_model = MagicMock()
        mock_model.embed.side_effect = lambda texts, **kwargs: iter(
            [np.array([0.1, 0.2])]
        )
        mock_get_model.return_value = mock_model

        backend = Qwen3EmbedBackend()
        # Test with dimensions
        result = await backend.embed_texts(["text"], dimensions=2)
        assert result == [[0.1, 0.2]]
        mock_model.embed.assert_called_with(["text"], dim=2)

        # Test without dimensions to cover 446->448 branch
        result = await backend.embed_texts(["text"])
        assert result == [[0.1, 0.2]]
        mock_model.embed.assert_called_with(["text"])

    @patch("mnemo_mcp.embedder.Qwen3EmbedBackend._get_model")
    async def test_embed_texts_empty(self, mock_get_model):
        backend = Qwen3EmbedBackend()
        result = await backend.embed_texts([])
        assert result == []
        mock_get_model.assert_not_called()

    def test_get_model_lazy_loading(self):
        mock_text_embedding = MagicMock()
        with patch("mnemo_mcp.embedder.logger") as mock_logger:
            with patch.dict(
                "sys.modules",
                {"qwen3_embed": MagicMock(TextEmbedding=mock_text_embedding)},
            ):
                backend = Qwen3EmbedBackend()
                model1 = backend._get_model()
                model2 = backend._get_model()

                assert model1 == mock_text_embedding.return_value
                assert model1 == model2
                mock_text_embedding.assert_called_once()
                mock_logger.warning.assert_called_once()
                mock_logger.info.assert_called_once()

    @patch("mnemo_mcp.embedder.Qwen3EmbedBackend._get_model")
    def test_check_available_empty(self, mock_get_model):
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([])
        mock_get_model.return_value = mock_model

        backend = Qwen3EmbedBackend()
        assert backend.check_available() == 0


class TestCloudEmbeddingBackendCoverage:
    def test_litellm_model_mapping(self):
        # Case: slash in model name (line 199)
        b1 = CloudEmbeddingBackend(model="provider/custom-model")
        assert b1._litellm_model() == "provider/custom-model"

        # Case: jina provider (line 201)
        b2 = CloudEmbeddingBackend(model="jina-embeddings-v2")
        assert b2._litellm_model() == "jina_ai/jina-embeddings-v2"

        # Case: gemini provider (line 203)
        b3 = CloudEmbeddingBackend(model="gemini-embedding-exp")
        assert b3._litellm_model() == "gemini/gemini-embedding-exp"

        # Case: cohere provider (line 205)
        b_cohere = CloudEmbeddingBackend(model="embed-multilingual-v3.0")
        assert b_cohere._litellm_model() == "cohere/embed-multilingual-v3.0"

        # Case: default/openai (line 207)
        b4 = CloudEmbeddingBackend(model="text-embedding-3-small")
        assert b4._litellm_model() == "text-embedding-3-small"

    def test_build_kwargs_cohere(self):
        # Case: cohere provider (line 214->216)
        b = CloudEmbeddingBackend(model="embed-english-v3.0")
        assert b._provider == "cohere"

        # Test WITH dimensions (covers 213 and 214->215)
        kwargs = b._build_kwargs(dimensions=1024)
        assert kwargs["input_type"] == "search_document"
        assert kwargs["dimensions"] == 1024

        # Test WITHOUT dimensions
        kwargs_no_dim = b._build_kwargs(dimensions=None)
        assert kwargs_no_dim["input_type"] == "search_document"
        assert "dimensions" not in kwargs_no_dim

    def test_build_kwargs_non_cohere(self):
        # Case: non-cohere provider (covers 214->216 False branch)
        b = CloudEmbeddingBackend(model="text-embedding-3-small")
        assert b._provider == "openai"
        kwargs = b._build_kwargs(dimensions=1024)
        assert "input_type" not in kwargs
        assert kwargs["dimensions"] == 1024

    @patch(
        "mnemo_mcp.embedder.CloudEmbeddingBackend._call_provider",
        new_callable=AsyncMock,
    )
    async def test_embed_texts_retry_loop_failure(self, mock_call):
        # Test retry loop (lines 268-302) and RuntimeError (line 305)
        with patch("mnemo_mcp.embedder.MAX_RETRIES", 0):
            backend = CloudEmbeddingBackend(model="test")
            with pytest.raises(RuntimeError, match="no retries attempted"):
                await backend.embed_texts(["test"])

    @patch(
        "mnemo_mcp.embedder.CloudEmbeddingBackend._call_provider",
        new_callable=AsyncMock,
    )
    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_embed_texts_local_truncation(self, mock_sleep, mock_call):
        # Test local truncation (line 274)
        mock_call.return_value = [[0.1, 0.2, 0.3]]
        backend = CloudEmbeddingBackend(model="test")
        result = await backend.embed_texts(["test"], dimensions=2)
        assert result == [[0.1, 0.2]]


class TestUtilsCoverage:
    def test_detect_embedding_provider_prefixes(self):
        assert _detect_embedding_provider("jina_ai/test") == "jina"
        assert _detect_embedding_provider("jina-test") == "jina"
        assert _detect_embedding_provider("gemini/test") == "gemini"
        assert _detect_embedding_provider("some-gemini-model") == "gemini"
        assert _detect_embedding_provider("embed-english") == "cohere"
        assert _detect_embedding_provider("cohere/model") == "cohere"
        assert _detect_embedding_provider("text-embedding-3") == "openai"
        assert _detect_embedding_provider("openai/model") == "openai"

    def test_detect_embedding_provider_env_vars(self):
        # Priority order: Jina -> Gemini -> OpenAI -> Cohere
        with patch.dict(os.environ, {"JINA_AI_API_KEY": "key"}, clear=True):
            assert _detect_embedding_provider("unknown") == "jina"

        with patch.dict(os.environ, {"GEMINI_API_KEY": "key"}, clear=True):
            assert _detect_embedding_provider("unknown") == "gemini"

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "key"}, clear=True):
            assert _detect_embedding_provider("unknown") == "gemini"

        with patch.dict(os.environ, {"OPENAI_API_KEY": "key"}, clear=True):
            assert _detect_embedding_provider("unknown") == "openai"

        with patch.dict(os.environ, {}, clear=True):
            assert _detect_embedding_provider("unknown") == "cohere"

    def test_strip_provider(self):
        assert _strip_provider("gemini/model-name") == "model-name"
        assert _strip_provider("model-name") == "model-name"
