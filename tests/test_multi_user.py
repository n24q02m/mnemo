"""HTTP multi-user credential-wiring tests.

Covers the per-request ``_current_sub`` contextvar that lets tool handlers
resolve credentials from ``$MNEMO_DATA_DIR/subs/<sub>/config.json`` instead
of the shared process env. Stdio + single-user HTTP must keep the existing
env-driven flow untouched.

Spec: ``~/projects/.superpower/mcp-core/specs/2026-05-01-stdio-pure-http-multiuser.md`` §4.2.
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _reset_current_sub():
    """Make sure ``_current_sub`` is ``None`` before/after every test.

    Pytest reuses the same event loop / module-level contextvar across tests.
    Failing to reset would leak a sub from one test into the next and mask
    isolation bugs.
    """
    from mnemo_mcp.credential_state import _current_sub

    token = _current_sub.set(None)
    try:
        yield
    finally:
        _current_sub.reset(token)


def test_stdio_mode_unchanged(tmp_path, monkeypatch):
    """Stdio mode (no ``_current_sub``, no ``PUBLIC_URL``): credentials come
    from ``os.environ`` filtered to ``CLOUD_KEYS``. Per-sub config files
    must NOT bleed into the response."""
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    # Pre-populate a per-sub config that should be invisible in stdio mode.
    from mnemo_mcp.credential_state import (
        CLOUD_KEYS,
        credentials_for_current_request,
        store_for_sub,
    )

    store_for_sub("ghost", {"JINA_AI_API_KEY": "ghost-key"})

    # Clear all CLOUD_KEYS from env then set just one, to verify filtering.
    for key in CLOUD_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "stdio-key")
    # Random unrelated env var must NOT appear in the result.
    monkeypatch.setenv("MNEMO_UNRELATED", "should-not-leak")

    creds = credentials_for_current_request()

    assert creds == {"OPENAI_API_KEY": "stdio-key"}


def test_http_sub_a_isolation(tmp_path, monkeypatch):
    """Sub A's request resolves Sub A's per-sub config, not env, not Sub B."""
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import (
        _current_sub,
        credentials_for_current_request,
        store_for_sub,
    )

    store_for_sub("alice", {"JINA_AI_API_KEY": "alice-key"})
    store_for_sub("bob", {"JINA_AI_API_KEY": "bob-key"})

    # Even if env has a different key, multi-user resolution ignores env.
    monkeypatch.setenv("JINA_AI_API_KEY", "env-must-be-ignored")

    token = _current_sub.set("alice")
    try:
        assert credentials_for_current_request() == {"JINA_AI_API_KEY": "alice-key"}
    finally:
        _current_sub.reset(token)


def test_http_sub_b_no_bleed(tmp_path, monkeypatch):
    """Sub B's request must never see Sub A's credentials."""
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import (
        _current_sub,
        credentials_for_current_request,
        store_for_sub,
    )

    store_for_sub("alice", {"JINA_AI_API_KEY": "alice-key"})
    store_for_sub("bob", {"OPENAI_API_KEY": "bob-key"})

    token = _current_sub.set("bob")
    try:
        creds = credentials_for_current_request()
    finally:
        _current_sub.reset(token)

    assert creds == {"OPENAI_API_KEY": "bob-key"}
    assert "JINA_AI_API_KEY" not in creds


def test_http_no_sub_returns_empty(tmp_path, monkeypatch):
    """Sub set but no per-sub config persisted yet: empty dict, no crash."""
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import _current_sub, credentials_for_current_request

    # Clean env so the contextvar branch is the only relevant path.
    for k in ("JINA_AI_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "COHERE_API_KEY"):
        monkeypatch.delenv(k, raising=False)

    token = _current_sub.set("never-onboarded")
    try:
        assert credentials_for_current_request() == {}
    finally:
        _current_sub.reset(token)


def test_concurrent_subs_isolation(tmp_path, monkeypatch):
    """Two concurrent ``asyncio`` tasks each set their own sub; resolution
    inside each task must yield that task's sub. Verifies the contextvar
    semantics (per-task copy on ``create_task``)."""
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import (
        _current_sub,
        credentials_for_current_request,
        store_for_sub,
    )

    store_for_sub("alice", {"JINA_AI_API_KEY": "alice-key"})
    store_for_sub("bob", {"OPENAI_API_KEY": "bob-key"})

    async def _request_for(sub: str) -> dict[str, str]:
        token = _current_sub.set(sub)
        try:
            # Yield to the loop so the two tasks actually interleave.
            await asyncio.sleep(0)
            return credentials_for_current_request()
        finally:
            _current_sub.reset(token)

    async def _runner() -> tuple[dict[str, str], dict[str, str]]:
        a = asyncio.create_task(_request_for("alice"))
        b = asyncio.create_task(_request_for("bob"))
        return await a, await b

    alice_creds, bob_creds = asyncio.run(_runner())

    assert alice_creds == {"JINA_AI_API_KEY": "alice-key"}
    assert bob_creds == {"OPENAI_API_KEY": "bob-key"}


def test_per_request_sub_scope_callback(tmp_path, monkeypatch):
    """The auth_scope middleware (closure built inside ``run_http``) must
    set the contextvar from ``claims['sub']``, await ``next_``, and reset
    on exit. We replicate the closure here against the public contextvar
    helpers since the closure itself is constructed at server start."""
    monkeypatch.setenv("MNEMO_DATA_DIR", str(tmp_path))
    from mnemo_mcp.credential_state import _current_sub, get_current_sub

    seen: list[str | None] = []

    async def _per_request_sub_scope(claims: dict, next_):
        token = _current_sub.set(claims.get("sub"))
        try:
            await next_()
        finally:
            _current_sub.reset(token)

    async def _next() -> None:
        seen.append(get_current_sub())

    async def _runner() -> None:
        # Before the middleware runs, sub must be unset.
        assert get_current_sub() is None
        await _per_request_sub_scope({"sub": "carol"}, _next)
        # After the middleware exits, the contextvar must be reset.
        assert get_current_sub() is None

    asyncio.run(_runner())

    assert seen == ["carol"]
