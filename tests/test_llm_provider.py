"""Tests for the LLM dispatch layer (``mnemo_mcp.llm``).

De-host rework: the multi-provider detection/env-override machinery pinned
removed internals and was deleted -- one ``[models.chat]`` provider cell now
serves every chat-shaped task. What remains to pin is the live
optional-enrichment contract of :func:`mnemo_mcp.llm.call_llm`:

- unconfigured cell -> ``None`` (debug, not warning),
- prompt/params forwarded verbatim to the cell client,
- provider failure -> ``None`` with a warning (never raises).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp import llm


def _cell_client(content="ok", exc=None):
    """Stub hull OpenAI-spec client for the chat cell."""
    client = MagicMock()
    client.chat = AsyncMock(return_value=content) if exc is None else AsyncMock(
        side_effect=exc
    )
    return client


@pytest.fixture(autouse=True)
def _cell_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the fake-HOME environment look like a configured chat cell."""
    monkeypatch.setattr("mnemo_mcp.runtime.cell_configured", lambda task: True)


def test_cell_not_configured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unconfigured chat cell: call_llm returns None and logs at debug level."""
    monkeypatch.setattr("mnemo_mcp.runtime.cell_configured", lambda task: False)
    with patch.object(llm.logger, "debug") as debug:
        result = asyncio.run(llm.call_llm("hello"))
    assert result is None
    assert debug.called, "expected a debug log on graceful skip"
    assert "not configured" in debug.call_args.args[0]


def test_dispatches_prompt_to_chat_cell() -> None:
    """call_llm sends the user prompt to the chat cell client."""
    client = _cell_client(content="from chat cell")
    monkey_client = MagicMock(return_value=client)
    with patch.object(llm, "_get_client", monkey_client):
        result = asyncio.run(llm.call_llm("hi"))

    assert result == "from chat cell"
    args, kwargs = client.chat.call_args
    assert args[0] == [{"role": "user", "content": "hi"}]
    assert kwargs["temperature"] == 0.0
    assert kwargs["max_tokens"] == 500


def test_forwards_temperature_and_max_tokens() -> None:
    """Sampling parameters are forwarded verbatim to the cell client."""
    client = _cell_client(content="ok")
    with patch.object(llm, "_get_client", MagicMock(return_value=client)):
        asyncio.run(llm.call_llm("hi", temperature=0.2, max_tokens=42))

    kwargs = client.chat.call_args.kwargs
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 42


def test_provider_failure_returns_none() -> None:
    """A failing cell call returns None (optional-enrichment contract)."""
    client = _cell_client(exc=RuntimeError("cell exploded"))
    with patch.object(llm, "_get_client", MagicMock(return_value=client)):
        with patch.object(llm.logger, "warning") as warn:
            result = asyncio.run(llm.call_llm("hi"))

    assert result is None
    assert warn.called, "expected a warning log when the cell call fails"
