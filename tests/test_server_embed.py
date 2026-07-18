from unittest.mock import AsyncMock, patch

import pytest
from litellm.exceptions import APIConnectionError, RateLimitError

from mnemo_mcp.embedder import Qwen3EmbedBackend
from mnemo_mcp.server import _embed


@pytest.mark.asyncio
async def test_embed_no_model():
    """Test _embed returns None when model is None."""
    result = await _embed("text", None, 768)
    assert result is None


@pytest.mark.asyncio
async def test_embed_with_generic_backend_query():
    """Test _embed with a generic backend (not Qwen3) calls embed_single even for query."""
    mock_backend = AsyncMock()
    mock_backend.embed_single.return_value = [0.1, 0.2]

    with patch("mnemo_mcp.embedder.get_backend", return_value=mock_backend):
        # Call with is_query=True
        result = await _embed("text", "model", 768, is_query=True)
        assert result == [0.1, 0.2]
        mock_backend.embed_single.assert_called_once_with("text", 768)


@pytest.mark.asyncio
async def test_embed_with_qwen3_backend_query():
    """Test _embed with Qwen3Backend and is_query=True calls embed_single_query."""
    mock_backend = AsyncMock(spec=Qwen3EmbedBackend)
    mock_backend.embed_single_query.return_value = [0.3, 0.4]

    with patch("mnemo_mcp.embedder.get_backend", return_value=mock_backend):
        result = await _embed("text", "model", 768, is_query=True)
        assert result == [0.3, 0.4]
        mock_backend.embed_single_query.assert_called_once_with("text", 768)


@pytest.mark.asyncio
async def test_embed_with_qwen3_backend_doc():
    """Test _embed with Qwen3Backend and is_query=False calls embed_single."""
    mock_backend = AsyncMock(spec=Qwen3EmbedBackend)
    mock_backend.embed_single.return_value = [0.5, 0.6]

    with patch("mnemo_mcp.embedder.get_backend", return_value=mock_backend):
        result = await _embed("text", "model", 768, is_query=False)
        assert result == [0.5, 0.6]
        mock_backend.embed_single.assert_called_once_with("text", 768)


@pytest.mark.asyncio
async def test_embed_transient_error_degrades_to_none():
    """A transient backend error (rate-limit/network) degrades this call to FTS5.

    The next call may succeed, so returning None (FTS5-only for this call) is the
    correct graceful degradation.
    """
    mock_backend = AsyncMock()
    mock_backend.embed_single.side_effect = RateLimitError(
        message="rate limit exceeded", llm_provider="cohere", model="embed-v4.0"
    )

    with patch("mnemo_mcp.embedder.get_backend", return_value=mock_backend):
        result = await _embed("text", "model", 768)
        assert result is None


@pytest.mark.asyncio
async def test_embed_permanent_error_raises_loudly():
    """A permanent backend error (bad key, unusable model/dims) must NOT be
    silently swallowed into None -- every embed would fail, so surface it loudly.
    """
    mock_backend = AsyncMock()
    mock_backend.embed_single.side_effect = APIConnectionError(
        message="AuthenticationError - invalid api key",
        llm_provider="cohere",
        model="embed-v4.0",
    )

    with patch("mnemo_mcp.embedder.get_backend", return_value=mock_backend):
        with pytest.raises(APIConnectionError):
            await _embed("text", "model", 768)
