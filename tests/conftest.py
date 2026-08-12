"""Shared test fixtures for Mnemo MCP Server."""

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

pytest_plugins = ["conftest_e2e"]

# litellm downloads model_prices_and_context_window.json from raw.githubusercontent
# the first time it is imported. It ships the same file inside the wheel and this
# env var selects that copy, so the import stops depending on the network. Set at
# module scope because litellm reads it during ``litellm.__init__``, which the
# lazy imports in embedder.py can trigger from the first test that runs.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


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
    ``pytest.fail`` is: the leak this guard was written for runs inside two
    nested ``except Exception`` handlers (``CloudEmbeddingBackend
    .check_available`` returns 0, ``server._init_embedding_backend`` logs a
    warning), and an ``Exception`` here is swallowed by both. The test then
    passes while still having gone to the network, which is the failure mode
    the guard exists to remove.
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
    return OutboundNetworkBlocked(
        f"Blocked outbound network access to {_host_text(host)}:{port} "
        "from a unit test.\n"
        "Unit tests must not talk to the internet. Patch the boundary the "
        "call crosses instead -- e.g. patch('mnemo_mcp.embedder.init_backend') "
        "when a server action initialises an embedding backend, or "
        "patch('mcp_core.llm.embedding') / patch('mcp_core.llm.aembedding') "
        "for a direct litellm call. A test that genuinely needs the network "
        "belongs behind one of the @pytest.mark."
        f"{{{','.join(_NETWORK_MARKERS)}}} markers."
    )


@pytest.fixture(autouse=True)
def _block_outbound_network(request, monkeypatch):
    """Fail fast, on every OS, when a unit test reaches the real internet.

    CI run 30755522961 lost its windows-latest job to the 30s pytest-timeout:
    ``test_server_setup_actions.py::TestSetupComplete::test_refreshes_state``
    drove ``config(action="setup_complete")`` through
    ``_init_embedding_backend`` into ``CloudEmbeddingBackend.check_available``,
    which issued a real HTTPS POST via litellm and then stalled reading the
    response headers. ``_DEFAULT_EMBEDDING_CHAIN`` in config.py starts at a
    ``jina_ai/`` model, so no env var is needed for a unit test to leave the
    box. The same request failed fast on Linux, which is why a missing patch
    looked like a Windows-only flake for as long as it did.

    Blocking the syscall converts that whole class of leak into an immediate
    and identical failure everywhere. Loopback stays open on purpose: tests
    that stand up a local server (relay, OAuth callback) must keep working.
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


@pytest.fixture(autouse=True)
def _never_open_a_real_browser(monkeypatch):
    """Keep the GDrive device-code path from hijacking the developer's browser.

    ``credential_state._trigger_gdrive_device_code`` calls ``try_open_browser``
    on the verification URL. Newer mcp-core honours ``MCP_NO_BROWSER``, but the
    import is lazy and older installs lack that guard, so patch the symbol too.
    Tests that assert on the launch patch ``mcp_core.try_open_browser``
    themselves, which shadows this fixture.
    """
    monkeypatch.setenv("MCP_NO_BROWSER", "1")
    monkeypatch.setattr("mcp_core.try_open_browser", lambda url: False, raising=False)


@pytest.fixture(autouse=True)
def _isolate_per_plugin_home(tmp_path_factory, monkeypatch):
    """Redirect ~/ to a per-test tmp dir so PerPluginStore writes don't
    pollute real ~/.mnemo-mcp/ between test runs (or worse, between
    parallel pytest workers in CI). Path.home() reads HOME on POSIX
    and USERPROFILE on Windows."""
    fake_home = tmp_path_factory.mktemp("mnemo_test_home")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))


@pytest.fixture(autouse=True)
def _set_credential_state_configured():
    """Set credential state to CONFIGURED for all tests.

    Prevents _init_embedding_backend / _init_reranker_backend from skipping
    in AWAITING_SETUP mode. Also mocks resolve_credential_state so the
    lifespan startup doesn't reset the state during unit tests.
    Tests that specifically test credential state should call set_state()
    themselves and patch resolve_credential_state separately.
    """
    from unittest.mock import patch

    from mnemo_mcp.credential_state import CredentialState, set_state

    set_state(CredentialState.CONFIGURED)
    with patch(
        "mnemo_mcp.credential_state.resolve_credential_state",
        return_value=CredentialState.CONFIGURED,
    ):
        yield
    set_state(CredentialState.CONFIGURED)


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


# --- added 2026-07-24: keep local test runs from hijacking the developer's browser.
# credential_state/relay flows call mcp_core.try_open_browser(), which opens
# http://127.0.0.1:<port> in the real browser. Newer mcp-core honours
# MCP_NO_BROWSER but older installs do not, so patch the symbol too.
@pytest.fixture(autouse=True)
def _never_open_a_real_browser_local_guard(monkeypatch):
    monkeypatch.setenv("MCP_NO_BROWSER", "1")
    monkeypatch.setenv("SKRET_NO_BROWSER", "1")
    monkeypatch.setattr("mcp_core.try_open_browser", lambda url: False, raising=False)
