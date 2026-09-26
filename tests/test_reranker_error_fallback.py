"""CloudReranker failure path: exception -> logged warning, empty results.

De-host rework: the model comes from the ``[models.rerank]`` cell now, so the
warning carries the cell-owned model id instead of a provider prefix.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from mnemo_mcp.reranker import CloudReranker


def _cell_client(model, exc):
    """Stub hull OpenAI-spec client for the rerank cell."""
    client = MagicMock()
    client.cell.model = model
    client.rerank = AsyncMock(side_effect=exc)
    return client


class TestCloudRerankerErrorFallback:
    def test_rerank_exception_logs_and_returns_empty(self):
        """An exception in the cloud rerank path is caught, logged, returns []."""
        reranker = CloudReranker(
            _cell_client("jina-reranker-v3", Exception("Mock cell failure"))
        )

        with patch("mnemo_mcp.reranker.logger") as mock_logger:
            results = reranker.rerank("test query", ["doc1"])

        assert results == []
        mock_logger.warning.assert_called_once()
        args, _ = mock_logger.warning.call_args
        assert (
            "Cloud reranking failed (jina-reranker-v3): Mock cell failure" in args[0]
        )

    def test_rerank_cohere_style_model_exception_logs_and_returns_empty(self):
        """Same failure contract for a cell-owned rerank-v4 model id."""
        reranker = CloudReranker(
            _cell_client("rerank-v4.0-pro", Exception("Mock cell failure"))
        )

        with patch("mnemo_mcp.reranker.logger") as mock_logger:
            results = reranker.rerank("test query", ["doc1"])

        assert results == []
        mock_logger.warning.assert_called_once()
        args, _ = mock_logger.warning.call_args
        assert "Cloud reranking failed (rerank-v4.0-pro): Mock cell failure" in args[0]
