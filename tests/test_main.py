"""Tests for mnemo_mcp.__main__ -- pure server entry point."""

from unittest.mock import patch


class TestMainModule:
    """__main__.py is a pure server entry point."""

    def test_main_calls_server_main(self):
        """Importing and running __main__ calls server.main."""
        with patch("mnemo_mcp.server.main") as mock_main:
            from mnemo_mcp.__main__ import main

            main()
            mock_main.assert_called_once()


class TestWarmupInitEmbeddingBackend:
    """Tests for _init_embedding_backend in server.py (background init).

    Must patch 'mnemo_mcp.server.settings' (not config.settings) because
    server.py imports settings at module level. Also must patch
    asyncio.to_thread to avoid threading issues in tests.
    """

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_cloud_explicit_model_success(
        self, mock_settings, mock_init, _mock_thread
    ):
        """When explicit model works, ctx is updated in-place."""
        from unittest.mock import MagicMock

        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.resolve_embedding_model.return_value = "gemini/model"
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "cloud"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 3072
        mock_init.return_value = mock_backend

        ctx: dict = {
            "embedding_model": None,
            "embedding_dims": 768,
        }

        await _init_embedding_backend("sdk", ctx)

        assert ctx["embedding_model"] == "gemini/model"
        assert ctx["embedding_dims"] == 768  # DEFAULT_EMBEDDING_DIMS

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_cloud_auto_detect_candidates(
        self, mock_settings, mock_init, _mock_thread
    ):
        """Auto-detect iterates through _EMBEDDING_CANDIDATES."""
        from unittest.mock import MagicMock

        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "cloud"

        # First candidate fails, second succeeds
        backend_fail = MagicMock()
        backend_fail.check_available.return_value = 0
        backend_ok = MagicMock()
        backend_ok.check_available.return_value = 768
        mock_init.side_effect = [backend_fail, backend_ok]

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}

        await _init_embedding_backend("sdk", ctx)

        assert ctx["embedding_model"] is not None
        assert ctx["embedding_dims"] == 768

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_cloud_unavailable_no_local_fallback(
        self, mock_settings, mock_init, _mock_thread
    ):
        """When cloud model not available, no local fallback in CONFIGURED state."""
        from unittest.mock import MagicMock

        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.resolve_embedding_model.return_value = "model"
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "cloud"

        # Cloud returns 0 dims (not available)
        cloud_backend = MagicMock()
        cloud_backend.check_available.return_value = 0
        mock_init.return_value = cloud_backend

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}

        await _init_embedding_backend("sdk", ctx)

        # No local fallback -- model stays None
        assert ctx["embedding_model"] is None
        # Only cloud was tried (1 call)
        assert mock_init.call_count == 1

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_direct_local_backend(self, mock_settings, mock_init, _mock_thread):
        """When backend_type is 'local', skips cloud entirely."""
        from unittest.mock import MagicMock

        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "local/m"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 1024
        mock_init.return_value = mock_backend

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}

        await _init_embedding_backend("local", ctx)

        mock_init.assert_called_once_with("local", "local/m")
        assert ctx["embedding_model"] == "__local__"

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_local_backend_failure_logs_error(
        self, mock_settings, mock_init, _mock_thread
    ):
        """When local backend also fails, ctx stays with None model."""
        from unittest.mock import MagicMock

        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "local/m"

        mock_backend = MagicMock()
        mock_backend.check_available.side_effect = Exception("import error")
        mock_init.return_value = mock_backend

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}

        await _init_embedding_backend("local", ctx)

        assert ctx["embedding_model"] is None

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.server.logger")
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_local_backend_init_raises_exception(
        self, mock_settings, mock_init, mock_logger, _mock_thread
    ):
        """When init_backend raises exception, logs error and ctx stays None."""
        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "local/m"

        mock_init.side_effect = Exception("Init Backend Failed")

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}
        await _init_embedding_backend("local", ctx)

        assert ctx["embedding_model"] is None
        mock_logger.error.assert_called_with(
            "Local embedding init failed: Init Backend Failed"
        )
