from unittest.mock import MagicMock, patch

import pytest

from mnemo_mcp.reranker import (
    CloudReranker,
    FallbackChainReranker,
    Qwen3Reranker,
    build_default_rerank_chain,
)


class TestQwen3RerankerCheckAvailableCoverage:
    def test_check_available_model_rerank_exception(self):
        """check_available returns False when model.rerank raises an exception."""
        reranker = Qwen3Reranker()
        mock_model = MagicMock()
        mock_model.rerank.side_effect = Exception("Rerank failed")

        with patch.object(reranker, "_get_model", return_value=mock_model):
            with patch("mnemo_mcp.reranker.logger") as mock_logger:
                assert reranker.check_available() is False
                mock_logger.debug.assert_called()
                args, _ = mock_logger.debug.call_args
                assert "Local reranker not available: Rerank failed" in args[0]

    def test_check_available_get_model_exception(self):
        """check_available returns False when _get_model raises an exception."""
        reranker = Qwen3Reranker()

        with patch.object(reranker, "_get_model", side_effect=Exception("Load failed")):
            with patch("mnemo_mcp.reranker.logger") as mock_logger:
                assert reranker.check_available() is False
                mock_logger.debug.assert_called()
                args, _ = mock_logger.debug.call_args
                assert "Local reranker not available: Load failed" in args[0]


class TestFallbackChainRerankerCoverage:
    def test_rerank_exception_path(self):
        """FallbackChainReranker continues on backend exception."""
        mock_bad = MagicMock()
        mock_bad.rerank.side_effect = Exception("Boom")
        mock_good = MagicMock()
        mock_good.rerank.return_value = [(0, 0.5)]

        chain = FallbackChainReranker([mock_bad, mock_good])
        results = chain.rerank("q", ["d"])
        assert results == [(0, 0.5)]

    def test_check_available_any_true(self):
        """check_available returns True if any backend is available."""
        mock_bad = MagicMock()
        mock_bad.check_available.side_effect = Exception("Boom")
        mock_good = MagicMock()
        mock_good.check_available.return_value = True

        chain = FallbackChainReranker([mock_bad, mock_good])
        assert chain.check_available() is True

    def test_check_available_all_fail(self):
        """check_available returns False if all backends fail or unavailable."""
        mock_bad = MagicMock()
        mock_bad.check_available.side_effect = Exception("Boom")
        mock_off = MagicMock()
        mock_off.check_available.return_value = False

        chain = FallbackChainReranker([mock_bad, mock_off])
        assert chain.check_available() is False


class TestBuildDefaultRerankChain:
    def test_build_prefer_local(self, monkeypatch):
        monkeypatch.setenv("JINA_AI_API_KEY", "test")
        chain = build_default_rerank_chain(prefer_local=True)
        assert isinstance(chain, FallbackChainReranker)
        assert len(chain._backends) == 2  # local + jina
        assert isinstance(chain._backends[0], Qwen3Reranker)

    def test_build_prefer_cloud(self, monkeypatch):
        monkeypatch.setenv("COHERE_API_KEY", "test")
        chain = build_default_rerank_chain(prefer_local=False)
        assert isinstance(chain, FallbackChainReranker)
        assert isinstance(chain._backends[0], CloudReranker)


class TestFallbackChainRerankerEdgeCases:
    def test_init_no_backends(self):
        with pytest.raises(ValueError, match="at least one backend"):
            FallbackChainReranker([])

    def test_rerank_empty_docs(self):
        chain = FallbackChainReranker([MagicMock()])
        assert chain.rerank("q", []) == []

    def test_rerank_all_empty(self):
        m1 = MagicMock()
        m1.rerank.return_value = []
        chain = FallbackChainReranker([m1])
        assert chain.rerank("q", ["d"]) == []
