"""Dual-backend reranking: Cloud ([models.rerank] cell) + fastretrieval (local ONNX).

Cloud reranking goes through the ``[models.rerank]`` provider cell
(``base_url + api_key + model``, plain HTTP via hull-core). Reranker takes
search results and re-scores them with a cross-encoder for better precision.
Pipeline: retrieve top-N*3 -> rerank -> return top-N.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from loguru import logger


class RerankerBackend(Protocol):
    """Protocol for reranker backends."""

    backend_name: str
    model_name: str

    def rerank(
        self, query: str, documents: list[str], top_n: int = 10
    ) -> list[tuple[int, float]]:
        """Rerank documents by relevance to query.

        Returns list of (original_index, relevance_score) sorted by score descending.
        """
        ...

    def check_available(self) -> bool:
        """Check if the reranker backend is available."""
        ...


@dataclass(frozen=True, slots=True)
class RerankOutcome:
    """Per-call rerank result and the backend that produced it."""

    results: list[tuple[int, float]]
    backend_name: str | None
    model_name: str | None


def describe_reranker(
    backend: RerankerBackend | None,
) -> tuple[str | None, str | None]:
    """Return public backend/model identity without provider credentials."""
    if backend is None:
        return None, None
    backend_name = getattr(backend, "backend_name", None)
    model_name = getattr(backend, "model_name", None)
    return (
        backend_name if isinstance(backend_name, str) else None,
        model_name if isinstance(model_name, str) else None,
    )


class CloudReranker:
    """Cloud reranking via the ``[models.rerank]`` provider cell.

    Wraps exactly one :class:`~hull_core.providers.openai_spec.
    OpenAICompatClient`; the cell owns base_url, api_key, and model. The hull
    client is async, so this backend drives it from a private event loop in
    the caller's thread (server dispatch runs rerank via ``asyncio.to_thread``).
    """

    def __init__(self, client: Any):
        self._client = client
        self.backend_name = "cloud"
        self.model_name = client.cell.model

    @property
    def model(self) -> str:
        """The cell-owned rerank model id (for logs and diagnostics)."""
        return self._client.cell.model

    def _call_rerank(
        self, query: str, documents: list[str], top_n: int
    ) -> list[tuple[int, float]]:
        """Single cloud path via the hull client (runs inside a worker thread)."""
        results = _run_async(self._client.rerank(query, documents, top_n=top_n))
        return [
            (int(r["index"]), float(r["relevance_score"]))
            for r in results
        ]

    def rerank(
        self, query: str, documents: list[str], top_n: int = 10
    ) -> list[tuple[int, float]]:
        """Rerank documents via the cloud rerank API."""
        if not documents:
            return []
        try:
            results = self._call_rerank(query, documents, top_n)
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_n]
        except Exception as e:
            logger.warning(f"Cloud reranking failed ({self.model}): {e}")
            return []

    def check_available(self) -> bool:
        """Check if the cloud reranker model is reachable."""
        try:
            results = self._call_rerank("test", ["test document"], 1)
            return bool(results)
        except Exception as e:
            msg = str(e).lower()
            if any(
                p in msg for p in ("401", "403", "invalid", "unauthorized", "api key")
            ):
                logger.warning(f"API key invalid for reranker {self.model}: {e}")
            else:
                logger.debug(f"Reranker {self.model} not available: {e}")
            return False


def _run_async(coro: Any) -> Any:
    """Run one coroutine to completion on this thread's event loop.

    The server calls rerank inside ``asyncio.to_thread`` workers, where no
    loop is running; a fresh loop per call is fine for a single request.
    """
    return asyncio.run(coro)


class Qwen3Reranker:
    """Local ONNX cross-encoder reranking via fastretrieval."""

    # YesNo variant: ~598 MB at inference vs ~12 GB for the full-vocab build,
    # mathematically equivalent and batch-invariant for the reference profile.
    DEFAULT_MODEL = "n24q02m/Qwen3-Reranker-0.6B-ONNX-YesNo"

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or self.DEFAULT_MODEL
        self.backend_name = "local"
        self.model_name = self._model_name
        self._model = None

    def _get_model(self):
        """Lazy-load the cross-encoder model.

        On first call, downloads the ONNX model (~570 MB) from HuggingFace
        if not already cached.
        """
        if self._model is None:
            from fastretrieval import TextCrossEncoder

            logger.warning(
                f"Loading local reranker: {self._model_name} (~570 MB on first run)"
            )
            self._model = TextCrossEncoder(model_name=self._model_name)
            logger.info("Local reranker model loaded")
        return self._model

    def rerank(
        self, query: str, documents: list[str], top_n: int = 10
    ) -> list[tuple[int, float]]:
        """Rerank documents using local cross-encoder."""
        if not documents:
            return []
        try:
            model = self._get_model()
            scores = list(model.rerank(query, documents))
            results = list(enumerate(scores))
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_n]
        except Exception as e:
            logger.warning(f"Local reranking failed: {e}")
            return []

    def check_available(self) -> bool:
        """Check if the local reranker model is available."""
        try:
            model = self._get_model()
            scores = list(model.rerank("test", ["test document"]))
            return len(scores) > 0
        except Exception as e:
            logger.debug(f"Local reranker not available: {e}")
            return False


# ---------------------------------------------------------------------------
# Factory + module-level state
# ---------------------------------------------------------------------------

_backend: RerankerBackend | None = None


def get_reranker() -> RerankerBackend | None:
    """Get the current reranker backend singleton."""
    return _backend


def clear_reranker() -> None:
    """Clear the cached reranker backend."""
    global _backend
    _backend = None


def init_reranker(
    backend_type: str,
    model: str | Any = None,
    api_base: str | None = None,
    api_key: str | None = None,
) -> RerankerBackend:
    """Initialize and cache the reranker backend.

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
        _backend = CloudReranker(client)
    elif backend_type == "local":
        _backend = Qwen3Reranker(model if isinstance(model, str) else None)
    else:
        raise ValueError(f"Unknown reranker backend: {backend_type}")

    return _backend


def _cell_client() -> Any:
    """Build an OpenAI-spec client from the ``[models.rerank]`` cell."""
    from mnemo_mcp.runtime import provider_client

    return provider_client("rerank")


class FallbackChainReranker:
    """Reranker that tries an ordered list of backends until one returns scores.

    Phase 1 retrieval polish (spec section 4.2) requires a cross-encoder
    rerank with the chain: ``qwen3-reranker local`` -> Jina -> Cohere. When
    every backend in the chain fails, ``rerank`` returns an empty list so the
    caller keeps the original ordering.
    """

    def __init__(self, backends: list[RerankerBackend]):
        if not backends:
            raise ValueError("FallbackChainReranker requires at least one backend")
        self._backends = backends

    @property
    def backend_name(self) -> str:
        return "fallback-chain"

    @property
    def model_name(self) -> str:
        return ",".join(
            model_name
            for backend in self._backends
            if (model_name := describe_reranker(backend)[1]) is not None
        )

    def rerank(
        self, query: str, documents: list[str], top_n: int = 10
    ) -> list[tuple[int, float]]:
        return self.rerank_with_identity(query, documents, top_n=top_n).results

    def rerank_with_identity(
        self, query: str, documents: list[str], top_n: int = 10
    ) -> RerankOutcome:
        """Rerank once and return call-local selection metadata."""
        if not documents:
            return RerankOutcome([], None, None)
        for backend in self._backends:
            try:
                ranked = backend.rerank(query, documents, top_n=top_n)
            except Exception as e:
                logger.warning(
                    f"FallbackChainReranker: backend {type(backend).__name__} "
                    f"raised {type(e).__name__}: {e}"
                )
                continue
            if ranked:
                backend_name, model_name = describe_reranker(backend)
                return RerankOutcome(ranked, backend_name, model_name)
        return RerankOutcome([], None, None)

    def check_available(self) -> bool:
        """Available if any backend in the chain reports availability."""
        for backend in self._backends:
            try:
                if backend.check_available():
                    return True
            except Exception:
                continue
        return False


def rerank_with_identity(
    backend: RerankerBackend,
    query: str,
    documents: list[str],
    top_n: int = 10,
) -> RerankOutcome:
    """Run one backend and preserve call-local selection metadata."""
    if isinstance(backend, FallbackChainReranker):
        return backend.rerank_with_identity(query, documents, top_n=top_n)
    results = backend.rerank(query, documents, top_n=top_n)
    backend_name, model_name = describe_reranker(backend)
    return RerankOutcome(results, backend_name, model_name)


def build_default_rerank_chain(
    *,
    prefer_local: bool = True,
) -> FallbackChainReranker:
    """Build the canonical rerank chain.

    Order: the ``[models.rerank]`` cell (when the host configured a key) ->
    qwen3 local cross-encoder. Every cloud env-key discovery is gone with the
    de-host: the host decides the single cloud cell; the local ONNX model is
    the always-available fallback.

    Args:
        prefer_local: When ``True`` (default), the local backend runs first
            and the cell only serves as fallback.
    """
    chain: list[RerankerBackend] = []
    from mnemo_mcp.runtime import cell_configured

    cloud: list[RerankerBackend] = []
    if cell_configured("rerank"):
        cloud.append(CloudReranker(_cell_client()))
    local = Qwen3Reranker()

    if prefer_local:
        chain.append(local)
        chain.extend(cloud)
    else:
        chain.extend(cloud)
        chain.append(local)

    return FallbackChainReranker(chain)
