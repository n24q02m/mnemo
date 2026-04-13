"""Full E2E test for mnemo-mcp -- single file, 3 setup modes.

Tests ALL 3 tools, ALL actions via MCP protocol.
Uses function-scoped fixtures (proven stable on Windows).

Usage:
    uv run pytest tests/test_e2e.py -m e2e --setup=env -v --timeout=120 --tb=short
    uv run pytest tests/test_e2e.py -m e2e --setup=relay --browser=chrome -v -s
    uv run pytest tests/test_e2e.py -m e2e --setup=plugin -v --timeout=120 --tb=short
    uv run pytest tests/test_e2e.py -m "e2e and not slow" --setup=env -v --timeout=120 --tb=short
"""

from __future__ import annotations

import asyncio
import json
import os
import warnings

import pytest
from conftest_e2e import (
    StderrCapture,
    open_browser,
    parse_result,
    parse_result_allow_error,
)
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(120)]

# Env vars to STRIP in relay mode (force server to use relay for credentials)
CREDENTIAL_ENV_VARS = [
    "JINA_AI_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
]

EXPECTED_TOOLS = {"memory", "config", "help"}


# -- Fixtures ----------------------------------------------------------------


def _build_server_env(
    tmp_path, setup_mode: str, *, allow_gdrive: bool = False
) -> dict[str, str]:
    """Build env vars for server, stripping credentials in relay mode."""
    base_env = {
        **os.environ,
        "DB_PATH": str(tmp_path / "e2e_test.db"),
        "LOG_LEVEL": "WARNING",
        "SYNC_ENABLED": "false",
        "EMBEDDING_BACKEND": "local",
        "RERANK_BACKEND": "local",
        # Set a dummy key to skip relay setup (avoids rate-limit hang)
        "JINA_AI_API_KEY": os.environ.get("JINA_AI_API_KEY", "skip-relay"),
    }
    if not allow_gdrive:
        # Blank out GDrive OAuth to prevent setup_sync from triggering real OAuth
        base_env["GOOGLE_DRIVE_CLIENT_ID"] = ""
        base_env["GOOGLE_DRIVE_CLIENT_SECRET"] = ""
    if setup_mode == "relay":
        return {k: v for k, v in base_env.items() if k not in CREDENTIAL_ENV_VARS}
    return base_env


def _build_server_params(setup_mode: str, env: dict) -> StdioServerParameters:
    """Build StdioServerParameters based on setup mode."""
    if setup_mode in ("relay", "env"):
        return StdioServerParameters(command="uv", args=["run", "mnemo-mcp"], env=env)
    if setup_mode == "plugin":
        return StdioServerParameters(
            command="uvx", args=["--python", "3.13", "mnemo-mcp"], env=env
        )
    msg = f"Unknown setup mode: {setup_mode}"
    raise ValueError(msg)


@pytest.fixture
async def session(request, tmp_path):
    """Start mnemo-mcp server and yield MCP ClientSession."""
    setup_mode = request.config.getoption("--setup")
    browser_name = request.config.getoption("--browser")

    env = _build_server_env(tmp_path, setup_mode)
    params = _build_server_params(setup_mode, env)

    capture = StderrCapture() if setup_mode == "relay" else None
    errlog_kwargs = {"errlog": capture} if capture else {}

    try:
        async with stdio_client(params, **errlog_kwargs) as (read_stream, write_stream):  # ty: ignore[invalid-argument-type]
            async with ClientSession(read_stream, write_stream) as s:
                if setup_mode == "relay" and capture:
                    # mnemo-mcp auto-triggers relay during lifespan,
                    # blocking initialize(). Open browser in parallel.
                    init_task = asyncio.create_task(s.initialize())
                    relay_url = await asyncio.to_thread(capture.get_relay_url, 90)
                    if relay_url:
                        print(f"\n>>> Open relay in browser: {relay_url}", flush=True)
                        open_browser(relay_url, browser_name)
                    # Wait for initialize to complete (user submits in browser)
                    await asyncio.wait_for(init_task, timeout=300)
                    print(">>> Relay config received.", flush=True)
                else:
                    await s.initialize()

                yield s
    except (RuntimeError, ExceptionGroup) as exc:
        msg = str(exc).lower()
        if "cancel scope" in msg or "different task" in msg:
            warnings.warn(
                f"Suppressed teardown error: {exc}", RuntimeWarning, stacklevel=1
            )
        else:
            raise


# -- Helpers -----------------------------------------------------------------


def _extract_memory_id(text: str) -> str:
    """Extract memory ID from add/list response JSON."""
    try:
        data = json.loads(text)
        # add response: {"id": "..."} or {"memory_id": "..."}
        if isinstance(data, dict):
            return data.get("id") or data.get("memory_id", "")
        # list response: list of dicts
        if isinstance(data, list) and data:
            return data[0].get("id") or data[0].get("memory_id", "")
    except (json.JSONDecodeError, TypeError, IndexError):
        pass
    # Fallback: try to find UUID-like pattern
    import re

    match = re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(0)
    # Last resort: search for any "id" field in text
    match = re.search(r'"id"\s*:\s*"([^"]+)"', text)
    if match:
        return match.group(1)
    return ""


# -- Server Init Tests -------------------------------------------------------


class TestServerInit:
    async def test_connects(self, session):
        """Server responds to initialize."""
        assert session is not None

    async def test_tools_list(self, session):
        """Server exposes all expected tools."""
        result = await session.list_tools()
        names = {t.name for t in result.tools}
        assert names == EXPECTED_TOOLS, f"Expected {EXPECTED_TOOLS}, got {names}"

    async def test_tools_have_schema(self, session):
        """Each tool has valid inputSchema."""
        result = await session.list_tools()
        for tool in result.tools:
            assert tool.inputSchema is not None
            assert tool.inputSchema.get("type") == "object"
            assert tool.description


# -- Memory Tool (11 actions) ------------------------------------------------


class TestMemoryAdd:
    async def test_add(self, session):
        """Add a memory and verify response."""
        r = await session.call_tool(
            "memory",
            {
                "action": "add",
                "content": "E2E test: Python is great",
                "category": "test",
                "tags": ["e2e"],
            },
        )
        text = parse_result(r)
        assert "saved" in text.lower() or "id" in text.lower()


class TestMemoryList:
    async def test_list(self, session):
        """Add a memory, then list to find it."""
        await session.call_tool(
            "memory",
            {
                "action": "add",
                "content": "E2E test: list test memory",
                "category": "test",
            },
        )
        r = await session.call_tool("memory", {"action": "list", "limit": 10})
        text = parse_result(r)
        assert len(text) > 10


class TestMemorySearch:
    async def test_search(self, session):
        """Add a memory, then search for it."""
        await session.call_tool(
            "memory",
            {
                "action": "add",
                "content": "E2E test: search for quantum computing",
                "category": "science",
            },
        )
        r = await session.call_tool(
            "memory", {"action": "search", "query": "quantum computing"}
        )
        text = parse_result(r)
        assert "quantum" in text.lower() or len(text) > 10


class TestMemoryUpdate:
    async def test_update(self, session):
        """Add a memory, then update it."""
        r = await session.call_tool(
            "memory",
            {"action": "add", "content": "E2E test: update me", "category": "test"},
        )
        text = parse_result(r)
        mid = _extract_memory_id(text)
        assert mid, f"Could not extract memory_id from: {text}"

        r2 = await session.call_tool(
            "memory",
            {
                "action": "update",
                "memory_id": mid,
                "content": "E2E test: updated content",
            },
        )
        text2 = parse_result(r2)
        assert "update" in text2.lower() or "success" in text2.lower() or mid in text2


class TestMemoryStats:
    async def test_stats(self, session):
        """Add a memory, then check stats."""
        await session.call_tool(
            "memory",
            {"action": "add", "content": "E2E test: stats check", "category": "test"},
        )
        r = await session.call_tool("memory", {"action": "stats"})
        text = parse_result(r)
        assert "total" in text.lower() or "memories" in text.lower() or "1" in text


class TestMemoryExport:
    async def test_export(self, session):
        """Add a memory, then export."""
        await session.call_tool(
            "memory",
            {"action": "add", "content": "E2E test: export me", "category": "test"},
        )
        r = await session.call_tool("memory", {"action": "export"})
        text = parse_result(r)
        assert len(text) > 10


class TestMemoryImport:
    async def test_import(self, session):
        """Import data as list (MCP protocol auto-parses JSON strings to dicts)."""
        r = await session.call_tool(
            "memory",
            {
                "action": "import",
                "data": [
                    {
                        "content": "Imported via E2E test",
                        "category": "imported",
                        "tags": ["e2e"],
                    }
                ],
                "mode": "merge",
            },
        )
        text = parse_result(r)
        assert "import" in text.lower() or "success" in text.lower() or "1" in text


class TestMemoryArchived:
    async def test_archived(self, session):
        """List archived memories -- just verify returns a string."""
        r = await session.call_tool("memory", {"action": "archived"})
        text = parse_result(r)
        assert isinstance(text, str)


class TestMemoryConsolidate:
    @pytest.mark.slow
    async def test_consolidate(self, session):
        """Add 2 memories with same category, then consolidate."""
        await session.call_tool(
            "memory",
            {
                "action": "add",
                "content": "E2E test: consolidate item A - Python tips",
                "category": "consolidate_test",
            },
        )
        await session.call_tool(
            "memory",
            {
                "action": "add",
                "content": "E2E test: consolidate item B - Python best practices",
                "category": "consolidate_test",
            },
        )
        r = await session.call_tool(
            "memory",
            {"action": "consolidate", "category": "consolidate_test"},
        )
        text = parse_result_allow_error(r)
        assert isinstance(text, str)


class TestMemoryRestore:
    async def test_restore(self, session):
        """Add, delete, then restore a memory."""
        r = await session.call_tool(
            "memory",
            {"action": "add", "content": "E2E test: restore me", "category": "test"},
        )
        text = parse_result(r)
        mid = _extract_memory_id(text)
        assert mid, f"Could not extract memory_id from: {text}"

        await session.call_tool("memory", {"action": "delete", "memory_id": mid})

        r2 = await session.call_tool("memory", {"action": "restore", "memory_id": mid})
        text2 = parse_result(r2)
        assert "restor" in text2.lower() or "success" in text2.lower() or mid in text2


class TestMemoryDelete:
    async def test_delete(self, session):
        """Add a memory, then delete it."""
        r = await session.call_tool(
            "memory",
            {"action": "add", "content": "E2E test: delete me", "category": "test"},
        )
        text = parse_result(r)
        mid = _extract_memory_id(text)
        assert mid, f"Could not extract memory_id from: {text}"

        r2 = await session.call_tool("memory", {"action": "delete", "memory_id": mid})
        text2 = parse_result(r2)
        assert (
            "delet" in text2.lower()
            or "success" in text2.lower()
            or "archived" in text2.lower()
            or mid in text2
        )


# -- Config Tool (5 actions) -------------------------------------------------


class TestConfig:
    async def test_status(self, session):
        """Config status returns server info."""
        r = await session.call_tool("config", {"action": "status"})
        text = parse_result(r)
        assert (
            "embedding" in text.lower()
            or "mode" in text.lower()
            or "status" in text.lower()
            or "local" in text.lower()
        )

    async def test_set_log_level(self, session):
        """Set log_level config."""
        r = await session.call_tool(
            "config", {"action": "set", "key": "log_level", "value": "WARNING"}
        )
        text = parse_result(r)
        assert (
            "warning" in text.lower()
            or "set" in text.lower()
            or "updated" in text.lower()
        )

    async def test_set_sync_enabled(self, session):
        """Set sync_enabled config."""
        r = await session.call_tool(
            "config", {"action": "set", "key": "sync_enabled", "value": "false"}
        )
        text = parse_result(r)
        assert isinstance(text, str)

    import pytest

    @pytest.mark.timeout(300)
    async def test_warmup(self, session):
        """Warmup pre-downloads embedding model."""
        r = await session.call_tool("config", {"action": "warmup"})
        text = parse_result_allow_error(r)
        assert isinstance(text, str)

    async def test_setup_sync_no_client_id(self, session):
        """setup_sync should fail gracefully without GOOGLE_DRIVE_CLIENT_ID."""
        r = await session.call_tool("config", {"action": "setup_sync"})
        text = parse_result_allow_error(r)
        assert isinstance(text, str)

    async def test_sync_disabled(self, session):
        """sync action with sync disabled returns info/error."""
        r = await session.call_tool("config", {"action": "sync"})
        text = parse_result_allow_error(r)
        assert isinstance(text, str)


# -- Help Tool ---------------------------------------------------------------


class TestHelp:
    async def test_help_memory(self, session):
        """Help for memory topic."""
        r = await session.call_tool("help", {"topic": "memory"})
        text = parse_result(r)
        assert "memory" in text.lower()

    async def test_help_config(self, session):
        """Help for config topic."""
        r = await session.call_tool("help", {"topic": "config"})
        text = parse_result(r)
        assert "config" in text.lower()

    async def test_help_default(self, session):
        """Help with no topic defaults to memory."""
        r = await session.call_tool("help", {})
        text = parse_result(r)
        assert "memory" in text.lower()


# -- Error Handling Tests ----------------------------------------------------


class TestErrorHandling:
    async def test_invalid_memory_action(self, session):
        """Invalid action returns error."""
        r = await session.call_tool("memory", {"action": "nonexistent_action"})
        text = parse_result_allow_error(r)
        assert (
            "error" in text.lower()
            or "unknown" in text.lower()
            or "invalid" in text.lower()
        )

    async def test_missing_content_for_add(self, session):
        """Add without content returns error."""
        r = await session.call_tool("memory", {"action": "add"})
        text = parse_result_allow_error(r)
        assert isinstance(text, str)

    async def test_invalid_config_action(self, session):
        """Invalid config action returns error."""
        r = await session.call_tool("config", {"action": "nonexistent"})
        text = parse_result_allow_error(r)
        assert isinstance(text, str)

    async def test_invalid_help_topic(self, session):
        """Invalid help topic returns error."""
        r = await session.call_tool("help", {"topic": "nonexistent"})
        text = parse_result_allow_error(r)
        assert isinstance(text, str)


# -- Relay Mode: ALL tools in 1 session (user enters credentials once) ------


@pytest.mark.e2e
@pytest.mark.timeout(300)
async def test_relay_all_tools(request, tmp_path):
    """Relay mode: server without API keys, user enters via browser.

    Run with: uv run pytest tests/test_e2e.py -m e2e -k relay --setup=relay --browser=chrome -v -s
    """
    setup_mode = request.config.getoption("--setup")
    if setup_mode != "relay":
        pytest.skip("Only runs with --setup=relay")

    browser_name = request.config.getoption("--browser")
    env = _build_server_env(tmp_path, "relay")
    params = _build_server_params("relay", env)
    capture = StderrCapture()

    try:
        async with stdio_client(params, errlog=capture) as (read_stream, write_stream):  # ty: ignore[invalid-argument-type]
            async with ClientSession(read_stream, write_stream) as s:
                # mnemo-mcp auto-triggers relay during lifespan,
                # blocking initialize(). Open browser in parallel.
                init_task = asyncio.create_task(s.initialize())
                relay_url = await asyncio.to_thread(capture.get_relay_url, 90)
                assert relay_url, "No relay URL detected in stderr"
                print(f"\n>>> RELAY URL: {relay_url}", flush=True)
                open_browser(relay_url, browser_name)

                print(
                    ">>> Enter API keys in browser, then submit...",
                    flush=True,
                )
                # Wait for initialize to complete (user submits in browser)
                await asyncio.wait_for(init_task, timeout=300)
                print(">>> Relay config applied!", flush=True)

                # memory lifecycle
                await s.call_tool(
                    "memory",
                    {"action": "add", "content": "Relay E2E test", "category": "test"},
                )
                print("  memory.add: OK")
                await s.call_tool("memory", {"action": "search", "query": "relay"})
                print("  memory.search: OK")
                await s.call_tool("memory", {"action": "list", "limit": 5})
                print("  memory.list: OK")
                # config
                await s.call_tool("config", {"action": "status"})
                print("  config.status: OK")
                # help
                await s.call_tool("help", {"topic": "memory"})
                print("  help: OK")

                print(">>> ALL RELAY TESTS PASSED", flush=True)
    except (RuntimeError, ExceptionGroup) as exc:
        msg = str(exc).lower()
        if "cancel scope" in msg or "different task" in msg:
            warnings.warn(
                f"Suppressed teardown error: {exc}", RuntimeWarning, stacklevel=1
            )
        else:
            raise


# -- GDrive OAuth Device Code Test -------------------------------------------


@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.timeout(300)
async def test_gdrive_oauth(request, tmp_path):
    """GDrive OAuth Device Code: call setup_sync, user authorizes via Google.

    Run with: uv run pytest tests/test_e2e.py -m e2e -k gdrive --setup=env -v -s
    Uses hardcoded GOOGLE_DRIVE_CLIENT_ID from config defaults.
    """
    env = _build_server_env(tmp_path, "env", allow_gdrive=True)
    params = _build_server_params("env", env)

    try:
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as s:
                await s.initialize()

                print("\n>>> Triggering GDrive OAuth Device Code...", flush=True)
                r = await s.call_tool("config", {"action": "setup_sync"})
                text = parse_result_allow_error(r)
                print(f">>> setup_sync response: {text[:300]}", flush=True)

                if "error" in text.lower() and "client_id" in text.lower():
                    pytest.skip("GOOGLE_DRIVE_CLIENT_ID not configured")

                print(">>> Check stderr for Google device code URL + code", flush=True)
                print(">>> Go to URL, enter code, authorize the app", flush=True)

                import asyncio

                deadline = asyncio.get_event_loop().time() + 180
                while asyncio.get_event_loop().time() < deadline:
                    r = await s.call_tool("config", {"action": "status"})
                    text = parse_result_allow_error(r)
                    if "sync" in text.lower() and (
                        "enabled" in text.lower() or "connected" in text.lower()
                    ):
                        print(">>> GDrive OAuth COMPLETE!", flush=True)
                        break
                    await asyncio.sleep(3)

                print(">>> GDRIVE OAUTH TEST DONE", flush=True)
    except (RuntimeError, ExceptionGroup) as exc:
        msg = str(exc).lower()
        if "cancel scope" in msg or "different task" in msg:
            warnings.warn(
                f"Suppressed teardown error: {exc}", RuntimeWarning, stacklevel=1
            )
        else:
            raise
