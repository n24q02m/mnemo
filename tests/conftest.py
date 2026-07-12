"""Shared test fixtures for Mnemo MCP Server."""

# Force-import fastmcp BEFORE test_security_log_level.py loads its
# module-level ``patch("importlib.metadata.version")``. Once fastmcp is
# cached in sys.modules, later imports skip its ``__init__`` (which would
# otherwise try to resolve its own version via the leaked mock).
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import fastmcp  # noqa: F401
import pytest

from mnemo_mcp.db import MemoryDB

pytest_plugins = ["conftest_e2e"]


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
