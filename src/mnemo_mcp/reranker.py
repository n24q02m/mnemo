"""Dual-backend reranking: Cloud (Jina/Cohere) + qwen3-embed (local ONNX).

Reranker takes search results and re-scores them with a cross-encoder
for better precision. Pipeline: retrieve top-N*3 -> rerank -> return top-N.
"""

from __future__ import annotations

import os
from typing import Protocol

from loguru import logger


def _detect_rerank_provider(model: str) -> str:
    """Detect reranker provider from model name.

    Returns 'jina' or 'cohere'.
    """
    lower = model.lower()
    if lower.startswith("jina_ai/") or lower.startswith("jina"):
        return "jina"
    # Fallback: check env vars in priority order
    if not (lower.startswith("rerank") or lower.startswith("cohere/")):
        if os.getenv("JINA_AI_API_KEY"):
            return "jina"
    return "cohere"


def _strip_provider(model: str) -> str:
    """Strip provider prefix (e.g. 'jina_ai/model' -> 'model')."""
    if "/" in model:
        return model.split("/", 1)[1]
    return model


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


class CloudReranker:
    """Cloud reranking via Jina AI or Cohere SDK."""

    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        api_key: str | None = None,
    ):
        self.model = model or "rerank-v4.0-pro"
        self.api_base = api_base
        self.api_key = api_key
        self._provider = _detect_rerank_provider(self.model)
        self._bare_model = _strip_provider(self.model)

    def rerank(
        self, query: str, documents: list[str], top_n: int = 10
    ) -> list[tuple[int, float]]:
        """Rerank documents via cloud API (Jina or Cohere)."""
        if not documents:
            return []
        try:
            if self._provider == "jina":
                return self._rerank_jina(query, documents, top_n)
            return self._rerank_cohere(query, documents, top_n)
        except Exception as e:
            logger.warning(f"Cloud reranking failed ({self._provider}): {e}")
            return []

    def _rerank_jina(
        self, query: str, documents: list[str], top_n: int
    ) -> list[tuple[int, float]]:
        """Rerank via Jina AI REST API."""
        import httpx

        key = self.api_key or os.getenv("JINA_AI_API_KEY") or ""
        payload: dict = {
            "model": self._bare_model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
        }

        response = httpx.post(
            "https://api.jina.ai/v1/rerank",
            json=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()["results"]

        results: list[tuple[int, float]] = []
        for item in data:
            results.append((item["index"], item["relevance_score"]))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_n]

    def _rerank_cohere(
        self, query: str, documents: list[str], top_n: int
    ) -> list[tuple[int, float]]:
        """Rerank via Cohere SDK."""
        import cohere

        key = (
            self.api_key or os.getenv("COHERE_API_KEY") or os.getenv("CO_API_KEY") or ""
        )
        client = cohere.ClientV2(api_key=key)
        response = client.rerank(
            model=self._bare_model,
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

    def check_available(self) -> bool:
        """Check if the cloud reranker model is reachable."""
        try:
            if self._provider == "jina":
                return self._check_jina()
            return self._check_cohere()
        except Exception as e:
            msg = str(e).lower()
            if any(
                p in msg for p in ("401", "403", "invalid", "unauthorized", "api key")
            ):
                logger.warning(f"API key invalid for reranker {self.model}: {e}")
            else:
                logger.debug(f"Reranker {self.model} not available: {e}")
            return False

    def _check_jina(self) -> bool:
        """Check Jina reranker availability."""
        import httpx

        key = self.api_key or os.getenv("JINA_AI_API_KEY") or ""
        response = httpx.post(
            "https://api.jina.ai/v1/rerank",
            json={
                "model": self._bare_model,
                "query": "test",
                "documents": ["test"],
                "top_n": 1,
            },
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        response.raise_for_status()
        return bool(response.json().get("results"))

    def _check_cohere(self) -> bool:
        """Check Cohere reranker availability."""
        import cohere

        key = (
            self.api_key or os.getenv("COHERE_API_KEY") or os.getenv("CO_API_KEY") or ""
        )
        client = cohere.ClientV2(api_key=key)
        response = client.rerank(
            model=self._bare_model,
            query="test",
            documents=["test"],
            top_n=1,
        )
        return bool(response.results)


# Backward compatibility aliases
CohereReranker = CloudReranker
LiteLLMReranker = CloudReranker


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
        _backend = CloudReranker(model, api_base=api_base, api_key=api_key)
    elif backend_type == "local":
        _backend = Qwen3Reranker(model)
    else:
        raise ValueError(f"Unknown reranker backend: {backend_type}")

    return _backend


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

    def rerank(
        self, query: str, documents: list[str], top_n: int = 10
    ) -> list[tuple[int, float]]:
        if not documents:
            return []
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
                return ranked
        return []

    def check_available(self) -> bool:
        """Available if any backend in the chain reports availability."""
        for backend in self._backends:
            try:
                if backend.check_available():
                    return True
            except Exception:
                continue
        return False


def build_default_rerank_chain(
    *,
    prefer_local: bool = True,
) -> FallbackChainReranker:
    """Build the canonical Phase 1 rerank chain.

    Order: qwen3 local cross-encoder -> Jina (``JINA_AI_API_KEY``) ->
    Cohere (``COHERE_API_KEY`` / ``CO_API_KEY``). Models keep the env-detected
    default so :memory:`feedback_dont_change_model_names` stays satisfied.

    Args:
        prefer_local: When ``False``, cloud backends come first.
    """
    chain: list[RerankerBackend] = []
    local = Qwen3Reranker()

    cloud: list[RerankerBackend] = []
    if os.getenv("JINA_AI_API_KEY"):
        cloud.append(CloudReranker(model="jina_ai/jina-reranker-v3"))
    if os.getenv("COHERE_API_KEY") or os.getenv("CO_API_KEY"):
        cloud.append(CloudReranker(model="rerank-v4.0-pro"))

    if prefer_local:
        chain.append(local)
        chain.extend(cloud)
    else:
        chain.extend(cloud)
        chain.append(local)

    return FallbackChainReranker(chain)
