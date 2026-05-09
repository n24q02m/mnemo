"""Multi-provider LLM dispatch layer (Phase 1 foundation).

Provides a single ``call_llm`` entry point that auto-detects the active
provider from environment variables and dispatches to the appropriate native
SDK. The priority order matches the spec
(`2026-04-19-mnemo-v2-design.md` §4.2):

    1. Gemini (``GEMINI_API_KEY`` or ``GOOGLE_API_KEY``)
    2. OpenAI (``OPENAI_API_KEY``)
    3. Anthropic (``ANTHROPIC_API_KEY``)
    4. xAI / Grok (``XAI_API_KEY``)

If no provider key is available, ``call_llm`` logs a warning and returns
``None`` so callers (e.g. the upcoming ``capture`` action's optional fact
extraction) can gracefully skip LLM-dependent enrichment.

This module is intentionally a *dispatch layer only*. The actual
fact-extraction prompting / parsing logic is deferred to Phase 2
(compression). Existing graph-extraction logic continues to live in
``graph.py`` and is not migrated here in this slice.
"""

from __future__ import annotations

import os
from typing import Final

from loguru import logger

# Provider priority is encoded once and consumed by both detection and
# default-model lookup so they cannot drift apart.
_PROVIDER_ENV_VARS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("gemini", ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    ("openai", ("OPENAI_API_KEY",)),
    ("anthropic", ("ANTHROPIC_API_KEY",)),
    ("xai", ("XAI_API_KEY",)),
)

# Sane per-provider defaults if ``LLM_MODELS`` env var is not set or does not
# specify the active provider. Names follow the user's prior choices in the
# repo (see CLAUDE.md "Default AI models" section); keep these exact unless
# explicitly directed — see ~/.claude memory feedback_dont_change_model_names.
_DEFAULT_MODELS: Final[dict[str, str]] = {
    "gemini": "gemini-3-flash-preview",
    "openai": "gpt-5.4-mini-2026-03-17",
    "anthropic": "claude-haiku-4-5",
    "xai": "grok-4-fast",
}


def detect_provider() -> str | None:
    """Return the highest-priority provider with a configured API key.

    Returns ``None`` when no provider key is found in the environment so
    callers can short-circuit to a graceful skip path.
    """
    for provider, env_vars in _PROVIDER_ENV_VARS:
        for env_var in env_vars:
            if os.environ.get(env_var):
                return provider
    return None


def get_default_model(provider: str) -> str:
    """Return the model name for ``provider``, honouring the ``LLM_MODELS`` env var.

    ``LLM_MODELS`` accepts comma-separated ``provider=model`` or
    ``provider/model`` pairs (matching the existing settings format), e.g.::

        LLM_MODELS="gemini=gemini-3-flash,openai=gpt-5-mini"
        LLM_MODELS="gemini/gemini-3-flash,openai/gpt-5-mini"

    The first matching entry wins. If the env var is unset or contains no
    entry for ``provider``, the per-provider sane default from
    ``_DEFAULT_MODELS`` is returned.
    """
    raw = os.environ.get("LLM_MODELS", "").strip()
    if raw:
        for pair in raw.split(","):
            pair = pair.strip()
            if not pair:
                continue
            for sep in ("=", "/"):
                if sep in pair:
                    key, _, model = pair.partition(sep)
                    if key.strip().lower() == provider:
                        model = model.strip()
                        if model:
                            return model
                    break

    return _DEFAULT_MODELS.get(provider, "")


async def call_llm(
    prompt: str,
    provider: str | None = None,
    model: str | None = None,
    *,
    temperature: float = 0.0,
    max_tokens: int = 500,
) -> str | None:
    """Dispatch ``prompt`` to the configured LLM provider.

    Args:
        prompt: User prompt text. Treated as a single-turn user message.
        provider: Optional explicit provider override
            (``"gemini"`` / ``"openai"`` / ``"anthropic"`` / ``"xai"``).
            When ``None`` (the default), auto-detection runs.
        model: Optional explicit model override. When ``None``, the result of
            :func:`get_default_model` for the resolved provider is used.
        temperature: Sampling temperature passed through to the SDK.
        max_tokens: Maximum response tokens to request from the provider.

    Returns:
        The text content of the LLM response, or ``None`` when no provider
        could be resolved (caller is expected to gracefully skip the
        LLM-dependent enrichment in that case).
    """
    resolved_provider = provider or detect_provider()
    if resolved_provider is None:
        logger.warning(
            "call_llm: no LLM provider API key found in environment "
            "(GEMINI_API_KEY / GOOGLE_API_KEY / OPENAI_API_KEY / "
            "ANTHROPIC_API_KEY / XAI_API_KEY); returning None for graceful skip"
        )
        return None

    resolved_model = model or get_default_model(resolved_provider)

    try:
        if resolved_provider == "gemini":
            return await _call_gemini(resolved_model, prompt, temperature, max_tokens)
        if resolved_provider == "openai":
            return await _call_openai(resolved_model, prompt, temperature, max_tokens)
        if resolved_provider == "anthropic":
            return await _call_anthropic(
                resolved_model, prompt, temperature, max_tokens
            )
        if resolved_provider == "xai":
            return await _call_xai(resolved_model, prompt, temperature, max_tokens)
    except Exception as e:  # pragma: no cover - per-provider runtime guard
        logger.warning(
            f"call_llm: provider={resolved_provider} model={resolved_model} failed: {e}"
        )
        return None

    logger.warning(f"call_llm: unknown provider {resolved_provider!r}")
    return None


async def _call_gemini(
    model: str, prompt: str, temperature: float, max_tokens: int
) -> str:
    """Dispatch to ``google-genai``. Mirrors graph.py LLM completion path."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text or ""


async def _call_openai(
    model: str, prompt: str, temperature: float, max_tokens: int
) -> str:
    """Dispatch to OpenAI Chat Completions via the ``openai`` SDK."""
    import openai

    api_key = os.environ.get("OPENAI_API_KEY")
    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


async def _call_anthropic(
    model: str, prompt: str, temperature: float, max_tokens: int
) -> str:
    """Dispatch to Anthropic Messages API via the ``anthropic`` SDK.

    The ``anthropic`` package is not declared as a hard dependency yet — when
    a user sets ``ANTHROPIC_API_KEY`` without installing it, ``call_llm``
    catches the ``ImportError`` and returns ``None``.
    """
    import anthropic  # noqa: I001 - lazy optional import

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = getattr(message, "content", []) or []
    return "".join(getattr(p, "text", "") for p in parts)


async def _call_xai(
    model: str, prompt: str, temperature: float, max_tokens: int
) -> str:
    """Dispatch to xAI Grok via the OpenAI-compatible endpoint."""
    import openai

    api_key = os.environ.get("XAI_API_KEY")
    client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""
