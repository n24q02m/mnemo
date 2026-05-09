"""Tests for reranker.py -- Jina provider and detection logic coverage.

Targets: _detect_rerank_provider (Jina env fallback, non-rerank/cohere model),
_strip_provider, CloudReranker Jina backend, CloudReranker._check_jina,
CloudReranker._check_cohere, Qwen3Reranker lazy load.
"""

from unittest.mock import MagicMock, patch

from mnemo_mcp.reranker import (
    CloudReranker,
    Qwen3Reranker,
    _detect_rerank_provider,
    _strip_provider,
)

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
# CloudReranker -- Jina backend
# ---------------------------------------------------------------------------


class TestCloudRerankerJina:
    @patch("httpx.post")
    def test_rerank_jina_success(self, mock_post):
        """Jina reranker returns sorted results."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.3},
                {"index": 1, "relevance_score": 0.9},
                {"index": 2, "relevance_score": 0.6},
            ]
        }
        mock_post.return_value = mock_response

        reranker = CloudReranker(
            model="jina_ai/jina-reranker-v3",
            api_key="jina_test",
        )
        results = reranker.rerank("query", ["doc0", "doc1", "doc2"], top_n=2)

        assert len(results) == 2
        assert results[0] == (1, 0.9)
        assert results[1] == (2, 0.6)

    @patch("httpx.post")
    def test_rerank_jina_failure(self, mock_post):
        """Jina reranker returns empty on failure."""
        mock_post.side_effect = Exception("API error")

        reranker = CloudReranker(
            model="jina_ai/jina-reranker-v3",
            api_key="jina_test",
        )
        results = reranker.rerank("query", ["doc0"])
        assert results == []


# ---------------------------------------------------------------------------
# CloudReranker -- check_available (Jina and Cohere paths)
# ---------------------------------------------------------------------------


class TestCheckAvailableReranker:
    @patch("httpx.post")
    def test_check_jina_available(self, mock_post):
        """Jina check_available returns True on success."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "results": [{"index": 0, "relevance_score": 0.5}]
        }
        mock_post.return_value = mock_response

        reranker = CloudReranker(
            model="jina_ai/jina-reranker-v3",
            api_key="jina_test",
        )
        assert reranker.check_available() is True

    @patch("httpx.post")
    def test_check_jina_api_key_invalid(self, mock_post):
        """Jina check_available returns False and logs warning on 401."""
        mock_post.side_effect = Exception("401 Unauthorized")

        reranker = CloudReranker(
            model="jina_ai/jina-reranker-v3",
            api_key="bad_key",
        )
        with patch("mnemo_mcp.reranker.logger") as mock_logger:
            assert reranker.check_available() is False
            mock_logger.warning.assert_called()
            assert "API key invalid" in mock_logger.warning.call_args[0][0]

    @patch("cohere.ClientV2")
    def test_check_cohere_available(self, mock_client_cls):
        """Cohere check_available returns True on success."""
        mock_result = MagicMock()
        mock_result.index = 0
        mock_result.relevance_score = 0.5

        mock_response = MagicMock()
        mock_response.results = [mock_result]

        mock_client = MagicMock()
        mock_client.rerank.return_value = mock_response
        mock_client_cls.return_value = mock_client

        reranker = CloudReranker(
            model="rerank-v4.0-pro",
            api_key="co_test",
        )
        assert reranker.check_available() is True

    @patch("cohere.ClientV2")
    def test_check_cohere_api_key_invalid_logging(self, mock_client_cls):
        """Cohere check_available logs warning for auth errors."""
        mock_client = MagicMock()
        mock_client.rerank.side_effect = Exception("invalid api key")
        mock_client_cls.return_value = mock_client

        reranker = CloudReranker(
            model="rerank-v4.0-pro",
            api_key="bad_key",
        )
        with patch("mnemo_mcp.reranker.logger") as mock_logger:
            assert reranker.check_available() is False
            mock_logger.warning.assert_called()
            assert "API key invalid" in mock_logger.warning.call_args[0][0]

    @patch("cohere.ClientV2")
    def test_check_cohere_non_auth_error(self, mock_client_cls):
        """Cohere check_available returns False on non-auth error."""
        mock_client = MagicMock()
        mock_client.rerank.side_effect = Exception("Model not found")
        mock_client_cls.return_value = mock_client

        reranker = CloudReranker(
            model="rerank-v4.0-pro",
            api_key="co_test",
        )
        with patch("mnemo_mcp.reranker.logger") as mock_logger:
            assert reranker.check_available() is False
            mock_logger.debug.assert_called()
            assert "not available" in mock_logger.debug.call_args[0][0]


# ---------------------------------------------------------------------------
# Qwen3Reranker lazy load
# ---------------------------------------------------------------------------


class TestQwen3RerankerLazyLoad:
    @patch("qwen3_embed.TextCrossEncoder")
    def test_lazy_load(self, mock_ce):
        """Model is loaded lazily on first _get_model() call."""
        mock_model = MagicMock()
        mock_ce.return_value = mock_model

        reranker = Qwen3Reranker("test/model")
        assert reranker._model is None

        result = reranker._get_model()
        assert result == mock_model
        mock_ce.assert_called_once_with(model_name="test/model")

    @patch("qwen3_embed.TextCrossEncoder")
    def test_caches_model(self, mock_ce):
        """Model is only loaded once (cached)."""
        mock_model = MagicMock()
        mock_ce.return_value = mock_model

        reranker = Qwen3Reranker()
        reranker._get_model()
        reranker._get_model()

        mock_ce.assert_called_once()

    def test_check_available_empty_scores(self):
        """check_available returns False when rerank returns empty."""
        reranker = Qwen3Reranker()
        mock_model = MagicMock()
        mock_model.rerank.return_value = []

        with patch.object(reranker, "_get_model", return_value=mock_model):
            assert reranker.check_available() is False
