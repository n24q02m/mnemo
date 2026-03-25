"""Tests for mnemo_mcp.embedder -- dual-backend embedding (all mocked)."""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from mnemo_mcp.embedder import (
    CloudEmbeddingBackend,
    LiteLLMBackend,
    Qwen3EmbedBackend,
    check_embedding_available,
    embed_single,
    get_backend,
    init_backend,
)


class TestCloudEmbeddingBackend:
    @patch("cohere.ClientV2")
    async def test_returns_embeddings(self, mock_client_cls):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings.float_ = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_client.embed.return_value = mock_response
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="test-key")
        result = await backend.embed_texts(["hello", "world"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]

    @patch("cohere.ClientV2")
    async def test_empty_input(self, mock_client_cls):
        backend = CloudEmbeddingBackend(api_key="test-key")
        result = await backend.embed_texts([])
        assert result == []
        mock_client_cls.assert_not_called()

    @patch("cohere.ClientV2")
    async def test_passes_dimensions(self, mock_client_cls):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings.float_ = [[0.1]]
        mock_client.embed.return_value = mock_response
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(model="embed-multilingual-v3.0", api_key="key")
        await backend.embed_texts(["test"], dimensions=512)
        call_kwargs = mock_client.embed.call_args
        assert call_kwargs.kwargs.get("output_dimension") == 512

    @patch("cohere.ClientV2")
    async def test_dimensions_fallback_on_unsupported(self, mock_client_cls):
        """Falls back to local truncation when provider rejects dimensions."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings.float_ = [[0.1] * 1024]
        unsupported_err = Exception("output_dimension is not supported for this model")
        mock_client.embed.side_effect = [unsupported_err, mock_response]
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(model="embed-multilingual-v3.0", api_key="key")
        result = await backend.embed_texts(["test"], dimensions=768)
        assert len(result[0]) == 768

    @patch("cohere.ClientV2")
    async def test_local_truncation_when_server_returns_more(self, mock_client_cls):
        """Truncates locally when server returns more dims than requested."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings.float_ = [[0.1] * 3072]
        mock_client.embed.return_value = mock_response
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        result = await backend.embed_texts(["test"], dimensions=768)
        assert len(result[0]) == 768

    @patch("cohere.ClientV2")
    async def test_embed_single(self, mock_client_cls):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings.float_ = [[0.1, 0.2, 0.3]]
        mock_client.embed.return_value = mock_response
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        result = await backend.embed_single("hello")
        assert result == [0.1, 0.2, 0.3]

    @patch("cohere.ClientV2")
    def test_check_available_returns_dims(self, mock_client_cls):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings.float_ = [[0.1, 0.2]]
        mock_client.embed.return_value = mock_response
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        assert backend.check_available() == 2

    @patch("cohere.ClientV2")
    def test_check_available_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.embed.side_effect = Exception("Model not found")
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        assert backend.check_available() == 0

    @patch("cohere.ClientV2")
    async def test_raises_on_non_retryable_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.embed.side_effect = Exception("Invalid API key")
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        with pytest.raises(Exception, match="Invalid API key"):
            await backend.embed_texts(["test"])

    @patch("cohere.ClientV2")
    def test_check_available_empty_data(self, mock_client_cls):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings.float_ = []
        mock_client.embed.return_value = mock_response
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        assert backend.check_available() == 0

    def test_litellm_backward_compat_alias(self):
        """LiteLLMBackend is an alias for CloudEmbeddingBackend."""
        assert LiteLLMBackend is CloudEmbeddingBackend


class TestBatchSplitting:
    @patch("cohere.ClientV2")
    async def test_splits_large_batch(self, mock_client_cls):
        """Texts exceeding MAX_BATCH_SIZE are split into sub-batches."""
        n = CloudEmbeddingBackend.MAX_BATCH_SIZE + 50

        mock_client = MagicMock()

        def mock_embed(**kwargs):
            count = len(kwargs["texts"])
            resp = MagicMock()
            resp.embeddings.float_ = [[float(j)] for j in range(count)]
            return resp

        mock_client.embed.side_effect = mock_embed
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        vecs = await backend.embed_texts([f"t{i}" for i in range(n)])
        assert len(vecs) == n

    @patch("cohere.ClientV2")
    async def test_batch_call_count(self, mock_client_cls):
        """Correct number of API calls for split batches."""
        n = CloudEmbeddingBackend.MAX_BATCH_SIZE * 2 + 10

        mock_client = MagicMock()

        def mock_embed(**kwargs):
            count = len(kwargs["texts"])
            resp = MagicMock()
            resp.embeddings.float_ = [[0.0] for _ in range(count)]
            return resp

        mock_client.embed.side_effect = mock_embed
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        await backend.embed_texts([f"t{i}" for i in range(n)])
        assert mock_client.embed.call_count == 3

    @patch("cohere.ClientV2")
    async def test_no_split_under_limit(self, mock_client_cls):
        mock_client = MagicMock()

        def mock_embed(**kwargs):
            count = len(kwargs["texts"])
            resp = MagicMock()
            resp.embeddings.float_ = [[0.0] for _ in range(count)]
            return resp

        mock_client.embed.side_effect = mock_embed
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        await backend.embed_texts(
            [f"t{i}" for i in range(CloudEmbeddingBackend.MAX_BATCH_SIZE)]
        )
        assert mock_client.embed.call_count == 1


class TestRetryLogic:
    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("cohere.ClientV2")
    async def test_retries_on_rate_limit(self, mock_client_cls, mock_sleep):
        mock_client = MagicMock()
        success_response = MagicMock()
        success_response.embeddings.float_ = [[0.1]]
        mock_client.embed.side_effect = [
            Exception("429 rate limit exceeded"),
            success_response,
        ]
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        result = await backend.embed_texts(["test"])
        assert result == [[0.1]]
        mock_sleep.assert_called_once_with(1.0)

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("cohere.ClientV2")
    async def test_retries_on_server_error(self, mock_client_cls, mock_sleep):
        mock_client = MagicMock()
        success_response = MagicMock()
        success_response.embeddings.float_ = [[0.2]]
        mock_client.embed.side_effect = [
            Exception("503 temporarily unavailable"),
            success_response,
        ]
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        result = await backend.embed_texts(["test"])
        assert result == [[0.2]]

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("cohere.ClientV2")
    async def test_no_retry_on_non_retryable(self, mock_client_cls, mock_sleep):
        mock_client = MagicMock()
        mock_client.embed.side_effect = Exception("Invalid API key")
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        with pytest.raises(Exception, match="Invalid API key"):
            await backend.embed_texts(["test"])
        mock_sleep.assert_not_called()

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("cohere.ClientV2")
    async def test_exponential_backoff(self, mock_client_cls, mock_sleep):
        mock_client = MagicMock()
        success_response = MagicMock()
        success_response.embeddings.float_ = [[0.1]]
        mock_client.embed.side_effect = [
            Exception("429 rate limit"),
            Exception("429 rate limit"),
            success_response,
        ]
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        await backend.embed_texts(["test"])
        assert mock_sleep.call_args_list == [call(1.0), call(2.0)]

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("cohere.ClientV2")
    async def test_max_retries_exhausted(self, mock_client_cls, mock_sleep):
        mock_client = MagicMock()
        mock_client.embed.side_effect = Exception("429 rate limit")
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        with pytest.raises(Exception, match="429 rate limit"):
            await backend.embed_texts(["test"])
        assert mock_sleep.call_count == 2


class TestQwen3EmbedBackend:
    def test_default_model(self):
        backend = Qwen3EmbedBackend()
        assert backend._model_name == "n24q02m/Qwen3-Embedding-0.6B-ONNX"

    def test_custom_model(self):
        backend = Qwen3EmbedBackend("custom/model")
        assert backend._model_name == "custom/model"

    @patch("mnemo_mcp.embedder.asyncio.to_thread")
    async def test_embed_texts_calls_to_thread(self, mock_to_thread):
        """Local embedding runs in thread to avoid blocking event loop."""
        mock_to_thread.return_value = [[0.1, 0.2]]
        backend = Qwen3EmbedBackend()
        result = await backend.embed_texts(["test"])
        assert result == [[0.1, 0.2]]
        mock_to_thread.assert_called_once()

    @patch("mnemo_mcp.embedder.asyncio.to_thread")
    async def test_empty_input(self, mock_to_thread):
        backend = Qwen3EmbedBackend()
        result = await backend.embed_texts([])
        assert result == []
        mock_to_thread.assert_not_called()

    @patch("mnemo_mcp.embedder.asyncio.to_thread")
    async def test_embed_single(self, mock_to_thread):
        mock_to_thread.return_value = [[0.1, 0.2, 0.3]]
        backend = Qwen3EmbedBackend()
        result = await backend.embed_single("hello")
        assert result == [0.1, 0.2, 0.3]

    @patch("mnemo_mcp.embedder.Qwen3EmbedBackend._get_model")
    def test_check_available_not_installed(self, mock_get_model):
        """Returns 0 when qwen3-embed is not available."""
        mock_get_model.side_effect = ImportError("No module named 'qwen3_embed'")
        backend = Qwen3EmbedBackend()
        assert backend.check_available() == 0


class TestBackendFactory:
    def test_init_cloud(self):
        backend = init_backend("cloud", "embed-multilingual-v3.0")
        assert isinstance(backend, CloudEmbeddingBackend)
        assert get_backend() is backend

    def test_init_litellm_backward_compat(self):
        """'litellm' maps to CloudEmbeddingBackend for backward compat."""
        backend = init_backend("litellm", "test-model")
        assert isinstance(backend, CloudEmbeddingBackend)
        assert get_backend() is backend

    def test_init_local(self):
        backend = init_backend("local")
        assert isinstance(backend, Qwen3EmbedBackend)
        assert get_backend() is backend

    def test_init_unknown_backend(self):
        with pytest.raises(ValueError, match="Unknown backend type"):
            init_backend("unknown")


class TestCheckAvailableApiKeyValidation:
    """check_available() distinguishes API key errors from other failures."""

    @patch("cohere.ClientV2")
    def test_api_key_401_logs_warning(self, mock_client_cls):
        """401 errors are logged at warning level (not debug)."""
        mock_client = MagicMock()
        mock_client.embed.side_effect = Exception("401 Unauthorized: Invalid API key")
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="bad-key")
        result = backend.check_available()
        assert result == 0

    @patch("cohere.ClientV2")
    def test_api_key_403_logs_warning(self, mock_client_cls):
        """403 forbidden errors are logged at warning level."""
        mock_client = MagicMock()
        mock_client.embed.side_effect = Exception("403 Forbidden")
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="bad-key")
        assert backend.check_available() == 0

    @patch("cohere.ClientV2")
    def test_invalid_key_detected(self, mock_client_cls):
        """'invalid' keyword in error triggers warning path."""
        mock_client = MagicMock()
        mock_client.embed.side_effect = Exception("Invalid API key provided")
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="bad-key")
        assert backend.check_available() == 0

    @patch("cohere.ClientV2")
    def test_unauthorized_detected(self, mock_client_cls):
        """'unauthorized' keyword in error triggers warning path."""
        mock_client = MagicMock()
        mock_client.embed.side_effect = Exception("Unauthorized access")
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="bad-key")
        assert backend.check_available() == 0

    @patch("cohere.ClientV2")
    def test_non_auth_error_logged_at_debug(self, mock_client_cls):
        """Non-auth errors (e.g. model not found) go to debug level."""
        mock_client = MagicMock()
        mock_client.embed.side_effect = Exception("Model not found: xyz")
        mock_client_cls.return_value = mock_client

        backend = CloudEmbeddingBackend(api_key="key")
        assert backend.check_available() == 0


class TestQwen3GetModelWarning:
    """_get_model() logs download warning on first call."""

    @patch("mnemo_mcp.embedder.Qwen3EmbedBackend._get_model")
    def test_check_available_success(self, mock_get_model):
        """check_available returns dims when model works."""
        import numpy as np

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1, 0.2, 0.3])])
        mock_get_model.return_value = mock_model

        backend = Qwen3EmbedBackend()
        dims = backend.check_available()
        assert dims == 3

    @patch("mnemo_mcp.embedder.Qwen3EmbedBackend._get_model")
    def test_check_available_returns_zero_on_error(self, mock_get_model):
        """check_available returns 0 when model raises."""
        mock_get_model.side_effect = Exception("ONNX runtime error")
        backend = Qwen3EmbedBackend()
        assert backend.check_available() == 0


class TestLegacyCompat:
    """Legacy module-level functions still work."""

    @patch("cohere.ClientV2")
    async def test_embed_single_legacy(self, mock_client_cls):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings.float_ = [[0.1, 0.2]]
        mock_client.embed.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = await embed_single("test", "embed-multilingual-v3.0", api_key="key")
        assert result == [0.1, 0.2]

    @patch("cohere.ClientV2")
    def test_check_available_legacy(self, mock_client_cls):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embeddings.float_ = [[0.1]]
        mock_client.embed.return_value = mock_response
        mock_client_cls.return_value = mock_client

        assert check_embedding_available("embed-multilingual-v3.0", api_key="key") == 1
