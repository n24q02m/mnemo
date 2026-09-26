"""Tests for reranker.py -- cloud check_available branches + local lazy load.

De-host rework: provider/env detection, provider-prefix stripping and the
provider-prefixed cloud passthrough pinned removed internals and were deleted
-- the ``[models.rerank]`` cell now owns base_url, api_key and model, and the
cell-based cloud path is covered in tests/test_reranker.py.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

from mnemo_mcp.reranker import CloudReranker, Qwen3Reranker


def _cell_client(model="cell-model", exc=None):
    """Stub hull OpenAI-spec client for the rerank cell."""
    client = MagicMock()
    client.cell.model = model
    if exc is not None:
        client.rerank = AsyncMock(side_effect=exc)
    else:
        client.rerank = AsyncMock(return_value=[{"index": 0, "relevance_score": 0.5}])
    return client


# ---------------------------------------------------------------------------
# CloudReranker -- check_available (auth vs non-auth branches)
# ---------------------------------------------------------------------------


class TestCheckAvailableCloudReranker:
    """check_available() distinguishes API key errors from other failures."""

    def test_check_available_true(self):
        """check_available returns True on success."""
        reranker = CloudReranker(_cell_client())
        assert reranker.check_available() is True

    def test_check_api_key_invalid_logs_warning(self):
        """check_available returns False and logs warning on 401."""
        reranker = CloudReranker(_cell_client(exc=Exception("401 Unauthorized")))
        with patch("mnemo_mcp.reranker.logger") as mock_logger:
            assert reranker.check_available() is False
            mock_logger.warning.assert_called()
            assert "API key invalid" in mock_logger.warning.call_args[0][0]

    def test_check_non_auth_error_logs_debug(self):
        """check_available returns False and logs debug on non-auth errors."""
        reranker = CloudReranker(_cell_client(exc=Exception("Model not found")))
        with patch("mnemo_mcp.reranker.logger") as mock_logger:
            assert reranker.check_available() is False
            mock_logger.debug.assert_called()
            assert "not available" in mock_logger.debug.call_args[0][0]


# ---------------------------------------------------------------------------
# Qwen3Reranker lazy load
# ---------------------------------------------------------------------------


class TestQwen3RerankerLazyLoad:
    def test_lazy_load(self):
        """Model is loaded lazily on first _get_model() call."""
        mock_fastretrieval = MagicMock()
        mock_model = MagicMock()
        mock_fastretrieval.TextCrossEncoder.return_value = mock_model

        with patch.dict(sys.modules, {"fastretrieval": mock_fastretrieval}):
            reranker = Qwen3Reranker("test/model")
            assert reranker._model is None

            result = reranker._get_model()
            assert result == mock_model
            mock_fastretrieval.TextCrossEncoder.assert_called_once_with(
                model_name="test/model"
            )

    def test_caches_model(self):
        """Model is only loaded once (cached)."""
        mock_fastretrieval = MagicMock()
        mock_model = MagicMock()
        mock_fastretrieval.TextCrossEncoder.return_value = mock_model

        with patch.dict(sys.modules, {"fastretrieval": mock_fastretrieval}):
            reranker = Qwen3Reranker()
            reranker._get_model()
            reranker._get_model()

            mock_fastretrieval.TextCrossEncoder.assert_called_once()

    def test_check_available_empty_scores(self):
        """check_available returns False when rerank returns empty."""
        reranker = Qwen3Reranker()
        mock_model = MagicMock()
        mock_model.rerank.return_value = []

        with patch.object(reranker, "_get_model", return_value=mock_model):
            assert reranker.check_available() is False
