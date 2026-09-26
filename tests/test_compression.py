"""Tests for the Phase 2 LLM-driven compression pipeline.

Covers:
- ``compress`` returns compressed text when a provider is available.
- Graceful skip when no provider env vars are set.
- ``COMPRESSION_ENABLED=false`` env override skips even with a provider.
- Empty / whitespace-only LLM response degrades to graceful skip.
- Token counting via tiktoken cl100k_base is reflected in ``tokens_in/out``.
- ``capture()`` wires compression through ``add_with_context_type``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mnemo_mcp.capture import capture
from mnemo_mcp.compression import COMPRESSION_PROMPT, compress, count_tokens
from mnemo_mcp.db import MemoryDB

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_db(tmp_path: Path) -> Iterator[MemoryDB]:
    db = MemoryDB(tmp_path / "memories.db", embedding_dims=0)
    yield db
    db.close()


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip all LLM provider env vars so the test starts from a clean slate."""
    for env in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
        "COMPRESSION_ENABLED",
        "COMPRESSION_PROVIDER",
        "COMPRESSION_MODEL",
        "DEDUP_THRESHOLD",
    ):
        monkeypatch.delenv(env, raising=False)


# ---------------------------------------------------------------------------
# Direct compress() tests
# ---------------------------------------------------------------------------


SAMPLE_TURN = (
    "User said: I prefer dark mode in VS Code, the editor at /home/me/.config/Code. "
    "Decision: switch to Catppuccin Mocha theme on 2026-05-10. "
    "API key for Gemini lives in env var GEMINI_API_KEY (never commit). "
    "Project budget: $1500 for tooling. Email me at user@example.com when done."
)


async def test_compress_graceful_skip_when_no_provider() -> None:
    """No provider env -> returns original text + compressed=False."""
    result = await compress("any text")
    assert result["compressed"] is False
    assert result["text"] == "any text"
    assert result["text_raw"] is None
    assert result["compression_provider"] is None
    assert result["compression_model"] is None
    assert result["tokens_in"] == result["tokens_out"]


def _configure_chat_cell(monkeypatch: pytest.MonkeyPatch, model="test-chat-model"):
    """Make the fake-HOME environment look like a configured chat cell."""
    monkeypatch.setattr("mnemo_mcp.runtime.cell_configured", lambda task: True)
    monkeypatch.setattr(
        "mnemo_mcp.runtime.model_cell", lambda task: SimpleNamespace(model=model)
    )


async def test_compress_returns_compressed_text_when_provider_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the chat cell configured + mocked call_llm, compress rewrites text."""
    _configure_chat_cell(monkeypatch)

    short_compressed = (
        "User: dark mode VS Code (~/.config/Code). "
        "Decision 2026-05-10: Catppuccin Mocha. "
        "GEMINI_API_KEY in env. Budget $1500. Email user@example.com."
    )

    async def _fake_call(prompt, **kwargs):
        assert "<turn>" in prompt
        assert kwargs["temperature"] == 0.0
        return short_compressed

    with patch("mnemo_mcp.compression.call_llm", side_effect=_fake_call):
        result = await compress(SAMPLE_TURN)

    assert result["compressed"] is True
    assert result["text"] == short_compressed
    assert result["text_raw"] == SAMPLE_TURN
    assert result["compression_provider"] == "chat-cell"
    assert result["compression_model"] == "test-chat-model"
    assert result["tokens_out"] < result["tokens_in"]


async def test_compress_disabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """COMPRESSION_ENABLED=false skips the pipeline even with a key."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("COMPRESSION_ENABLED", "false")

    async def _should_not_be_called(*args, **kwargs):
        raise AssertionError("call_llm must not run when COMPRESSION_ENABLED=false")

    with patch("mnemo_mcp.compression.call_llm", side_effect=_should_not_be_called):
        result = await compress(SAMPLE_TURN)

    assert result["compressed"] is False
    assert result["text"] == SAMPLE_TURN
    assert result["text_raw"] is None


async def test_provider_model_args_ignored_cell_owns_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit provider/model args are accepted for compatibility but the
    chat cell owns dispatch -- they never reach call_llm."""
    _configure_chat_cell(monkeypatch)

    captured: dict = {}

    async def _fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        captured["kwargs"] = kwargs
        return "compressed"

    with patch("mnemo_mcp.compression.call_llm", side_effect=_fake_call):
        result = await compress("text", provider="openai", model="gpt-test")

    assert result["compression_provider"] == "chat-cell"
    assert "provider" not in captured["kwargs"]
    assert "model" not in captured["kwargs"]


async def test_compress_empty_response_degrades_to_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty / whitespace LLM response -> graceful skip path."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    async def _fake_call(prompt, provider, model, *, temperature, max_tokens):
        return "   "

    with patch("mnemo_mcp.compression.call_llm", side_effect=_fake_call):
        result = await compress("hello")

    assert result["compressed"] is False
    assert result["text"] == "hello"


async def test_compress_sdk_exception_degrades_to_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SDK raising mid-call must not bubble into the caller."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    async def _fake_call(prompt, provider, model, *, temperature, max_tokens):
        raise RuntimeError("simulated SDK failure")

    with patch("mnemo_mcp.compression.call_llm", side_effect=_fake_call):
        result = await compress("hello")

    assert result["compressed"] is False
    assert result["text"] == "hello"


def test_count_tokens_matches_encoder() -> None:
    """count_tokens uses cl100k_base; non-zero for non-empty text."""
    assert count_tokens("") == 0
    assert count_tokens("hello world") > 0
    # The compression prompt itself must be non-empty.
    assert "<turn>" in COMPRESSION_PROMPT


# ---------------------------------------------------------------------------
# capture() integration: compression columns reach the DB
# ---------------------------------------------------------------------------


async def test_capture_writes_compression_columns_when_provider_active(
    isolated_db: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_chat_cell(monkeypatch)

    async def _fake_call(prompt, **kwargs):
        return "tight summary keeping facts"

    with patch("mnemo_mcp.compression.call_llm", side_effect=_fake_call):
        result = await capture(
            isolated_db,
            text="long verbose original text with the same fact repeated x3",
            context_type="fact",
        )

    assert result["deduplicated"] is False
    assert result["compressed"] is True
    assert result["compression_provider"] == "chat-cell"

    row = isolated_db._conn.execute(
        "SELECT content, text_raw, compressed, compression_provider "
        "FROM memories WHERE id = ?",
        (result["memory_id"],),
    ).fetchone()
    assert row["content"] == "tight summary keeping facts"
    assert (
        row["text_raw"] == "long verbose original text with the same fact repeated x3"
    )
    assert row["compressed"] == 1
    assert row["compression_provider"] == "chat-cell"


async def test_capture_skips_compression_when_no_provider(
    isolated_db: MemoryDB,
) -> None:
    """No provider -> row stored as-is, columns NULL/0."""
    result = await capture(
        isolated_db,
        text="hello world",
        context_type="conversation",
    )

    assert result["deduplicated"] is False
    assert result["compressed"] is False

    row = isolated_db._conn.execute(
        "SELECT content, text_raw, compressed, compression_provider "
        "FROM memories WHERE id = ?",
        (result["memory_id"],),
    ).fetchone()
    assert row["content"] == "hello world"
    assert row["text_raw"] is None
    assert row["compressed"] == 0
    assert row["compression_provider"] is None


async def test_capture_dedup_short_circuits_before_compression(
    isolated_db: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dedup hit must NOT call the LLM (cost + latency saving)."""
    # Phase 1: seed an existing memory.
    seeded = await capture(
        isolated_db,
        text="The quick brown fox jumps over the lazy dog",
        context_type="fact",
    )

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("DEDUP_THRESHOLD", "0.1")

    async def _should_not_run(*args, **kwargs):
        raise AssertionError("compression must not run on dedup hit")

    with patch("mnemo_mcp.compression.call_llm", side_effect=_should_not_run):
        result = await capture(
            isolated_db,
            text="The quick brown fox jumps over the lazy dog",
            context_type="fact",
        )

    assert result["deduplicated"] is True
    assert result["memory_id"] == seeded["memory_id"]
