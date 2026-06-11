"""Tests for mnemo_mcp.reranker -- dual-backend reranking.

Cloud reranking goes through mcp_core.llm (litellm passthrough); tests patch
the sync mirror ``mcp_core.llm.rerank``.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import mnemo_mcp.reranker as reranker_mod
from mnemo_mcp.reranker import (
    CloudReranker,
    CohereReranker,
    LiteLLMReranker,
    Qwen3Reranker,
    get_reranker,
    init_reranker,
)


def _rerank_resp(*results):
    """Build a litellm-shaped RerankResponse (resp.results)."""
    return SimpleNamespace(results=list(results))


@pytest.fixture(autouse=True)
def _reset_reranker_backend():
    """Reset module-level _backend before each test."""
    original = reranker_mod._backend
    reranker_mod._backend = None
    yield
    reranker_mod._backend = original


class TestCohereReranker:
    def test_rerank_success(self):
        """Cloud reranker returns sorted (index, score) tuples."""
        reranker = CohereReranker(api_key="test-key")
        resp = _rerank_resp(
            SimpleNamespace(index=0, relevance_score=0.3),
            SimpleNamespace(index=1, relevance_score=0.9),
            SimpleNamespace(index=2, relevance_score=0.6),
        )

        with patch("mcp_core.llm.rerank", return_value=resp):
            results = reranker.rerank("test query", ["doc0", "doc1", "doc2"], top_n=2)

        assert len(results) == 2
        assert results[0] == (1, 0.9)
        assert results[1] == (2, 0.6)

    def test_rerank_with_dict_results(self):
        """Cloud reranker handles dict-style results."""
        reranker = CohereReranker(api_key="test-key")
        resp = _rerank_resp(
            {"index": 0, "relevance_score": 0.8},
            {"index": 1, "relevance_score": 0.5},
        )

        with patch("mcp_core.llm.rerank", return_value=resp):
            results = reranker.rerank("query", ["doc0", "doc1"])

        assert results[0] == (0, 0.8)
        assert results[1] == (1, 0.5)

    def test_rerank_none_results_guarded(self):
        """litellm RerankResponse.results defaults to None -> empty list."""
        reranker = CohereReranker(api_key="test-key")
        resp = SimpleNamespace(results=None)

        with patch("mcp_core.llm.rerank", return_value=resp):
            results = reranker.rerank("query", ["doc"])

        assert results == []

    def test_rerank_empty_docs(self):
        """Empty documents list returns empty results."""
        reranker = CohereReranker(api_key="test-key")
        results = reranker.rerank("query", [])
        assert results == []

    def test_rerank_failure_returns_empty(self):
        """Reranker returns empty list on failure (never raises)."""
        reranker = CohereReranker(api_key="test-key")

        with patch("mcp_core.llm.rerank", side_effect=Exception("API error")):
            results = reranker.rerank("query", ["doc"])

        assert results == []

    def test_check_available_success(self):
        """check_available returns True when API responds."""
        reranker = CohereReranker(api_key="test-key")
        resp = _rerank_resp(SimpleNamespace(index=0, relevance_score=0.5))

        with patch("mcp_core.llm.rerank", return_value=resp):
            assert reranker.check_available() is True

    def test_check_available_failure(self):
        """check_available returns False on API failure."""
        reranker = CohereReranker(api_key="test-key")

        with patch("mcp_core.llm.rerank", side_effect=Exception("connection error")):
            assert reranker.check_available() is False

    def test_check_available_auth_error(self):
        """check_available logs warning for auth errors."""
        reranker = CohereReranker(api_key="bad-key")

        with patch("mcp_core.llm.rerank", side_effect=Exception("401 unauthorized")):
            assert reranker.check_available() is False

    def test_litellm_model_mapping(self):
        """Bare jina/cohere names map to litellm provider/model form."""
        assert CloudReranker(model="rerank-v4.0-pro")._litellm_model() == (
            "cohere/rerank-v4.0-pro"
        )
        assert CloudReranker(model="jina-reranker-v3")._litellm_model() == (
            "jina_ai/jina-reranker-v3"
        )
        assert CloudReranker(model="cohere/rerank-v4.0-pro")._litellm_model() == (
            "cohere/rerank-v4.0-pro"
        )

    def test_litellm_backward_compat_alias(self):
        """LiteLLMReranker is an alias for CloudReranker."""
        assert LiteLLMReranker is CloudReranker

    def test_cohere_backward_compat_alias(self):
        """CohereReranker is an alias for CloudReranker."""
        assert CohereReranker is CloudReranker


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
        assert reranker._model_name == "n24q02m/Qwen3-Reranker-0.6B-ONNX-YesNo"

    def test_none_model_uses_default(self):
        """None model name falls back to default."""
        reranker = Qwen3Reranker(None)
        assert reranker._model_name == "n24q02m/Qwen3-Reranker-0.6B-ONNX-YesNo"

    def test_lazy_load(self):
        """Model is not loaded until _get_model is called."""
        reranker = Qwen3Reranker()
        assert reranker._model is None


class TestInitReranker:
    def test_init_cloud(self):
        """init_reranker creates CohereReranker for 'cloud'."""
        backend = init_reranker("cloud", "rerank-v4.0-pro")
        assert isinstance(backend, CohereReranker)
        assert get_reranker() is backend

    def test_init_litellm_backward_compat(self):
        """init_reranker creates CohereReranker for 'litellm' (backward compat)."""
        backend = init_reranker("litellm", "rerank-v4.0-pro")
        assert isinstance(backend, CohereReranker)
        assert get_reranker() is backend

    def test_init_local(self):
        """init_reranker creates Qwen3Reranker."""
        backend = init_reranker("local")
        assert isinstance(backend, Qwen3Reranker)
        assert get_reranker() is backend

    def test_init_unknown_backend(self):
        """init_reranker raises ValueError for unknown backend."""
        with pytest.raises(ValueError, match="Unknown reranker backend"):
            init_reranker("invalid")

    def test_get_reranker_none_before_init(self):
        """get_reranker returns None before init."""
        assert get_reranker() is None

    def test_init_cloud_with_kwargs(self):
        """init_reranker passes api_base/api_key to CohereReranker."""
        backend = init_reranker(
            "cloud",
            "model",
            api_base="http://proxy:4000",
            api_key="sk-test",
        )
        assert isinstance(backend, CohereReranker)
        assert backend.api_base == "http://proxy:4000"
        assert backend.api_key == "sk-test"

    def test_init_local_with_custom_model(self):
        """init_reranker passes custom model to Qwen3Reranker."""
        backend = init_reranker("local", "custom/model")
        assert isinstance(backend, Qwen3Reranker)
        assert backend._model_name == "custom/model"
