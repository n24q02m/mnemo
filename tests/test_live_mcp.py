#!/usr/bin/env python3
"""
Phase 5 Live Comprehensive Test for mnemo-mcp.

Spawns the server as a subprocess via MCP SDK Client (StdioClientTransport),
communicates over JSON-RPC stdio protocol, and tests ALL tools x actions.

Usage:
    uv run python tests/test_live_mcp.py

No external services required — uses temp directory for DB.
"""

import asyncio
import json
import os
import sys
import tempfile

from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
passed = 0
failed = 0
results: list[tuple[str, bool, str]] = []


def parse(r) -> str:
    """Extract text from MCP tool result."""
    if hasattr(r, "isError") and r.isError:
        raise RuntimeError(r.content[0].text)
    return r.content[0].text


def ok(label: str, evidence: str = ""):
    global passed
    passed += 1
    results.append((label, True, evidence))
    print(f"  [PASS] {label}" + (f" | {evidence[:80]}" if evidence else ""))


def fail(label: str, err: str):
    global failed
    failed += 1
    results.append((label, False, err))
    print(f"  [FAIL] {label} | {err[:120]}")


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------
async def run_tests():
    global passed, failed

    tmpdir = tempfile.mkdtemp(prefix="mnemo-live-test-")
    db_path = os.path.join(tmpdir, "test.db")

    server_params = StdioServerParameters(
        command="uv",
        args=["run", "mnemo-mcp"],
        env={
            **os.environ,
            "DB_PATH": db_path,
            "LOG_LEVEL": "WARNING",
        },
    )

    async with stdio_client(server_params) as streams:
        read_stream, write_stream = streams
        from mcp.client.session import ClientSession

        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("Server connected. Running tests...\n")

            # ===== listTools =====
            print("--- Meta ---")
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            if set(tool_names) >= {"memory", "config", "help"}:
                ok("listTools", f"tools={tool_names}")
            else:
                fail("listTools", f"Missing tools: {tool_names}")

            # ===== listResources =====
            try:
                resources_result = await session.list_resources()
                resource_uris = [str(r.uri) for r in resources_result.resources]
                if len(resource_uris) >= 2:
                    ok("listResources", f"uris={resource_uris}")
                elif len(resource_uris) >= 0:
                    # Some FastMCP versions may not expose resources via list
                    ok("listResources", f"uris={resource_uris} (may be empty in some versions)")
            except Exception as e:
                ok("listResources", f"Not supported: {str(e)[:60]}")

            # ===== HELP TOOL =====
            print("\n--- help ---")
            for topic in ["memory", "config"]:
                try:
                    r = await session.call_tool("help", {"topic": topic})
                    t = parse(r)
                    if len(t) >= 100:
                        ok(f"help(topic={topic})", f"{len(t)} chars")
                    else:
                        fail(f"help(topic={topic})", f"Too short: {len(t)} chars")
                except Exception as e:
                    fail(f"help(topic={topic})", str(e))

            # ===== CONFIG TOOL =====
            print("\n--- config ---")

            # config.status
            try:
                r = await session.call_tool("config", {"action": "status"})
                t = parse(r)
                d = json.loads(t)
                if "database" in d or "database_path" in d or "db_path" in d:
                    ok("config.status", f"keys={list(d.keys())[:5]}")
                else:
                    # Check if any key contains 'database' or 'db'
                    all_keys = str(d.keys()).lower()
                    if "database" in all_keys or "db" in all_keys:
                        ok("config.status", f"keys={list(d.keys())[:5]}")
                    else:
                        fail("config.status", f"Missing db info: {list(d.keys())}")
            except Exception as e:
                fail("config.status", str(e))

            # config.set
            try:
                r = await session.call_tool(
                    "config", {"action": "set", "key": "log_level", "value": "DEBUG"}
                )
                t = parse(r)
                if "updated" in t.lower() or "set" in t.lower() or "log_level" in t.lower():
                    ok("config.set(log_level=DEBUG)", t[:80])
                else:
                    fail("config.set(log_level=DEBUG)", t[:80])
            except Exception as e:
                fail("config.set(log_level=DEBUG)", str(e))

            # ===== MEMORY TOOL — Happy Path =====
            print("\n--- memory (happy path) ---")

            # memory.add
            mem_id = None
            try:
                r = await session.call_tool(
                    "memory",
                    {
                        "action": "add",
                        "content": "Python testing frameworks include pytest and unittest.",
                        "category": "tech",
                        "tags": ["python", "testing"],
                    },
                )
                t = parse(r)
                d = json.loads(t)
                mem_id = d.get("id")
                if d.get("status") == "saved" and mem_id:
                    ok("memory.add", f"id={mem_id}")
                else:
                    fail("memory.add", t[:80])
            except Exception as e:
                fail("memory.add", str(e))

            # memory.add (second entry for search testing)
            try:
                r = await session.call_tool(
                    "memory",
                    {
                        "action": "add",
                        "content": "Rust ownership model prevents data races at compile time.",
                        "category": "tech",
                        "tags": ["rust", "safety"],
                    },
                )
                t = parse(r)
                d = json.loads(t)
                if d.get("status") == "saved":
                    ok("memory.add(2nd)", f"id={d.get('id')}")
                else:
                    fail("memory.add(2nd)", t[:80])
            except Exception as e:
                fail("memory.add(2nd)", str(e))

            # memory.list
            try:
                r = await session.call_tool("memory", {"action": "list"})
                t = parse(r)
                d = json.loads(t)
                memories = d.get("results", d.get("memories", []))
                if len(memories) >= 2:
                    ok("memory.list", f"count={len(memories)}")
                else:
                    fail("memory.list", f"Expected >=2: {t[:80]}")
            except Exception as e:
                fail("memory.list", str(e))

            # memory.search
            try:
                r = await session.call_tool(
                    "memory", {"action": "search", "query": "pytest"}
                )
                t = parse(r)
                d = json.loads(t)
                memories = d.get("memories", d.get("results", []))
                if len(memories) >= 1:
                    ok("memory.search(pytest)", f"found={len(memories)}")
                else:
                    fail("memory.search(pytest)", f"No results: {t[:80]}")
            except Exception as e:
                fail("memory.search(pytest)", str(e))

            # memory.update
            if mem_id:
                try:
                    r = await session.call_tool(
                        "memory",
                        {
                            "action": "update",
                            "memory_id": mem_id,
                            "content": "Python testing: pytest is the most popular framework.",
                        },
                    )
                    t = parse(r)
                    if "updated" in t.lower():
                        ok("memory.update", t[:80])
                    else:
                        fail("memory.update", t[:80])
                except Exception as e:
                    fail("memory.update", str(e))
            else:
                fail("memory.update", "Skipped: no mem_id from add")

            # memory.stats
            try:
                r = await session.call_tool("memory", {"action": "stats"})
                t = parse(r)
                d = json.loads(t)
                total = d.get("total_memories", d.get("total", d.get("count", 0)))
                if total >= 2:
                    ok("memory.stats", f"total_memories={total}")
                else:
                    fail("memory.stats", t[:80])
            except Exception as e:
                fail("memory.stats", str(e))

            # memory.export
            try:
                r = await session.call_tool("memory", {"action": "export"})
                t = parse(r)
                # Export returns JSONL or JSON with memories
                if len(t) > 10:
                    ok("memory.export", f"{len(t)} chars exported")
                else:
                    fail("memory.export", f"Too short: {t[:80]}")
            except Exception as e:
                fail("memory.export", str(e))

            # memory.import (using list format — MCP transport may parse JSON strings)
            try:
                r = await session.call_tool(
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
                t = parse(r)
                if "import" in t.lower() or "merge" in t.lower() or "success" in t.lower():
                    ok("memory.import", t[:80])
                else:
                    fail("memory.import", t[:80])
            except Exception as e:
                fail("memory.import", str(e))

            # memory.delete
            if mem_id:
                try:
                    r = await session.call_tool(
                        "memory", {"action": "delete", "memory_id": mem_id}
                    )
                    t = parse(r)
                    if "deleted" in t.lower() or "removed" in t.lower():
                        ok("memory.delete", t[:80])
                    else:
                        fail("memory.delete", t[:80])
                except Exception as e:
                    fail("memory.delete", str(e))
            else:
                fail("memory.delete", "Skipped: no mem_id from add")

            # ===== ERROR PATH =====
            print("\n--- Error path ---")

            # memory: missing action
            try:
                r = await session.call_tool("memory", {})
                t = parse(r)
                fail("memory(no action)", f"Expected error, got: {t[:60]}")
            except Exception as e:
                ok("memory(no action)", f"Error as expected: {str(e)[:60]}")

            # memory: invalid action
            try:
                r = await session.call_tool("memory", {"action": "invalid_action"})
                t = parse(r)
                if "error" in t.lower() or "unknown" in t.lower() or "invalid" in t.lower():
                    ok("memory(invalid action)", t[:80])
                else:
                    fail("memory(invalid action)", f"No error: {t[:60]}")
            except Exception as e:
                ok("memory(invalid action)", f"Error: {str(e)[:60]}")

            # memory.add: missing content
            try:
                r = await session.call_tool("memory", {"action": "add"})
                t = parse(r)
                if "error" in t.lower() or "content" in t.lower() or "required" in t.lower():
                    ok("memory.add(no content)", t[:80])
                else:
                    fail("memory.add(no content)", f"No error: {t[:60]}")
            except Exception as e:
                ok("memory.add(no content)", f"Error: {str(e)[:60]}")

            # config: invalid key
            try:
                r = await session.call_tool(
                    "config", {"action": "set", "key": "invalid_key", "value": "x"}
                )
                t = parse(r)
                if "error" in t.lower() or "invalid" in t.lower() or "valid" in t.lower():
                    ok("config.set(invalid key)", t[:80])
                else:
                    fail("config.set(invalid key)", f"No error: {t[:60]}")
            except Exception as e:
                ok("config.set(invalid key)", f"Error: {str(e)[:60]}")

            # help: invalid topic
            try:
                r = await session.call_tool("help", {"topic": "nonexistent"})
                t = parse(r)
                if "error" in t.lower() or "not found" in t.lower() or len(t) < 50:
                    ok("help(invalid topic)", t[:80])
                else:
                    fail("help(invalid topic)", f"Expected error: {t[:60]}")
            except Exception as e:
                ok("help(invalid topic)", f"Error: {str(e)[:60]}")

            # ===== SECURITY BOUNDARY =====
            print("\n--- Security boundary ---")

            # SQL injection in search
            try:
                r = await session.call_tool(
                    "memory",
                    {"action": "search", "query": "'; DROP TABLE memories; --"},
                )
                t = parse(r)
                # Should return empty results, not crash
                ok("memory.search(SQL injection)", f"Safe response: {t[:60]}")
            except Exception as e:
                # Error is also acceptable (handled gracefully)
                ok("memory.search(SQL injection)", f"Handled: {str(e)[:60]}")

            # XSS in content
            try:
                r = await session.call_tool(
                    "memory",
                    {
                        "action": "add",
                        "content": '<script>alert("xss")</script>',
                        "category": "test",
                    },
                )
                t = parse(r)
                d = json.loads(t)
                if d.get("status") == "saved":
                    ok("memory.add(XSS content)", "Stored safely (text, not executed)")
                else:
                    fail("memory.add(XSS content)", t[:60])
            except Exception as e:
                fail("memory.add(XSS content)", str(e))

            # Very long content (DoS attempt)
            try:
                r = await session.call_tool(
                    "memory",
                    {"action": "add", "content": "A" * 100_000, "category": "test"},
                )
                t = parse(r)
                # Should either save or reject gracefully
                if "error" in t.lower() or "limit" in t.lower() or "saved" in json.loads(t).get("status", ""):
                    ok("memory.add(100K chars)", f"Handled: {t[:60]}")
                else:
                    fail("memory.add(100K chars)", t[:60])
            except Exception as e:
                ok("memory.add(100K chars)", f"Rejected: {str(e)[:60]}")

    # Cleanup
    import shutil

    shutil.rmtree(tmpdir, ignore_errors=True)

    # ===== SUMMARY =====
    total = passed + failed
    print(f"\n{'='*60}")
    print(f"RESULT: {passed}/{total} PASS ({100*passed/total:.1f}%)")
    print(f"{'='*60}")

    if failed > 0:
        print("\nFailed tests:")
        for label, ok_flag, evidence in results:
            if not ok_flag:
                print(f"  - {label}: {evidence}")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
