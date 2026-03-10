"""Additional tests for mnemo_mcp.embedder — covering uncovered lines.

Targets: LiteLLMBackend with api_base/api_key, Qwen3EmbedBackend._get_model,
embed_texts inner function, embed_single_query, check_available result empty.
"""

from unittest.mock import MagicMock, patch

from mnemo_mcp.embedder import LiteLLMBackend, Qwen3EmbedBackend, _is_retryable

# ---------------------------------------------------------------------------
# LiteLLMBackend with api_base/api_key
# ---------------------------------------------------------------------------


class TestLiteLLMBackendCustomEndpoint:
    @patch("litellm.embedding")
    async def test_passes_api_base(self, mock_embed):
        """api_base is passed through to litellm embedding call."""
        mock_embed.return_value = MagicMock(data=[{"index": 0, "embedding": [0.1]}])
        backend = LiteLLMBackend("model", api_base="https://custom.api.com")
        await backend.embed_texts(["test"])
        mock_embed.assert_called_once_with(
            model="model", input=["test"], api_base="https://custom.api.com"
        )

    @patch("litellm.embedding")
    async def test_passes_api_key(self, mock_embed):
        """api_key is passed through to litellm embedding call."""
        mock_embed.return_value = MagicMock(data=[{"index": 0, "embedding": [0.1]}])
        backend = LiteLLMBackend("model", api_key="sk-custom")
        await backend.embed_texts(["test"])
        mock_embed.assert_called_once_with(
            model="model", input=["test"], api_key="sk-custom"
        )

    @patch("litellm.embedding")
    async def test_passes_both_api_base_and_key(self, mock_embed):
        """Both api_base and api_key are passed through."""
        mock_embed.return_value = MagicMock(data=[{"index": 0, "embedding": [0.1]}])
        backend = LiteLLMBackend("model", api_base="https://api.com", api_key="sk-key")
        await backend.embed_texts(["test"])
        mock_embed.assert_called_once_with(
            model="model", input=["test"], api_base="https://api.com", api_key="sk-key"
        )

    @patch("litellm.embedding")
    def test_check_available_with_api_base(self, mock_embed):
        """check_available passes api_base for custom endpoint validation."""
        mock_embed.return_value = MagicMock(data=[{"embedding": [0.1, 0.2]}])
        backend = LiteLLMBackend("model", api_base="https://api.com")
        dims = backend.check_available()
        assert dims == 2
        mock_embed.assert_called_once_with(
            model="model", input=["test"], api_base="https://api.com"
        )

    @patch("litellm.embedding")
    def test_check_available_with_api_key(self, mock_embed):
        """check_available passes api_key for custom endpoint validation."""
        mock_embed.return_value = MagicMock(data=[{"embedding": [0.1]}])
        backend = LiteLLMBackend("model", api_key="sk-key")
        dims = backend.check_available()
        assert dims == 1
        mock_embed.assert_called_once_with(
            model="model", input=["test"], api_key="sk-key"
        )


# ---------------------------------------------------------------------------
# Qwen3EmbedBackend._get_model
# ---------------------------------------------------------------------------


class TestQwen3GetModel:
    @patch("qwen3_embed.TextEmbedding")
    def test_lazy_loads_model(self, mock_te):
        """Model is loaded lazily on first _get_model() call."""
        mock_model = MagicMock()
        mock_te.return_value = mock_model

        backend = Qwen3EmbedBackend("test/model")
        assert backend._model is None

        result = backend._get_model()
        assert result == mock_model
        mock_te.assert_called_once_with(model_name="test/model")

    @patch("qwen3_embed.TextEmbedding")
    def test_caches_model(self, mock_te):
        """Model is only loaded once (cached)."""
        mock_model = MagicMock()
        mock_te.return_value = mock_model

        backend = Qwen3EmbedBackend()
        backend._get_model()
        backend._get_model()

        # Only called once despite two _get_model() calls
        mock_te.assert_called_once()


# ---------------------------------------------------------------------------
# Qwen3EmbedBackend.embed_texts (inner function)
# ---------------------------------------------------------------------------


class TestQwen3EmbedTextsInner:
    @patch("qwen3_embed.TextEmbedding")
    async def test_embed_texts_with_dimensions(self, mock_te):
        """embed_texts passes dim parameter to model.embed()."""
        import numpy as np

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1, 0.2])])
        mock_te.return_value = mock_model

        backend = Qwen3EmbedBackend()
        result = await backend.embed_texts(["test"], dimensions=512)

        assert result == [[0.1, 0.2]]
        # Verify dim was passed
        mock_model.embed.assert_called_once()
        call_kwargs = mock_model.embed.call_args
        assert call_kwargs[1].get("dim") == 512

    @patch("qwen3_embed.TextEmbedding")
    async def test_embed_texts_without_dimensions(self, mock_te):
        """embed_texts works without dimensions parameter."""
        import numpy as np

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1, 0.2, 0.3])])
        mock_te.return_value = mock_model

        backend = Qwen3EmbedBackend()
        result = await backend.embed_texts(["test"])

        assert result == [[0.1, 0.2, 0.3]]


# ---------------------------------------------------------------------------
# Qwen3EmbedBackend.embed_single_query
# ---------------------------------------------------------------------------


class TestQwen3EmbedSingleQuery:
    @patch("qwen3_embed.TextEmbedding")
    async def test_embed_single_query(self, mock_te):
        """embed_single_query uses query_embed for asymmetric retrieval."""
        import numpy as np

        mock_model = MagicMock()
        mock_model.query_embed.return_value = iter([np.array([0.5, 0.6, 0.7])])
        mock_te.return_value = mock_model

        backend = Qwen3EmbedBackend()
        result = await backend.embed_single_query("search query")

        assert result == [0.5, 0.6, 0.7]
        mock_model.query_embed.assert_called_once()

    @patch("qwen3_embed.TextEmbedding")
    async def test_embed_single_query_with_dimensions(self, mock_te):
        """embed_single_query passes dim parameter."""
        import numpy as np

        mock_model = MagicMock()
        mock_model.query_embed.return_value = iter([np.array([0.5, 0.6])])
        mock_te.return_value = mock_model

        backend = Qwen3EmbedBackend()
        result = await backend.embed_single_query("query", dimensions=256)

        assert result == [0.5, 0.6]
        call_kwargs = mock_model.query_embed.call_args
        assert call_kwargs[1].get("dim") == 256


# ---------------------------------------------------------------------------
# Qwen3EmbedBackend.check_available (empty result)
# ---------------------------------------------------------------------------


class TestQwen3CheckAvailableEdge:
    @patch("mnemo_mcp.embedder.Qwen3EmbedBackend._get_model")
    def test_check_available_empty_result(self, mock_get_model):
        """check_available returns 0 when embed returns empty list."""
        mock_model = MagicMock()
        mock_model.embed.return_value = iter([])
        mock_get_model.return_value = mock_model

        backend = Qwen3EmbedBackend()
        assert backend.check_available() == 0


# ---------------------------------------------------------------------------
# _is_retryable
# ---------------------------------------------------------------------------


class TestIsRetryable:
    def test_rate_limit(self):
        assert _is_retryable(Exception("429 rate limit exceeded")) is True

    def test_timeout(self):
        assert _is_retryable(Exception("Connection timed out")) is True

    def test_server_error(self):
        assert _is_retryable(Exception("503 service temporarily unavailable")) is True

    def test_resource_exhausted(self):
        assert _is_retryable(Exception("resource_exhausted")) is True

    def test_non_retryable(self):
        assert _is_retryable(Exception("Invalid model name")) is False

    def test_overloaded(self):
        assert _is_retryable(Exception("Server overloaded")) is True
