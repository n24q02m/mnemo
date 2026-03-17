"""Tests for mnemo_mcp.reranker -- dual-backend reranking."""

from unittest.mock import MagicMock, patch

import pytest

import mnemo_mcp.reranker as reranker_mod
from mnemo_mcp.reranker import (
    LiteLLMReranker,
    Qwen3Reranker,
    get_reranker,
    init_reranker,
)


@pytest.fixture(autouse=True)
def _reset_reranker_backend():
    """Reset module-level _backend before each test."""
    original = reranker_mod._backend
    reranker_mod._backend = None
    yield
    reranker_mod._backend = original


class TestLiteLLMReranker:
    @patch("mnemo_mcp.reranker.LiteLLMReranker._setup_litellm")
    def test_rerank_success(self, _mock_setup):
        """LiteLLM reranker returns sorted (index, score) tuples."""
        reranker = LiteLLMReranker("jina_ai/jina-reranker-v3")

        mock_result_0 = MagicMock()
        mock_result_0.index = 0
        mock_result_0.relevance_score = 0.3

        mock_result_1 = MagicMock()
        mock_result_1.index = 1
        mock_result_1.relevance_score = 0.9

        mock_result_2 = MagicMock()
        mock_result_2.index = 2
        mock_result_2.relevance_score = 0.6

        mock_response = MagicMock()
        mock_response.results = [mock_result_0, mock_result_1, mock_result_2]

        with patch("litellm.rerank", return_value=mock_response):
            results = reranker.rerank("test query", ["doc0", "doc1", "doc2"], top_n=2)

        assert len(results) == 2
        assert results[0] == (1, 0.9)
        assert results[1] == (2, 0.6)

    @patch("mnemo_mcp.reranker.LiteLLMReranker._setup_litellm")
    def test_rerank_with_dict_results(self, _mock_setup):
        """LiteLLM reranker handles dict-style results."""
        reranker = LiteLLMReranker("jina_ai/jina-reranker-v3")

        mock_response = MagicMock()
        mock_response.results = [
            {"index": 0, "relevance_score": 0.8},
            {"index": 1, "relevance_score": 0.5},
        ]

        with patch("litellm.rerank", return_value=mock_response):
            results = reranker.rerank("query", ["doc0", "doc1"])

        assert results[0] == (0, 0.8)
        assert results[1] == (1, 0.5)

    @patch("mnemo_mcp.reranker.LiteLLMReranker._setup_litellm")
    def test_rerank_empty_docs(self, _mock_setup):
        """Empty documents list returns empty results."""
        reranker = LiteLLMReranker("jina_ai/jina-reranker-v3")
        results = reranker.rerank("query", [])
        assert results == []

    @patch("mnemo_mcp.reranker.LiteLLMReranker._setup_litellm")
    def test_rerank_failure_returns_empty(self, _mock_setup):
        """Reranker returns empty list on failure (never raises)."""
        reranker = LiteLLMReranker("jina_ai/jina-reranker-v3")

        with patch("litellm.rerank", side_effect=Exception("API error")):
            results = reranker.rerank("query", ["doc"])

        assert results == []

    @patch("mnemo_mcp.reranker.LiteLLMReranker._setup_litellm")
    def test_check_available_success(self, _mock_setup):
        """check_available returns True when API responds."""
        reranker = LiteLLMReranker("jina_ai/jina-reranker-v3")

        mock_response = MagicMock()
        mock_response.results = [MagicMock()]

        with patch("litellm.rerank", return_value=mock_response):
            assert reranker.check_available() is True

    @patch("mnemo_mcp.reranker.LiteLLMReranker._setup_litellm")
    def test_check_available_failure(self, _mock_setup):
        """check_available returns False on API failure."""
        reranker = LiteLLMReranker("jina_ai/jina-reranker-v3")

        with patch("litellm.rerank", side_effect=Exception("connection error")):
            assert reranker.check_available() is False

    @patch("mnemo_mcp.reranker.LiteLLMReranker._setup_litellm")
    def test_check_available_auth_error(self, _mock_setup):
        """check_available logs warning for auth errors."""
        reranker = LiteLLMReranker("jina_ai/jina-reranker-v3")

        with patch("litellm.rerank", side_effect=Exception("401 unauthorized")):
            assert reranker.check_available() is False

    @patch("mnemo_mcp.reranker.LiteLLMReranker._setup_litellm")
    def test_rerank_with_api_base_and_key(self, _mock_setup):
        """api_base and api_key are passed to litellm.rerank()."""
        reranker = LiteLLMReranker(
            "model", api_base="http://proxy:4000", api_key="sk-test"
        )

        mock_response = MagicMock()
        mock_response.results = []

        with patch("litellm.rerank", return_value=mock_response) as mock_rerank:
            reranker.rerank("query", ["doc"])
            call_kwargs = mock_rerank.call_args[1]
            assert call_kwargs["api_base"] == "http://proxy:4000"
            assert call_kwargs["api_key"] == "sk-test"


class TestQwen3Reranker:
    def test_rerank_success(self):
        """Local reranker returns sorted (index, score) tuples."""
        reranker = Qwen3Reranker()

        mock_model = MagicMock()
        mock_model.rerank.return_value = [0.3, 0.9, 0.6]

        with patch.object(reranker, "_get_model", return_value=mock_model):
            results = reranker.rerank("query", ["doc0", "doc1", "doc2"], top_n=2)

        assert len(results) == 2
        assert results[0] == (1, 0.9)
        assert results[1] == (2, 0.6)

    def test_rerank_empty_docs(self):
        """Empty documents list returns empty results."""
        reranker = Qwen3Reranker()
        results = reranker.rerank("query", [])
        assert results == []

    def test_rerank_failure_returns_empty(self):
        """Local reranker returns empty list on failure."""
        reranker = Qwen3Reranker()

        mock_model = MagicMock()
        mock_model.rerank.side_effect = RuntimeError("ONNX error")

        with patch.object(reranker, "_get_model", return_value=mock_model):
            results = reranker.rerank("query", ["doc"])

        assert results == []

    def test_check_available_success(self):
        """check_available returns True when model loads."""
        reranker = Qwen3Reranker()

        mock_model = MagicMock()
        mock_model.rerank.return_value = [0.5]

        with patch.object(reranker, "_get_model", return_value=mock_model):
            assert reranker.check_available() is True

    def test_check_available_failure(self):
        """check_available returns False when model fails."""
        reranker = Qwen3Reranker()

        with patch.object(
            reranker, "_get_model", side_effect=ImportError("no qwen3_embed")
        ):
            assert reranker.check_available() is False

    def test_custom_model_name(self):
        """Custom model name is stored."""
        reranker = Qwen3Reranker("custom/model")
        assert reranker._model_name == "custom/model"

    def test_default_model_name(self):
        """Default model name is used when none specified."""
        reranker = Qwen3Reranker()
        assert reranker._model_name == "n24q02m/Qwen3-Reranker-0.6B-ONNX"

    def test_none_model_uses_default(self):
        """None model name falls back to default."""
        reranker = Qwen3Reranker(None)
        assert reranker._model_name == "n24q02m/Qwen3-Reranker-0.6B-ONNX"

    def test_lazy_load(self):
        """Model is not loaded until _get_model is called."""
        reranker = Qwen3Reranker()
        assert reranker._model is None


class TestInitReranker:
    def test_init_litellm(self):
        """init_reranker creates LiteLLMReranker."""
        with patch("mnemo_mcp.reranker.LiteLLMReranker._setup_litellm"):
            backend = init_reranker("litellm", "jina_ai/jina-reranker-v3")

        assert isinstance(backend, LiteLLMReranker)
        assert get_reranker() is backend

    def test_init_local(self):
        """init_reranker creates Qwen3Reranker."""
        backend = init_reranker("local")
        assert isinstance(backend, Qwen3Reranker)
        assert get_reranker() is backend

    def test_init_litellm_requires_model(self):
        """init_reranker raises ValueError without model for litellm."""
        with pytest.raises(ValueError, match="model is required"):
            init_reranker("litellm")

    def test_init_unknown_backend(self):
        """init_reranker raises ValueError for unknown backend."""
        with pytest.raises(ValueError, match="Unknown reranker backend"):
            init_reranker("invalid")

    def test_get_reranker_none_before_init(self):
        """get_reranker returns None before init."""
        assert get_reranker() is None

    def test_init_litellm_with_kwargs(self):
        """init_reranker passes api_base/api_key to LiteLLMReranker."""
        with patch("mnemo_mcp.reranker.LiteLLMReranker._setup_litellm"):
            backend = init_reranker(
                "litellm",
                "model",
                api_base="http://proxy:4000",
                api_key="sk-test",
            )

        assert isinstance(backend, LiteLLMReranker)
        assert backend.api_base == "http://proxy:4000"
        assert backend.api_key == "sk-test"

    def test_init_local_with_custom_model(self):
        """init_reranker passes custom model to Qwen3Reranker."""
        backend = init_reranker("local", "custom/model")
        assert isinstance(backend, Qwen3Reranker)
        assert backend._model_name == "custom/model"
