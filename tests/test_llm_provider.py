"""Tests for the chain-based LLM dispatch layer (``mnemo_mcp.llm``).

Focus is on:
- ``acomplete`` dispatches over the resolved ``settings.llm_chain()``.
- Ordered fallback: a failing primary falls through to the next chain entry.
- Empty chain (no provider key, no LLM_MODELS) -> graceful ``None``.
- Provider is derived from each model's prefix (bare gemini gets prefixed).
- ``call_llm`` is a single-user-message wrapper over ``acomplete``.
- ``LLM_MODELS`` env override flows through the chain.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from mnemo_mcp import llm


def _fake_completion(content: str) -> SimpleNamespace:
    """Build a litellm-shaped completion response (resp.choices[0].message.content)."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


_ALL_KEYS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "JINA_AI_API_KEY",
    "COHERE_API_KEY",
    "LLM_MODELS",
    "LLM_API_BASE",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip provider env vars before each test for deterministic dispatch."""
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# _normalize_model
# ---------------------------------------------------------------------------


def test_normalize_model_slash_form_passthrough() -> None:
    assert llm._normalize_model("openai/gpt-test") == "openai/gpt-test"


def test_normalize_model_bare_gemini_prefixed() -> None:
    assert (
        llm._normalize_model("gemini-3-flash-preview")
        == "gemini/gemini-3-flash-preview"
    )


def test_normalize_model_bare_other_passthrough() -> None:
    assert llm._normalize_model("gpt-5.4-mini") == "gpt-5.4-mini"


def test_provider_for_model_derives_from_prefix() -> None:
    assert llm.provider_for_model("gemini/gemini-3-flash-preview") == "gemini"
    assert llm.provider_for_model("openai/gpt-test") == "openai"
    # bare gemini normalises then resolves to gemini
    assert llm.provider_for_model("gemini-3-flash-preview") == "gemini"
    # bare non-gemini is an OpenAI model by litellm convention
    assert llm.provider_for_model("gpt-5.4-mini") == "openai"


# ---------------------------------------------------------------------------
# acomplete — chain dispatch
# ---------------------------------------------------------------------------


def test_acomplete_dispatches_primary_of_explicit_chain() -> None:
    mock = AsyncMock(return_value=_fake_completion("ok"))
    with patch("mcp_core.llm.acompletion", mock):
        result = asyncio.run(
            llm.acomplete(
                [{"role": "user", "content": "hi"}],
                models=["gemini/gemini-3-flash-preview"],
            )
        )
    assert result == "ok"
    assert mock.call_args.kwargs["model"] == "gemini/gemini-3-flash-preview"
    assert mock.call_args.kwargs["messages"] == [{"role": "user", "content": "hi"}]


def test_acomplete_empty_chain_returns_none() -> None:
    with patch.object(llm.logger, "warning") as warn:
        result = asyncio.run(
            llm.acomplete([{"role": "user", "content": "hi"}], models=[])
        )
    assert result is None
    assert warn.called


def test_acomplete_falls_back_to_next_model_on_failure() -> None:
    mock = AsyncMock(
        side_effect=[Exception("primary down"), _fake_completion("from fallback")]
    )
    with patch("mcp_core.llm.acompletion", mock):
        result = asyncio.run(
            llm.acomplete(
                [{"role": "user", "content": "hi"}],
                models=["gemini/gemini-3-flash-preview", "openai/gpt-test"],
            )
        )
    assert result == "from fallback"
    assert mock.await_count == 2
    # Second call used the fallback model.
    assert mock.call_args.kwargs["model"] == "openai/gpt-test"


def test_acomplete_all_fail_returns_none() -> None:
    mock = AsyncMock(side_effect=Exception("boom"))
    with (
        patch("mcp_core.llm.acompletion", mock),
        patch.object(llm.logger, "warning") as warn,
    ):
        result = asyncio.run(
            llm.acomplete(
                [{"role": "user", "content": "hi"}],
                models=["gemini/a", "openai/b"],
            )
        )
    assert result is None
    assert mock.await_count == 2
    assert warn.called


def test_acomplete_response_format_forwarded_only_when_set() -> None:
    mock = AsyncMock(return_value=_fake_completion("{}"))
    with patch("mcp_core.llm.acompletion", mock):
        asyncio.run(
            llm.acomplete(
                [{"role": "user", "content": "hi"}],
                models=["openai/gpt-test"],
                response_format={"type": "json_object"},
            )
        )
    assert mock.call_args.kwargs["response_format"] == {"type": "json_object"}

    mock2 = AsyncMock(return_value=_fake_completion("{}"))
    with patch("mcp_core.llm.acompletion", mock2):
        asyncio.run(
            llm.acomplete(
                [{"role": "user", "content": "hi"}], models=["openai/gpt-test"]
            )
        )
    assert "response_format" not in mock2.call_args.kwargs


def test_acomplete_bare_gemini_model_prefixed() -> None:
    mock = AsyncMock(return_value=_fake_completion("ok"))
    with patch("mcp_core.llm.acompletion", mock):
        asyncio.run(
            llm.acomplete(
                [{"role": "user", "content": "hi"}],
                models=["gemini-3-flash-preview"],
            )
        )
    assert mock.call_args.kwargs["model"] == "gemini/gemini-3-flash-preview"


def test_acomplete_passes_api_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_BASE", "https://proxy.example/v1")
    mock = AsyncMock(return_value=_fake_completion("ok"))
    with patch("mcp_core.llm.acompletion", mock):
        asyncio.run(
            llm.acomplete(
                [{"role": "user", "content": "hi"}], models=["openai/gpt-test"]
            )
        )
    assert mock.call_args.kwargs["api_base"] == "https://proxy.example/v1"


def test_acomplete_uses_settings_chain_when_models_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """acomplete(models=None) consumes the resolved settings.llm_chain()."""
    monkeypatch.setattr(
        "mnemo_mcp.config.settings.llm_models", "openai/gpt-from-settings"
    )
    mock = AsyncMock(return_value=_fake_completion("ok"))
    with patch("mcp_core.llm.acompletion", mock):
        result = asyncio.run(llm.acomplete([{"role": "user", "content": "hi"}]))
    assert result == "ok"
    assert mock.call_args.kwargs["model"] == "openai/gpt-from-settings"


# ---------------------------------------------------------------------------
# call_llm — single-prompt wrapper
# ---------------------------------------------------------------------------


def test_call_llm_graceful_skip_no_provider() -> None:
    """No LLM_MODELS + no provider key -> empty chain -> None."""
    with patch.object(llm.logger, "warning") as warn:
        result = asyncio.run(llm.call_llm("hello"))
    assert result is None
    assert warn.called


def test_call_llm_wraps_prompt_in_user_message() -> None:
    mock = AsyncMock(return_value=_fake_completion("answer"))
    with patch("mcp_core.llm.acompletion", mock):
        result = asyncio.run(
            llm.call_llm(
                "hi", models=["openai/gpt-test"], temperature=0.2, max_tokens=42
            )
        )
    assert result == "answer"
    assert mock.call_args.kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert mock.call_args.kwargs["temperature"] == 0.2
    assert mock.call_args.kwargs["max_tokens"] == 42


def test_call_llm_uses_settings_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mnemo_mcp.config.settings.llm_models", "gemini/gemini-3-flash-from-settings"
    )
    mock = AsyncMock(return_value=_fake_completion("ok"))
    with patch("mcp_core.llm.acompletion", mock):
        asyncio.run(llm.call_llm("hi"))
    assert mock.call_args.kwargs["model"] == "gemini/gemini-3-flash-from-settings"
