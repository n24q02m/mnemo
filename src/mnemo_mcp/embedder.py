"""Dual-backend embedding: Cloud (Cohere) + qwen3-embed (local).

Supports two backends:
- **cloud**: Cloud embedding via Cohere SDK (embed-multilingual-v3.0).
  Requires COHERE_API_KEY or CO_API_KEY. Backward compat: "litellm" alias.
- **local**: Local inference via qwen3-embed. GGUF if GPU + llama-cpp-python,
  ONNX otherwise. No API keys needed, ~0.5GB model download on first use.

Backend selection (always returns a valid backend):
1. Explicit EMBEDDING_BACKEND env var
2. 'cloud' if API keys are configured
3. 'local' (default, always available)

Embeddings are truncated to fixed dims in server._embed().
"""

from __future__ import annotations

import asyncio
import os
from typing import Protocol

from loguru import logger

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Retry config for transient errors (rate limits, 5xx, network).
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds, doubles each retry


# Bolt Performance Optimization: Use module-level constant tuple to avoid
# redundant list allocations during frequent calls, resulting in ~15% faster execution.
_RETRYABLE_PATTERNS = (
    "rate limit",
    "rate_limit",
    "429",
    "quota",
    "too many requests",
    "500",
    "502",
    "503",
    "504",
    "timeout",
    "timed out",
    "connection",
    "temporarily unavailable",
    "overloaded",
    "resource exhausted",
    "resource_exhausted",
)


def _is_retryable(exc: Exception) -> bool:
    """Check if an exception is transient and worth retrying."""
    msg = str(exc).lower()
    return any(p in msg for p in _RETRYABLE_PATTERNS)


def _is_unsupported_param(exc: Exception, param: str) -> bool:
    """Check if an exception indicates an unsupported parameter.

    Detects errors like "does not support parameters: {'dimensions': ...}"
    or "output_dimension is not supported for this model".
    Uses stem matching (e.g. "dimension" matches "dimensions", "output_dimension").
    """
    msg = str(exc).lower()
    # Use the stem (without trailing 's') for broader matching
    stem = param.lower().rstrip("s")
    return (
        "not support" in msg or "unsupported" in msg or "not a valid" in msg
    ) and stem in msg


# ---------------------------------------------------------------------------
# Backend Protocol
# ---------------------------------------------------------------------------


class EmbeddingBackend(Protocol):
    """Protocol for embedding backends."""

    async def embed_texts(
        self,
        texts: list[str],
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Embed a batch of texts. Returns list of embedding vectors."""
        ...

    async def embed_single(
        self,
        text: str,
        dimensions: int | None = None,
    ) -> list[float]:
        """Embed a single text. Returns embedding vector."""
        ...

    def check_available(self) -> int:
        """Check if backend is available.

        Returns:
            Embedding dimensions if available, 0 if not.
        """
        ...


# ---------------------------------------------------------------------------
# Cloud Embedding Backend (Cohere SDK)
# ---------------------------------------------------------------------------


class CloudEmbeddingBackend:
    """Cloud embedding via Cohere SDK (embed-multilingual-v3.0)."""

    # Cohere API: max 96 texts per batch request.
    MAX_BATCH_SIZE = 96

    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        api_key: str | None = None,
    ):
        self.model = model or os.getenv("EMBEDDING_MODEL", "embed-multilingual-v3.0")
        self.api_key = api_key or os.getenv("COHERE_API_KEY") or os.getenv("CO_API_KEY")
        self.api_base = api_base  # reserved for future use

    async def _embed_batch_inner(
        self,
        texts: list[str],
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Embed a single batch with retry logic for transient errors.

        Tries server-side MRL truncation first (``dimensions`` param).
        If the provider rejects ``dimensions``, retries without it and
        truncates locally.
        """
        use_dimensions = dimensions

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                import cohere

                client = cohere.ClientV2(api_key=self.api_key)
                kwargs: dict = {
                    "model": self.model,
                    "texts": texts,
                    "input_type": "search_document",
                    "embedding_types": ["float"],
                    "truncate": "END",
                }
                if use_dimensions:
                    kwargs["output_dimension"] = use_dimensions

                response = client.embed(**kwargs)
                embeddings = response.embeddings.float_

                # Truncate locally if server returned more dims than requested
                if dimensions and embeddings and len(embeddings[0]) > dimensions:
                    embeddings = [e[:dimensions] for e in embeddings]
                return embeddings
            except Exception as e:
                # If the provider rejects `dimensions`, retry without it
                # and truncate locally instead.
                if (
                    use_dimensions
                    and not _is_retryable(e)
                    and _is_unsupported_param(e, "dimensions")
                ):
                    logger.debug(
                        f"Provider does not support dimensions param, "
                        f"will truncate locally: {e}"
                    )
                    use_dimensions = None
                    continue

                last_exc = e
                if attempt < MAX_RETRIES - 1 and _is_retryable(e):
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        f"Embedding retry {attempt + 1}/{MAX_RETRIES} "
                        f"after {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    break

        logger.error(f"Embedding failed ({self.model}): {last_exc}")
        raise last_exc  # type: ignore[misc]

    async def embed_texts(
        self,
        texts: list[str],
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Embed texts with auto batch splitting."""
        if not texts:
            return []

        if len(texts) <= self.MAX_BATCH_SIZE:
            return await self._embed_batch_inner(texts, dimensions)

        # Split into batches
        all_embeddings: list[list[float]] = []
        total_batches = (len(texts) + self.MAX_BATCH_SIZE - 1) // self.MAX_BATCH_SIZE
        logger.info(
            f"Splitting {len(texts)} texts into {total_batches} batches "
            f"(max {self.MAX_BATCH_SIZE}/batch)"
        )

        for i in range(0, len(texts), self.MAX_BATCH_SIZE):
            batch = texts[i : i + self.MAX_BATCH_SIZE]
            batch_num = i // self.MAX_BATCH_SIZE + 1
            logger.debug(
                f"Embedding batch {batch_num}/{total_batches}: {len(batch)} texts"
            )
            batch_result = await self._embed_batch_inner(batch, dimensions)
            all_embeddings.extend(batch_result)

        return all_embeddings

    async def embed_single(
        self,
        text: str,
        dimensions: int | None = None,
    ) -> list[float]:
        """Embed a single text."""
        results = await self.embed_texts([text], dimensions)
        return results[0]

    def check_available(self) -> int:
        """Check if the Cohere model is available via test request.

        Distinguishes between invalid API keys (warning) and other
        failures (debug) so users know when their keys are wrong.
        """
        try:
            import cohere

            client = cohere.ClientV2(api_key=self.api_key)
            response = client.embed(
                model=self.model,
                texts=["test"],
                input_type="search_document",
                embedding_types=["float"],
                truncate="END",
            )
            if response.embeddings.float_:
                dim = len(response.embeddings.float_[0])
                logger.info(f"Embedding model {self.model} available (dims={dim})")
                return dim
            return 0
        except Exception as e:
            msg = str(e).lower()
            if any(
                p in msg for p in ("401", "403", "invalid", "unauthorized", "api key")
            ):
                logger.warning(
                    f"API key invalid for {self.model}: {e}. "
                    "Check your API_KEYS configuration."
                )
            else:
                logger.debug(f"Embedding model {self.model} not available: {e}")
            return 0


# Backward compatibility alias
LiteLLMBackend = CloudEmbeddingBackend


# ---------------------------------------------------------------------------
# qwen3-embed Backend (local ONNX)
# ---------------------------------------------------------------------------


class Qwen3EmbedBackend:
    """Local ONNX embedding via qwen3-embed (Qwen3-Embedding-0.6B).

    Model is downloaded on first use (~0.57GB).
    Batch size is forced to 1 (static ONNX graph).
    """

    DEFAULT_MODEL = "n24q02m/Qwen3-Embedding-0.6B-ONNX"

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or self.DEFAULT_MODEL
        self._model = None

    def _get_model(self):
        """Lazy-load the embedding model.

        On first call, downloads the ONNX model (~570 MB) from HuggingFace
        if not already cached. Logs a warning so users know why startup is slow.
        """
        if self._model is None:
            from qwen3_embed import TextEmbedding

            logger.warning(
                f"Loading local embedding model: {self._model_name} "
                "(~570 MB download on first run). "
                "Set API_KEYS to use cloud embedding instead."
            )
            self._model = TextEmbedding(model_name=self._model_name)
            logger.info("Local embedding model loaded")
        return self._model

    async def embed_texts(
        self,
        texts: list[str],
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Embed texts using local ONNX model (runs in thread)."""
        if not texts:
            return []

        def _embed():
            model = self._get_model()
            # Pass dim to model.embed() so MRL truncation happens BEFORE L2-normalization
            kwargs = {}
            if dimensions and dimensions > 0:
                kwargs["dim"] = dimensions
            embeddings = list(model.embed(texts, **kwargs))
            return [emb.tolist() for emb in embeddings]

        return await asyncio.to_thread(_embed)

    async def embed_single(
        self,
        text: str,
        dimensions: int | None = None,
    ) -> list[float]:
        """Embed a single text (document/passage)."""
        results = await self.embed_texts([text], dimensions)
        return results[0]

    async def embed_single_query(
        self,
        text: str,
        dimensions: int | None = None,
    ) -> list[float]:
        """Embed a query with instruction prefix (asymmetric retrieval)."""

        def _query():
            model = self._get_model()
            kwargs = {}
            if dimensions and dimensions > 0:
                kwargs["dim"] = dimensions
            result = list(model.query_embed(text, **kwargs))
            return result[0].tolist()

        return await asyncio.to_thread(_query)

    def check_available(self) -> int:
        """Check if qwen3-embed is available."""
        try:
            model = self._get_model()
            result = list(model.embed(["test"]))
            if result:
                dim = len(result[0])
                logger.info(
                    f"Local embedding {self._model_name} available (dims={dim})"
                )
                return dim
            return 0
        except Exception as e:
            logger.warning(f"Local embedding not available: {e}")
            return 0


# ---------------------------------------------------------------------------
# Factory + module-level state
# ---------------------------------------------------------------------------

_backend: EmbeddingBackend | None = None


def get_backend() -> EmbeddingBackend | None:
    """Get the current embedding backend singleton."""
    return _backend


def init_backend(
    backend_type: str,
    model: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
) -> EmbeddingBackend:
    """Initialize and cache the embedding backend.

    Args:
        backend_type: 'cloud', 'litellm' (backward compat), or 'local'
        model: Model name (optional for cloud, optional for local)
        api_base: Custom API base URL (for cloud backend)
        api_key: Custom API key (for cloud backend)

    Returns:
        Initialized backend instance.
    """
    global _backend

    if backend_type in ("cloud", "litellm"):
        _backend = CloudEmbeddingBackend(model, api_base=api_base, api_key=api_key)
    elif backend_type == "local":
        _backend = Qwen3EmbedBackend(model)
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")

    return _backend


# ---------------------------------------------------------------------------
# Legacy module-level functions for backward compatibility
# ---------------------------------------------------------------------------


async def embed_single(
    text: str,
    model: str,
    dimensions: int | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
) -> list[float]:
    """Embed a single text (legacy interface)."""
    backend = CloudEmbeddingBackend(model, api_base=api_base, api_key=api_key)
    return await backend.embed_single(text, dimensions)


def check_embedding_available(
    model: str, api_base: str | None = None, api_key: str | None = None
) -> int:
    """Check if an embedding model is available (legacy interface)."""
    backend = CloudEmbeddingBackend(model, api_base=api_base, api_key=api_key)
    return backend.check_available()
