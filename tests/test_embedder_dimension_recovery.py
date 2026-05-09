from unittest.mock import AsyncMock, call, patch

import pytest

from mnemo_mcp.embedder import MAX_RETRIES, CloudEmbeddingBackend


@pytest.mark.asyncio
class TestDimensionRecovery:
    @patch("mnemo_mcp.embedder.CloudEmbeddingBackend._call_provider")
    async def test_dimension_unsupported_recovery(self, mock_call_provider):
        """
        Test that if the provider rejects the 'dimensions' parameter,
        the backend retries without it and truncates locally.
        """
        # First call fails with unsupported dimensions error
        # Second call succeeds but returns more dimensions than requested
        mock_call_provider.side_effect = [
            Exception("Model does not support dimensions parameter"),
            [[0.1] * 1024],  # Returns 1024 dims
        ]

        backend = CloudEmbeddingBackend(model="test-model")

        # We request 512 dimensions
        result = await backend._embed_batch_inner(["hello"], dimensions=512)

        # Verify results are truncated to 512
        assert len(result[0]) == 512
        assert result[0] == [0.1] * 512

        # Verify calls to _call_provider
        assert mock_call_provider.call_count == 2

        # First call should have had dimensions=512
        # Second call should have had dimensions=None
        mock_call_provider.assert_has_calls(
            [call(["hello"], 512), call(["hello"], None)]
        )

    @patch("mnemo_mcp.embedder.CloudEmbeddingBackend._call_provider")
    async def test_no_recovery_on_other_error(self, mock_call_provider):
        """
        Test that other non-retryable errors do not trigger recovery.
        """
        mock_call_provider.side_effect = Exception("Some other error")

        backend = CloudEmbeddingBackend(model="test-model")

        with pytest.raises(Exception, match="Some other error"):
            await backend._embed_batch_inner(["hello"], dimensions=512)

        # Should only be called once if it's not retryable and not unsupported param
        assert mock_call_provider.call_count == 1

    @patch("mnemo_mcp.embedder.CloudEmbeddingBackend._call_provider")
    @patch("mnemo_mcp.embedder.asyncio.sleep", new_callable=AsyncMock)
    async def test_retryable_error_takes_precedence(
        self, mock_sleep, mock_call_provider
    ):
        """
        Test that retryable errors (like rate limits) still trigger standard retry logic,
        even if they might contain the word 'dimension'.
        """
        # 429 is retryable
        mock_call_provider.side_effect = Exception(
            "429 rate limit exceeded (dimension quota)"
        )

        backend = CloudEmbeddingBackend(model="test-model")

        with pytest.raises(Exception, match="429 rate limit"):
            await backend._embed_batch_inner(["hello"], dimensions=512)

        # Should retry MAX_RETRIES times
        assert mock_call_provider.call_count == MAX_RETRIES
