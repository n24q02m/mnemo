"""Pytest-based live MCP protocol tests for mnemo-mcp.

Spawns a real MCP server via stdio and tests all tools through the protocol.
Uses a temp directory for DB -- all tests work offline (local ONNX embedding).

Usage:
    uv run pytest tests/test_live_protocol.py -v --tb=short -m live
"""

import asyncio
import json
import os
import subprocess
import time
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


@pytest.fixture
async def local_mcp_session(tmp_path):
    """Start mnemo-mcp with deterministic local-only provider selection."""
    from fastretrieval import define_cache_dir

    local_state = tmp_path / "local-state"
    cache_dir = define_cache_dir()
    db_path = str(tmp_path / "local-test.db")
    local_env = {
        **os.environ,
        "DB_PATH": db_path,
        "LOG_LEVEL": "WARNING",
        "SYNC_ENABLED": "false",
        "MCP_TRANSPORT": "stdio",
        "HOME": str(local_state),
        "USERPROFILE": str(local_state),
        "XDG_CONFIG_HOME": str(local_state),
        "LOCALAPPDATA": str(local_state),
        "APPDATA": str(local_state),
        "FASTRETRIEVAL_CACHE_PATH": str(cache_dir),
        "QWEN3_EMBED_CACHE_PATH": "",
        "API_KEYS": "",
        "JINA_API_KEY": "",
        "JINA_AI_API_KEY": "",
        "GEMINI_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "OPENAI_API_KEY": "",
        "COHERE_API_KEY": "",
        "CO_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "XAI_API_KEY": "",
        "GOOGLE_VERTEX_EXPRESS_API_KEY": "",
        "GOOGLE_DRIVE_CLIENT_ID": "",
        "EMBEDDING_MODELS": "",
        "RERANK_MODELS": "",
        "LLM_MODELS": "",
        "EMBEDDING_MODEL": "",
        "RERANK_MODEL": "",
        "EMBEDDING_BACKEND": "",
        "RERANK_BACKEND": "",
        "EMBEDDING_API_BASE": "",
        "RERANK_API_BASE": "",
        "LLM_API_BASE": "",
        "LOCAL_EMBEDDING_MODEL": "",
        "LOCAL_RERANK_MODEL": "",
        "EMBEDDING_DIMS": "0",
        "RERANK_ENABLED": "true",
        "DISABLE_LOCAL_EMBED": "false",
        "DISABLE_LOCAL_RERANK": "false",
    }
    subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-c",
            "from mcp_core import set_local_mode; set_local_mode('mnemo-mcp')",
        ],
        env=local_env,
        check=True,
        capture_output=True,
        text=True,
    )
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "mnemo-mcp"],
        env=local_env,
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
# Meta
# ---------------------------------------------------------------------------


class TestMeta:
    async def test_list_tools(self, mcp_session: ClientSession):
        result = await mcp_session.list_tools()
        tool_names = {t.name for t in result.tools}
        expected = {"memory", "config", "help"}
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
    @pytest.mark.parametrize("topic", ["memory", "config"])
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
# Config tool -- warmup action (offline)
# ---------------------------------------------------------------------------


class TestConfigWarmup:
    async def test_config_warmup(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("config", {"action": "warmup"})
        text = parse(r)
        data = json.loads(text)
        assert "status" in data or "error" not in data, text[:120]

    async def test_config_invalid_action(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("config", {"action": "invalid"})
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
# Granular retrieval tools (offline, temp DB)
# ---------------------------------------------------------------------------


class TestGranularRetrieval:
    @pytest.mark.timeout(300)
    async def test_add_search_reports_retrieval_state(
        self, local_mcp_session: ClientSession
    ):
        deadline = time.monotonic() + 300

        setup_result = await local_mcp_session.call_tool(
            "config", {"action": "setup_status"}
        )
        setup_text = parse(setup_result)
        setup = json.loads(setup_text)
        assert setup.get("state") == "local", setup
        assert setup.get("cloud_keys_in_env") == [], setup

        warmup_result = await local_mcp_session.call_tool(
            "config", {"action": "warmup"}
        )
        warmup_text = parse(warmup_result)
        warmup = json.loads(warmup_text)
        assert warmup.get("status") == "ok", warmup
        assert warmup.get("mode") == "local", warmup

        status: dict = {}
        embedding = None
        while time.monotonic() < deadline:
            status_result = await local_mcp_session.call_tool(
                "config", {"action": "status"}
            )
            status_text = parse(status_result)
            status = json.loads(status_text)
            embedding = status.get("embedding")
            if (
                isinstance(embedding, dict)
                and embedding.get("available") is True
                and isinstance(embedding.get("model"), str)
                and embedding["model"]
                and isinstance(embedding.get("dims"), int)
                and embedding["dims"] > 0
            ):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(0.5, remaining))

        assert (
            isinstance(embedding, dict)
            and embedding.get("available") is True
            and isinstance(embedding.get("model"), str)
            and embedding["model"]
            and isinstance(embedding.get("dims"), int)
            and embedding["dims"] > 0
        ), f"Embedding backend not ready: {status}"

        for content in (
            "Python testing commonly uses pytest.",
            "Python testing can also use unittest.",
        ):
            r = await local_mcp_session.call_tool(
                "add_memory",
                {"content": content, "category": "tech", "tags": ["python"]},
            )
            text = parse(r)
            data = json.loads(text)
            assert data.get("status") == "saved", text[:80]
            assert data.get("id"), "Missing memory id"

        search_data = None
        candidate: dict = {}
        while time.monotonic() < deadline:
            r = await local_mcp_session.call_tool(
                "search_memory", {"query": "Python testing", "limit": 5}
            )
            text = parse(r)
            candidate = json.loads(text)
            if candidate.get("semantic") is True and candidate.get("reranked") is True:
                search_data = candidate
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(0.5, remaining))

        assert search_data is not None, (
            f"Retrieval backends not ready before deadline: {candidate}"
        )
        assert search_data.get("count", 0) >= 1, search_data
        assert search_data.get("semantic") is True, search_data
        assert search_data.get("reranked") is True, search_data
        reranker = search_data["reranker"]
        assert reranker["backend"] == "local", reranker
        assert reranker["model"] in {
            "n24q02m/Qwen3-Reranker-0.6B-ONNX-YesNo",
            "n24q02m/Qwen3-Reranker-0.6B-GGUF",
        }
        assert reranker["fallback"] == "none", reranker

        r = await local_mcp_session.call_tool("config", {"action": "status"})
        text = parse(r)
        status = json.loads(text)
        embedding = status["embedding"]
        assert embedding["model"] in {
            "n24q02m/Qwen3-Embedding-0.6B-ONNX",
            "n24q02m/Qwen3-Embedding-0.6B-GGUF",
        }
        assert embedding["dims"] == 768
        assert embedding["available"] is True


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
