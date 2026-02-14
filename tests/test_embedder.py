"""Tests for mnemo_mcp.embedder — dual-backend embedding (all mocked)."""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from mnemo_mcp.embedder import (
    LiteLLMBackend,
    Qwen3EmbedBackend,
    check_embedding_available,
    embed_single,
    embed_texts,
    get_backend,
    init_backend,
)


class TestLiteLLMBackend:
    @patch("litellm.embedding")
    async def test_returns_embeddings(self, mock_embed):
        mock_embed.return_value = MagicMock(
            data=[
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                {"index": 1, "embedding": [0.4, 0.5, 0.6]},
            ]
        )
        backend = LiteLLMBackend("test-model")
        result = await backend.embed_texts(["hello", "world"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]

    @patch("litellm.embedding")
    async def test_empty_input(self, mock_embed):
        backend = LiteLLMBackend("test-model")
        result = await backend.embed_texts([])
        assert result == []
        mock_embed.assert_not_called()

    @patch("litellm.embedding")
    async def test_preserves_order(self, mock_embed):
        """Results sorted by index even if API returns out of order."""
        mock_embed.return_value = MagicMock(
            data=[
                {"index": 1, "embedding": [0.4, 0.5]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        )
        backend = LiteLLMBackend("test-model")
        result = await backend.embed_texts(["a", "b"])
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.4, 0.5]

    @patch("litellm.embedding")
    async def test_passes_dimensions(self, mock_embed):
        mock_embed.return_value = MagicMock(data=[{"index": 0, "embedding": [0.1]}])
        backend = LiteLLMBackend("model")
        await backend.embed_texts(["test"], dimensions=512)
        mock_embed.assert_called_once_with(
            model="model", input=["test"], dimensions=512
        )

    @patch("litellm.embedding")
    async def test_embed_single(self, mock_embed):
        mock_embed.return_value = MagicMock(
            data=[{"index": 0, "embedding": [0.1, 0.2, 0.3]}]
        )
        backend = LiteLLMBackend("model")
        result = await backend.embed_single("hello")
        assert result == [0.1, 0.2, 0.3]

    @patch("litellm.embedding")
    def test_check_available_returns_dims(self, mock_embed):
        mock_embed.return_value = MagicMock(data=[{"embedding": [0.1, 0.2]}])
        backend = LiteLLMBackend("model")
        assert backend.check_available() == 2

    @patch("litellm.embedding")
    def test_check_available_error(self, mock_embed):
        mock_embed.side_effect = Exception("Model not found")
        backend = LiteLLMBackend("model")
        assert backend.check_available() == 0

    @patch("litellm.embedding")
    async def test_raises_on_non_retryable_error(self, mock_embed):
        mock_embed.side_effect = Exception("Invalid API key")
        backend = LiteLLMBackend("model")
        with pytest.raises(Exception, match="Invalid API key"):
            await backend.embed_texts(["test"])

    @patch("litellm.embedding")
    def test_check_available_empty_data(self, mock_embed):
        mock_embed.return_value = MagicMock(data=[])
        backend = LiteLLMBackend("model")
        assert backend.check_available() == 0


class TestBatchSplitting:
    @patch("litellm.embedding")
    async def test_splits_large_batch(self, mock_embed):
        """Texts exceeding MAX_BATCH_SIZE are split into sub-batches."""
        n = LiteLLMBackend.MAX_BATCH_SIZE + 50

        def mock_fn(**kwargs):
            resp = MagicMock()
            resp.data = [
                {"index": j, "embedding": [float(j)]}
                for j in range(len(kwargs["input"]))
            ]
            return resp

        mock_embed.side_effect = mock_fn
        backend = LiteLLMBackend("model")
        vecs = await backend.embed_texts([f"t{i}" for i in range(n)])
        assert len(vecs) == n

    @patch("litellm.embedding")
    async def test_batch_call_count(self, mock_embed):
        """Correct number of API calls for split batches."""
        n = LiteLLMBackend.MAX_BATCH_SIZE * 2 + 10

        def mock_fn(**kwargs):
            resp = MagicMock()
            resp.data = [
                {"index": j, "embedding": [0.0]} for j in range(len(kwargs["input"]))
            ]
            return resp

        mock_embed.side_effect = mock_fn
        backend = LiteLLMBackend("model")
        await backend.embed_texts([f"t{i}" for i in range(n)])
        assert mock_embed.call_count == 3

    @patch("litellm.embedding")
    async def test_no_split_under_limit(self, mock_embed):
        def mock_fn(**kwargs):
            resp = MagicMock()
            resp.data = [
                {"index": j, "embedding": [0.0]} for j in range(len(kwargs["input"]))
            ]
            return resp

        mock_embed.side_effect = mock_fn
        backend = LiteLLMBackend("model")
        await backend.embed_texts(
            [f"t{i}" for i in range(LiteLLMBackend.MAX_BATCH_SIZE)]
        )
        assert mock_embed.call_count == 1


class TestRetryLogic:
    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("litellm.embedding")
    async def test_retries_on_rate_limit(self, mock_embed, mock_sleep):
        success = MagicMock(data=[{"index": 0, "embedding": [0.1]}])
        mock_embed.side_effect = [Exception("429 rate limit exceeded"), success]
        backend = LiteLLMBackend("model")
        result = await backend.embed_texts(["test"])
        assert result == [[0.1]]
        mock_sleep.assert_called_once_with(1.0)

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("litellm.embedding")
    async def test_retries_on_server_error(self, mock_embed, mock_sleep):
        success = MagicMock(data=[{"index": 0, "embedding": [0.2]}])
        mock_embed.side_effect = [
            Exception("503 temporarily unavailable"),
            success,
        ]
        backend = LiteLLMBackend("model")
        result = await backend.embed_texts(["test"])
        assert result == [[0.2]]

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("litellm.embedding")
    async def test_no_retry_on_non_retryable(self, mock_embed, mock_sleep):
        mock_embed.side_effect = Exception("Invalid API key")
        backend = LiteLLMBackend("model")
        with pytest.raises(Exception, match="Invalid API key"):
            await backend.embed_texts(["test"])
        mock_sleep.assert_not_called()

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("litellm.embedding")
    async def test_exponential_backoff(self, mock_embed, mock_sleep):
        success = MagicMock(data=[{"index": 0, "embedding": [0.1]}])
        mock_embed.side_effect = [
            Exception("429 rate limit"),
            Exception("429 rate limit"),
            success,
        ]
        backend = LiteLLMBackend("model")
        await backend.embed_texts(["test"])
        assert mock_sleep.call_args_list == [call(1.0), call(2.0)]

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("litellm.embedding")
    async def test_max_retries_exhausted(self, mock_embed, mock_sleep):
        mock_embed.side_effect = Exception("429 rate limit")
        backend = LiteLLMBackend("model")
        with pytest.raises(Exception, match="429 rate limit"):
            await backend.embed_texts(["test"])
        assert mock_sleep.call_count == 2


class TestQwen3EmbedBackend:
    def test_default_model(self):
        backend = Qwen3EmbedBackend()
        assert backend._model_name == "Qwen/Qwen3-Embedding-0.6B"

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

    def test_check_available_not_installed(self):
        """Returns 0 when qwen3-embed is not installed."""
        backend = Qwen3EmbedBackend()
        # In test env, qwen3-embed is not installed
        assert backend.check_available() == 0


class TestBackendFactory:
    def test_init_litellm(self):
        backend = init_backend("litellm", "test-model")
        assert isinstance(backend, LiteLLMBackend)
        assert get_backend() is backend

    def test_init_local(self):
        backend = init_backend("local")
        assert isinstance(backend, Qwen3EmbedBackend)
        assert get_backend() is backend

    def test_init_litellm_requires_model(self):
        with pytest.raises(ValueError, match="model is required"):
            init_backend("litellm")

    def test_init_unknown_backend(self):
        with pytest.raises(ValueError, match="Unknown backend type"):
            init_backend("unknown")


class TestLegacyCompat:
    """Legacy module-level functions still work."""

    @patch("litellm.embedding")
    async def test_embed_texts_legacy(self, mock_embed):
        mock_embed.return_value = MagicMock(data=[{"index": 0, "embedding": [0.1]}])
        result = await embed_texts(["test"], "model")
        assert result == [[0.1]]

    @patch("litellm.embedding")
    async def test_embed_single_legacy(self, mock_embed):
        mock_embed.return_value = MagicMock(
            data=[{"index": 0, "embedding": [0.1, 0.2]}]
        )
        result = await embed_single("test", "model")
        assert result == [0.1, 0.2]

    @patch("litellm.embedding")
    def test_check_available_legacy(self, mock_embed):
        mock_embed.return_value = MagicMock(data=[{"embedding": [0.1]}])
        assert check_embedding_available("model") == 1
