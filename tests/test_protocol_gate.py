"""Protocol gate for mnemo: every registered tool reachable via ClientSession.

Scope honesty (read before editing):
- This gate runs against the SOURCE TREE: the subprocess below boots the
  editable install (``uv run mnemo-mcp``), i.e. the code in this repository,
  not a published artifact. It is pre-BETA hardening only.
- The authoritative D3 gate runs against the installed BETA artifact with
  ``uvx --from mnemo-mcp==<beta>`` driven by ``mcp.ClientSession``; that is
  blocked until PyPI trusted publishing exists. This file does NOT claim D3
  is satisfied.
- Transport: mnemo has no stdio mode since the de-host (``main()`` in
  ``src/mnemo/server.py``: "there is no stdio spawn mode anymore"), so
  the sessions below connect over streamable HTTP on loopback with the
  default no-auth mode. The stale stdio fixtures in ``test_full_live.py`` /
  ``test_live_protocol.py`` predate that switch.
- The expected tool set is the authoritative set of ``@mcp.tool``
  registrations in ``src/mnemo/server.py`` (verified live 2026-10-02).
  There is NO ``help`` tool; ``TestMeta`` in ``test_live_protocol.py``
  predates the granular-tool split and its ``{"memory", "config", "help"}``
  superset is stale.
- ``config`` status calls are dispatch/transport checks only (mcp-dev
  protocol-test-coverage Rule 1); the domain coverage here is the memory
  add -> search round-trip plus one real call per granular tool.
- ``restore_memory`` / ``archived_memories``: the happy path needs rows
  older than ``archive_after_days`` (default 90) -- time-gated, so not
  reachable hermetically. Both tools are exercised via their deterministic
  handled-error round-trip instead; this is reported, not silently weakened.
- Concurrency: the server serializes tool calls onto one shared sqlite
  connection, so concurrent writes can each be answered with a handled
  error dict. The gate asserts the transport property (requests multiplexed
  on ONE session, every in-flight call answered) plus post-concurrency
  liveness, not write success.
"""

import asyncio
import json
import os
import socket
import subprocess
import time
import warnings
from pathlib import Path

import pytest
import pytest_asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

pytestmark = [
    pytest.mark.timeout(60),
    pytest.mark.asyncio(loop_scope="module"),
]

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Authoritative ``@mcp.tool`` registration set (src/mnemo/server.py).
EXPECTED_TOOLS = frozenset(
    {
        "add_memory",
        "archived_memories",
        "config",
        "consolidate_memories",
        "delete_memory",
        "export_memories",
        "import_memories",
        "list_memories",
        "memory",
        "memory_stats",
        "restore_memory",
        "search_memory",
        "update_memory",
    }
)

# Environment names needed to launch ``uv`` and its child process on all
# supported platforms. Everything else must be supplied explicitly below.
_PROCESS_ENV_KEYS = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "VIRTUAL_ENV",
    "UV_PROJECT_ENVIRONMENT",
)

# Blank these so the server can never pick up host credentials or reach a
# cloud provider; keeps the gate hermetic on all three OSes.
_KNOWN_PROVIDER_ENV_KEYS = (
    "API_KEYS",
    "JINA_API_KEY",
    "JINA_AI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
    "CO_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "GOOGLE_VERTEX_EXPRESS_API_KEY",
    "GOOGLE_DRIVE_CLIENT_ID",
    "EMBEDDING_MODELS",
    "RERANK_MODELS",
    "LLM_MODELS",
    "EMBEDDING_MODEL",
    "RERANK_MODEL",
    "EMBEDDING_BACKEND",
    "RERANK_BACKEND",
    "EMBEDDING_API_BASE",
    "RERANK_API_BASE",
    "LLM_API_BASE",
    "LOCAL_EMBEDDING_MODEL",
    "LOCAL_RERANK_MODEL",
    "MCP_RELAY_URL",
)


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


def _free_port() -> int:
    """Reserve an OS-assigned free loopback port for the server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_gate_env(
    state_dir: Path,
    *,
    port: int,
) -> dict[str, str]:
    """Credential-free temp environment for the server subprocess.

    Mirrors ``_build_local_replay_env`` from ``test_live_protocol.py`` with
    two deltas: no ``DB_PATH`` (the HTTP no-auth path resolves its store via
    ``Path.home()/.mnemo`` and mixing the two paths breaks first-run
    migrations), plus ``MNEMO_HOST``/``MNEMO_PORT`` to pin the bind.
    """
    parent_by_upper = {name.upper(): value for name, value in os.environ.items()}
    parent_env = {
        name: parent_by_upper[name.upper()]
        for name in _PROCESS_ENV_KEYS
        if name.upper() in parent_by_upper
    }
    config_dir = state_dir / "config"
    data_dir = state_dir / "data"
    cache_dir = state_dir / "cache"
    temp_dir = state_dir / "tmp"
    env = {
        **parent_env,
        "LOG_LEVEL": "WARNING",
        "SYNC_ENABLED": "false",
        "HOME": str(state_dir),
        "USERPROFILE": str(state_dir),
        "XDG_CONFIG_HOME": str(config_dir),
        "XDG_CACHE_HOME": str(cache_dir),
        "XDG_DATA_HOME": str(data_dir),
        "LOCALAPPDATA": str(state_dir),
        "APPDATA": str(state_dir),
        "TMP": str(temp_dir),
        "TEMP": str(temp_dir),
        "TMPDIR": str(temp_dir),
        "MNEMO_HOST": "127.0.0.1",
        "MNEMO_PORT": str(port),
    }
    env.update(dict.fromkeys(_KNOWN_PROVIDER_ENV_KEYS, ""))
    return env


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """Boot the real mnemo HTTP server once; yield its base URL."""
    state_dir = tmp_path_factory.mktemp("mnemo-gate-state")
    for sub in ("config", "data", "cache", "tmp"):
        (state_dir / sub).mkdir()
    port = _free_port()
    out_path = state_dir / "server-stdout.log"
    err_path = state_dir / "server-stderr.log"
    with out_path.open("w") as out_f, err_path.open("w") as err_f:
        proc = subprocess.Popen(
            ["uv", "run", "mnemo-mcp"],
            cwd=str(_REPO_ROOT),
            env=_build_gate_env(state_dir, port=port),
            stdin=subprocess.DEVNULL,
            stdout=out_f,
            stderr=err_f,
        )
        try:
            deadline = time.monotonic() + 45
            while True:
                if proc.poll() is not None:
                    tail = err_path.read_text(errors="replace")[-2000:]
                    raise RuntimeError(
                        f"mnemo-mcp exited rc={proc.returncode} before readiness:"
                        f"\n{tail}"
                    )
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=1):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        tail = err_path.read_text(errors="replace")[-2000:]
                        raise RuntimeError(
                            f"mnemo-mcp not ready on 127.0.0.1:{port} within 45s:"
                            f"\n{tail}"
                        ) from None
                    time.sleep(0.25)
            yield f"http://127.0.0.1:{port}"
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def mcp_session(server):
    """Open one MCP ClientSession against the booted server (per module).

    A single session is shared by the module: streamable-HTTP teardown pays
    a reconnect/cancel dance per session, so per-test sessions would dominate
    the wall time. Suppresses anyio cancel-scope teardown errors that occur
    when pytest-asyncio tears down the event loop in a different task
    context.
    """
    try:
        async with streamable_http_client(f"{server}/mcp") as (
            read_stream,
            write_stream,
            _session_id,
        ):
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
# Tool contract
# ---------------------------------------------------------------------------


class TestToolContract:
    async def test_list_tools_exact_set(self, mcp_session: ClientSession):
        result = await mcp_session.list_tools()
        tool_names = {t.name for t in result.tools}
        assert tool_names == EXPECTED_TOOLS, (
            f"Tool contract drift: missing={EXPECTED_TOOLS - tool_names} "
            f"unexpected={tool_names - EXPECTED_TOOLS}"
        )
        for tool in result.tools:
            assert tool.description, f"Tool {tool.name} has empty description"
            assert tool.inputSchema, f"Tool {tool.name} has no input schema"


# ---------------------------------------------------------------------------
# Granular tools -- one real call per tool (offline, temp DB)
# ---------------------------------------------------------------------------


class TestGranularTools:
    async def test_add_memory(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "add_memory",
            {
                "content": "Gate granular add: pytest gate stores a memory.",
                "category": "tech",
            },
        )
        data = parse_json(r)
        assert data.get("status") == "saved", f"Expected saved, got: {data}"
        assert data.get("id"), "Missing memory id"

    async def test_search_memory_round_trip(self, mcp_session: ClientSession):
        content = "Gate search round trip: hull stack stage one four."
        r = await mcp_session.call_tool(
            "add_memory", {"content": content, "category": "tech"}
        )
        parse(r)

        r = await mcp_session.call_tool("search_memory", {"query": "hull stack stage"})
        data = parse_json(r)
        memories = data.get("memories", data.get("results", []))
        assert any(m["content"] == content for m in memories), (
            f"Added memory not found via search: {data}"
        )

    async def test_list_memories(self, mcp_session: ClientSession):
        content = "Gate list: rust prevents data races at compile time."
        r = await mcp_session.call_tool(
            "add_memory", {"content": content, "category": "tech"}
        )
        parse(r)

        r = await mcp_session.call_tool("list_memories", {"limit": 20})
        data = parse_json(r)
        memories = data.get("results", data.get("memories", []))
        assert any(m["content"] == content for m in memories), (
            f"Added memory not found via list: {data}"
        )

    async def test_update_memory(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "add_memory",
            {"content": "Gate update: original content here.", "category": "test"},
        )
        mem_id = parse_json(r)["id"]

        r = await mcp_session.call_tool(
            "update_memory",
            {"memory_id": mem_id, "content": "Gate update: updated content here."},
        )
        data = parse_json(r)
        assert data.get("status") == "updated", f"Expected updated, got: {data}"

    async def test_delete_memory(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "add_memory",
            {"content": "Gate delete: this row will be removed.", "category": "test"},
        )
        mem_id = parse_json(r)["id"]

        r = await mcp_session.call_tool("delete_memory", {"memory_id": mem_id})
        data = parse_json(r)
        assert data.get("status") == "deleted", f"Expected deleted, got: {data}"

    async def test_export_memories(self, mcp_session: ClientSession):
        content = "Gate export: jsonl backup contains this sentence."
        r = await mcp_session.call_tool(
            "add_memory", {"content": content, "category": "tech"}
        )
        parse(r)

        r = await mcp_session.call_tool("export_memories", {})
        data = parse_json(r)
        assert data.get("format") == "jsonl", f"Expected jsonl export, got: {data}"
        assert content in data.get("data", ""), "Export missing the added memory"

    async def test_import_memories(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool(
            "import_memories",
            {
                "data": [{"content": "Gate import: merged from jsonl payload."}],
                "mode": "merge",
            },
        )
        data = parse_json(r)
        assert data.get("status") == "imported", f"Expected imported, got: {data}"

    async def test_memory_stats(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("memory_stats", {})
        data = parse_json(r)
        assert isinstance(data.get("total_memories"), int), f"Bad stats: {data}"

    async def test_restore_memory(self, mcp_session: ClientSession):
        # Happy path needs a row archived by archive_by_score, which requires
        # rows older than archive_after_days (90d default) -- time-gated, so
        # not hermetically reachable. Deterministic handled error instead.
        r = await mcp_session.call_tool("restore_memory", {"memory_id": "f" * 32})
        data = parse_json(r)
        assert "error" in data, f"Expected handled not-found error, got: {data}"

    async def test_archived_memories(self, mcp_session: ClientSession):
        # Fresh hermetic DB rows are never old enough to auto-archive, so
        # assert the response contract instead of a specific archived row.
        r = await mcp_session.call_tool("archived_memories", {"limit": 100})
        data = parse_json(r)
        assert isinstance(data.get("count"), int), f"Bad archived response: {data}"
        assert isinstance(data.get("results"), list), f"Bad archived response: {data}"

    async def test_consolidate_memories_offline(self, mcp_session: ClientSession):
        # No [models.chat] provider cell in the hermetic env, so the server
        # must answer with a handled error dict, not a crash.
        r = await mcp_session.call_tool("consolidate_memories", {"category": "tech"})
        data = parse_json(r)
        assert "error" in data, f"Expected handled offline error, got: {data}"


# ---------------------------------------------------------------------------
# Legacy composite dispatcher
# ---------------------------------------------------------------------------


class TestLegacyComposite:
    async def test_memory_search_round_trip(self, mcp_session: ClientSession):
        """Legacy ``memory`` dispatcher: add -> action=search returns the row."""
        content = "Gate composite: legacy memory search round trip."
        r = await mcp_session.call_tool(
            "add_memory", {"content": content, "category": "tech"}
        )
        parse(r)

        r = await mcp_session.call_tool(
            "memory", {"action": "search", "query": "legacy memory search"}
        )
        data = parse_json(r)
        memories = data.get("memories", data.get("results", []))
        assert any(m["content"] == content for m in memories), (
            f"Composite search lost the added memory: {data}"
        )

    async def test_memory_stats_deprecation(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("memory", {"action": "stats"})
        data = parse_json(r)
        assert isinstance(data.get("total_memories"), int), f"Bad stats: {data}"
        assert data.get("_deprecation"), "Composite tool missing deprecation notice"


# ---------------------------------------------------------------------------
# Dispatch/transport checks (NOT domain coverage -- Rule 1)
# ---------------------------------------------------------------------------


class TestDispatchChecks:
    async def test_config_status(self, mcp_session: ClientSession):
        r = await mcp_session.call_tool("config", {"action": "status"})
        data = parse_json(r)
        all_keys = str(data.keys()).lower()
        assert "database" in all_keys or "db" in all_keys, (
            f"Missing db info: {list(data.keys())}"
        )


# ---------------------------------------------------------------------------
# Concurrency on one session
# ---------------------------------------------------------------------------


class TestConcurrency:
    async def test_concurrent_calls_on_one_session(self, mcp_session: ClientSession):
        """Requests multiplexed on ONE session all get well-formed answers.

        The server funnels calls onto a single shared sqlite connection, so
        concurrent writes may individually be answered with a handled error
        dict; the transport property under test is that every in-flight
        request is answered and correlated, and that the session stays
        usable afterwards.
        """
        contents = [
            "Gate concurrent: alpha payload.",
            "Gate concurrent: bravo payload.",
            "Gate concurrent: charlie payload.",
        ]
        results = await asyncio.gather(
            *(
                mcp_session.call_tool(
                    "add_memory", {"content": content, "category": "tech"}
                )
                for content in contents
            )
        )
        for r in results:
            data = parse_json(r)
            assert isinstance(data, dict), f"Non-JSON concurrent response: {r}"

        # Liveness after the concurrent burst: a fresh round-trip must work.
        content = "Gate concurrent: sequenced after the burst."
        parse(
            await mcp_session.call_tool(
                "add_memory", {"content": content, "category": "tech"}
            )
        )
        r = await mcp_session.call_tool("search_memory", {"query": "sequenced burst"})
        data = parse_json(r)
        memories = data.get("memories", data.get("results", []))
        assert any(m["content"] == content for m in memories), (
            f"Post-concurrency round-trip lost the memory: {data}"
        )
