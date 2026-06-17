import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from mnemo_mcp.reranker import (
    CloudReranker,
    FallbackChainReranker,
    Qwen3Reranker,
    _detect_rerank_provider,
    _strip_provider,
    build_default_rerank_chain,
)


def test_detect_rerank_provider_jina_env():
    """Test _detect_rerank_provider detects jina from env var."""
    with patch.dict(os.environ, {"JINA_AI_API_KEY": "test-key"}):
        # model 'rerank' usually defaults to cohere, but jina key makes it jina
        assert _detect_rerank_provider("something-else") == "jina"


def test_strip_provider():
    """Test _strip_provider handles slash correctly."""
    assert _strip_provider("jina_ai/model") == "model"
    assert _strip_provider("bare-model") == "bare-model"


def test_qwen3_reranker_full_flow():
    """Test Qwen3Reranker lazy loading and reranking."""
    reranker = Qwen3Reranker()

    mock_model_instance = MagicMock()
    mock_model_instance.rerank.return_value = [0.1, 0.2]

    # Mock sys.modules to avoid importing qwen3_embed (which triggers numpy issues)
    mock_qwen3 = MagicMock()
    mock_qwen3.TextCrossEncoder.return_value = mock_model_instance

    with patch.dict(sys.modules, {"qwen3_embed": mock_qwen3}):
        results = reranker.rerank("q", ["d1", "d2"])
        assert len(results) == 2
        assert results[0][0] == 1  # d2 had higher score
        assert reranker._model is not None


class TestFallbackChainReranker:
    def test_init_empty(self):
        with pytest.raises(
            ValueError, match="FallbackChainReranker requires at least one backend"
        ):
            FallbackChainReranker([])

    def test_rerank_empty_docs(self):
        chain = FallbackChainReranker([MagicMock()])
        assert chain.rerank("q", []) == []

    def test_rerank_success_chain(self):
        backend1 = MagicMock()
        backend1.rerank.return_value = []  # Empty means "try next" or "no results"

        backend2 = MagicMock()
        backend2.rerank.return_value = [(0, 0.9)]

        chain = FallbackChainReranker([backend1, backend2])
        results = chain.rerank("q", ["d"])
        assert results == [(0, 0.9)]
        assert backend1.rerank.called
        assert backend2.rerank.called

    def test_rerank_backend_exception(self):
        backend1 = MagicMock()
        backend1.rerank.side_effect = RuntimeError("fail")

        backend2 = MagicMock()
        backend2.rerank.return_value = [(0, 0.8)]

        chain = FallbackChainReranker([backend1, backend2])
        results = chain.rerank("q", ["d"])
        assert results == [(0, 0.8)]

    def test_rerank_all_fail(self):
        backend1 = MagicMock()
        backend1.rerank.return_value = []

        chain = FallbackChainReranker([backend1])
        assert chain.rerank("q", ["d"]) == []

    def test_check_available_chain(self):
        backend1 = MagicMock()
        backend1.check_available.side_effect = Exception("crash")

        backend2 = MagicMock()
        backend2.check_available.return_value = True

        chain = FallbackChainReranker([backend1, backend2])
        assert chain.check_available() is True

        backend2.check_available.return_value = False
        assert chain.check_available() is False


def test_build_default_rerank_chain_variants():
    # Test prefer_local=True, only local
    with patch.dict(os.environ, {}, clear=True):
        chain = build_default_rerank_chain(prefer_local=True)
        assert len(chain._backends) == 1
        assert isinstance(chain._backends[0], Qwen3Reranker)

    # Test prefer_local=False, Jina and Cohere
    env = {"JINA_AI_API_KEY": "j-key", "COHERE_API_KEY": "c-key"}
    with patch.dict(os.environ, env, clear=True):
        chain = build_default_rerank_chain(prefer_local=False)
        # Order: Jina, Cohere, Local
        assert len(chain._backends) == 3
        assert isinstance(chain._backends[0], CloudReranker)
        assert chain._backends[0].model == "jina_ai/jina-reranker-v3"
        assert isinstance(chain._backends[2], Qwen3Reranker)

    # Test CO_API_KEY fallback
    with patch.dict(os.environ, {"CO_API_KEY": "co-key"}, clear=True):
        chain = build_default_rerank_chain()
        assert any(
            isinstance(b, CloudReranker) and b.model == "rerank-v4.0-pro"
            for b in chain._backends
        )
