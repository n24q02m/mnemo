"""Dual-backend embedding: Cloud (OpenAI-spec via hull-core) + fastretrieval (local).

Supports two backends:
- **cloud**: Cloud embedding via the ``[models.embed]`` provider cell
  (``base_url + api_key + model``, plain OpenAI-spec HTTP through hull-core).
  Requires the host to configure the cell (config.toml or
  ``HULL_EMBED_API_KEY``).
- **local**: Local inference via fastretrieval. GGUF if GPU + llama-cpp-python,
  ONNX otherwise. No API keys needed, ~0.5GB model download on first use.

Backend selection (always returns a valid backend):
1. cloud when the ``[models.embed]`` cell has a key
2. 'local' otherwise (default, always available)

Embeddings are truncated to fixed dims in server._embed().
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Literal, Protocol

from loguru import logger

EmbeddingRole = Literal["document", "query"]

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Retry config for transient errors (rate limits, 5xx, network).
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds, doubles each retry

# Wall-clock bound on the availability probe (``check_available``).
# ``config(action="setup_complete")`` awaits that probe before it returns, so
# without a bound a slow or blackholed provider makes the user's tool call hang
# for as long as the provider takes. CI run 30755522961 lost its windows-latest
# job to exactly that: the probe stalled reading response headers for longer
# than the 30s pytest-timeout. hull-core's OpenAICompatClient therefore takes
# an explicit ``timeout`` (default 60s) instead of a provider SDK default.


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


# Patterns marking a PERMANENT client-side error (invalid request, unsupported
# capability, auth). Client layers frequently re-wrap these as connection errors --
# whose class name contains "connection" and whose status_code is a hardcoded
# 500 -- so classification MUST look at the message semantics, not the exception
# class or status code. Retrying a permanent error re-sends the same doomed
# request and (worse) would block capability fallbacks such as dropping an
# unsupported `dimensions` argument.
_PERMANENT_PATTERNS = (
    "not a valid",
    "not support",
    "unsupported",
    "invalid request",
    "invalid_request",
    "invalid api key",
    "output_dimension",
    "unauthorized",
    "forbidden",
    "authentication",
    "no such model",
    "model not found",
    "does not exist",
    "401",
    "403",
    "404",
    "422",
)


def _is_retryable(exc: Exception) -> bool:
    """Return True only for TRANSIENT errors worth retrying.

    Classifies on error semantics, NOT the exception class name or a synthetic
    status_code: client layers wrap a provider's permanent 4xx (e.g. a 422 "invalid
    output_dimension") as ``APIConnectionError`` whose repr contains "connection"
    and whose ``status_code`` is a hardcoded 500 -- matching either would wrongly
    retry a request that can never succeed and skip the dimensions fallback.
    """
    msg = str(exc).lower()
    if any(p in msg for p in _PERMANENT_PATTERNS):
        return False
    return any(p in msg for p in _RETRYABLE_PATTERNS)


def _is_unsupported_param(exc: Exception, param: str) -> bool:
    """Check if an exception indicates an unsupported parameter.

    Detects errors like "does not support parameters: {'dimensions': ...}"
    or "output_dimension is not supported for this model", plus provider
    cap rejections such as "dimensions ≤1024" / "dimensions must be at most
    1024" (Jina v5 small caps at 1024 while the CF deployment requests the
    1536 storage width — F2 layer 2, 2026-09-16).
    Uses stem matching (e.g. "dimension" matches "dimensions", "output_dimension").
    """
    msg = str(exc).lower()
    # Use the stem (without trailing 's') for broader matching
    stem = param.lower().rstrip("s")
    if stem not in msg:
        return False
    if "not support" in msg or "unsupported" in msg or "not a valid" in msg:
        return True
    # Cap-style rejections: "dimensions ≤1024", "must be at most 1024",
    # "maximum of", "cannot exceed", "<= 1024", "less than or equal to 1024"
    # (Jina v5 small's actual wording, observed live 2026-09-17).
    return any(
        marker in msg
        for marker in ("≤", "<=", "at most", "maximum", "exceed", "less than")
    )


# ---------------------------------------------------------------------------
# Backend Protocol
# ---------------------------------------------------------------------------


class EmbeddingBackend(Protocol):
    """Protocol for embedding backends."""

    async def embed_texts(
        self,
        texts: list[str],
        dimensions: int | None = None,
        *,
        role: EmbeddingRole = "document",
    ) -> list[list[float]]:
        """Embed a batch of texts. Returns list of embedding vectors."""
        ...

    async def embed_single(
        self,
        text: str,
        dimensions: int | None = None,
        *,
        role: EmbeddingRole = "document",
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
# Cloud Embedding Backend ([models.embed] provider cell)
# ---------------------------------------------------------------------------


class CloudEmbeddingBackend:
    """Cloud embedding via the ``[models.embed]`` provider cell.

    Wraps exactly one :class:`~hull_core.providers.openai_spec.
    OpenAICompatClient` built from the cell; the cell owns base_url, api_key,
    and model -- there is no provider prefix and no per-request credential
    resolution.
    """

    MAX_BATCH_SIZE = 96  # Common safe batch size across providers

    def __init__(self, client: Any) -> None:
        self._client = client

    @property
    def model(self) -> str:
        """The cell-owned embedding model id (for logs and diagnostics)."""
        return self._client.cell.model

    async def _embed_batch_inner(
        self,
        texts: list[str],
        dimensions: int | None = None,
        *,
        role: EmbeddingRole = "document",
    ) -> list[list[float]]:
        """Embed a single batch with retry logic for transient errors.

        Tries server-side MRL truncation first (``dimensions`` param).
        If the provider rejects ``dimensions``, retries without it and
        truncates locally. ``role`` is accepted for protocol compatibility;
        the OpenAI-spec ``/embeddings`` endpoint has no asymmetric query mode,
        so queries embed exactly like documents (only the local ONNX backend
        has a true query embedding).
        """
        use_dimensions = dimensions

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                embeddings = await self._client.embeddings(
                    texts, dimensions=use_dimensions
                )

                # Truncate locally if server returned more dims than requested
                if dimensions and embeddings and len(embeddings[0]) > dimensions:
                    embeddings = [e[:dimensions] for e in embeddings]
                return embeddings
            except Exception as e:
                # A dimensions rejection is PERMANENT -- retrying with the same
                # dims can never succeed. Recover (drop `dimensions`, truncate
                # locally) BEFORE the retryability check: providers may wrap the
                # 422 in a transport error, so retry classification must not
                # gate this capability fallback.
                if use_dimensions and _is_unsupported_param(e, "dimensions"):
                    logger.warning(
                        f"Provider {self.model} rejected dimensions="
                        f"{use_dimensions}; retrying without it and truncating "
                        f"locally: {e}"
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
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"Embedding failed ({self.model}): no retries attempted")

    async def embed_texts(
        self,
        texts: list[str],
        dimensions: int | None = None,
        *,
        role: EmbeddingRole = "document",
    ) -> list[list[float]]:
        """Embed texts with auto batch splitting."""
        if not texts:
            return []

        if len(texts) <= self.MAX_BATCH_SIZE:
            return await self._embed_batch_inner(texts, dimensions, role=role)

        # Split into batches
        total_batches = (len(texts) + self.MAX_BATCH_SIZE - 1) // self.MAX_BATCH_SIZE
        logger.info(
            f"Splitting {len(texts)} texts into {total_batches} batches "
            f"(max {self.MAX_BATCH_SIZE}/batch)"
        )

        # Bolt Performance Optimization:
        # Process batches concurrently using asyncio.gather with a Semaphore.
        # This optimizes throughput for large text arrays while safely preventing
        # rate-limit (HTTP 429) failures from the embedding provider.
        sem = asyncio.Semaphore(5)

        async def process_batch(
            batch_idx: int, batch_texts: list[str]
        ) -> tuple[int, list[list[float]]]:
            async with sem:
                logger.debug(
                    f"Embedding batch {batch_idx + 1}/{total_batches}: {len(batch_texts)} texts"
                )
                res = await self._embed_batch_inner(batch_texts, dimensions, role=role)
                return batch_idx, res

        tasks = []
        for i in range(0, len(texts), self.MAX_BATCH_SIZE):
            batch = texts[i : i + self.MAX_BATCH_SIZE]
            batch_idx = i // self.MAX_BATCH_SIZE
            tasks.append(process_batch(batch_idx, batch))

        results = await asyncio.gather(*tasks)
        # Ensure ordered flattening
        results.sort(key=lambda x: x[0])
        all_embeddings: list[list[float]] = []
        for _, batch_result in results:
            all_embeddings.extend(batch_result)

        return all_embeddings

    async def embed_single(
        self,
        text: str,
        dimensions: int | None = None,
        *,
        role: EmbeddingRole = "document",
    ) -> list[float]:
        """Embed a single text."""
        results = await self.embed_texts([text], dimensions, role=role)
        return results[0]

    async def check_available(self) -> int:
        """Return the cell model's native embedding dims, 0 when unavailable.

        Distinguishes between invalid API keys (warning) and other
        failures (debug) so users know when their key is wrong.
        """
        try:
            embeddings = await self._client.embeddings(["ping"])
            if embeddings:
                dim = len(embeddings[0])
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
                    "Check the api_key of the [models.embed] cell in "
                    "~/.mnemo/config.toml."
                )
            else:
                logger.debug(f"Embedding model {self.model} not available: {e}")
            return 0


# ---------------------------------------------------------------------------
# fastretrieval Backend (local ONNX)
# ---------------------------------------------------------------------------


class Qwen3EmbedBackend:
    """Local ONNX embedding via fastretrieval.

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
            from fastretrieval import TextEmbedding

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
        *,
        role: EmbeddingRole = "document",
    ) -> list[list[float]]:
        """Embed texts using local ONNX model (runs in thread)."""
        if not texts:
            return []

        def _embed() -> list[list[float]]:
            model = self._get_model()
            kwargs = {"dim": dimensions} if dimensions and dimensions > 0 else {}
            if role == "query":
                return [
                    list(model.query_embed(text, **kwargs))[0].tolist()
                    for text in texts
                ]
            return [embedding.tolist() for embedding in model.embed(texts, **kwargs)]

        return await asyncio.to_thread(_embed)

    async def embed_single(
        self,
        text: str,
        dimensions: int | None = None,
        *,
        role: EmbeddingRole = "document",
    ) -> list[float]:
        """Embed a single text."""
        results = await self.embed_texts([text], dimensions, role=role)
        return results[0]

    def check_available(self) -> int:
        """Kiểm tra runtime fastretrieval cục bộ có hoạt động hay không."""
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
    model: str | Any = None,
    api_base: str | None = None,
    api_key: str | None = None,
) -> EmbeddingBackend:
    """Initialize and cache the embedding backend.

    Args:
        backend_type: 'cloud' or 'local'
        model: Model name for 'local'; for 'cloud' either the hull provider
            client itself (preferred) or unused (the cell owns the model).
        api_base: Unused (kept for call-site compatibility); the cell owns it.
        api_key: Unused (kept for call-site compatibility); the cell owns it.

    Returns:
        Initialized backend instance.
    """
    global _backend

    if backend_type == "cloud":
        client = model if model is not None else _cell_client()
        _backend = CloudEmbeddingBackend(client)
    elif backend_type == "local":
        _backend = Qwen3EmbedBackend(model if isinstance(model, str) else None)
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")

    return _backend


def _cell_client() -> Any:
    """Build an OpenAI-spec client from the ``[models.embed]`` cell."""
    from mnemo_mcp.runtime import provider_client

    return provider_client("embed")
