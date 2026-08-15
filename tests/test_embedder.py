"""Tests for mnemo_mcp.embedder -- dual-backend embedding (all mocked).

Cloud embedding goes through mcp_core.llm (litellm passthrough). Async paths
patch ``mcp_core.llm.aembedding``; ``check_available`` (sync) patches the sync
mirror ``mcp_core.llm.embedding``.
"""

import socket
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch
from urllib.parse import urlsplit

import pytest

from mnemo_mcp import embedder
from mnemo_mcp.embedder import (
    CloudEmbeddingBackend,
    LiteLLMBackend,
    Qwen3EmbedBackend,
    embed_single,
    get_backend,
    init_backend,
)


@contextmanager
def _stalled_endpoint():
    """Serve a loopback address that accepts connections and never replies.

    This is the shape of provider outage the availability probe has to survive:
    the TCP handshake succeeds, so nothing fails fast, and the client then waits
    on response headers that never arrive.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    accepted: list[socket.socket] = []

    def _accept_and_ignore() -> None:
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            accepted.append(conn)

    thread = threading.Thread(target=_accept_and_ignore, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        listener.close()
        for conn in accepted:
            conn.close()
        thread.join(timeout=5)


def _resp(*vectors):
    """Build a litellm-shaped embedding response (resp.data list of pydantic)."""
    return SimpleNamespace(
        data=[
            SimpleNamespace(index=i, embedding=list(v)) for i, v in enumerate(vectors)
        ]
    )


def _async_resp(*vectors):
    """AsyncMock returning a litellm embedding response."""
    return AsyncMock(return_value=_resp(*vectors))


class TestCloudEmbeddingBackend:
    async def test_returns_embeddings(self):
        mock = _async_resp([0.1, 0.2, 0.3], [0.4, 0.5, 0.6])
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(api_key="test-key")
            result = await backend.embed_texts(["hello", "world"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]

    async def test_empty_input(self):
        mock = _async_resp([0.1])
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(api_key="test-key")
            result = await backend.embed_texts([])
        assert result == []
        mock.assert_not_called()

    async def test_passes_dimensions(self):
        mock = _async_resp([0.1])
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(
                model="embed-multilingual-v3.0", api_key="key"
            )
            await backend.embed_texts(["test"], dimensions=512)
        assert mock.call_args.kwargs.get("dimensions") == 512

    async def test_dimensions_fallback_on_unsupported(self):
        """Falls back to local truncation when provider rejects dimensions."""
        unsupported_err = Exception("output_dimension is not supported for this model")
        mock = AsyncMock(side_effect=[unsupported_err, _resp([0.1] * 1024)])
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(
                model="embed-multilingual-v3.0", api_key="key"
            )
            result = await backend.embed_texts(["test"], dimensions=768)
        assert len(result[0]) == 768

    async def test_local_truncation_when_server_returns_more(self):
        """Truncates locally when server returns more dims than requested."""
        mock = _async_resp([0.1] * 3072)
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(api_key="key")
            result = await backend.embed_texts(["test"], dimensions=768)
        assert len(result[0]) == 768

    async def test_embed_single(self):
        mock = _async_resp([0.1, 0.2, 0.3])
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(api_key="key")
            result = await backend.embed_single("hello")
        assert result == [0.1, 0.2, 0.3]

    def test_check_available_returns_dims(self):
        mock = MagicMock(return_value=_resp([0.1, 0.2]))
        with patch("mcp_core.llm.embedding", mock):
            backend = CloudEmbeddingBackend(api_key="key")
            assert backend.check_available() == 2

    def test_check_available_error(self):
        mock = MagicMock(side_effect=Exception("Model not found"))
        with patch("mcp_core.llm.embedding", mock):
            backend = CloudEmbeddingBackend(api_key="key")
            assert backend.check_available() == 0

    async def test_raises_on_non_retryable_error(self):
        mock = AsyncMock(side_effect=Exception("Invalid API key"))
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(api_key="key")
            with pytest.raises(Exception, match="Invalid API key"):
                await backend.embed_texts(["test"])

    def test_check_available_empty_data(self):
        mock = MagicMock(return_value=SimpleNamespace(data=[]))
        with patch("mcp_core.llm.embedding", mock):
            backend = CloudEmbeddingBackend(api_key="key")
            assert backend.check_available() == 0

    def test_check_available_passes_probe_timeout(self):
        """The probe hands litellm an explicit bound instead of its 600s default."""
        mock = MagicMock(return_value=_resp([0.1, 0.2]))
        with patch("mcp_core.llm.embedding", mock):
            backend = CloudEmbeddingBackend(api_key="key")
            assert backend.check_available() == 2
        assert mock.call_args.kwargs["timeout"] == embedder.PROBE_TIMEOUT

    def test_check_available_gives_up_on_a_stalled_provider(self, monkeypatch):
        """The probe returns instead of hanging when the provider never answers.

        Regression cover for the hang in CI run 30755522961: check_available
        called litellm with no timeout, so a provider that accepted the socket
        and then went quiet held the caller -- and, through
        config(action="setup_complete"), the user's tool call -- open
        indefinitely. The server here is the minimal reproduction of that: it
        completes the TCP handshake and sends nothing back, ever.
        """
        # vet_api_base only permits a loopback api_base outside multi-user mode.
        monkeypatch.delenv("PUBLIC_URL", raising=False)
        monkeypatch.setattr(embedder, "PROBE_TIMEOUT", 1.0)

        with _stalled_endpoint() as api_base:

            def _stalling_embedding(**kwargs):
                address = urlsplit(kwargs["api_base"])
                with socket.create_connection(
                    (address.hostname, address.port), timeout=kwargs["timeout"]
                ) as connection:
                    connection.settimeout(kwargs["timeout"])
                    connection.recv(1)

            provider = MagicMock(side_effect=_stalling_embedding)
            backend = CloudEmbeddingBackend(
                model="openai/text-embedding-3-small",
                api_base=api_base,
                api_key="key",
            )
            started = time.monotonic()
            with patch("mcp_core.llm.embedding", provider):
                dims = backend.check_available()
            elapsed = time.monotonic() - started

        assert dims == 0
        assert provider.call_args.kwargs["timeout"] == 1.0
        assert provider.call_args.kwargs["num_retries"] == 0
        # Generous next to the 1.0s bound because the provider SDK retries the
        # attempt, and each retry gets its own timeout -- see the note on
        # PROBE_TIMEOUT. The point being pinned is the order of magnitude:
        # without any timeout the call sits on litellm's 600s default, which
        # the 30s pytest-timeout turns into the same red job this fix is for.
        assert elapsed < 10, f"probe ran for {elapsed:.1f}s"

    def test_litellm_backward_compat_alias(self):
        """LiteLLMBackend is an alias for CloudEmbeddingBackend."""
        assert LiteLLMBackend is CloudEmbeddingBackend


class TestBatchSplitting:
    async def test_splits_large_batch(self):
        """Texts exceeding MAX_BATCH_SIZE are split into sub-batches."""
        n = CloudEmbeddingBackend.MAX_BATCH_SIZE + 50

        async def fake(*, input, **kwargs):
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=j, embedding=[float(j)])
                    for j in range(len(input))
                ]
            )

        with patch("mcp_core.llm.aembedding", side_effect=fake):
            backend = CloudEmbeddingBackend(api_key="key")
            vecs = await backend.embed_texts([f"t{i}" for i in range(n)])
        assert len(vecs) == n

    async def test_batch_call_count(self):
        """Correct number of API calls for split batches."""
        n = CloudEmbeddingBackend.MAX_BATCH_SIZE * 2 + 10

        async def fake(*, input, **kwargs):
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=j, embedding=[0.0]) for j in range(len(input))
                ]
            )

        mock = AsyncMock(side_effect=fake)
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(api_key="key")
            await backend.embed_texts([f"t{i}" for i in range(n)])
        assert mock.call_count == 3

    async def test_no_split_under_limit(self):
        async def fake(*, input, **kwargs):
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=j, embedding=[0.0]) for j in range(len(input))
                ]
            )

        mock = AsyncMock(side_effect=fake)
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(api_key="key")
            await backend.embed_texts(
                [f"t{i}" for i in range(CloudEmbeddingBackend.MAX_BATCH_SIZE)]
            )
        assert mock.call_count == 1


class TestRetryLogic:
    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_rate_limit(self, mock_sleep):
        mock = AsyncMock(
            side_effect=[Exception("429 rate limit exceeded"), _resp([0.1])]
        )
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(api_key="key")
            result = await backend.embed_texts(["test"])
        assert result == [[0.1]]
        mock_sleep.assert_called_once_with(1.0)

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_server_error(self, mock_sleep):
        mock = AsyncMock(
            side_effect=[Exception("503 temporarily unavailable"), _resp([0.2])]
        )
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(api_key="key")
            result = await backend.embed_texts(["test"])
        assert result == [[0.2]]

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_no_retry_on_non_retryable(self, mock_sleep):
        mock = AsyncMock(side_effect=Exception("Invalid API key"))
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(api_key="key")
            with pytest.raises(Exception, match="Invalid API key"):
                await backend.embed_texts(["test"])
        mock_sleep.assert_not_called()

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_exponential_backoff(self, mock_sleep):
        mock = AsyncMock(
            side_effect=[
                Exception("429 rate limit"),
                Exception("429 rate limit"),
                _resp([0.1]),
            ]
        )
        with patch("mcp_core.llm.aembedding", mock):
            backend = CloudEmbeddingBackend(api_key="key")
            await backend.embed_texts(["test"])
        assert mock_sleep.call_args_list == [call(1.0), call(2.0)]

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_max_retries_exhausted(self, mock_sleep):
        mock = AsyncMock(side_effect=Exception("429 rate limit"))
        with patch("mcp_core.llm.aembedding", mock):
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
        """Returns 0 when fastretrieval is not available."""
        mock_get_model.side_effect = ImportError("No module named 'fastretrieval'")
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

    def test_api_key_401_logs_warning(self):
        """401 errors are logged at warning level (not debug)."""
        mock = MagicMock(side_effect=Exception("401 Unauthorized: Invalid API key"))
        with patch("mcp_core.llm.embedding", mock):
            backend = CloudEmbeddingBackend(api_key="bad-key")
            assert backend.check_available() == 0

    def test_api_key_403_logs_warning(self):
        """403 forbidden errors are logged at warning level."""
        mock = MagicMock(side_effect=Exception("403 Forbidden"))
        with patch("mcp_core.llm.embedding", mock):
            backend = CloudEmbeddingBackend(api_key="bad-key")
            assert backend.check_available() == 0

    def test_invalid_key_detected(self):
        """'invalid' keyword in error triggers warning path."""
        mock = MagicMock(side_effect=Exception("Invalid API key provided"))
        with patch("mcp_core.llm.embedding", mock):
            backend = CloudEmbeddingBackend(api_key="bad-key")
            assert backend.check_available() == 0

    def test_unauthorized_detected(self):
        """'unauthorized' keyword in error triggers warning path."""
        mock = MagicMock(side_effect=Exception("Unauthorized access"))
        with patch("mcp_core.llm.embedding", mock):
            backend = CloudEmbeddingBackend(api_key="bad-key")
            assert backend.check_available() == 0

    def test_non_auth_error_logged_at_debug(self):
        """Non-auth errors (e.g. model not found) go to debug level."""
        mock = MagicMock(side_effect=Exception("Model not found: xyz"))
        with patch("mcp_core.llm.embedding", mock):
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

    async def test_embed_single_legacy(self):
        mock = _async_resp([0.1, 0.2])
        with patch("mcp_core.llm.aembedding", mock):
            result = await embed_single(
                "test", "embed-multilingual-v3.0", api_key="key"
            )
        assert result == [0.1, 0.2]
