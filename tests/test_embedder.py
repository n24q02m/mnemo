"""Tests for mnemo_mcp.embedder — LiteLLM embedding wrapper (all mocked)."""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from mnemo_mcp.embedder import (
    MAX_BATCH_SIZE,
    check_embedding_available,
    embed_single,
    embed_texts,
)


class TestEmbedTexts:
    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_returns_embeddings(self, mock_embed):
        mock_embed.return_value = MagicMock(
            data=[
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                {"index": 1, "embedding": [0.4, 0.5, 0.6]},
            ]
        )
        result = await embed_texts(["hello", "world"], "test-model")
        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]

    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_empty_input(self, mock_embed):
        result = await embed_texts([], "test-model")
        assert result == []
        mock_embed.assert_not_called()

    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_preserves_order(self, mock_embed):
        """Results sorted by index even if API returns out of order."""
        mock_embed.return_value = MagicMock(
            data=[
                {"index": 1, "embedding": [0.4, 0.5]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        )
        result = await embed_texts(["a", "b"], "test-model")
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.4, 0.5]

    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_passes_dimensions(self, mock_embed):
        mock_embed.return_value = MagicMock(data=[{"index": 0, "embedding": [0.1]}])
        await embed_texts(["test"], "model", dimensions=512)
        mock_embed.assert_called_once_with(
            model="model", input=["test"], dimensions=512
        )

    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_omits_dimensions_when_none(self, mock_embed):
        mock_embed.return_value = MagicMock(data=[{"index": 0, "embedding": [0.1]}])
        await embed_texts(["test"], "model", dimensions=None)
        mock_embed.assert_called_once_with(model="model", input=["test"])

    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_raises_on_non_retryable_error(self, mock_embed):
        mock_embed.side_effect = Exception("Invalid API key")
        with pytest.raises(Exception, match="Invalid API key"):
            await embed_texts(["test"], "model")


class TestBatchSplitting:
    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_splits_large_batch(self, mock_embed):
        """Texts exceeding MAX_BATCH_SIZE are split into sub-batches."""
        n = MAX_BATCH_SIZE + 50  # 150 texts -> 2 batches

        def mock_fn(**kwargs):
            batch_input = kwargs["input"]
            resp = MagicMock()
            resp.data = [
                {"index": j, "embedding": [float(j)]} for j in range(len(batch_input))
            ]
            return resp

        mock_embed.side_effect = mock_fn
        vecs = await embed_texts([f"t{i}" for i in range(n)], "model")
        assert len(vecs) == n

    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_batch_call_count(self, mock_embed):
        """Correct number of API calls for split batches."""
        n = MAX_BATCH_SIZE * 2 + 10  # 210 -> 3 batches

        def mock_fn(**kwargs):
            resp = MagicMock()
            resp.data = [
                {"index": j, "embedding": [0.0]} for j in range(len(kwargs["input"]))
            ]
            return resp

        mock_embed.side_effect = mock_fn
        await embed_texts([f"t{i}" for i in range(n)], "model")
        assert mock_embed.call_count == 3

    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_no_split_under_limit(self, mock_embed):
        """No splitting when under MAX_BATCH_SIZE."""

        def mock_fn(**kwargs):
            resp = MagicMock()
            resp.data = [
                {"index": j, "embedding": [0.0]} for j in range(len(kwargs["input"]))
            ]
            return resp

        mock_embed.side_effect = mock_fn
        await embed_texts([f"t{i}" for i in range(MAX_BATCH_SIZE)], "model")
        assert mock_embed.call_count == 1


class TestRetryLogic:
    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_retries_on_rate_limit(self, mock_embed, mock_sleep):
        """Retries on rate limit errors with exponential backoff."""
        success = MagicMock(data=[{"index": 0, "embedding": [0.1]}])
        mock_embed.side_effect = [Exception("429 rate limit exceeded"), success]
        result = await embed_texts(["test"], "model")
        assert result == [[0.1]]
        mock_sleep.assert_called_once_with(1.0)

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_retries_on_server_error(self, mock_embed, mock_sleep):
        """Retries on 5xx server errors."""
        success = MagicMock(data=[{"index": 0, "embedding": [0.2]}])
        mock_embed.side_effect = [
            Exception("503 temporarily unavailable"),
            success,
        ]
        result = await embed_texts(["test"], "model")
        assert result == [[0.2]]

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_no_retry_on_non_retryable(self, mock_embed, mock_sleep):
        """Non-retryable errors fail immediately."""
        mock_embed.side_effect = Exception("Invalid API key")
        with pytest.raises(Exception, match="Invalid API key"):
            await embed_texts(["test"], "model")
        mock_sleep.assert_not_called()

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_exponential_backoff(self, mock_embed, mock_sleep):
        """Retry delays use exponential backoff."""
        success = MagicMock(data=[{"index": 0, "embedding": [0.1]}])
        mock_embed.side_effect = [
            Exception("429 rate limit"),
            Exception("429 rate limit"),
            success,
        ]
        await embed_texts(["test"], "model")
        assert mock_sleep.call_args_list == [call(1.0), call(2.0)]

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_max_retries_exhausted(self, mock_embed, mock_sleep):
        """Raises after all retries exhausted."""
        mock_embed.side_effect = Exception("429 rate limit")
        with pytest.raises(Exception, match="429 rate limit"):
            await embed_texts(["test"], "model")
        assert mock_sleep.call_count == 2


class TestEmbedSingle:
    @patch("mnemo_mcp.embedder.litellm_embedding")
    async def test_returns_single_vector(self, mock_embed):
        mock_embed.return_value = MagicMock(
            data=[{"index": 0, "embedding": [0.1, 0.2, 0.3]}]
        )
        result = await embed_single("hello", "model")
        assert result == [0.1, 0.2, 0.3]


class TestCheckAvailable:
    @patch("mnemo_mcp.embedder.litellm_embedding")
    def test_available_returns_dims(self, mock_embed):
        mock_embed.return_value = MagicMock(data=[{"embedding": [0.1, 0.2]}])
        assert check_embedding_available("model") == 2

    @patch("mnemo_mcp.embedder.litellm_embedding")
    def test_not_available_returns_zero(self, mock_embed):
        mock_embed.side_effect = Exception("Model not found")
        assert check_embedding_available("model") == 0

    @patch("mnemo_mcp.embedder.litellm_embedding")
    def test_empty_data_returns_zero(self, mock_embed):
        mock_embed.return_value = MagicMock(data=[])
        assert check_embedding_available("model") == 0
