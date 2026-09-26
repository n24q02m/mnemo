"""Shared test fixtures for Mnemo MCP Server (de-hosted stack, hull-core)."""

# Force-import fastmcp BEFORE test_security_log_level.py loads its
# module-level ``patch("importlib.metadata.version")``. Once fastmcp is
# cached in sys.modules, later imports skip its ``__init__`` (which would
# otherwise try to resolve its own version via the leaked mock).
import ipaddress
import os
import socket
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import fastmcp  # noqa: F401
import pytest

from mnemo_mcp.db import MemoryDB

# ---------------------------------------------------------------------------
# Outbound network guard
# ---------------------------------------------------------------------------

# Markers for tests that are allowed to reach the real internet. Every one of
# them is deselected by ``addopts`` in pyproject.toml, but each must still run
# when it is selected by hand (``pytest -m live`` and friends).
_NETWORK_MARKERS = ("integration", "live", "full", "e2e")

# Names that resolve to this machine. Numeric addresses are classified by
# ``ipaddress`` rather than listed here.
_LOOPBACK_HOSTNAMES = frozenset(
    {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
)


class OutboundNetworkBlocked(BaseException):
    """A test tried to open a connection that leaves this machine.

    Derived from ``BaseException`` -- not ``Exception`` -- for the same reason
    ``pytest.fail`` is: the leak this guard was written for ran inside nested
    ``except Exception`` handlers that log a warning and keep going, so an
    ``Exception`` here was swallowed and the test passed while still having
    gone to the network.
    """


def _host_text(host: object) -> str:
    """Normalise a host as it may arrive at the socket layer.

    anyio hands ``getaddrinfo`` an ASCII-encoded host, so ``bytes`` has to be
    decoded rather than ``str()``-ed: ``str(b"127.0.0.1")`` is
    ``"b'127.0.0.1'"``, which parses as no address at all and would get
    loopback blocked on every async client in the suite.
    """
    if isinstance(host, bytes | bytearray):
        host = bytes(host).decode("ascii", "replace")
    return str(host).strip("[]")


def _is_local_host(host: object) -> bool:
    """True when ``host`` cannot address a peer outside this machine.

    ``None`` and ``""`` are the wildcard forms passed when binding a listener,
    and ``0.0.0.0`` / ``::`` are the unspecified addresses -- none of them name
    a remote peer, so all stay allowed alongside the loopback range.
    """
    if host is None or host == "" or host == b"":
        return True
    text = _host_text(host)
    if text in _LOOPBACK_HOSTNAMES:
        return True
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def _blocked(host: object, port: object) -> OutboundNetworkBlocked:
    markers = ",".join(_NETWORK_MARKERS)
    return OutboundNetworkBlocked(
        f"Blocked outbound network access to {_host_text(host)}:{port} "
        "from a unit test.\n"
        "Unit tests must not talk to the internet. Patch the boundary the "
        "call crosses instead -- e.g. patch('mnemo_mcp.embedder.init_backend') "
        "or patch('mnemo_mcp.embedder._cell_client') for embedding backends, "
        "patch('mnemo_mcp.reranker.init_reranker') for rerankers, or "
        "patch('mnemo_mcp.runtime.provider_client') / "
        "patch('mnemo_mcp.llm._get_client') for provider-cell calls. A test "
        "that genuinely needs the network belongs behind one of the "
        f"@pytest.mark.{{{markers}}} markers."
    )


@pytest.fixture(autouse=True)
def _block_outbound_network(request, monkeypatch):
    """Fail fast, on every OS, when a unit test reaches the real internet.

    Blocking the syscall converts the whole class of network leak into an
    immediate and identical failure everywhere. Loopback stays open on
    purpose: tests that stand up a local HTTP server (the hull auth
    surface) must keep working.
    """
    if any(request.node.get_closest_marker(m) for m in _NETWORK_MARKERS):
        return

    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _check_address(address: object) -> None:
        # AF_UNIX addresses are str/bytes paths and never leave the machine.
        if not isinstance(address, tuple) or not address:
            return
        host = address[0]
        port = address[1] if len(address) > 1 else None
        if not _is_local_host(host):
            raise _blocked(host, port)

    def guarded_getaddrinfo(host, port, *args, **kwargs):
        # Resolution is guarded too, so the error can name the host the caller
        # asked for rather than whichever address DNS happened to return.
        if not _is_local_host(host):
            raise _blocked(host, port)
        return real_getaddrinfo(host, port, *args, **kwargs)

    def guarded_connect(self, address, *args, **kwargs):
        _check_address(address)
        return real_connect(self, address, *args, **kwargs)

    def guarded_connect_ex(self, address, *args, **kwargs):
        _check_address(address)
        return real_connect_ex(self, address, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)


# ---------------------------------------------------------------------------
# Environment / state isolation
# ---------------------------------------------------------------------------

def _settings_env_keys() -> list[str]:
    """Every env var pydantic-settings would read into ``Settings``."""
    from mnemo_mcp.config import Settings

    keys = {name.upper() for name in Settings.model_fields}
    keys.update({"DB_PATH", "MNEMO_DB_PATH"})  # validation aliases
    return sorted(keys)


@pytest.fixture(autouse=True)
def _isolate_fake_home(tmp_path_factory, monkeypatch):
    """Redirect ~/ to a per-test tmp dir so instance state never leaks.

    The de-hosted runtime derives everything instance-shaped from
    ``~/.mnemo/`` (config.toml, memories.db, per-sub stores), so pointing
    HOME/USERPROFILE at a scratch dir isolates every test from the
    developer's real mnemo state -- and from parallel pytest workers.
    Path.home() reads HOME on POSIX and USERPROFILE on Windows.
    """
    from mnemo_mcp.runtime import reset_settings_cache

    fake_home = tmp_path_factory.mktemp("mnemo_test_home")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture(autouse=True)
def _clear_provider_environment(monkeypatch):
    """Keep unit tests independent of workstation and CI provider secrets."""
    for key in (
        # hull provider cells (the only provider keys the runtime reads).
        "HULL_EMBED_API_KEY",
        "HULL_RERANK_API_KEY",
        "HULL_CHAT_API_KEY",
        "HULL_JEV_SCORE_API_KEY",
    ) + tuple(_settings_env_keys()):
        monkeypatch.delenv(key, raising=False)

    from mnemo_mcp.config import Settings, settings

    # Reset the singleton so tests that mutate it directly (validate_assignment
    # fields, no monkeypatch) start from defaults every test.
    for name, field in Settings.model_fields.items():
        setattr(settings, name, field.get_default(call_default_factory=True))


@pytest.fixture(autouse=True)
def _reset_module_singletons():
    """Drop cached runtime singletons between tests.

    ``runtime.hull_settings`` is mtime-keyed so it mostly self-heals under the
    fake HOME, but the embedder/reranker singletons and the cached chat
    client hold objects built from the previous test's provider cells.
    """
    import mnemo_mcp.embedder as embedder_mod
    import mnemo_mcp.llm as llm_mod
    import mnemo_mcp.reranker as reranker_mod
    from mnemo_mcp.server import _sub_db_cache

    embedder_mod._backend = None
    reranker_mod.clear_reranker()
    llm_mod.reset_client()
    _sub_db_cache.clear()
    yield
    embedder_mod._backend = None
    reranker_mod.clear_reranker()
    llm_mod.reset_client()
    _sub_db_cache.clear()


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path: Path) -> Generator[MemoryDB]:
    """Temporary MemoryDB without embeddings."""
    db = MemoryDB(tmp_path / "test.db", embedding_dims=0)
    yield db
    db.close()


@pytest.fixture
def tmp_db_with_data(tmp_db: MemoryDB) -> MemoryDB:
    """MemoryDB seeded with sample data."""
    tmp_db.add(
        "Python is a programming language",
        category="tech",
        tags=["python", "lang"],
    )
    tmp_db.add(
        "TypeScript is used for web development",
        category="tech",
        tags=["typescript", "web"],
    )
    tmp_db.add(
        "Remember to buy groceries",
        category="personal",
        tags=["todo"],
    )
    tmp_db.add(
        "Meeting at 3pm on Friday",
        category="work",
        tags=["meeting", "schedule"],
    )
    return tmp_db


@pytest.fixture
def mock_ctx(tmp_db: MemoryDB):
    """Mock MCP Context with DB (no embeddings)."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {
        "db": tmp_db,
        "embedding_model": None,
        "embedding_dims": 0,
    }
    return ctx, tmp_db
