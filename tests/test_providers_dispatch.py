"""Bounded reflect provider dispatch paths and the chat-cell client cache."""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_core.ports import CapExceeded
from mnemo_mcp.llm import _get_client, reset_client
from mnemo_mcp.providers import BoundedReflectProvider, _count_tokens


@pytest.fixture(autouse=True)
def _fresh_llm_client():
    reset_client()
    yield
    reset_client()


# ---------------------------------------------------------------------------
# llm client cache
# ---------------------------------------------------------------------------


def test_get_client_caches_until_reset():
    sentinel = MagicMock()
    with patch("mnemo_mcp.runtime.provider_client", return_value=sentinel) as pc:
        assert _get_client() is sentinel
        assert _get_client() is sentinel
        assert pc.call_count == 1

    reset_client()
    other = MagicMock()
    with patch("mnemo_mcp.runtime.provider_client", return_value=other) as pc:
        assert _get_client() is other
        assert pc.call_count == 1


# ---------------------------------------------------------------------------
# token estimation
# ---------------------------------------------------------------------------


def test_count_tokens_is_cl100k_estimate():
    assert _count_tokens("hello world") == 2
    assert _count_tokens("") == 0


# ---------------------------------------------------------------------------
# provider construction + bounded session
# ---------------------------------------------------------------------------


def test_empty_model_falls_back_to_chat_cell():
    cell = MagicMock()
    cell.model = "cell/chat-model"
    with patch("mnemo_mcp.runtime.model_cell", return_value=cell):
        provider = BoundedReflectProvider(model="", api_key="k")
    assert provider.model == "cell/chat-model"


def test_synthesize_uses_injected_transport():
    """The transport replaces the network and the cost receipt is accurate."""
    calls: list[tuple[str, str, int]] = []

    def transport(model, prompt, max_tokens):
        calls.append((model, prompt, max_tokens))
        return ("answer", 10, 5)

    provider = BoundedReflectProvider(
        model="cohere/command-r7b-12-2024",
        api_key="k",
        cap_usd=1.0,
        transport=transport,
    )
    answer = provider.synthesize("q", [{"text": "note"}])
    assert answer["text"] == "answer"
    assert answer["prompt_tokens"] == 10
    assert answer["completion_tokens"] == 5
    assert provider.calls == 1
    # (0.0375, 0.15) USD per 1M for this model: 10 in + 5 out tokens.
    expected_cost = 10 / 1_000_000 * 0.0375 + 5 / 1_000_000 * 0.15
    assert provider.spent_usd == pytest.approx(expected_cost)
    assert calls and calls[0][2] == 400  # max_tokens pinned by synthesize


def test_synthesize_raises_cap_exceeded_before_dispatch():
    transport = MagicMock()
    provider = BoundedReflectProvider(
        model="cohere/command-r7b-12-2024",
        api_key="k",
        cap_usd=0.0,
        transport=transport,
    )
    with pytest.raises(CapExceeded):
        provider.synthesize("q", [])
    transport.assert_not_called()


# ---------------------------------------------------------------------------
# real dispatch path (network client mocked at the boundary)
# ---------------------------------------------------------------------------


class _FakeClient:
    instances: list["_FakeClient"] = []

    def __init__(self, cell, auth_mode=None, timeout=60.0):
        self.cell = cell
        self.auth_mode = auth_mode
        self.chat = AsyncMock(return_value="llm text")
        self.aclose = AsyncMock()
        _FakeClient.instances.append(self)


@pytest.fixture(autouse=True)
def _reset_fake_instances():
    _FakeClient.instances = []
    yield
    _FakeClient.instances = []


def _apply_runtime_patches(fake_settings):
    """Start both patches on an ExitStack; returns the stack for cleanup."""
    stack = ExitStack()
    stack.enter_context(
        patch("hull_core.providers.openai_spec.OpenAICompatClient", _FakeClient)
    )
    stack.enter_context(
        patch("mnemo_mcp.runtime.hull_settings", return_value=fake_settings)
    )
    return stack


def test_dispatch_builds_cell_from_model_and_key():
    fake_settings = MagicMock()
    fake_settings.server.auth = "no-auth"
    base_cell = MagicMock()
    base_cell.base_url = "http://cell-base"
    with _apply_runtime_patches(fake_settings):
        with patch("mnemo_mcp.runtime.model_cell", return_value=base_cell):
            provider = BoundedReflectProvider(
                model="cohere/command-r7b-12-2024", api_key="k", api_base=None
            )
            text, p_tok, c_tok = provider._dispatch("prompt text", 50)

    assert text == "llm text"
    assert (p_tok, c_tok) == (_count_tokens("prompt text"), _count_tokens("llm text"))
    client = _FakeClient.instances[0]
    assert client.cell.task == "chat"
    assert client.cell.model == "cohere/command-r7b-12-2024"
    assert client.cell.api_key == "k"
    # api_base unset -> base_url resolved from the chat cell
    assert client.cell.base_url == "http://cell-base"
    assert client.auth_mode == "no-auth"
    client.aclose.assert_awaited_once()


def test_dispatch_falls_back_to_configured_chat_cell():
    fake_settings = MagicMock()
    fake_settings.server.auth = "token"
    cell = MagicMock()
    cell.model = "cell/chat-model"
    with _apply_runtime_patches(fake_settings):
        with patch("mnemo_mcp.runtime.model_cell", return_value=cell):
            provider = BoundedReflectProvider(model="", api_key="")
            text, _, _ = provider._dispatch("prompt", 50)

    assert text == "llm text"
    client = _FakeClient.instances[0]
    assert client.cell is cell
    assert client.auth_mode == "token"


def test_dispatch_via_synthesize_when_no_transport():
    """synthesize() without a transport runs the real dispatch pipeline."""
    fake_settings = MagicMock()
    fake_settings.server.auth = "no-auth"
    cell = MagicMock()
    cell.model = "cell/chat-model"
    with _apply_runtime_patches(fake_settings):
        with patch("mnemo_mcp.runtime.model_cell", return_value=cell):
            provider = BoundedReflectProvider(model="", api_key="")
            answer = provider.synthesize("q", [{"text": "note"}])

    assert answer["text"] == "llm text"
    assert provider.calls == 1
    assert provider.spent_usd > 0
