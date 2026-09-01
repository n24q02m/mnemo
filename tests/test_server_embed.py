from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from litellm.exceptions import APIConnectionError, RateLimitError

from mnemo_mcp.server import _embed


@pytest.mark.asyncio
async def test_embed_no_model():
    """Test _embed returns None when model is None."""
    result = await _embed("text", None, 768)
    assert result is None


@pytest.mark.asyncio
async def test_embed_query_passes_query_role_to_any_backend():
    """Queries use the protocol role rather than a concrete backend branch."""
    backend = MagicMock()
    backend.embed_single = AsyncMock(return_value=[0.3, 0.4])

    result = await _embed(
        "search query", "some-model", 768, is_query=True, backend=backend
    )

    assert result == [0.3, 0.4]
    backend.embed_single.assert_awaited_once_with("search query", 768, role="query")


@pytest.mark.asyncio
async def test_embed_document_passes_document_role():
    """Documents use the protocol's explicit document role."""
    backend = MagicMock()
    backend.embed_single = AsyncMock(return_value=[0.5, 0.6])

    result = await _embed("memory body", "some-model", 768, backend=backend)

    assert result == [0.5, 0.6]
    backend.embed_single.assert_awaited_once_with("memory body", 768, role="document")


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
