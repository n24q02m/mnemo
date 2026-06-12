"""Custom exceptions for Mnemo MCP Server."""

from __future__ import annotations


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
