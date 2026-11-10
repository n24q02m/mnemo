"""Custom exceptions for Mnemo MCP Server."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hull_core.credentials import PoolExhaustedError


class EmbeddingModelMismatch(RuntimeError):
    """Raised when the active embedding identity differs from the stored one.

    The vector store records the ``(embedding_model, embedding_dims)`` that
    produced its stored vectors. Opening the store with a different model or
    dimension would silently mix incompatible vectors and corrupt similarity
    search, so the open is aborted (touching NO data) unless the operator
    opts into a destructive rebuild via ``REINDEX_ON_MODEL_CHANGE=true``.
    """

    def __init__(
        self,
        stored_model: str,
        stored_dims: int,
        requested_model: str,
        requested_dims: int,
    ) -> None:
        self.stored_model = stored_model
        self.stored_dims = stored_dims
        self.requested_model = requested_model
        self.requested_dims = requested_dims
        super().__init__(
            "Embedding model identity changed: vector store was built with "
            f"model={stored_model!r} dims={stored_dims}, but the server is now "
            f"configured for model={requested_model!r} dims={requested_dims}. "
            "Mixing vectors from different models corrupts similarity search. "
            "To rebuild the vector store with the new model, set "
            "REINDEX_ON_MODEL_CHANGE=true (this DROPS the stored vectors and "
            "re-embeds on the next pass). To keep the existing vectors, restore "
            "the previous embedding model configuration."
        )


class ProviderCredentialsExhausted(RuntimeError):
    """No usable credential for a task cell's provider pool.

    Raised instead of hull's ``PoolExhaustedError`` so call sites depend on
    mnemo's error surface. The message is hull's already-redacted pool
    diagnosis -- counts, the earliest ``retry_after`` in seconds, and a last
    error with every stored key replaced by ``[redacted]`` -- so it is safe to
    log.

    Attributes:
        provider: provider identity whose pool is exhausted.
        account: named account scope, or ``None`` for the default pool.
        total / disabled / cooling_down / leased: pool counts at failure time.
        retry_after: seconds until the earliest cooldown expires, or ``None``.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        account: str | None = None,
        total: int = 0,
        disabled: int = 0,
        cooling_down: int = 0,
        leased: int = 0,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.account = account
        self.total = total
        self.disabled = disabled
        self.cooling_down = cooling_down
        self.leased = leased
        self.retry_after = retry_after

    @classmethod
    def from_pool_error(cls, error: PoolExhaustedError) -> ProviderCredentialsExhausted:
        """Rebuild hull's exhaustion error without importing hull at module load."""
        return cls(
            str(error),
            provider=error.provider,
            account=error.account_id,
            total=error.total,
            disabled=error.disabled,
            cooling_down=error.cooling_down,
            leased=error.leased,
            retry_after=error.retry_after,
        )
