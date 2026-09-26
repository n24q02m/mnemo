"""Regression tests for the silent semantic-degrade bug.

When a cloud provider rejects the requested output ``dimensions`` (e.g.
``cohere/embed-v4.0`` at mnemo's default 768; cohere-v4 supports only
{256, 512, 1024, 1536}), client layers re-wrap the provider's HTTP 422 as a
connection error whose class name contains "connection" and whose
``status_code`` is a synthetic 500. The old ``_is_retryable`` matched the
"connection" substring, so the dimensions-fallback was bypassed and the call
was retried 3x with the SAME rejected dims, then gave up -> ``_embed`` returned
None -> semantic search silently degraded to FTS5 with no error surfaced.

These tests reproduce that exact shape with plain stand-in exception classes
(the legacy provider SDK is gone with the de-host; ``_is_retryable`` now
classifies purely on message patterns) plus a dims-aware client stub, and lock
in the fix: unsupported-dimensions recover via retry-without-dims + local
truncate, and permanent client errors are never retried.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from mnemo_mcp.embedder import MAX_RETRIES, CloudEmbeddingBackend, _is_retryable

# The exact provider body cohere returns for an unsupported output_dimension,
# as a client layer surfaces it after wrapping the 422 in a connection error.
_COHERE_422_BODY = (
    'CohereException - {"message": "768 is not a valid output_dimension, '
    'use one of 256, 512, 1024, 1536"}'
)


class _ClientConnectionError(Exception):
    """Stand-in for a client layer re-wrapping a permanent 4xx.

    Mirrors the tricky shape the old matcher missed: the exception text
    contains "connection" (a retryable pattern) and status_code is a hardcoded
    500, so classification must key on the message semantics, not the class
    name or status code.
    """

    status_code = 500

    def __str__(self) -> str:
        return f"{type(self).__name__}: Connection error. {self.args[0]}"


class _ClientRateLimitError(Exception):
    """Stand-in for a client rate-limit error (message carries 'rate limit')."""

    status_code = 429


def _wrapped_422() -> _ClientConnectionError:
    """A connection-shaped error wrapping cohere's 422 dims rejection."""
    return _ClientConnectionError(_COHERE_422_BODY)


def _cell_client(model="cohere/embed-v4.0"):
    """Stub hull OpenAI-spec client for the embed cell."""
    client = MagicMock()
    client.cell.model = model
    client.embeddings = AsyncMock(return_value=[])
    return client


class TestIsRetryableClassification:
    """`_is_retryable` must classify on error semantics, not class name."""

    def test_wrapped_422_unsupported_dimension_is_not_retryable(self):
        exc = _wrapped_422()
        # Guard: this really is the tricky shape (text mentions "connection",
        # synthetic 500) that fooled the old substring matcher.
        assert "connection" in str(exc).lower()
        assert getattr(exc, "status_code", None) == 500

        assert _is_retryable(exc) is False

    def test_genuine_connection_error_is_retryable(self):
        exc = _ClientConnectionError("Connection error.")
        assert _is_retryable(exc) is True

    def test_rate_limit_is_retryable(self):
        exc = _ClientRateLimitError("rate limit exceeded")
        assert _is_retryable(exc) is True

    def test_invalid_api_key_is_not_retryable(self):
        exc = _ClientConnectionError("AuthenticationError - invalid api key")
        assert _is_retryable(exc) is False


@pytest.mark.asyncio
class TestWrappedDimsRejectionRecovery:
    """The connection-wrapped 422 must trigger the retry-without-dims fallback."""

    async def test_wrapped_422_triggers_dims_fallback_and_truncates(self):
        # Dims-aware fake: the provider REJECTS every dims-bearing call (as
        # cohere-v4 does at 768) and only succeeds when dims are dropped.
        # A non-dims-aware mock would let the buggy retry "recover" by luck and
        # hide the defect.
        native_dim = 1536

        async def fake_embeddings(texts, dimensions=None):
            if dimensions is not None:
                raise _wrapped_422()
            return [[0.1] * native_dim for _ in texts]

        client = _cell_client()
        client.embeddings = AsyncMock(side_effect=fake_embeddings)
        backend = CloudEmbeddingBackend(client)

        result = await backend._embed_batch_inner(["hello"], dimensions=768)

        # Recovered: valid vector truncated locally to the requested 768.
        assert len(result[0]) == 768
        assert result[0] == [0.1] * 768
        # Exactly two provider calls: dims=768 (rejected) then dims=None (ok).
        assert client.embeddings.call_count == 2
        assert client.embeddings.call_args_list[0].args[0] == ["hello"]
        assert client.embeddings.call_args_list[0].kwargs["dimensions"] == 768
        assert client.embeddings.call_args_list[1].kwargs["dimensions"] is None

    async def test_wrapped_422_is_not_retried_with_same_dims(self):
        # If the fallback did NOT fire, the buggy code would retry MAX_RETRIES
        # times with the same rejected dims. Assert it does NOT.
        async def always_reject(texts, dimensions=None):
            raise _wrapped_422()

        client = _cell_client()
        client.embeddings = AsyncMock(side_effect=always_reject)
        backend = CloudEmbeddingBackend(client)

        with pytest.raises(_ClientConnectionError):
            await backend._embed_batch_inner(["hello"], dimensions=768)

        # 1 dims=768 attempt (rejected) + 1 dims=None fallback attempt (also
        # rejected) = 2. NOT MAX_RETRIES retries of the same bad dims.
        assert client.embeddings.call_count == 2
        assert client.embeddings.call_count < MAX_RETRIES + 1
        assert client.embeddings.call_args_list[0].kwargs["dimensions"] == 768
        assert client.embeddings.call_args_list[1].kwargs["dimensions"] is None
