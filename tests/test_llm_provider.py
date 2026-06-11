"""Tests for the multi-provider LLM dispatch layer (``mnemo_mcp.llm``).

Focus is on:
- Auto-detection priority order across the 4 supported providers.
- Graceful skip path when no provider key is present.
- Explicit ``provider`` / ``model`` overrides bypass detection.
- ``LLM_MODELS`` env override resolves model names per provider.
- Per-provider dispatch routes to the correct SDK call site.
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
    "LLM_MODELS",
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip all provider env vars before each test for deterministic dispatch."""
    for key in _ALL_KEYS:
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# detect_provider
# ---------------------------------------------------------------------------


def test_detect_provider_gemini_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")
    assert llm.detect_provider() == "gemini"


def test_detect_provider_google_alias_resolves_to_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "g-key")
    assert llm.detect_provider() == "gemini"


def test_detect_provider_priority_order(monkeypatch: pytest.MonkeyPatch) -> None:
    # OpenAI beats Anthropic and xAI when Gemini is absent.
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-key")
    monkeypatch.setenv("XAI_API_KEY", "x-key")
    assert llm.detect_provider() == "openai"

    # Removing OpenAI promotes Anthropic.
    monkeypatch.delenv("OPENAI_API_KEY")
    assert llm.detect_provider() == "anthropic"

    # Removing Anthropic promotes xAI as last resort.
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert llm.detect_provider() == "xai"


def test_detect_provider_none_when_no_keys() -> None:
    assert llm.detect_provider() is None


# ---------------------------------------------------------------------------
# get_default_model
# ---------------------------------------------------------------------------


def test_get_default_model_falls_back_to_builtin() -> None:
    assert llm.get_default_model("gemini") == llm._DEFAULT_MODELS["gemini"]
    assert llm.get_default_model("openai") == llm._DEFAULT_MODELS["openai"]
    assert llm.get_default_model("anthropic") == llm._DEFAULT_MODELS["anthropic"]
    assert llm.get_default_model("xai") == llm._DEFAULT_MODELS["xai"]


def test_get_default_model_from_env_equals_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_MODELS", "gemini=gemini-3-flash-test,openai=gpt-test")
    assert llm.get_default_model("gemini") == "gemini-3-flash-test"
    assert llm.get_default_model("openai") == "gpt-test"


def test_get_default_model_from_env_slash_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LLM_MODELS", "gemini/gemini-3-flash,openai/gpt-5.4-mini-2026-03-17"
    )
    assert llm.get_default_model("gemini") == "gemini-3-flash"
    assert llm.get_default_model("openai") == "gpt-5.4-mini-2026-03-17"


def test_get_default_model_unknown_provider_returns_empty() -> None:
    assert llm.get_default_model("unknown-provider") == ""


# ---------------------------------------------------------------------------
# call_llm — graceful skip
# ---------------------------------------------------------------------------


def test_call_llm_graceful_skip_no_provider() -> None:
    """When no provider is configured, call_llm returns None and warns."""
    with patch.object(llm.logger, "warning") as warn:
        result = asyncio.run(llm.call_llm("hello"))
    assert result is None
    assert warn.called, "expected a warning log on graceful skip"
    msg = warn.call_args.args[0] if warn.call_args.args else ""
    assert "no LLM provider" in msg


def test_call_llm_unknown_explicit_provider_returns_none() -> None:
    """Explicit but unsupported provider returns None when litellm raises."""
    mock = AsyncMock(side_effect=Exception("bogus provider"))
    with (
        patch("mcp_core.llm.acompletion", mock),
        patch.object(llm.logger, "warning") as warn,
    ):
        result = asyncio.run(llm.call_llm("hello", provider="bogus"))
    assert result is None
    assert warn.called


# ---------------------------------------------------------------------------
# call_llm — litellm passthrough dispatch
# ---------------------------------------------------------------------------


def test_call_llm_dispatches_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")

    mock = AsyncMock(return_value=_fake_completion("from gemini"))
    with patch("mcp_core.llm.acompletion", mock):
        result = asyncio.run(llm.call_llm("hi"))

    assert result == "from gemini"
    call_kwargs = mock.call_args.kwargs
    assert call_kwargs["model"] == f"gemini/{llm._DEFAULT_MODELS['gemini']}"
    assert call_kwargs["messages"] == [{"role": "user", "content": "hi"}]


def test_call_llm_dispatches_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")

    mock = AsyncMock(return_value=_fake_completion("from openai"))
    with patch("mcp_core.llm.acompletion", mock):
        result = asyncio.run(
            llm.call_llm("hi", model="gpt-test", temperature=0.2, max_tokens=42)
        )

    assert result == "from openai"
    call_kwargs = mock.call_args.kwargs
    assert call_kwargs["model"] == "openai/gpt-test"
    assert call_kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["max_tokens"] == 42


def test_call_llm_dispatches_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """ANTHROPIC_API_KEY now works WITHOUT the anthropic package (litellm)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-key")

    mock = AsyncMock(return_value=_fake_completion("from anthropic"))
    # No `anthropic` package: ensure import is never attempted.
    with patch.dict("sys.modules", {"anthropic": None}):
        with patch("mcp_core.llm.acompletion", mock):
            result = asyncio.run(llm.call_llm("hi"))

    assert result == "from anthropic"
    call_kwargs = mock.call_args.kwargs
    assert call_kwargs["model"] == f"anthropic/{llm._DEFAULT_MODELS['anthropic']}"
    assert call_kwargs["messages"] == [{"role": "user", "content": "hi"}]


def test_call_llm_dispatches_xai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "x-key")

    mock = AsyncMock(return_value=_fake_completion("from xai"))
    with patch("mcp_core.llm.acompletion", mock):
        result = asyncio.run(llm.call_llm("hi"))

    assert result == "from xai"
    call_kwargs = mock.call_args.kwargs
    assert call_kwargs["model"] == f"xai/{llm._DEFAULT_MODELS['xai']}"


def test_call_llm_passes_api_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_API_BASE flows through to acompletion as api_base."""
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("LLM_API_BASE", "https://proxy.example/v1")

    mock = AsyncMock(return_value=_fake_completion("ok"))
    with patch("mcp_core.llm.acompletion", mock):
        asyncio.run(llm.call_llm("hi"))

    assert mock.call_args.kwargs["api_base"] == "https://proxy.example/v1"


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_call_llm_explicit_provider_override_skips_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``provider="openai"`` must dispatch to OpenAI even when Gemini is detected."""
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")

    mock = AsyncMock(return_value=_fake_completion("from openai"))
    with patch("mcp_core.llm.acompletion", mock):
        result = asyncio.run(llm.call_llm("hi", provider="openai"))

    assert result == "from openai"
    call_kwargs = mock.call_args.kwargs
    assert call_kwargs["model"].startswith("openai/")


def test_call_llm_uses_env_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("LLM_MODELS", "gemini=gemini-3-flash-from-env")

    mock = AsyncMock(return_value=_fake_completion("ok"))
    with patch("mcp_core.llm.acompletion", mock):
        asyncio.run(llm.call_llm("hi"))

    call_kwargs = mock.call_args.kwargs
    assert call_kwargs["model"] == "gemini/gemini-3-flash-from-env"
