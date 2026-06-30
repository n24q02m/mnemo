"""Tests for reranker.py -- provider detection logic and cloud path coverage.

Targets: _detect_rerank_provider (Jina env fallback, non-rerank/cohere model),
_strip_provider, CloudReranker litellm passthrough (Jina + Cohere routing),
check_available auth/non-auth branches, Qwen3Reranker lazy load.
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mnemo_mcp.reranker import (
    CloudReranker,
    Qwen3Reranker,
    _detect_rerank_provider,
    _strip_provider,
)


def _rerank_resp(*results):
    """Build a litellm-shaped RerankResponse (resp.results)."""
    return SimpleNamespace(results=list(results))


# ---------------------------------------------------------------------------
# _detect_rerank_provider
# ---------------------------------------------------------------------------


class TestDetectRerankProvider:
    def test_jina_prefix(self):
        assert _detect_rerank_provider("jina_ai/jina-reranker-v3") == "jina"

    def test_jina_short_prefix(self):
        assert _detect_rerank_provider("jina-reranker-v3") == "jina"

    def test_cohere_rerank_prefix(self):
        assert _detect_rerank_provider("rerank-v4.0-pro") == "cohere"

    def test_cohere_provider_prefix(self):
        assert _detect_rerank_provider("cohere/rerank-v4.0-pro") == "cohere"

    def test_unknown_model_with_jina_env(self, monkeypatch):
        """Falls back to jina when JINA_AI_API_KEY is set for unknown model."""
        monkeypatch.setenv("JINA_AI_API_KEY", "jina_test")
        assert _detect_rerank_provider("custom-model") == "jina"

    def test_unknown_model_no_env(self, monkeypatch):
        """Falls back to cohere when no jina env var for unknown model."""
        monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
        assert _detect_rerank_provider("custom-model") == "cohere"


class TestStripProviderReranker:
    def test_with_prefix(self):
        assert _strip_provider("jina_ai/jina-reranker-v3") == "jina-reranker-v3"

    def test_without_prefix(self):
        assert _strip_provider("rerank-v4.0-pro") == "rerank-v4.0-pro"


# ---------------------------------------------------------------------------
# CloudReranker -- cloud path (litellm passthrough)
# ---------------------------------------------------------------------------


class TestCloudRerankerJina:
    def test_rerank_jina_success(self):
        """Jina-model reranker returns sorted results via litellm."""
        resp = _rerank_resp(
            {"index": 0, "relevance_score": 0.3},
            {"index": 1, "relevance_score": 0.9},
            {"index": 2, "relevance_score": 0.6},
        )
        reranker = CloudReranker(model="jina_ai/jina-reranker-v3", api_key="jina_test")
        with patch("mcp_core.llm.rerank", return_value=resp) as mock:
            results = reranker.rerank("query", ["doc0", "doc1", "doc2"], top_n=2)

        assert len(results) == 2
        assert results[0] == (1, 0.9)
        assert results[1] == (2, 0.6)
        assert mock.call_args.kwargs["model"] == "jina_ai/jina-reranker-v3"

    def test_rerank_jina_failure(self):
        """Reranker returns empty on failure."""
        reranker = CloudReranker(model="jina_ai/jina-reranker-v3", api_key="jina_test")
        with patch("mcp_core.llm.rerank", side_effect=Exception("API error")):
            results = reranker.rerank("query", ["doc0"])
        assert results == []


# ---------------------------------------------------------------------------
# CloudReranker -- check_available (auth vs non-auth branches)
# ---------------------------------------------------------------------------


class TestCheckAvailableReranker:
    def test_check_jina_available(self):
        """check_available returns True on success."""
        resp = _rerank_resp({"index": 0, "relevance_score": 0.5})
        reranker = CloudReranker(model="jina_ai/jina-reranker-v3", api_key="jina_test")
        with patch("mcp_core.llm.rerank", return_value=resp):
            assert reranker.check_available() is True

    def test_check_jina_api_key_invalid(self):
        """check_available returns False and logs warning on 401."""
        reranker = CloudReranker(model="jina_ai/jina-reranker-v3", api_key="bad_key")
        with (
            patch("mcp_core.llm.rerank", side_effect=Exception("401 Unauthorized")),
            patch("mnemo_mcp.reranker.logger") as mock_logger,
        ):
            assert reranker.check_available() is False
            mock_logger.warning.assert_called()
            assert "API key invalid" in mock_logger.warning.call_args[0][0]

    def test_check_cohere_available(self):
        """check_available returns True on success for cohere model."""
        resp = _rerank_resp(SimpleNamespace(index=0, relevance_score=0.5))
        reranker = CloudReranker(model="rerank-v4.0-pro", api_key="co_test")
        with patch("mcp_core.llm.rerank", return_value=resp):
            assert reranker.check_available() is True

    def test_check_cohere_api_key_invalid_logging(self):
        """check_available logs warning for auth errors."""
        reranker = CloudReranker(model="rerank-v4.0-pro", api_key="bad_key")
        with (
            patch("mcp_core.llm.rerank", side_effect=Exception("invalid api key")),
            patch("mnemo_mcp.reranker.logger") as mock_logger,
        ):
            assert reranker.check_available() is False
            mock_logger.warning.assert_called()
            assert "API key invalid" in mock_logger.warning.call_args[0][0]

    def test_check_cohere_non_auth_error(self):
        """check_available returns False on non-auth error."""
        reranker = CloudReranker(model="rerank-v4.0-pro", api_key="co_test")
        with (
            patch("mcp_core.llm.rerank", side_effect=Exception("Model not found")),
            patch("mnemo_mcp.reranker.logger") as mock_logger,
        ):
            assert reranker.check_available() is False
            mock_logger.debug.assert_called()
            assert "not available" in mock_logger.debug.call_args[0][0]


# ---------------------------------------------------------------------------
# Qwen3Reranker lazy load
# ---------------------------------------------------------------------------


class TestQwen3RerankerLazyLoad:
    def test_lazy_load(self):
        """Model is loaded lazily on first _get_model() call."""
        mock_qwen = MagicMock()
        mock_model = MagicMock()
        mock_qwen.TextCrossEncoder.return_value = mock_model

        with patch.dict(sys.modules, {"qwen3_embed": mock_qwen}):
            reranker = Qwen3Reranker("test/model")
            assert reranker._model is None

            result = reranker._get_model()
            assert result == mock_model
            mock_qwen.TextCrossEncoder.assert_called_once_with(model_name="test/model")

    def test_caches_model(self):
        """Model is only loaded once (cached)."""
        mock_qwen = MagicMock()
        mock_model = MagicMock()
        mock_qwen.TextCrossEncoder.return_value = mock_model

        with patch.dict(sys.modules, {"qwen3_embed": mock_qwen}):
            reranker = Qwen3Reranker()
            reranker._get_model()
            reranker._get_model()

            mock_qwen.TextCrossEncoder.assert_called_once()

    def test_check_available_empty_scores(self):
        """check_available returns False when rerank returns empty."""
        reranker = Qwen3Reranker()
        mock_model = MagicMock()
        mock_model.rerank.return_value = []

        with patch.object(reranker, "_get_model", return_value=mock_model):
            assert reranker.check_available() is False
