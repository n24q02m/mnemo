"""Dimension-recovery behaviour of CloudEmbeddingBackend._embed_batch_inner.

De-host rework: the removed ``_call_provider`` indirection is gone -- the
backend calls the injected hull client's ``embeddings`` directly. The
unsupported-dimensions capability fallback deliberately runs BEFORE the
retryability check (client layers may re-wrap a permanent 4xx as a transport
error), so a retryable message that also mentions the param stem loses one
attempt to the fallback and then exhausts the standard retry budget.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.embedder import MAX_RETRIES, CloudEmbeddingBackend


def _cell_client(model="test-model"):
    """Stub hull OpenAI-spec client for the embed cell."""
    client = MagicMock()
    client.cell.model = model
    client.embeddings = AsyncMock(return_value=[])
    return client


@pytest.mark.asyncio
class TestDimensionRecovery:
    async def test_dimension_unsupported_recovery(self):
        """
        Test that if the provider rejects the 'dimensions' parameter,
        the backend retries without it and truncates locally.
        """
        client = _cell_client()
        client.embeddings = AsyncMock(
            side_effect=[
                Exception("Model does not support dimensions parameter"),
                [[0.1] * 1024],  # Returns 1024 dims
            ]
        )
        backend = CloudEmbeddingBackend(client)

        # We request 512 dimensions
        result = await backend._embed_batch_inner(["hello"], dimensions=512)

        # Verify results are truncated to 512
        assert len(result[0]) == 512
        assert result[0] == [0.1] * 512

        # Verify calls to the cell client
        assert client.embeddings.call_count == 2

        # First call should have had dimensions=512
        # Second call should have had dimensions=None
        assert client.embeddings.call_args_list[0].args[0] == ["hello"]
        assert client.embeddings.call_args_list[0].kwargs["dimensions"] == 512
        assert client.embeddings.call_args_list[1].args[0] == ["hello"]
        assert client.embeddings.call_args_list[1].kwargs["dimensions"] is None

    async def test_no_recovery_on_other_error(self):
        """
        Test that other non-retryable errors do not trigger recovery.
        """
        client = _cell_client()
        client.embeddings = AsyncMock(side_effect=Exception("Some other error"))
        backend = CloudEmbeddingBackend(client)

        with pytest.raises(Exception, match="Some other error"):
            await backend._embed_batch_inner(["hello"], dimensions=512)

        # Should only be called once if it's not retryable and not unsupported param
        assert client.embeddings.call_count == 1

    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_retryable_error_still_exhausts_retries(self, mock_sleep):
        """
        Test that retryable errors (like rate limits) still exhaust the standard
        retry budget, even when the message mentions the param stem: the
        capability fallback consumes one attempt (dropping the param), then the
        remaining attempts follow the normal retryable path.
        """
        # 429 is retryable; the wording also trips the cap-marker heuristic.
        client = _cell_client()
        client.embeddings = AsyncMock(
            side_effect=Exception("429 rate limit exceeded (dimension quota)")
        )
        backend = CloudEmbeddingBackend(client)

        with pytest.raises(Exception, match="429 rate limit"):
            await backend._embed_batch_inner(["hello"], dimensions=512)

        # Fallback attempt (dims=512 -> dims=None) plus retries == MAX_RETRIES
        assert client.embeddings.call_count == MAX_RETRIES
        assert client.embeddings.call_args_list[0].kwargs["dimensions"] == 512
        assert client.embeddings.call_args_list[1].kwargs["dimensions"] is None
        mock_sleep.assert_called_once()
