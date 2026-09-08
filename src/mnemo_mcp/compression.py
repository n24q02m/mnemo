"""LLM-driven compression pipeline (Phase 2).

Compresses captured turn-style text via the multi-provider LLM dispatch layer
in :mod:`mnemo_mcp.llm` while preserving every concrete fact / decision /
identifier so retrieval quality stays unchanged.

Spec reference: ``2026-04-19-mnemo-v2-design.md`` section 4.1 (LLM compression
3x reduction at >=0.9 fact retention) + section 5.4 (compression pipeline
diagram).

Behaviour:

1. **No provider available** -> graceful skip. Returns the original text with
   ``compressed=False`` and matching ``tokens_in == tokens_out``. The caller
   stores the row as-is and a single warning is logged. No exception raised.
2. **Provider available** -> calls :func:`mnemo_mcp.llm.call_llm` with a
   deterministic compression prompt (temperature=0). Tokens counted via
   tiktoken cl100k_base (matches OpenAI / Anthropic Claude estimates closely
   enough for the 3x reduction metric). On empty / failed response -> the
   pipeline degrades to the graceful skip path.
3. **Env override** -> ``COMPRESSION_PROVIDER`` and ``COMPRESSION_MODEL`` win
   over the auto-detect priority order in :func:`mnemo_mcp.llm.detect_provider`
   (Task 3 of the Phase 2 plan). ``COMPRESSION_ENABLED=false`` skips the
   pipeline entirely.

The module exposes the canonical prompt as :data:`COMPRESSION_PROMPT` so the
fact-retention benchmark fixture can keep both prompt and ground-truth aligned
in source control.
"""

from __future__ import annotations

import os
from typing import Final

import tiktoken
from loguru import logger

from mnemo_mcp.llm import call_llm, detect_provider, get_default_model

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Compression prompt (constant + visible) so reviewers can audit the exact
#: instruction the LLM receives and so the fact-retention fixture can pin to
#: it in tests. Spec section 5.4 calls for explicit fact / identifier
#: preservation; we list the categories inline so the model cannot drop them
#: silently for "summarisation".
COMPRESSION_PROMPT: Final[str] = (
    "Compress this conversation turn to <= 1/3 of the original tokens "
    "while preserving every concrete fact, decision, preference, name, "
    "date, number, file path, URL, code identifier, and quoted phrase. "
    "Return ONLY the compressed text - no explanation, no JSON wrapper.\n\n"
    "<turn>\n{text}\n</turn>"
)

#: tiktoken encoding shared with OpenAI / Anthropic estimates. Loaded once at
#: import time so the per-call ``len(_ENCODING.encode(text))`` is microseconds.
_ENCODING = tiktoken.get_encoding("cl100k_base")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env_compression_enabled() -> bool:
    """Read ``COMPRESSION_ENABLED`` env var (Phase 2 Task 3 override).

    Default is ``True`` so a fresh install with an LLM key starts compressing
    immediately. The MCP ``config(action="set", key="compression_enabled", ...)``
    surface (future) flips this without restart.
    """
    raw = os.environ.get("COMPRESSION_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _resolve_provider(explicit: str | None) -> str | None:
    """Pick provider: explicit arg > COMPRESSION_PROVIDER env > auto-detect."""
    if explicit:
        return explicit
    env = os.environ.get("COMPRESSION_PROVIDER", "").strip()
    if env:
        return env
    return detect_provider()


def _resolve_model(provider: str, explicit: str | None) -> str:
    """Pick model: explicit arg > COMPRESSION_MODEL env > provider default."""
    if explicit:
        return explicit
    env = os.environ.get("COMPRESSION_MODEL", "").strip()
    if env:
        return env
    return get_default_model(provider)


def count_tokens(text: str) -> int:
    """Public token counter - exposed for benchmark fixtures + status probes."""
    return len(_ENCODING.encode(text))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def compress(
    text: str,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """Compress ``text`` via the configured LLM provider.

    Returns a dict with keys:

    - ``text`` (str): the compressed text (or original on skip).
    - ``text_raw`` (str | None): the original uncompressed text when
      compression succeeded; ``None`` when skipped.
    - ``compressed`` (bool): True only when an LLM rewrite landed.
    - ``compression_provider`` (str | None): provider name used.
    - ``compression_model`` (str | None): model name used.
    - ``tokens_in`` / ``tokens_out`` (int): token counts via tiktoken
      cl100k_base. Equal when the pipeline gracefully skips so callers can
      compute ``ratio = tokens_in / tokens_out`` without divide-by-zero.

    The pipeline NEVER raises - any failure (no provider, SDK error, empty
    response, env-disabled) returns the same shape with ``compressed=False``
    so the caller's downstream insert path stays unchanged.
    """
    tokens_in = count_tokens(text)

    skip_payload: dict = {
        "text": text,
        "text_raw": None,
        "compressed": False,
        "compression_provider": None,
        "compression_model": None,
        "tokens_in": tokens_in,
        "tokens_out": tokens_in,
    }

    if not _env_compression_enabled():
        logger.debug("compression: COMPRESSION_ENABLED=false, skipping")
        return skip_payload

    resolved_provider = _resolve_provider(provider)
    if resolved_provider is None:
        logger.warning(
            "compression: no LLM provider available - storing raw text "
            "(set GEMINI_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / "
            "XAI_API_KEY to enable compression)"
        )
        return skip_payload

    resolved_model = _resolve_model(resolved_provider, model)

    try:
        compressed_text = await call_llm(
            COMPRESSION_PROMPT.format(text=text),
            provider=resolved_provider,
            model=resolved_model,
            temperature=0.0,
            max_tokens=max(64, tokens_in // 2),
        )
    except Exception as e:  # pragma: no cover - SDK guard
        logger.warning(
            f"compression: provider={resolved_provider} model={resolved_model} "
            f"failed with {e}; storing raw text"
        )
        return skip_payload

    if not compressed_text or not compressed_text.strip():
        logger.warning(
            f"compression: provider={resolved_provider} returned empty text; "
            "storing raw text"
        )
        return skip_payload

    tokens_out = count_tokens(compressed_text)
    return {
        "text": compressed_text,
        "text_raw": text,
        "compressed": True,
        "compression_provider": resolved_provider,
        "compression_model": resolved_model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }
