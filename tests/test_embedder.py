"""Tests for mnemo_mcp.embedder -- dual-backend embedding (all mocked).

Cloud embedding goes through the ``[models.embed]`` provider cell. Async paths
drive a stubbed hull OpenAI-spec client injected as ``CloudEmbeddingBackend(client)``;
``check_available`` awaits the same stub with ``["ping"]``.
"""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from mnemo_mcp.embedder import (
    CloudEmbeddingBackend,
    Qwen3EmbedBackend,
    get_backend,
    init_backend,
)


def _cell_client(model="cell-model", vectors=None, exc=None, side_effect=None):
    """Stub hull OpenAI-spec client for the embed cell (mirrors test_reranker.py)."""
    client = MagicMock()
    client.cell.model = model
    if side_effect is not None:
        client.embeddings = AsyncMock(side_effect=side_effect)
    elif exc is not None:
        client.embeddings = AsyncMock(side_effect=exc)
    else:
        client.embeddings = AsyncMock(return_value=list(vectors or []))
    return client


class TestCloudEmbeddingBackend:
    async def test_returns_embeddings(self):
        client = _cell_client(vectors=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        backend = CloudEmbeddingBackend(client)

        result = await backend.embed_texts(["hello", "world"])

        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        client.embeddings.assert_awaited_once_with(["hello", "world"], dimensions=None)

    async def test_empty_input(self):
        client = _cell_client(vectors=[[0.1]])
        backend = CloudEmbeddingBackend(client)

        assert await backend.embed_texts([]) == []
        client.embeddings.assert_not_called()

    async def test_model_identity_from_cell(self):
        """The logged/diagnostic model id comes from the provider cell."""
        client = _cell_client(model="jina-embeddings-v5")
        assert CloudEmbeddingBackend(client).model == "jina-embeddings-v5"

    async def test_passes_dimensions(self):
        client = _cell_client(vectors=[[0.1]])
        backend = CloudEmbeddingBackend(client)

        await backend.embed_texts(["test"], dimensions=512)

        assert client.embeddings.call_args.kwargs.get("dimensions") == 512

    async def test_dimensions_fallback_on_unsupported(self):
        """Falls back to local truncation when provider rejects dimensions."""
        unsupported_err = Exception("output_dimension is not supported for this model")
        client = _cell_client(side_effect=[unsupported_err, [[0.1] * 1024]])
        backend = CloudEmbeddingBackend(client)

        result = await backend.embed_texts(["test"], dimensions=768)

        assert len(result[0]) == 768
        assert client.embeddings.call_args_list[1].kwargs["dimensions"] is None

    async def test_dimensions_fallback_with_query_role(self):
        """The unsupported-dimensions fallback also fires for query-role calls."""
        unsupported_err = Exception("output_dimension is not supported for this model")
        client = _cell_client(side_effect=[unsupported_err, [[0.1] * 1024]])
        backend = CloudEmbeddingBackend(client)

        result = await backend.embed_texts(["test"], dimensions=768, role="query")

        assert len(result[0]) == 768

    async def test_local_truncation_when_server_returns_more(self):
        """Truncates locally when server returns more dims than requested."""
        client = _cell_client(vectors=[[0.1] * 3072])
        backend = CloudEmbeddingBackend(client)

        result = await backend.embed_texts(["test"], dimensions=768)

        assert len(result[0]) == 768

    async def test_embed_single(self):
        client = _cell_client(vectors=[[0.1, 0.2, 0.3]])
        backend = CloudEmbeddingBackend(client)

        assert await backend.embed_single("hello") == [0.1, 0.2, 0.3]

    async def test_check_available_returns_dims(self):
        client = _cell_client(vectors=[[0.1, 0.2]])
        backend = CloudEmbeddingBackend(client)
        assert await backend.check_available() == 2

    async def test_check_available_error(self):
        client = _cell_client(exc=Exception("Model not found"))
        backend = CloudEmbeddingBackend(client)
        assert await backend.check_available() == 0

    async def test_check_available_empty_result(self):
        client = _cell_client(vectors=[])
        backend = CloudEmbeddingBackend(client)
        assert await backend.check_available() == 0

    async def test_raises_on_non_retryable_error(self):
        client = _cell_client(exc=Exception("Invalid API key"))
        backend = CloudEmbeddingBackend(client)
        with pytest.raises(Exception, match="Invalid API key"):
            await backend.embed_texts(["test"])


class TestBatchSplitting:
    async def test_splits_large_batch(self):
        """Texts exceeding MAX_BATCH_SIZE are split into sub-batches."""
        n = CloudEmbeddingBackend.MAX_BATCH_SIZE + 50

        def fake_embeddings(texts, dimensions=None):
            return [[float(j)] for j in range(len(texts))]

        client = _cell_client()
        client.embeddings = AsyncMock(side_effect=fake_embeddings)
        backend = CloudEmbeddingBackend(client)

        vecs = await backend.embed_texts([f"t{i}" for i in range(n)])

        assert len(vecs) == n

    async def test_batch_call_count(self):
        """Correct number of API calls for split batches."""
        n = CloudEmbeddingBackend.MAX_BATCH_SIZE * 2 + 10

        def fake_embeddings(texts, dimensions=None):
            return [[0.0] for _ in texts]

        client = _cell_client()
        client.embeddings = AsyncMock(side_effect=fake_embeddings)
        backend = CloudEmbeddingBackend(client)

        await backend.embed_texts([f"t{i}" for i in range(n)])

        assert client.embeddings.call_count == 3

    async def test_no_split_under_limit(self):
        def fake_embeddings(texts, dimensions=None):
            return [[0.0] for _ in texts]

        client = _cell_client()
        client.embeddings = AsyncMock(side_effect=fake_embeddings)
        backend = CloudEmbeddingBackend(client)

        await backend.embed_texts(
            [f"t{i}" for i in range(CloudEmbeddingBackend.MAX_BATCH_SIZE)]
        )

        assert client.embeddings.call_count == 1


class TestRetryLogic:
    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_rate_limit(self, mock_sleep):
        client = _cell_client(
            side_effect=[Exception("429 rate limit exceeded"), [[0.1]]]
        )
        backend = CloudEmbeddingBackend(client)

        result = await backend.embed_texts(["test"])

        assert result == [[0.1]]
        mock_sleep.assert_called_once_with(1.0)

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_server_error(self, mock_sleep):
        client = _cell_client(
            side_effect=[Exception("503 temporarily unavailable"), [[0.2]]]
        )
        backend = CloudEmbeddingBackend(client)

        assert await backend.embed_texts(["test"]) == [[0.2]]

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_no_retry_on_non_retryable(self, mock_sleep):
        client = _cell_client(exc=Exception("Invalid API key"))
        backend = CloudEmbeddingBackend(client)

        with pytest.raises(Exception, match="Invalid API key"):
            await backend.embed_texts(["test"])

        mock_sleep.assert_not_called()

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_exponential_backoff(self, mock_sleep):
        client = _cell_client(
            side_effect=[
                Exception("429 rate limit"),
                Exception("429 rate limit"),
                [[0.1]],
            ]
        )
        backend = CloudEmbeddingBackend(client)

        await backend.embed_texts(["test"])

        assert mock_sleep.call_args_list == [call(1.0), call(2.0)]

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_max_retries_exhausted(self, mock_sleep):
        client = _cell_client(side_effect=Exception("429 rate limit"))
        backend = CloudEmbeddingBackend(client)

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
        """Returns 0 when fastretrieval is not available."""
        mock_get_model.side_effect = ImportError("No module named 'fastretrieval'")
        backend = Qwen3EmbedBackend()
        assert backend.check_available() == 0


class TestBackendFactory:
    def test_init_cloud_uses_cell_client(self):
        client = _cell_client()
        with patch("mnemo_mcp.embedder._cell_client", return_value=client):
            backend = init_backend("cloud")

        assert isinstance(backend, CloudEmbeddingBackend)
        assert backend.model == "cell-model"
        assert get_backend() is backend

    def test_init_cloud_with_injected_client(self):
        """init_backend accepts the provider client itself as 'model'."""
        client = _cell_client()
        backend = init_backend("cloud", client)

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

    async def test_api_key_401_logs_warning(self):
        """401 errors are logged at warning level (not debug)."""
        client = _cell_client(exc=Exception("401 Unauthorized: Invalid API key"))
        backend = CloudEmbeddingBackend(client)
        assert await backend.check_available() == 0

    async def test_api_key_403_logs_warning(self):
        """403 forbidden errors are logged at warning level."""
        client = _cell_client(exc=Exception("403 Forbidden"))
        backend = CloudEmbeddingBackend(client)
        assert await backend.check_available() == 0

    async def test_invalid_key_detected(self):
        """'invalid' keyword in error triggers warning path."""
        client = _cell_client(exc=Exception("Invalid API key provided"))
        backend = CloudEmbeddingBackend(client)
        assert await backend.check_available() == 0

    async def test_unauthorized_detected(self):
        """'unauthorized' keyword in error triggers warning path."""
        client = _cell_client(exc=Exception("Unauthorized access"))
        backend = CloudEmbeddingBackend(client)
        assert await backend.check_available() == 0

    async def test_non_auth_error_logged_at_debug(self):
        """Non-auth errors (e.g. model not found) go to debug level."""
        client = _cell_client(exc=Exception("Model not found: xyz"))
        backend = CloudEmbeddingBackend(client)
        assert await backend.check_available() == 0


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
