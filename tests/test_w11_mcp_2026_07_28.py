"""Unit and real E2E tests for W11 MCP 2026-07-28 upgrades (Skills + Tasks)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
from fastmcp import Context
from fastmcp.skills.models import (
    GetSkillParams,
    GetSkillRequest,
    GetSkillResult,
    ListSkillsParams,
    ListSkillsRequest,
    ListSkillsResult,
)
from fastmcp_tasks.client import TasksClientExtension
from fastmcp_tasks.client_models import (
    ClientCreateTaskResult,
    ClientGetTaskResult,
    GetTaskRequest,
    GetTaskRequestParams,
)
from hull_core.server import SKILLS_EXTENSION_ID, TASKS_EXTENSION_ID
from mcp.client.extension import ResultClaim
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent, TextResourceContents

from mnemo import server
from tests.live_http import mnemo_http_server

EXPECTED_SKILLS = {
    "knowledge-audit",
    "memory-commit",
    "recall-context",
    "session-handoff",
    "temporal-query",
}


def _isolated_env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["USERPROFILE"] = str(tmp_path)
    env["LOG_LEVEL"] = "WARNING"
    env["DISABLE_LOCAL_EMBED"] = "true"
    env["DISABLE_LOCAL_RERANK"] = "true"
    for key in ("N24Q02M_HOME", "N24Q02M_USE_XDG", "MNEMO_PROFILE", "HULL_PROFILE"):
        env.pop(key, None)
    return env


def _task_and_skills_extensions() -> tuple[
    dict[str, dict[str, Any]], dict[str, list[ResultClaim[Any]]]
]:
    task_ext = TasksClientExtension()
    claims: dict[str, list[ResultClaim[Any]]] = {
        TASKS_EXTENSION_ID: list(task_ext.claims())
    }
    extensions: dict[str, dict[str, Any]] = {
        SKILLS_EXTENSION_ID: {},
        TASKS_EXTENSION_ID: task_ext.settings(),
    }
    return extensions, claims


def test_server_registers_skills_and_tasks_extensions() -> None:
    """FastMCP server wires both io.modelcontextprotocol/skills and tasks."""
    extensions = getattr(server.mcp, "_extensions", {})
    assert SKILLS_EXTENSION_ID in extensions
    assert TASKS_EXTENSION_ID in extensions


@pytest.mark.asyncio
async def test_long_running_tools_advertise_optional_tasks() -> None:
    """Long-running job tools allow optional background tasks with sync fallback."""
    for tool_name in (
        "export_memories",
        "import_memories",
        "consolidate_memories",
        "config",
    ):
        tool = await server.mcp.get_tool(tool_name)
        assert tool is not None, f"Missing tool {tool_name}"
        assert tool.task_config.mode == "optional"

    fast_tool = await server.mcp.get_tool("add_memory")
    assert fast_tool is not None
    assert not fast_tool.task_config.supports_tasks()


def test_resolve_skills_dir_wheel_repo_and_missing(tmp_path: Path) -> None:
    """_resolve_skills_dir prefers packaged mnemo/skills, falls back to repo, and fails loudly."""
    pkg_dir = tmp_path / "site-packages" / "mnemo"
    pkg_file = pkg_dir / "server.py"
    pkg_skills = pkg_dir / "skills"
    pkg_skills.mkdir(parents=True)
    with patch.object(server, "__file__", str(pkg_file)):
        assert server._resolve_skills_dir() == pkg_skills

    # Fallback to parents[2]/skills when package skills/ does not exist.
    src_repo = tmp_path / "repo"
    repo_server_file = src_repo / "src" / "mnemo" / "server.py"
    repo_server_file.parent.mkdir(parents=True)
    repo_skills = src_repo / "skills"
    repo_skills.mkdir(parents=True)
    with patch.object(server, "__file__", str(repo_server_file)):
        assert server._resolve_skills_dir() == repo_skills

    empty_root = tmp_path / "empty" / "src" / "mnemo" / "server.py"
    empty_root.parent.mkdir(parents=True)
    with patch.object(server, "__file__", str(empty_root)):
        with pytest.raises(FileNotFoundError, match="Skills directory not found"):
            server._resolve_skills_dir()


def test_get_ctx_worker_and_fallback_paths(tmp_db) -> None:
    """_get_ctx handles FastMCP worker ctx (request_context=None) and uninitialized error."""
    state = {"db": tmp_db, "embedding_model": None, "embedding_dims": 0}
    worker_ctx = cast(
        Context, SimpleNamespace(lifespan_context=state, request_context=None)
    )
    db, model, dims = server._get_ctx(worker_ctx)
    assert db is tmp_db
    assert model is None
    assert dims == 0

    bare_ctx = cast(
        Context, SimpleNamespace(lifespan_context=None, request_context=None)
    )
    with patch.object(server, "_lifespan_state", state):
        db2, _, _ = server._get_ctx(bare_ctx)
        assert db2 is tmp_db

    with patch.object(server, "_lifespan_state", None):
        with pytest.raises(ValueError, match="lifespan has not initialized"):
            server._get_ctx(bare_ctx)


async def _poll_task_until_done(
    session: ClientSession, task_id: str, timeout_s: float = 30.0
) -> ClientGetTaskResult:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        res = await session.send_request(
            GetTaskRequest(params=GetTaskRequestParams(task_id=task_id)),
            ClientGetTaskResult,
        )
        if res.status in {"completed", "failed", "cancelled"}:
            return res
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail(
                f"Timed out waiting for task {task_id}; last status={res.status}"
            )
        await asyncio.sleep(0.05)


def _extract_json_text(result) -> dict[str, Any]:
    assert result.content, f"Expected non-empty content, got {result}"
    item = result.content[0]
    assert isinstance(item, TextContent), f"Expected TextContent, got {type(item)}"
    return json.loads(item.text)


async def _verify_skills_and_tasks_e2e(session: ClientSession) -> None:
    disc = await session.discover()
    assert session.protocol_version == "2026-07-28"
    caps = disc.capabilities
    assert caps.extensions is not None
    assert SKILLS_EXTENSION_ID in caps.extensions
    assert TASKS_EXTENSION_ID in caps.extensions

    # 1. skills/list + skills/get
    listed_skills = await session.send_request(
        ListSkillsRequest(params=ListSkillsParams()),
        ListSkillsResult,
    )
    skill_names = {s.frontmatter.name for s in listed_skills.skills}
    assert EXPECTED_SKILLS.issubset(skill_names), f"Got skills: {skill_names}"

    got_skill = await session.send_request(
        GetSkillRequest(params=GetSkillParams(uri="skill://memory-commit/SKILL.md")),
        GetSkillResult,
    )
    assert got_skill.skill.frontmatter.name == "memory-commit"

    # 2. skill:// resource listing & reading
    resources = await session.list_resources()
    uris = {str(r.uri) for r in resources.resources}
    assert "skill://memory-commit/SKILL.md" in uris
    read_res = await session.read_resource("skill://memory-commit/SKILL.md")
    assert read_res.contents
    first_content = read_res.contents[0]
    assert isinstance(first_content, TextResourceContents)
    assert "memory-commit" in first_content.text

    # 3. Tasks execution via explicit CreateTaskResult + tasks/get
    added = await session.call_tool(
        "add_memory",
        {"content": "W11 E2E task seed memory", "category": "e2e"},
    )
    assert not added.is_error

    created = await session.call_tool(
        "export_memories",
        {},
        allow_claimed=True,
    )
    assert isinstance(created, ClientCreateTaskResult), (
        f"Expected CreateTaskResult, got {type(created)}: {created}"
    )
    final_task = await _poll_task_until_done(session, created.task_id)
    assert final_task.status == "completed", f"Task failed: {final_task}"
    assert final_task.result is not None
    exported = json.loads(final_task.result["content"][0]["text"])
    assert exported["count"] >= 1
    assert "W11 E2E task seed memory" in exported["data"]

    # 4. Task execution on config(action="status") via ClientCreateTaskResult + tasks/get
    cfg_created = await session.call_tool(
        "config", {"action": "status"}, allow_claimed=True
    )
    assert isinstance(cfg_created, ClientCreateTaskResult), (
        f"Expected CreateTaskResult, got {type(cfg_created)}: {cfg_created}"
    )
    cfg_task = await _poll_task_until_done(session, cfg_created.task_id)
    assert cfg_task.status == "completed", f"Config task failed: {cfg_task}"
    assert cfg_task.result is not None
    cfg_data = json.loads(cfg_task.result["content"][0]["text"])
    assert "database" in cfg_data or "total_memories" in str(cfg_data)


@pytest.mark.e2e
@pytest.mark.timeout(120)
async def test_e2e_stdio_skills_and_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real stdio E2E: skills/list, skill://, and MCP Tasks execution."""
    # Windows subprocess startup (fastmcp_tasks + Alembic init) can exceed 10s.
    monkeypatch.setattr("mcp.client.session.DISCOVER_TIMEOUT_SECONDS", 60.0)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mnemo.cli", "mcp"],
        env=_isolated_env(tmp_path),
    )
    extensions, claims = _task_and_skills_extensions()

    async with stdio_client(params) as (read, write):
        async with ClientSession(
            read, write, extensions=extensions, result_claims=claims
        ) as session:
            await _verify_skills_and_tasks_e2e(session)


@pytest.mark.e2e
@pytest.mark.timeout(120)
async def test_e2e_stdio_without_tasks_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real stdio E2E: client without task support falls back to sync execution."""
    monkeypatch.setattr("mcp.client.session.DISCOVER_TIMEOUT_SECONDS", 60.0)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mnemo.cli", "mcp"],
        env=_isolated_env(tmp_path),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(
            read, write, extensions={SKILLS_EXTENSION_ID: {}}
        ) as session:
            await session.discover()
            sync_export = await session.call_tool("export_memories", {})
            assert not sync_export.is_error
            payload = _extract_json_text(sync_export)
            assert "count" in payload


@pytest.mark.e2e
@pytest.mark.timeout(120)
async def test_e2e_streamable_http_skills_tasks_and_fallback(tmp_path: Path) -> None:
    """Real Streamable HTTP E2E: skills/list, skill://, MCP Tasks, and fallback."""
    env = _isolated_env(tmp_path / "home")
    extensions, claims = _task_and_skills_extensions()
    async with mnemo_http_server(env, tmp_path / "http.log") as port:
        url = f"http://127.0.0.1:{port}/mcp"

        # Client 1: advertises skills + tasks extensions
        async with streamable_http_client(url) as (read, write):
            async with ClientSession(
                read, write, extensions=extensions, result_claims=claims
            ) as session:
                await _verify_skills_and_tasks_e2e(session)

        # Client 2: modern 2026-07-28 client without tasks capability -> sync fallback
        async with streamable_http_client(url) as (read, write):
            async with ClientSession(
                read, write, extensions={SKILLS_EXTENSION_ID: {}}
            ) as session:
                await session.discover()
                sync_res = await session.call_tool(
                    "import_memories",
                    {
                        "data": json.dumps(
                            {
                                "content": "Sync fallback HTTP import",
                                "category": "e2e",
                            }
                        ),
                        "mode": "merge",
                    },
                )
                assert not sync_res.is_error
                imported = _extract_json_text(sync_res)
                assert imported.get("imported", 0) >= 1 or imported.get("added", 0) >= 1

        # Client 3: legacy initialize() client -> sync fallback
        async with streamable_http_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                legacy_res = await session.call_tool("export_memories", {})
                assert not legacy_res.is_error
                assert _extract_json_text(legacy_res)["count"] >= 1
