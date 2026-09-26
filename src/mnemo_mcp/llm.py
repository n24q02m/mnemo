"""Completion dispatch through the ``[models.chat]`` provider cell.

One cell (``base_url + api_key + model``, plain OpenAI-spec HTTP via
hull-core) serves every chat-shaped task: compression, entity extraction,
consolidation summaries. The host configures the cell in
``~/.mnemo/config.toml`` (or ``HULL_CHAT_API_KEY``); an unconfigured cell
skips optional enrichment — it never falls back to another provider.

Provider errors return None to optional enrichment callers, not another model.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

_client: Any = None


def _get_client() -> Any:
    """Cached OpenAI-spec client for the chat cell."""
    global _client
    if _client is None:
        from mnemo_mcp.runtime import provider_client

        _client = provider_client("chat")
    return _client


def reset_client() -> None:
    """Drop the cached chat client (config edited, tests)."""
    global _client
    _client = None


async def call_llm(
    prompt: str,
    provider: str | None = None,
    model: str | None = None,
    *,
    temperature: float = 0.0,
    max_tokens: int = 500,
) -> str | None:
    """Dispatch ``prompt`` to the ``[models.chat]`` cell.

    Args:
        prompt: The user prompt text.
        provider: Ignored (kept for call-site compatibility; the cell owns
            the provider endpoint).
        model: Ignored (the cell owns the model id).
        temperature: Sampling temperature forwarded verbatim.
        max_tokens: Completion budget forwarded verbatim.

    Returns:
        The assistant message content, or ``None`` when the cell is not
        configured or the provider call fails (optional-enrichment contract).
    """
    from mnemo_mcp.runtime import cell_configured

    if not cell_configured("chat"):
        logger.debug("call_llm: [models.chat] cell not configured; skipping")
        return None

    try:
        return await _get_client().chat(
            [{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:  # pragma: no cover - per-provider runtime guard
        logger.warning(f"call_llm: chat cell call failed: {e}")
        return None
