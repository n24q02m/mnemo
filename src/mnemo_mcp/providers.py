"""Bounded reflect providers (P4 paid path).

The adapter wraps the same completion dispatch the rest of the server uses
(the ``[models.chat]`` provider cell via hull-core) but adds the three
contracts the pilot requires: a hard session spend cap with a pre-call
estimate, a per-call cost receipt, and an injectable transport so tests
exercise the full path without any network or spend.

Token counts on the real path are tiktoken cl100k_base estimates (the
OpenAI-spec chat endpoint returns no usage block through hull-core).
"""

from __future__ import annotations

import asyncio
from typing import Any

from mnemo_core.ports import CapExceeded, ProviderAnswer, ReflectPort

def _count_tokens(text: str) -> int:
    """tiktoken cl100k_base estimate (same encoding the compression pipeline uses)."""
    import tiktoken

    return len(tiktoken.get_encoding("cl100k_base").encode(text))


# USD per 1M tokens (input, output). Verified 2026-09-12 against
# docs.cohere.com; OpenRouter passes the same through for cohere/* models.
_PRICES_PER_1M: dict[str, tuple[float, float]] = {
    "cohere/command-r7b-12-2024": (0.0375, 0.15),
    "cohere/command-r-08-2024": (0.15, 0.60),
    "openrouter/minimax/minimax-m3:free": (0.0, 0.0),
}
_DEFAULT_PRICE = (2.50, 10.00)


class BoundedReflectProvider(ReflectPort):
    """Session-bounded completion provider for ``operations.reflect``.

    Args:
        model: Provider-qualified model name (e.g. ``cohere/command-r7b-12-2024``).
        api_key: Gateway/provider key (never logged).
        api_base: Optional gateway base (CF AI Gateway suffix).
        cap_usd: Hard ceiling on cumulative estimated spend for this session.
        transport: Optional callable ``(model, messages, max_tokens) ->
            (text, prompt_tokens, completion_tokens)``. When given it replaces
            the network entirely (tests); when omitted the real chat cell
            dispatch runs.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        api_base: str | None = None,
        cap_usd: float = 5.00,
        transport: Any = None,
    ) -> None:
        if not model:
            from mnemo_mcp.runtime import model_cell

            model = model_cell("chat").model
        self.model = model
        self._api_key = api_key
        self._api_base = api_base
        self.cap_usd = cap_usd
        self._transport = transport
        self._in_price, self._out_price = _PRICES_PER_1M.get(model, _DEFAULT_PRICE)
        self.spent_usd = 0.0
        self.calls = 0

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimated USD for one call at this provider's model price."""
        return (
            prompt_tokens / 1_000_000 * self._in_price
            + completion_tokens / 1_000_000 * self._out_price
        )

    def synthesize(self, query: str, citations: list[dict[str, Any]]) -> ProviderAnswer:
        """One bounded completion. Raises CapExceeded before exceeding cap."""
        prompt = self._prompt(query, citations)
        max_tokens = 400
        projected = self.spent_usd + self.estimate_cost(max_tokens, max_tokens)
        if projected > self.cap_usd:
            raise CapExceeded(
                f"session cap exhausted: spent ${self.spent_usd:.6f} of "
                f"${self.cap_usd:.2f}; next call projected ${projected:.6f}"
            )
        if self._transport is not None:
            text, p_tok, c_tok = self._transport(self.model, prompt, max_tokens)
        else:
            text, p_tok, c_tok = self._dispatch(prompt, max_tokens)
        cost = self.estimate_cost(p_tok, c_tok)
        self.spent_usd += cost
        self.calls += 1
        return {
            "text": text,
            "model": self.model,
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
        }

    def _dispatch(self, prompt: str, max_tokens: int) -> tuple[str, int, int]:
        """Real network dispatch through the chat provider cell."""

        async def _run() -> tuple[str, int, int]:
            from hull_core.config.models import ModelCell
            from hull_core.providers.openai_spec import OpenAICompatClient

            from mnemo_mcp.runtime import hull_settings, model_cell

            if self.model and self._api_key:
                cell = ModelCell(
                    task="chat", model=self.model,
                    api_key=self._api_key,
                    base_url=self._api_base or model_cell("chat").base_url,
                )
            else:
                cell = model_cell("chat")
            client = OpenAICompatClient(cell, auth_mode=hull_settings().server.auth)
            try:
                text = await client.chat(
                    [{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=max_tokens,
                )
            finally:
                await client.aclose()
            p_tok, c_tok = _count_tokens(prompt), _count_tokens(text)
            return (text, p_tok, c_tok)

        return asyncio.run(_run())

    @staticmethod
    def _prompt(query: str, citations: list[dict[str, Any]]) -> str:
        # Deliberately NO escape clause: conditional instructions ("if the
        # notes lack the answer, reply NOT_IN_NOTES") fold badly on small
        # command models — they answer the refusal branch even when the notes
        # contain the answer (verified live 2026-09-12). Abstention is the
        # core's job (empty retrieval never reaches the provider); the eval's
        # needle check keeps the model honest about copying from notes.
        lines = [
            "Answer the question using ONLY the numbered notes. "
            "Copy the relevant note text as your answer.",
            "",
            f"Question: {query}",
            "",
            "Notes:",
        ]
        for i, c in enumerate(citations, 1):
            lines.append(f"[{i}] {c.get('content', '')}")
        return "\n".join(lines)
