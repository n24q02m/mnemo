from unittest.mock import patch

from mnemo_mcp.reranker import CloudReranker


class TestCloudRerankerErrorFallback:
    def test_rerank_jina_exception_logs_and_returns_empty(self):
        """Verify that an exception in _rerank_jina is caught, logged, and returns []."""
        with patch("mnemo_mcp.reranker.CloudReranker._rerank_jina") as mock_jina:
            mock_jina.side_effect = Exception("Mock Jina Failure")
            reranker = CloudReranker(model="jina-reranker-v3")

            with patch("mnemo_mcp.reranker.logger") as mock_logger:
                results = reranker.rerank("test query", ["doc1"])

                assert results == []
                mock_logger.warning.assert_called_once()
                args, _ = mock_logger.warning.call_args
                assert "Cloud reranking failed (jina): Mock Jina Failure" in args[0]

    def test_rerank_cohere_exception_logs_and_returns_empty(self):
        """Verify that an exception in _rerank_cohere is caught, logged, and returns []."""
        with patch("mnemo_mcp.reranker.CloudReranker._rerank_cohere") as mock_cohere:
            mock_cohere.side_effect = Exception("Mock Cohere Failure")
            reranker = CloudReranker(model="rerank-v4.0-pro")

            with patch("mnemo_mcp.reranker.logger") as mock_logger:
                results = reranker.rerank("test query", ["doc1"])

                assert results == []
                mock_logger.warning.assert_called_once()
                args, _ = mock_logger.warning.call_args
                assert "Cloud reranking failed (cohere): Mock Cohere Failure" in args[0]
