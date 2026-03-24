"""Dual-backend reranking: Cohere (cloud) + qwen3-embed (local ONNX).

Reranker takes search results and re-scores them with a cross-encoder
for better precision. Pipeline: retrieve top-N*3 -> rerank -> return top-N.
"""

from __future__ import annotations

import os
from typing import Protocol

from loguru import logger


class RerankerBackend(Protocol):
    """Protocol for reranker backends."""

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


class CohereReranker:
    """Cloud reranking via Cohere SDK rerank API."""

    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        api_key: str | None = None,
    ):
        self.model = model or "rerank-v4.0-pro"
        self.api_base = api_base  # reserved for future use
        self.api_key = api_key or os.getenv("COHERE_API_KEY") or os.getenv("CO_API_KEY")

    def rerank(
        self, query: str, documents: list[str], top_n: int = 10
    ) -> list[tuple[int, float]]:
        """Rerank documents via Cohere cloud API."""
        if not documents:
            return []
        try:
            import cohere

            client = cohere.ClientV2(api_key=self.api_key)
            response = client.rerank(
                model=self.model,
                query=query,
                documents=documents,
                top_n=top_n,
            )
            results: list[tuple[int, float]] = []
            for item in response.results:
                if isinstance(item, dict):
                    results.append((item["index"], item["relevance_score"]))
                else:
                    results.append((item.index, item.relevance_score))
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_n]
        except Exception as e:
            logger.warning(f"Cohere reranking failed: {e}")
            return []

    def check_available(self) -> bool:
        """Check if the cloud reranker model is reachable."""
        try:
            import cohere

            client = cohere.ClientV2(api_key=self.api_key)
            response = client.rerank(
                model=self.model,
                query="test",
                documents=["test"],
                top_n=1,
            )
            return bool(response.results)
        except Exception as e:
            msg = str(e).lower()
            if any(
                p in msg for p in ("401", "403", "invalid", "unauthorized", "api key")
            ):
                logger.warning(f"API key invalid for reranker {self.model}: {e}")
            else:
                logger.debug(f"Reranker {self.model} not available: {e}")
            return False


# Backward compatibility alias
LiteLLMReranker = CohereReranker


class Qwen3Reranker:
    """Local ONNX cross-encoder reranking via qwen3-embed."""

    DEFAULT_MODEL = "n24q02m/Qwen3-Reranker-0.6B-ONNX"

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or self.DEFAULT_MODEL
        self._model = None

    def _get_model(self):
        """Lazy-load the cross-encoder model.

        On first call, downloads the ONNX model (~570 MB) from HuggingFace
        if not already cached.
        """
        if self._model is None:
            from qwen3_embed import TextCrossEncoder

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


def init_reranker(
    backend_type: str,
    model: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
) -> RerankerBackend:
    """Initialize and cache the reranker backend.

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
        _backend = CohereReranker(model, api_base=api_base, api_key=api_key)
    elif backend_type == "local":
        _backend = Qwen3Reranker(model)
    else:
        raise ValueError(f"Unknown reranker backend: {backend_type}")

    return _backend
