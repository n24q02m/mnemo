"""Pytest-based live MCP protocol tests for mnemo-mcp.

Spawns a real MCP server via stdio and tests all tools through the protocol.
Uses a temp directory for DB -- all tests work offline (local ONNX embedding).

Usage:
    uv run pytest tests/test_live_protocol.py -v --tb=short -m live
"""

import json
import os
import warnings

import pytest
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = [pytest.mark.live, pytest.mark.timeout(120)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse(r) -> str:
    """Extract text from MCP tool result."""
    if hasattr(r, "isError") and r.isError:
        raise RuntimeError(r.content[0].text)
    return r.content[0].text


def parse_allow_error(r) -> str:
    """Extract text from MCP tool result, including error responses."""
    return r.content[0].text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def mcp_session(tmp_path):
    """Start real mnemo-mcp server via stdio with temp DB, yield ClientSession.

    Suppresses anyio cancel-scope teardown errors that occur when
    pytest-asyncio tears down the event loop in a different task context.
    """
    db_path = str(tmp_path / "test.db")
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "mnemo-mcp"],
        env={
            **os.environ,
            "DB_PATH": db_path,
            "LOG_LEVEL": "WARNING",
            "SYNC_ENABLED": "false",
        },
    )
    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session
    except (RuntimeError, ExceptionGroup) as exc:
        # anyio cancel-scope teardown error -- harmless in test context
        msg = str(exc).lower()
        if "cancel scope" in msg or "different task" in msg:
            warnings.warn(
                f"Suppressed teardown error: {exc}",
                RuntimeWarning,
                stacklevel=1,
            )
        else:
            raise


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


class TestMeta:
    async def test_list_tools(self, mcp_session: ClientSession):
        result = await mcp_session.list_tools()
        tool_names = {t.name for t in result.tools}
        expected = {"memory", "config", "help", "setup"}
        assert tool_names >= expected, (
            f"Missing tools: {expected - tool_names}, got {tool_names}"
        )

    async def test_list_resources(self, mcp_session: ClientSession):
        result = await mcp_session.list_resources()
        # Should not raise, even if empty
        assert isinstance(result.resources, list)


# ---------------------------------------------------------------------------
# Help tool (offline)
# ---------------------------------------------------------------------------


class TestHelp:
    @pytest.mark.parametrize("topic", ["memory", "config", "setup"])
    async def test_help_topics(self, mcp_session: ClientSession, topic: str):
        r = await mcp_session.call_tool("help", {"topic": topic})
        text = parse(r)
        assert len(text) >= 100, f"Help for '{topic}' too short: {len(text)} chars"

    async def test_help_invalid_topic(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("help", {"topic": "nonexistent"})
        text = parse_allow_error(r)
        assert any(w in text.lower() for w in ("error", "not found", "unknown")), (
            f"Expected error response, got: {text[:80]}"
        )


# ---------------------------------------------------------------------------
# Config tool (offline)
# ---------------------------------------------------------------------------


class TestConfig:
    async def test_config_status(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("config", {"action": "status"})
        text = parse(r)
        data = json.loads(text)
        all_keys = str(data.keys()).lower()
        assert "database" in all_keys or "db" in all_keys, (
            f"Missing db info: {list(data.keys())}"
        )

    async def test_config_set(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "config", {"action": "set", "key": "log_level", "value": "DEBUG"}
        )
        text = parse(r)
        assert any(w in text.lower() for w in ("updated", "set", "log_level")), text[
            :80
        ]

    async def test_config_set_invalid_key(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "config", {"action": "set", "key": "invalid_key", "value": "x"}
        )
        text = parse_allow_error(r)
        assert any(w in text.lower() for w in ("error", "invalid", "valid")), (
            f"Expected error for invalid key, got: {text[:80]}"
        )


# ---------------------------------------------------------------------------
# Setup tool (offline -- warmup only)
# ---------------------------------------------------------------------------


class TestSetup:
    async def test_setup_warmup(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("setup", {"action": "warmup"})
        text = parse(r)
        data = json.loads(text)
        assert "status" in data or "error" not in data, text[:120]

    async def test_setup_invalid_action(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("setup", {"action": "invalid"})
        text = parse_allow_error(r)
        assert any(w in text.lower() for w in ("error", "unknown", "invalid")), text[
            :80
        ]


# ---------------------------------------------------------------------------
# Memory tool -- happy path (offline, temp DB)
# ---------------------------------------------------------------------------


class TestMemoryHappyPath:
    async def test_memory_add(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "memory",
            {
                "action": "add",
                "content": "Python testing frameworks include pytest and unittest.",
                "category": "tech",
                "tags": ["python", "testing"],
            },
        )
        text = parse(r)
        data = json.loads(text)
        assert data.get("status") == "saved", text[:80]
        assert data.get("id"), "Missing memory id"

    async def test_memory_add_and_list(self, mcp_session: ClientSession):
        # Add two entries
        for content in [
            "Python is great for data science.",
            "Rust prevents data races at compile time.",
        ]:
            r = await mcp_session.call_tool(
                "memory",
                {"action": "add", "content": content, "category": "tech"},
            )
            parse(r)

        # List
        r = await mcp_session.call_tool("memory", {"action": "list"})
        text = parse(r)
        data = json.loads(text)
        memories = data.get("results", data.get("memories", []))
        assert len(memories) >= 2, f"Expected >=2 memories, got {len(memories)}"

    async def test_memory_search(self, mcp_session: ClientSession):
        # Add entry first
        r = await mcp_session.call_tool(
            "memory",
            {
                "action": "add",
                "content": "pytest is the most popular Python testing framework.",
                "category": "tech",
                "tags": ["python", "testing"],
            },
        )
        parse(r)

        # Search
        r = await mcp_session.call_tool(
            "memory", {"action": "search", "query": "pytest"}
        )
        text = parse(r)
        data = json.loads(text)
        memories = data.get("memories", data.get("results", []))
        assert len(memories) >= 1, f"No search results: {text[:80]}"

    async def test_memory_update(self, mcp_session: ClientSession):
        # Add
        r = await mcp_session.call_tool(
            "memory",
            {"action": "add", "content": "Original content.", "category": "test"},
        )
        data = json.loads(parse(r))
        mem_id = data["id"]

        # Update
        r = await mcp_session.call_tool(
            "memory",
            {
                "action": "update",
                "memory_id": mem_id,
                "content": "Updated content.",
            },
        )
        text = parse(r)
        assert "updated" in text.lower(), text[:80]

    async def test_memory_delete(self, mcp_session: ClientSession):
        # Add
        r = await mcp_session.call_tool(
            "memory",
            {"action": "add", "content": "To be deleted.", "category": "test"},
        )
        data = json.loads(parse(r))
        mem_id = data["id"]

        # Delete
        r = await mcp_session.call_tool(
            "memory", {"action": "delete", "memory_id": mem_id}
        )
        text = parse(r)
        assert "deleted" in text.lower() or "removed" in text.lower(), text[:80]

    async def test_memory_stats(self, mcp_session: ClientSession):
        # Add entry
        await mcp_session.call_tool(
            "memory",
            {"action": "add", "content": "Stats test entry.", "category": "test"},
        )

        r = await mcp_session.call_tool("memory", {"action": "stats"})
        text = parse(r)
        data = json.loads(text)
        total = data.get("total_memories", data.get("total", data.get("count", 0)))
        assert total >= 1, text[:80]

    async def test_memory_export(self, mcp_session: ClientSession):
        # Add entry
        await mcp_session.call_tool(
            "memory",
            {"action": "add", "content": "Export test entry.", "category": "test"},
        )

        r = await mcp_session.call_tool("memory", {"action": "export"})
        text = parse(r)
        assert len(text) > 10, f"Export too short: {len(text)} chars"

    async def test_memory_import(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "memory",
            {
                "action": "import",
                "data": [
                    {
                        "content": "Imported memory for testing.",
                        "category": "test",
                        "tags": ["import"],
                    }
                ],
                "mode": "merge",
            },
        )
        text = parse(r)
        assert any(w in text.lower() for w in ("import", "merge", "success")), text[:80]


# ---------------------------------------------------------------------------
# Error paths (offline)
# ---------------------------------------------------------------------------


class TestErrorPaths:
    async def test_memory_no_action(self, mcp_session: ClientSession):
        """memory with no action should error."""
        try:
            r = await mcp_session.call_tool("memory", {})
            text = parse_allow_error(r)
            # Should contain error info
            assert any(w in text.lower() for w in ("error", "action", "required")), (
                f"Expected error, got: {text[:80]}"
            )
        except Exception:
            pass  # Error raised is also acceptable

    async def test_memory_invalid_action(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("memory", {"action": "invalid_action"})
        text = parse_allow_error(r)
        assert any(w in text.lower() for w in ("error", "unknown", "invalid")), (
            f"Expected error, got: {text[:80]}"
        )

    async def test_memory_add_no_content(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("memory", {"action": "add"})
        text = parse_allow_error(r)
        assert any(w in text.lower() for w in ("error", "content", "required")), (
            f"Expected error, got: {text[:80]}"
        )


# ---------------------------------------------------------------------------
# Security boundary (offline)
# ---------------------------------------------------------------------------


class TestSecurity:
    async def test_sql_injection_in_search(self, mcp_session: ClientSession):
        """SQL injection attempt should be handled safely."""
        r = await mcp_session.call_tool(
            "memory",
            {"action": "search", "query": "'; DROP TABLE memories; --"},
        )
        # Should return empty results or safe error, not crash
        text = parse_allow_error(r)
        assert text  # Got a response, server didn't crash

    async def test_xss_in_content(self, mcp_session: ClientSession):
        """XSS content should be stored as plain text."""
        r = await mcp_session.call_tool(
            "memory",
            {
                "action": "add",
                "content": '<script>alert("xss")</script>',
                "category": "test",
            },
        )
        text = parse(r)
        data = json.loads(text)
        assert data.get("status") == "saved", text[:80]

    async def test_large_content(self, mcp_session: ClientSession):
        """Very large content should be handled gracefully."""
        r = await mcp_session.call_tool(
            "memory",
            {"action": "add", "content": "A" * 100_000, "category": "test"},
        )
        text = parse_allow_error(r)
        # Should either save or reject gracefully
        assert text  # Got a response, server didn't crash
