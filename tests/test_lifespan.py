"""Tests for server lifespan management."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from mnemo_mcp.server import lifespan


@pytest.fixture
def mock_settings():
    with patch("mnemo_mcp.server.settings") as m:
        # Default happy path settings
        m.setup_api_keys.return_value = {"KEY": "123"}
        m.setup_litellm.return_value = "sdk"
        m.get_embedding_litellm_kwargs.return_value = {}
        m.resolve_embedding_model.return_value = "test-model"
        m.resolve_embedding_dims.return_value = 0
        m.resolve_embedding_backend.return_value = "litellm"
        m.sync_enabled = False
        m.get_db_path.return_value = "test.db"
        m.resolve_local_embedding_model.return_value = "local-model"
        yield m


@pytest.fixture
def mock_db():
    with patch("mnemo_mcp.server.MemoryDB") as m:
        db_instance = MagicMock()
        db_instance.stats.return_value = {"total_memories": 10, "vec_enabled": True}
        db_instance.vec_enabled = True
        m.return_value = db_instance
        yield m


@pytest.fixture
def mock_embedder():
    with patch("mnemo_mcp.embedder.init_backend") as m:
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


@pytest.mark.asyncio
async def test_lifespan_happy_path_cloud(
    mock_settings, mock_db, mock_embedder, mock_sync
):
    """Test normal startup with cloud embedding."""
    mock_settings.resolve_embedding_backend.return_value = "litellm"
    mock_settings.resolve_embedding_model.return_value = "cloud-model"
    mock_settings.resolve_embedding_dims.return_value = 128

    # Setup backend mock
    backend = mock_embedder.return_value
    backend.check_available.return_value = 128

    server = MagicMock()
    async with lifespan(server) as ctx:
        await asyncio.sleep(0.01)
        assert ctx["embedding_model"] == "cloud-model"
        assert ctx["embedding_dims"] == 128
        assert ctx["db"] == mock_db.return_value


@pytest.mark.asyncio
async def test_lifespan_sync_enabled(mock_settings, mock_db, mock_embedder, mock_sync):
    """Test auto-sync startup."""
    mock_settings.sync_enabled = True
    mock_settings.sync_remote = "remote"
    mock_settings.sync_folder = "folder"
    mock_settings.sync_interval = 60

    start_sync, stop_sync = mock_sync

    server = MagicMock()
    async with lifespan(server):
        pass

    start_sync.assert_called_once_with(mock_db.return_value)
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
        await asyncio.sleep(0.01)
        assert ctx["embedding_model"] == "__local__"
        assert ctx["embedding_dims"] == 768  # Default for stored


@pytest.mark.asyncio
async def test_lifespan_api_keys_logging(
    mock_settings, mock_db, mock_embedder, mock_sync
):
    """Test LiteLLM mode is logged during startup."""
    mock_settings.setup_litellm.return_value = "sdk"

    server = MagicMock()
    async with lifespan(server):
        pass

    # setup_litellm should be called once during lifespan
    mock_settings.setup_litellm.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_explicit_cloud_exception_fallback(
    mock_settings, mock_db, mock_embedder, mock_sync
):
    """Test fallback when explicit cloud model initialization raises exception."""
    mock_settings.resolve_embedding_backend.return_value = "litellm"
    mock_settings.resolve_embedding_model.return_value = "crash-model"
    mock_settings.resolve_embedding_dims.return_value = 0

    # First call (cloud) raises Exception
    # Second call (local) succeeds
    backend_local = MagicMock()
    backend_local.check_available.return_value = 384

    mock_embedder.side_effect = [Exception("API Error"), backend_local]

    server = MagicMock()
    async with lifespan(server) as ctx:
        await asyncio.sleep(0.01)
        assert ctx["embedding_model"] == "__local__"
        assert ctx["embedding_dims"] == 768


@pytest.mark.asyncio
async def test_lifespan_all_backends_fail(
    mock_settings, mock_db, mock_embedder, mock_sync
):
    """Test behavior when both cloud and local backends fail."""
    mock_settings.resolve_embedding_backend.return_value = "litellm"
    mock_settings.resolve_embedding_model.return_value = "crash-model"

    # Cloud raises, Local raises
    mock_embedder.side_effect = [Exception("Cloud fail"), Exception("Local fail")]

    server = MagicMock()
    async with lifespan(server) as ctx:
        await asyncio.sleep(0.01)
        assert ctx["embedding_model"] is None
        assert (
            ctx["embedding_dims"] == 768
        )  # Or whatever resolve_embedding_dims returns (0)

    # Should still init DB
    mock_db.return_value.stats.assert_called()
