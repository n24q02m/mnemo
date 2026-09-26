"""Tests for embedder.py -- parameter classification and batch-internal edges.

De-host rework: provider/env detection, provider-prefix stripping, the legacy
model-mapping table, response-shape parsing helpers and the per-provider call
routing pinned removed internals and were deleted -- the ``[models.embed]``
cell now owns base_url, api_key and model.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.embedder import CloudEmbeddingBackend, _is_unsupported_param


def _cell_client(model="cell-model"):
    """Stub hull OpenAI-spec client for the embed cell."""
    client = MagicMock()
    client.cell.model = model
    client.embeddings = AsyncMock(return_value=[])
    return client


# ---------------------------------------------------------------------------
# _is_unsupported_param
# ---------------------------------------------------------------------------


class TestIsUnsupportedParam:
    def test_unsupported_dimensions(self):
        exc = Exception("does not support parameters: {'dimensions': 768}")
        assert _is_unsupported_param(exc, "dimensions") is True

    def test_output_dimension_not_supported(self):
        exc = Exception("output_dimension is not supported for this model")
        assert _is_unsupported_param(exc, "dimensions") is True

    def test_not_a_valid_param(self):
        exc = Exception("dimension is not a valid parameter")
        assert _is_unsupported_param(exc, "dimensions") is True

    def test_unrelated_error(self):
        exc = Exception("Invalid API key")
        assert _is_unsupported_param(exc, "dimensions") is False

    def test_dimensions_cap_rejection(self):
        # Live F2 failure (2026-09-16): bad-request from Jina v5 small when
        # the CF deployment requests the 1536 storage width.
        exc = Exception(
            "BadRequestError: jina-embeddings-v5-text-small dimensions ≤1024"
        )
        assert _is_unsupported_param(exc, "dimensions") is True

    def test_dimensions_at_most_rejection(self):
        exc = Exception("dimensions must be at most 1024 for this model")
        assert _is_unsupported_param(exc, "dimensions") is True

    def test_dimensions_less_than_or_equal_rejection(self):
        # Jina v5 small's actual wording, observed live 2026-09-17.
        exc = Exception(
            "BadRequestError: Validation error: "
            "'body -> jina-embeddings-v5-text-small -> dimensions' Input should "
            "be less than or equal to 1024"
        )
        assert _is_unsupported_param(exc, "dimensions") is True

    def test_cap_phrase_without_param_stem_is_not_matched(self):
        exc = Exception("rate limit exceeded, retry later")
        assert _is_unsupported_param(exc, "dimensions") is False


# ---------------------------------------------------------------------------
# CloudEmbeddingBackend -- _embed_batch_inner no retries RuntimeError
# ---------------------------------------------------------------------------


class TestEmbedBatchInnerEdge:
    async def test_no_retries_runtime_error(self):
        """Raises RuntimeError when no retries were attempted (last_exc is None).

        This path is technically unreachable but is a defensive safeguard.
        We test it by mocking MAX_RETRIES to 0.
        """
        backend = CloudEmbeddingBackend(_cell_client(model="embed-multilingual-v3.0"))

        with patch("mnemo_mcp.embedder.MAX_RETRIES", 0):
            with pytest.raises(RuntimeError, match="no retries attempted"):
                await backend._embed_batch_inner(["test"])
