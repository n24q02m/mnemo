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
from unittest.mock import MagicMock, patch

import pytest

from mnemo_mcp import llm

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
    """Explicit but unsupported provider must not silently dispatch."""
    with patch.object(llm.logger, "warning") as warn:
        result = asyncio.run(llm.call_llm("hello", provider="bogus"))
    assert result is None
    assert warn.called


# ---------------------------------------------------------------------------
# call_llm — per-provider dispatch
# ---------------------------------------------------------------------------


def _install_fake_gemini() -> tuple[MagicMock, SimpleNamespace]:
    """Install fake ``google.genai`` modules into sys.modules and return handles.

    ``from X import Y`` resolves Y as an attribute of X *after* the import
    machinery loads X, so the SimpleNamespace standing in for ``google.genai``
    must expose ``types`` as an attribute too.
    """
    fake_response = SimpleNamespace(text="from gemini")
    fake_models = SimpleNamespace(
        generate_content=MagicMock(return_value=fake_response)
    )
    fake_client_cls = MagicMock(return_value=SimpleNamespace(models=fake_models))
    fake_types = SimpleNamespace(
        GenerateContentConfig=lambda **kw: SimpleNamespace(**kw)
    )
    fake_genai = SimpleNamespace(Client=fake_client_cls, types=fake_types)
    fake_google = SimpleNamespace(genai=fake_genai)

    return fake_client_cls, SimpleNamespace(
        google=fake_google,
        genai=fake_genai,
        types=fake_types,
        models=fake_models,
    )


def test_call_llm_dispatches_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")

    fake_client_cls, fakes = _install_fake_gemini()

    with patch.dict(
        "sys.modules",
        {
            "google": fakes.google,
            "google.genai": fakes.genai,
            "google.genai.types": fakes.types,
        },
    ):
        result = asyncio.run(llm.call_llm("hi"))

    assert result == "from gemini"
    fake_client_cls.assert_called_once_with(api_key="g-key")
    call_kwargs = fakes.models.generate_content.call_args.kwargs
    assert call_kwargs["contents"] == "hi"
    assert call_kwargs["model"] == llm._DEFAULT_MODELS["gemini"]


def test_call_llm_dispatches_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")

    fake_message = SimpleNamespace(content="from openai")
    fake_choice = SimpleNamespace(message=fake_message)
    fake_response = SimpleNamespace(choices=[fake_choice])
    fake_completions = SimpleNamespace(create=MagicMock(return_value=fake_response))
    fake_chat = SimpleNamespace(completions=fake_completions)
    fake_client = SimpleNamespace(chat=fake_chat)
    fake_openai_cls = MagicMock(return_value=fake_client)
    fake_openai = SimpleNamespace(OpenAI=fake_openai_cls)

    with patch.dict("sys.modules", {"openai": fake_openai}):
        result = asyncio.run(
            llm.call_llm("hi", model="gpt-test", temperature=0.2, max_tokens=42)
        )

    assert result == "from openai"
    fake_openai_cls.assert_called_once_with(api_key="o-key")
    call_kwargs = fake_completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-test"
    assert call_kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["max_tokens"] == 42


def test_call_llm_dispatches_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-key")

    fake_part = SimpleNamespace(text="from anthropic")
    fake_message = SimpleNamespace(content=[fake_part])
    fake_messages = SimpleNamespace(create=MagicMock(return_value=fake_message))
    fake_client = SimpleNamespace(messages=fake_messages)
    fake_anthropic_cls = MagicMock(return_value=fake_client)
    fake_anthropic = SimpleNamespace(Anthropic=fake_anthropic_cls)

    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        result = asyncio.run(llm.call_llm("hi"))

    assert result == "from anthropic"
    fake_anthropic_cls.assert_called_once_with(api_key="a-key")
    call_kwargs = fake_messages.create.call_args.kwargs
    assert call_kwargs["model"] == llm._DEFAULT_MODELS["anthropic"]
    assert call_kwargs["messages"] == [{"role": "user", "content": "hi"}]


def test_call_llm_dispatches_xai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "x-key")

    fake_message = SimpleNamespace(content="from xai")
    fake_choice = SimpleNamespace(message=fake_message)
    fake_response = SimpleNamespace(choices=[fake_choice])
    fake_completions = SimpleNamespace(create=MagicMock(return_value=fake_response))
    fake_chat = SimpleNamespace(completions=fake_completions)
    fake_client = SimpleNamespace(chat=fake_chat)
    fake_openai_cls = MagicMock(return_value=fake_client)
    fake_openai = SimpleNamespace(OpenAI=fake_openai_cls)

    with patch.dict("sys.modules", {"openai": fake_openai}):
        result = asyncio.run(llm.call_llm("hi"))

    assert result == "from xai"
    fake_openai_cls.assert_called_once_with(
        api_key="x-key", base_url="https://api.x.ai/v1"
    )
    call_kwargs = fake_completions.create.call_args.kwargs
    assert call_kwargs["model"] == llm._DEFAULT_MODELS["xai"]


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_call_llm_explicit_provider_override_skips_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``provider="openai"`` must dispatch to OpenAI even when Gemini is detected."""
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")

    fake_message = SimpleNamespace(content="from openai")
    fake_choice = SimpleNamespace(message=fake_message)
    fake_response = SimpleNamespace(choices=[fake_choice])
    fake_completions = SimpleNamespace(create=MagicMock(return_value=fake_response))
    fake_chat = SimpleNamespace(completions=fake_completions)
    fake_client = SimpleNamespace(chat=fake_chat)
    fake_openai_cls = MagicMock(return_value=fake_client)
    fake_openai = SimpleNamespace(OpenAI=fake_openai_cls)

    with patch.dict("sys.modules", {"openai": fake_openai}):
        result = asyncio.run(llm.call_llm("hi", provider="openai"))

    assert result == "from openai"
    fake_openai_cls.assert_called_once_with(api_key="o-key")


def test_call_llm_uses_env_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("LLM_MODELS", "gemini=gemini-3-flash-from-env")

    _, fakes = _install_fake_gemini()

    with patch.dict(
        "sys.modules",
        {
            "google": fakes.google,
            "google.genai": fakes.genai,
            "google.genai.types": fakes.types,
        },
    ):
        asyncio.run(llm.call_llm("hi"))

    call_kwargs = fakes.models.generate_content.call_args.kwargs
    assert call_kwargs["model"] == "gemini-3-flash-from-env"
