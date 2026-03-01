from unittest.mock import AsyncMock, patch

import pytest

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
async def test_embed_backend_exception():
    """Test _embed handles backend exceptions gracefully."""
    mock_backend = AsyncMock()
    mock_backend.embed_single.side_effect = Exception("Embed error")

    with patch("mnemo_mcp.embedder.get_backend", return_value=mock_backend):
        result = await _embed("text", "model", 768)
        assert result is None
