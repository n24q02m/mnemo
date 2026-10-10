"""Spawn the real mnemo HTTP MCP server for live tests.

De-host: mnemo has no stdio mode — ``python -m mnemo`` binds the HTTP MCP
endpoint at ``http://host:port/mcp`` (auth per ``~/.mnemo/config.toml``;
``no-auth`` on loopback is the default). These helpers spawn that server in
a subprocess on an ephemeral loopback port and hand out MCP
``ClientSession``s over the streamable-HTTP transport. Everything stays on
loopback with a tmp instance home -- no network, no credentials.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


def free_port() -> int:
    """Reserve an ephemeral loopback port for the spawned server."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def spawn_mnemo_server(
    env: dict[str, str], *, port: int, log_path: Path
) -> subprocess.Popen[bytes]:
    """Start ``python -m mnemo`` bound to ``127.0.0.1:port``.

    MNEMO_HOST/MNEMO_PORT are set here (not by the caller) so the bind is
    always the test's ephemeral loopback. Server logs go to ``log_path``.
    Returns the running subprocess; the caller owns termination
    (see ``mnemo_http_server``).
    """
    env = {**env, "MNEMO_HOST": "127.0.0.1", "MNEMO_PORT": str(port)}
    log_fh = open(log_path, "ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "mnemo"],
        env=env,
        stdout=log_fh,
        stderr=log_fh,
        close_fds=True,
    )
    log_fh.close()  # the child owns its inherited handle
    return proc


def _log_tail(log_path: Path, chars: int = 2000) -> str:
    try:
        return log_path.read_text(errors="replace")[-chars:]
    except OSError:
        return "<no log>"


def wait_until_up(
    proc: subprocess.Popen[bytes], port: int, log_path: Path, timeout: float = 120.0
) -> None:
    """Block until the spawned server answers HTTP (or die with its log)."""
    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"mnemo server exited with {proc.returncode} before accepting "
                f"connections; log {log_path}:\n{_log_tail(log_path)}"
            )
        try:
            # Any HTTP response (incl. 4xx from the auth layer or the
            # streamable endpoint) means the listener is serving requests.
            httpx.get(url, timeout=2.0)
            return
        except httpx.HTTPError:
            time.sleep(0.25)
    raise RuntimeError(
        f"mnemo server on port {port} never came up; log {log_path}:\n"
        f"{_log_tail(log_path)}"
    )


@asynccontextmanager
async def mcp_client_session(
    port: int, *, timeout: float = 120.0
) -> AsyncGenerator[ClientSession]:
    """Yield an initialized MCP ``ClientSession`` over streamable HTTP."""
    url = f"http://127.0.0.1:{port}/mcp"
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
    ) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


@asynccontextmanager
async def mnemo_http_server(env: dict[str, str], log_path: Path) -> AsyncGenerator[int]:
    """Spawn the server, wait for readiness, yield its port, then stop it."""
    port = free_port()
    proc = spawn_mnemo_server(env, port=port, log_path=log_path)
    try:
        wait_until_up(proc, port, log_path)
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
