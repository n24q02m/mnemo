"""Tests for server lifespan management."""

import asyncio
import pathlib
import sqlite3
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from loguru import logger

# The Cloudflare doubles live with the suites that pin them against
# ``src/worker.ts``; importing them here keeps one description of the Worker.
from test_db_cf import FakeD1Worker
from test_db_cf_vectors import FakeVectorizeWorker

from mnemo_mcp.server import lifespan

_MIGRATION = (
    pathlib.Path(__file__).resolve().parent.parent / "migrations" / "0001_init.sql"
)
_MIGRATION_2 = (
    pathlib.Path(__file__).resolve().parent.parent
    / "migrations"
    / "0002_per_sub_isolation.sql"
)
_MIGRATION_3 = (
    pathlib.Path(__file__).resolve().parent.parent
    / "migrations"
    / "0003_vector_state.sql"
)


@pytest.fixture
def mock_settings():
    with patch("mnemo_mcp.server.settings") as m:
        # Default happy path settings
        m.setup_api_keys.return_value = {"KEY": "123"}
        m.setup_providers.return_value = "sdk"
        m.embedding_chain.return_value = ["test-model"]
        m.resolve_embedding_dims.return_value = 0
        m.resolve_embedding_backend.return_value = "cloud"
        m.sync_enabled = False
        m.get_db_path.return_value = "test.db"
        m.resolve_local_embedding_model.return_value = "local-model"
        yield m


@pytest.fixture
def mock_db():
    # lifespan builds the store through open_memory_db, which picks SQLite or
    # Cloudflare D1 from MEMORY_DB_BACKEND; that factory is the construction
    # site to intercept.
    with patch("mnemo_mcp.server.open_memory_db") as m:
        db_instance = MagicMock()
        # db_path is part of what stats() always returns, on both backends; the
        # startup banner reads it, so a stub without it describes no real store.
        db_instance.stats.return_value = {
            "total_memories": 10,
            "vec_enabled": True,
            "db_path": "test.db",
        }
        db_instance.vec_enabled = True
        m.return_value = db_instance
        yield m


@pytest.fixture
def mock_embedder():
    with (
        patch("mnemo_mcp.embedder.init_backend") as m,
        # Isolate the BYO custom-model registration side effect; tests here
        # exercise backend selection, not qwen3-embed registration.
        patch("mnemo_mcp.server._maybe_register_custom_embed"),
    ):
        backend = MagicMock()
        backend.check_available.return_value = 100
        m.return_value = backend
        yield m


@pytest.fixture
def mock_sync():
    with (
        patch("mnemo_mcp.sync.start_auto_sync") as start,
        patch("mnemo_mcp.sync.stop_auto_sync") as stop,
    ):
        yield start, stop


async def _settle_background_init() -> None:
    """Wait for the background init tasks ``lifespan`` starts.

    ``lifespan`` kicks off embedding and reranker init with
    ``asyncio.create_task`` and keeps the handles to itself, so these tests
    had no signal to wait on and slept a fixed 10ms instead. Each task makes
    several ``asyncio.to_thread`` hops, which do not reliably finish inside
    10ms on a loaded machine, so the assertions could read the context before
    the task had written to it. ``start_auto_sync`` is mocked out here, so
    those two are the only tasks on this loop and draining them is exact.
    """
    current = asyncio.current_task()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 10.0
    while loop.time() < deadline:
        pending = {task for task in asyncio.all_tasks() if task is not current}
        if not pending:
            return
        await asyncio.wait(pending, timeout=deadline - loop.time())
    raise AssertionError("background lifespan init did not finish within 10s")


@pytest.mark.asyncio
async def test_lifespan_happy_path_cloud(
    mock_settings, mock_db, mock_embedder, mock_sync
):
    """Test normal startup with cloud embedding."""
    mock_settings.resolve_embedding_backend.return_value = "cloud"
    mock_settings.embedding_chain.return_value = ["cloud-model"]
    mock_settings.resolve_embedding_dims.return_value = 128

    # Setup backend mock
    backend = mock_embedder.return_value
    backend.check_available.return_value = 128

    server = MagicMock()
    async with lifespan(server) as ctx:
        await _settle_background_init()
        assert ctx["embedding_model"] == "cloud-model"
        assert ctx["embedding_dims"] == 128
        assert ctx["db"] == mock_db.return_value


@pytest.mark.asyncio
async def test_lifespan_sync_enabled(mock_settings, mock_db, mock_embedder, mock_sync):
    """Test auto-sync startup."""
    mock_settings.sync_enabled = True
    mock_settings.sync_folder = "folder"
    mock_settings.sync_interval = 60

    start_sync, stop_sync = mock_sync

    server = MagicMock()
    async with lifespan(server):
        pass

    start_sync.assert_called_once_with(mock_db.return_value)
    stop_sync.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_sync_disabled_skips_legacy_auto_sync(
    mock_settings, mock_db, mock_embedder, mock_sync
):
    """A Cloudflare cutover must not initialize the legacy Google Drive loop."""
    mock_settings.sync_enabled = False
    start_sync, stop_sync = mock_sync

    server = MagicMock()
    async with lifespan(server):
        pass

    start_sync.assert_not_called()
    stop_sync.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_local_backend_explicit(
    mock_settings, mock_db, mock_embedder, mock_sync
):
    """Test explicit local backend configuration."""
    mock_settings.resolve_embedding_backend.return_value = "local"
    mock_settings.resolve_local_embedding_model.return_value = "local-model"
    mock_settings.resolve_embedding_dims.return_value = 0

    backend = mock_embedder.return_value
    backend.check_available.return_value = 384

    server = MagicMock()
    async with lifespan(server) as ctx:
        await _settle_background_init()
        assert ctx["embedding_model"] == "__local__"
        assert ctx["embedding_dims"] == 768  # Default for stored


@pytest.mark.asyncio
async def test_lifespan_api_keys_logging(
    mock_settings, mock_db, mock_embedder, mock_sync
):
    """Test Provider mode is logged during startup."""
    mock_settings.setup_providers.return_value = "sdk"

    server = MagicMock()
    async with lifespan(server):
        pass

    # setup_providers should be called once during lifespan
    mock_settings.setup_providers.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_continues_when_credential_resolution_fails(
    mock_settings, mock_db, mock_embedder, mock_sync
):
    """A transient credential-state failure must not prevent server startup."""
    with (
        patch(
            "mnemo_mcp.credential_state.resolve_credential_state",
            side_effect=RuntimeError("credential probe failed"),
        ) as resolve_state,
        patch("mnemo_mcp.server.logger") as mock_logger,
    ):
        async with lifespan(MagicMock()):
            pass

    resolve_state.assert_called_once_with()
    mock_logger.debug.assert_any_call(
        "Credential resolution not available: credential probe failed"
    )


@pytest.mark.asyncio
async def test_lifespan_explicit_cloud_exception_no_local_fallback(
    mock_settings, mock_db, mock_embedder, mock_sync
):
    """Test no local fallback when explicit cloud model init raises exception."""
    mock_settings.resolve_embedding_backend.return_value = "cloud"
    mock_settings.embedding_chain.return_value = ["crash-model"]
    mock_settings.resolve_embedding_dims.return_value = 0

    # Cloud raises exception -- no local fallback in CONFIGURED state
    mock_embedder.side_effect = Exception("API Error")

    server = MagicMock()
    async with lifespan(server) as ctx:
        await _settle_background_init()
        # Model stays None since cloud failed and no local fallback
        assert ctx["embedding_model"] is None


@pytest.mark.asyncio
async def test_lifespan_all_backends_fail(
    mock_settings, mock_db, mock_embedder, mock_sync
):
    """Test behavior when both cloud and local backends fail."""
    mock_settings.resolve_embedding_backend.return_value = "cloud"
    mock_settings.embedding_chain.return_value = ["crash-model"]

    # Cloud raises, Local raises
    mock_embedder.side_effect = [Exception("Cloud fail"), Exception("Local fail")]

    server = MagicMock()
    async with lifespan(server) as ctx:
        await _settle_background_init()
        assert ctx["embedding_model"] is None
        assert (
            ctx["embedding_dims"] == 768
        )  # Or whatever resolve_embedding_dims returns (0)

    # Should still init DB
    mock_db.return_value.stats.assert_called()


@pytest.fixture
def startup_logs() -> Generator[list[str]]:
    """Collect loguru messages; loguru does not route through pytest's caplog."""
    messages: list[str] = []
    sink_id = logger.add(
        lambda message: messages.append(message.record["message"]),
        level="INFO",
        format="{message}",
    )
    yield messages
    logger.remove(sink_id)


@pytest.fixture
def real_store_settings(mock_settings):
    """``mock_settings`` with the values ``open_memory_db`` really consumes.

    The other tests here never build a store, so the MagicMock defaults are
    enough for them; a real one divides by ``recency_half_life_days`` and
    stamps ``embedding_primary()`` into the store, neither of which survives
    being a MagicMock.
    """
    mock_settings.recency_half_life_days = 7.0
    mock_settings.reindex_on_model_change = False
    mock_settings.embedding_primary.return_value = "test-model"
    return mock_settings


def _banner(messages: list[str]) -> str:
    return next(m for m in messages if m.startswith("Database: "))


class TestStartupLogNamesTheStoreItRead:
    """The startup banner must name the store its memory count came from.

    It printed ``settings.get_db_path()`` next to counts read from whichever
    backend ``MEMORY_DB_BACKEND`` selected, so a D1 deployment announced a
    SQLite file inside its container. This is the first line anyone reads when
    asking "where is my data", which is the worst place to be wrong.

    Both tests let ``open_memory_db`` run for real -- a mocked ``stats()`` would
    only prove the log prints whatever the mock was told to say.
    """

    @pytest.fixture
    def cf_d1_store(self, tmp_path, monkeypatch) -> Generator[None]:
        """Point ``MEMORY_DB_BACKEND=cf-d1`` at the in-process D1 double."""
        from mcp_core.storage.d1 import D1Backend
        from mcp_core.storage.vectorize import VectorizeBackend

        conn = sqlite3.connect(
            tmp_path / "d1.sqlite", isolation_level=None, check_same_thread=False
        )
        conn.executescript(_MIGRATION.read_text(encoding="utf-8"))
        conn.executescript(_MIGRATION_2.read_text(encoding="utf-8"))
        conn.executescript(_MIGRATION_3.read_text(encoding="utf-8"))
        monkeypatch.setenv("MEMORY_DB_BACKEND", "cf-d1")
        monkeypatch.setattr(
            "mnemo_mcp.db_cf.d1_backend_from_env",
            lambda: D1Backend(base_url="http://d1.internal", http=FakeD1Worker(conn)),
        )
        monkeypatch.setattr(
            "mnemo_mcp.db_cf._vectorize_from_env",
            lambda: VectorizeBackend(
                base_url="http://vectorize.internal",
                idx="mnemo-test",
                http=FakeVectorizeWorker(),
            ),
        )
        yield
        conn.close()

    async def test_cf_d1_startup_log_does_not_name_the_sqlite_file(
        self,
        real_store_settings,
        cf_d1_store,
        mock_embedder,
        mock_sync,
        startup_logs,
    ):
        # The path the Cloudflare container is configured with and never opens.
        sqlite_path = pathlib.Path("/data/memories.db")
        real_store_settings.get_db_path.return_value = sqlite_path

        async with lifespan(MagicMock()):
            pass

        banner = _banner(startup_logs)
        assert "cf-d1:http://d1.internal" in banner
        assert str(sqlite_path) not in banner

    async def test_sqlite_startup_log_names_the_sqlite_file(
        self,
        real_store_settings,
        tmp_path,
        monkeypatch,
        mock_embedder,
        mock_sync,
        startup_logs,
    ):
        """The other half of the guard: SQLite must still name its file.

        Reading the store's own answer has to stay honest in both directions --
        a fix that only ever printed the D1 URL would pass the test above.
        """
        monkeypatch.delenv("MEMORY_DB_BACKEND", raising=False)
        sqlite_path = tmp_path / "memories.db"
        real_store_settings.get_db_path.return_value = sqlite_path

        async with lifespan(MagicMock()):
            pass

        assert str(sqlite_path) in _banner(startup_logs)
