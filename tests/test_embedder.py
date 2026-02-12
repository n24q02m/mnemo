"""Tests for mnemo_mcp.embedder — LiteLLM embedding wrapper (all mocked)."""

from unittest.mock import MagicMock, patch

import pytest

from mnemo_mcp.embedder import (
    check_embedding_available,
    detect_embedding_dims,
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
    async def test_raises_on_api_error(self, mock_embed):
        mock_embed.side_effect = Exception("API rate limit exceeded")
        with pytest.raises(Exception, match="API rate limit exceeded"):
            await embed_texts(["test"], "model")


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
    def test_available(self, mock_embed):
        mock_embed.return_value = MagicMock(data=[{"embedding": [0.1, 0.2]}])
        assert check_embedding_available("model") is True

    @patch("mnemo_mcp.embedder.litellm_embedding")
    def test_not_available(self, mock_embed):
        mock_embed.side_effect = Exception("Model not found")
        assert check_embedding_available("model") is False

    @patch("mnemo_mcp.embedder.litellm_embedding")
    def test_empty_data(self, mock_embed):
        mock_embed.return_value = MagicMock(data=[])
        assert check_embedding_available("model") is False


class TestDetectDims:
    @patch("mnemo_mcp.embedder.litellm_embedding")
    def test_detects_dimensions(self, mock_embed):
        mock_embed.return_value = MagicMock(data=[{"embedding": [0.0] * 768}])
        assert detect_embedding_dims("model") == 768

    @patch("mnemo_mcp.embedder.litellm_embedding")
    def test_returns_zero_on_error(self, mock_embed):
        mock_embed.side_effect = Exception("fail")
        assert detect_embedding_dims("model") == 0
