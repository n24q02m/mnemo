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
