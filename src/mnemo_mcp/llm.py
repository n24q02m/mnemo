"""Chain-based LLM dispatch layer.

Provides a single entry point that dispatches a chat completion over the
configured LLM model chain (``settings.llm_chain()``) via ``mcp_core.llm``
(litellm passthrough). The chain is an ordered list of ``provider/model``
strings; the provider is derived from each model's prefix
(``mcp_core.llm.providers``) and litellm routes accordingly. Models are tried
in order so a transient failure on the primary falls back to the next entry.

If the chain is empty (``LLM_MODELS`` unset and no provider key configured for
any default model), dispatch logs a warning and returns ``None`` so callers
(compression, graph extraction, temporal extraction) can gracefully skip
LLM-dependent enrichment.

litellm calls each provider's API directly, so ``ANTHROPIC_API_KEY`` works
WITHOUT the ``anthropic`` package installed (no native SDK import).
"""

from __future__ import annotations

import os

from loguru import logger
from mcp_core.llm.providers import provider_of_model


def llm_chain() -> list[str]:
    """Return the resolved, key-gated LLM model chain from settings.

    A thin accessor so callers depend on this module (not ``config``) for the
    LLM chain, mirroring how ``settings.embedding_chain()`` /
    ``settings.rerank_chain()`` are consumed by the embed / rerank backends.
    """
    from mnemo_mcp.config import settings

    return settings.llm_chain()


def _normalize_model(model: str) -> str:
    """Normalise a model string to litellm ``provider/model`` form.

    A ``provider/model`` string passes through unchanged. A bare gemini model
    name (e.g. ``gemini-3-flash-preview``) is prefixed with ``gemini/`` so
    litellm routes it via ``GEMINI_API_KEY``; any other bare name is left as-is
    (litellm treats a bare name as an OpenAI model per its convention).
    """
    model = model.strip()
    if "/" in model:
        return model
    if "gemini" in model.lower():
        return f"gemini/{model}"
    return model


def provider_for_model(model: str) -> str:
    """Provider prefix for a chain model (via the mcp-core primitive)."""
    return provider_of_model(_normalize_model(model))


async def acomplete(
    messages: list[dict],
    *,
    models: list[str] | None = None,
    temperature: float = 0.0,
    max_tokens: int = 500,
    response_format: dict | None = None,
) -> str | None:
    """Dispatch a chat completion over the LLM chain with ordered fallback.

    Args:
        messages: OpenAI-shaped chat messages.
        models: Explicit chain override. When ``None`` the resolved
            ``settings.llm_chain()`` is used. The provider for each entry is
            derived from its prefix; litellm routes via ``<PROVIDER>_API_KEY``.
        temperature: Sampling temperature passed through to litellm.
        max_tokens: Maximum response tokens to request.
        response_format: Optional litellm ``response_format`` (e.g.
            ``{"type": "json_object"}``); only forwarded when provided.

    Returns:
        The text content of the first model that responds, or ``None`` when the
        chain is empty (no provider configured) or every model in the chain
        fails.
    """
    chain = models if models is not None else llm_chain()
    if not chain:
        logger.warning(
            "acomplete: no LLM model configured (LLM_MODELS empty and no "
            "default-model provider key set); returning None for graceful skip"
        )
        return None

    # Lazy import: litellm costs ~1-2s on first import.
    from mcp_core.llm import acompletion

    api_base = os.environ.get("LLM_API_BASE") or None
    extra: dict = {"response_format": response_format} if response_format else {}

    last_exc: Exception | None = None
    for model in chain:
        try:
            resp = await acompletion(
                model=_normalize_model(model),
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                api_base=api_base,
                **extra,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # per-model runtime guard; fall through to next
            last_exc = e
            logger.warning(f"acomplete: model={model} failed: {e}; trying next")
            continue

    logger.warning(
        f"acomplete: all {len(chain)} chain model(s) failed; last error: {last_exc}"
    )
    return None


async def call_llm(
    prompt: str,
    *,
    models: list[str] | None = None,
    temperature: float = 0.0,
    max_tokens: int = 500,
) -> str | None:
    """Dispatch a single-turn ``prompt`` over the LLM chain.

    Thin wrapper around :func:`acomplete` that wraps ``prompt`` in a single
    user message. Returns ``None`` when no provider could be resolved (caller
    is expected to gracefully skip the LLM-dependent enrichment).
    """
    return await acomplete(
        [{"role": "user", "content": prompt}],
        models=models,
        temperature=temperature,
        max_tokens=max_tokens,
    )
