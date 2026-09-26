"""Tests for mnemo_mcp.reranker -- dual-backend reranking.

Cloud reranking goes through the ``[models.rerank]`` provider cell (hull-core
OpenAI-spec client); tests inject a stub client instead of any network.
"""

from unittest.mock import MagicMock, patch

import pytest

import mnemo_mcp.reranker as reranker_mod
from mnemo_mcp.reranker import (
    CloudReranker,
    Qwen3Reranker,
    describe_reranker,
    get_reranker,
    init_reranker,
    rerank_with_identity,
)


def _cell_client(model="rerank-v4.0", results=None, exc=None):
    """Stub hull OpenAI-spec client for the rerank cell."""
    client = MagicMock()
    client.cell.model = model

    async def _rerank(query, documents, top_n=10):
        if exc is not None:
            raise exc
        # A live provider scores every document; the BACKEND truncates to top_n.
        return list(results or [])

    client.rerank = MagicMock(side_effect=_rerank)
    return client


@pytest.fixture(autouse=True)
def _reset_reranker_backend():
    """Reset module-level _backend before each test."""
    original = reranker_mod._backend
    reranker_mod._backend = None
    yield
    reranker_mod._backend = original


class TestCloudReranker:
    def test_rerank_success(self):
        """Cloud reranker returns sorted (index, score) tuples."""
        client = _cell_client(
            results=[
                {"index": 0, "relevance_score": 0.3},
                {"index": 1, "relevance_score": 0.9},
                {"index": 2, "relevance_score": 0.6},
            ]
        )
        reranker = CloudReranker(client)

        results = reranker.rerank("test query", ["doc0", "doc1", "doc2"], top_n=2)

        assert results == [(1, 0.9), (2, 0.6)]

    def test_rerank_empty_docs(self):
        """Empty documents list returns empty results without calling the API."""
        client = _cell_client()
        reranker = CloudReranker(client)

        assert reranker.rerank("query", []) == []
        client.rerank.assert_not_called()

    def test_rerank_failure_returns_empty(self):
        """Reranker returns empty list on failure (never raises)."""
        client = _cell_client(exc=RuntimeError("API error"))
        reranker = CloudReranker(client)

        assert reranker.rerank("query", ["doc"]) == []

    def test_check_available_success(self):
        """check_available returns True when API responds."""
        client = _cell_client(results=[{"index": 0, "relevance_score": 0.5}])
        reranker = CloudReranker(client)
        assert reranker.check_available() is True

    def test_check_available_failure(self):
        """check_available returns False on API failure."""
        client = _cell_client(exc=RuntimeError("connection error"))
        reranker = CloudReranker(client)
        assert reranker.check_available() is False

    def test_check_available_auth_error(self):
        """check_available logs warning for auth errors."""
        client = _cell_client(exc=RuntimeError("401 unauthorized"))
        reranker = CloudReranker(client)
        assert reranker.check_available() is False

    def test_model_identity_from_cell(self):
        """backend/model identity comes from the provider cell."""
        client = _cell_client(model="cohere/rerank-v4.0-pro")
        reranker = CloudReranker(client)
        assert reranker.model == "cohere/rerank-v4.0-pro"
        assert describe_reranker(reranker) == ("cloud", "cohere/rerank-v4.0-pro")

    def test_describe_reranker_none(self):
        assert describe_reranker(None) == (None, None)

    def test_rerank_with_identity(self):
        """Module helper returns results plus call-local identity."""
        client = _cell_client(
            model="rerank-x",
            results=[{"index": 1, "relevance_score": 0.7}],
        )
        outcome = rerank_with_identity(CloudReranker(client), "q", ["d0", "d1"])
        assert outcome.results == [(1, 0.7)]
        assert outcome.backend_name == "cloud"
        assert outcome.model_name == "rerank-x"


class TestQwen3Reranker:
    def test_rerank_success(self):
        """Local reranker returns sorted (index, score) tuples."""
        reranker = Qwen3Reranker()

        mock_model = MagicMock()
        mock_model.rerank.return_value = [0.3, 0.9, 0.6]

        with patch.object(reranker, "_get_model", return_value=mock_model):
            results = reranker.rerank("query", ["doc0", "doc1", "doc2"], top_n=2)

        assert results == [(1, 0.9), (2, 0.6)]

    def test_rerank_empty_docs(self):
        """Empty documents list returns empty results."""
        reranker = Qwen3Reranker()
        assert reranker.rerank("query", []) == []

    def test_rerank_failure_returns_empty(self):
        """Local reranker returns empty list on failure."""
        reranker = Qwen3Reranker()

        mock_model = MagicMock()
        mock_model.rerank.side_effect = RuntimeError("ONNX error")

        with patch.object(reranker, "_get_model", return_value=mock_model):
            assert reranker.rerank("query", ["doc"]) == []

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
            reranker, "_get_model", side_effect=ImportError("no fastretrieval")
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
    def test_init_cloud_uses_cell_client(self):
        """init_reranker('cloud') builds a CloudReranker around the cell client."""
        client = _cell_client()
        with patch("mnemo_mcp.reranker._cell_client", return_value=client):
            backend = init_reranker("cloud")
        assert isinstance(backend, CloudReranker)
        assert get_reranker() is backend

    def test_init_cloud_with_injected_client(self):
        """init_reranker accepts the provider client itself as 'model'."""
        client = _cell_client()
        backend = init_reranker("cloud", client)
        assert isinstance(backend, CloudReranker)
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
        """init_reranker accepts api_base/api_key for call-site compatibility."""
        client = _cell_client()
        with patch("mnemo_mcp.reranker._cell_client", return_value=client):
            backend = init_reranker(
                "cloud",
                api_base="http://proxy:4000",
                api_key="sk-test",
            )
        assert isinstance(backend, CloudReranker)

    def test_init_local_with_custom_model(self):
        """init_reranker passes custom model to Qwen3Reranker."""
        backend = init_reranker("local", "custom/model")
        assert isinstance(backend, Qwen3Reranker)
        assert backend._model_name == "custom/model"
