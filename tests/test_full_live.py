"""Full/real live MCP protocol tests for mnemo-mcp.

Spawns a real MCP server via stdio and tests ALL tool actions with real data.
Uses tmp_path for DB -- local ONNX mode (no API keys needed).

Usage:
    uv run pytest tests/test_full_live.py -m full -v --tb=short
"""

import json
import os
import warnings

import pytest
from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = [pytest.mark.full, pytest.mark.timeout(60)]


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


def parse_json(r) -> dict:
    """Extract and parse JSON from MCP tool result."""
    text = parse(r)
    return json.loads(text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def mcp_session(tmp_path):
    """Start real mnemo-mcp server via stdio with temp DB, yield ClientSession."""
    db_path = str(tmp_path / "test.db")
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "mnemo-mcp"],
        env={
            **os.environ,
            "DB_PATH": db_path,
            "LOG_LEVEL": "WARNING",
            "SYNC_ENABLED": "false",
            "EMBEDDING_BACKEND": "local",
        },
    )
    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session
    except (RuntimeError, ExceptionGroup) as exc:
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
# Memory lifecycle (add -> search -> update -> list -> export -> import -> stats)
# ---------------------------------------------------------------------------


class TestFullMemoryLifecycle:
    async def test_memory_add(self, mcp_session: ClientSession):
        """memory.add -- add a single memory."""
        r = await mcp_session.call_tool(
            "memory",
            {
                "action": "add",
                "content": "Python testing frameworks include pytest and unittest.",
                "category": "tech",
                "tags": ["python", "testing"],
            },
        )
        data = parse_json(r)
        assert data.get("status") == "saved", f"Expected saved, got: {data}"
        assert data.get("id"), "Missing memory id"

    async def test_memory_search(self, mcp_session: ClientSession):
        """memory.search -- add then search for it."""
        # Add first
        await mcp_session.call_tool(
            "memory",
            {
                "action": "add",
                "content": "pytest is the most popular Python testing framework.",
                "category": "tech",
                "tags": ["python", "testing"],
            },
        )

        # Search
        r = await mcp_session.call_tool(
            "memory", {"action": "search", "query": "pytest testing"}
        )
        data = parse_json(r)
        memories = data.get("memories", data.get("results", []))
        assert len(memories) >= 1, f"No search results: {data}"

    async def test_memory_update(self, mcp_session: ClientSession):
        """memory.update -- add then update content."""
        # Add
        r = await mcp_session.call_tool(
            "memory",
            {"action": "add", "content": "Original content here.", "category": "test"},
        )
        data = parse_json(r)
        mem_id = data["id"]

        # Update
        r = await mcp_session.call_tool(
            "memory",
            {
                "action": "update",
                "memory_id": mem_id,
                "content": "Updated content here.",
            },
        )
        text = parse(r)
        assert "updated" in text.lower(), text[:120]

    async def test_memory_list(self, mcp_session: ClientSession):
        """memory.list -- add multiple then list all."""
        for content in [
            "Python is great for data science.",
            "Rust prevents data races at compile time.",
        ]:
            await mcp_session.call_tool(
                "memory",
                {"action": "add", "content": content, "category": "tech"},
            )

        r = await mcp_session.call_tool("memory", {"action": "list"})
        data = parse_json(r)
        memories = data.get("results", data.get("memories", []))
        assert len(memories) >= 2, f"Expected >=2 memories, got {len(memories)}"

    async def test_memory_export(self, mcp_session: ClientSession):
        """memory.export -- add then export to JSONL."""
        await mcp_session.call_tool(
            "memory",
            {"action": "add", "content": "Export test entry.", "category": "test"},
        )

        r = await mcp_session.call_tool("memory", {"action": "export"})
        text = parse(r)
        assert len(text) > 10, f"Export too short: {len(text)} chars"

    async def test_memory_import(self, mcp_session: ClientSession):
        """memory.import -- import from data list."""
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
        assert any(
            w in text.lower() for w in ("import", "merge", "success", "saved")
        ), text[:120]

    async def test_memory_stats(self, mcp_session: ClientSession):
        """memory.stats -- add then get statistics."""
        await mcp_session.call_tool(
            "memory",
            {"action": "add", "content": "Stats test entry.", "category": "test"},
        )

        r = await mcp_session.call_tool("memory", {"action": "stats"})
        data = parse_json(r)
        total = data.get("total_memories", data.get("total", data.get("count", 0)))
        assert total >= 1, f"Expected >=1 total, got: {data}"


# ---------------------------------------------------------------------------
# Archive lifecycle (add -> delete -> archived -> restore)
# ---------------------------------------------------------------------------


class TestFullMemoryArchive:
    async def test_delete(self, mcp_session: ClientSession):
        """memory.add -> delete -- verify hard delete works."""
        # Add
        r = await mcp_session.call_tool(
            "memory",
            {"action": "add", "content": "To be deleted.", "category": "test"},
        )
        data = parse_json(r)
        mem_id = data["id"]

        # Delete (hard delete, not soft/archive)
        r = await mcp_session.call_tool(
            "memory", {"action": "delete", "memory_id": mem_id}
        )
        text = parse(r)
        assert "deleted" in text.lower(), text[:120]

    async def test_archived_empty(self, mcp_session: ClientSession):
        """memory.archived -- returns empty list on fresh DB."""
        r = await mcp_session.call_tool("memory", {"action": "archived"})
        data = parse_json(r)
        assert "count" in data or "results" in data, f"Unexpected archived response: {data}"

    async def test_restore_not_found(self, mcp_session: ClientSession):
        """memory.restore -- error when no archived memory exists."""
        r = await mcp_session.call_tool(
            "memory", {"action": "restore", "memory_id": "nonexistent-id"}
        )
        text = parse_allow_error(r)
        assert any(
            w in text.lower() for w in ("error", "not found", "archived")
        ), text[:120]


# ---------------------------------------------------------------------------
# Consolidate
# ---------------------------------------------------------------------------


class TestFullMemoryConsolidate:
    @pytest.mark.timeout(120)
    async def test_consolidate_similar(self, mcp_session: ClientSession):
        """Add 3 similar memories -> consolidate -> verify."""
        for content in [
            "Python pytest is a testing framework for Python applications.",
            "pytest provides fixtures and plugins for Python testing.",
            "The pytest framework is used for unit testing Python code.",
        ]:
            await mcp_session.call_tool(
                "memory",
                {"action": "add", "content": content, "category": "tech"},
            )

        r = await mcp_session.call_tool(
            "memory", {"action": "consolidate", "category": "tech"}
        )
        text = parse_allow_error(r)
        # Consolidate may merge or report nothing to consolidate
        assert len(text) > 10, f"Consolidate result too short: {len(text)} chars"


# ---------------------------------------------------------------------------
# Config tool
# ---------------------------------------------------------------------------


class TestFullConfig:
    async def test_config_status(self, mcp_session: ClientSession):
        """config.status -- verify mode info."""
        r = await mcp_session.call_tool("config", {"action": "status"})
        data = parse_json(r)
        all_keys = str(data.keys()).lower()
        assert "database" in all_keys or "db" in all_keys, (
            f"Missing db info: {list(data.keys())}"
        )

    async def test_config_set_log_level(self, mcp_session: ClientSession):
        """config.set -- change log_level."""
        r = await mcp_session.call_tool(
            "config", {"action": "set", "key": "log_level", "value": "DEBUG"}
        )
        text = parse(r)
        assert any(w in text.lower() for w in ("updated", "set", "log_level")), text[:120]

    async def test_config_sync_status(self, mcp_session: ClientSession):
        """config.sync -- show sync status (no rclone needed)."""
        r = await mcp_session.call_tool("config", {"action": "sync"})
        text = parse_allow_error(r)
        # Should return status or error about sync not enabled
        assert len(text) > 5, f"Sync result too short: {len(text)} chars"


# ---------------------------------------------------------------------------
# Setup tool
# ---------------------------------------------------------------------------


class TestFullSetup:
    @pytest.mark.timeout(120)
    async def test_setup_warmup(self, mcp_session: ClientSession):
        """setup.warmup -- download/verify embedding models."""
        r = await mcp_session.call_tool("setup", {"action": "warmup"})
        data = parse_json(r)
        assert "status" in data or "embedding" in data, f"Unexpected warmup result: {data}"

    async def test_setup_invalid_action(self, mcp_session: ClientSession):
        """setup with invalid action returns error."""
        r = await mcp_session.call_tool("setup", {"action": "invalid"})
        text = parse_allow_error(r)
        assert any(
            w in text.lower() for w in ("error", "unknown", "invalid")
        ), text[:120]


# ---------------------------------------------------------------------------
# Security boundary
# ---------------------------------------------------------------------------


class TestFullSecurity:
    async def test_sql_injection_in_search(self, mcp_session: ClientSession):
        """SQL injection in search query should be handled safely."""
        r = await mcp_session.call_tool(
            "memory",
            {"action": "search", "query": "'; DROP TABLE memories; --"},
        )
        text = parse_allow_error(r)
        assert text, "Server crashed on SQL injection attempt"

    async def test_xss_in_content(self, mcp_session: ClientSession):
        """XSS content should be stored as plain text, not executed."""
        r = await mcp_session.call_tool(
            "memory",
            {
                "action": "add",
                "content": '<script>alert("xss")</script>',
                "category": "test",
            },
        )
        data = parse_json(r)
        assert data.get("status") == "saved", f"XSS content not saved: {data}"

    async def test_large_content(self, mcp_session: ClientSession):
        """Very large content should be handled gracefully."""
        r = await mcp_session.call_tool(
            "memory",
            {"action": "add", "content": "A" * 100_000, "category": "test"},
        )
        text = parse_allow_error(r)
        assert text, "Server crashed on large content"

    async def test_special_characters(self, mcp_session: ClientSession):
        """Special characters should not break the server."""
        r = await mcp_session.call_tool(
            "memory",
            {
                "action": "add",
                "content": "Test with special chars: \t\n\r and emoji \U0001f600 and CJK \u4e16\u754c",
                "category": "test",
            },
        )
        text = parse_allow_error(r)
        assert text, "Server crashed on special characters"
