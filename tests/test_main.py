"""Tests for mnemo_mcp.__main__ — CLI dispatcher and warmup."""

import sys
from unittest.mock import MagicMock, patch

import numpy as np


class TestCli:
    """CLI dispatcher routes subcommands correctly."""

    @patch("mnemo_mcp.server.main")
    def test_default_runs_server(self, mock_main):
        from mnemo_mcp.__main__ import _cli

        with patch.object(sys, "argv", ["mnemo-mcp"]):
            _cli()
        mock_main.assert_called_once()

    @patch("mnemo_mcp.server.main")
    def test_unknown_arg_runs_server(self, mock_main):
        from mnemo_mcp.__main__ import _cli

        with patch.object(sys, "argv", ["mnemo-mcp", "--verbose"]):
            _cli()
        mock_main.assert_called_once()

    def test_warmup_subcommand(self):
        with patch("mnemo_mcp.__main__._warmup") as mock_warmup:
            from mnemo_mcp.__main__ import _cli

            with patch.object(sys, "argv", ["mnemo-mcp", "warmup"]):
                _cli()
            mock_warmup.assert_called_once()

    def test_setup_sync_subcommand_with_remote(self):
        with patch("mnemo_mcp.sync.setup_sync") as mock_setup:
            from mnemo_mcp.__main__ import _cli

            with patch.object(sys, "argv", ["mnemo-mcp", "setup-sync", "gdrive"]):
                _cli()
            mock_setup.assert_called_once_with("gdrive")

    def test_setup_sync_default_remote_type(self):
        with patch("mnemo_mcp.sync.setup_sync") as mock_setup:
            from mnemo_mcp.__main__ import _cli

            with patch.object(sys, "argv", ["mnemo-mcp", "setup-sync"]):
                _cli()
            mock_setup.assert_called_once_with("drive")


class TestWarmup:
    """_warmup() pre-downloads models or validates cloud embedding."""

    @patch("mnemo_mcp.server._EMBEDDING_CANDIDATES", ["gemini/model-1"])
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.config.settings")
    def test_cloud_embedding_success_skips_local(self, mock_settings, mock_init):
        """When cloud embedding works, no local model download needed."""
        from mnemo_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {"GEMINI_API_KEY": "key"}
        mock_settings.resolve_embedding_model.return_value = None

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init.return_value = mock_backend

        _warmup()

        mock_init.assert_called_once_with("litellm", "gemini/model-1")
        mock_backend.check_available.assert_called_once()

    @patch("qwen3_embed.TextEmbedding")
    @patch("mnemo_mcp.config.settings")
    def test_no_api_keys_downloads_local(self, mock_settings, mock_te):
        """Without API keys, downloads local model directly."""
        from mnemo_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {}
        mock_settings.resolve_local_embedding_model.return_value = "test/model"

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1, 0.2, 0.3])])
        mock_te.return_value = mock_model

        _warmup()

        mock_te.assert_called_once_with(model_name="test/model")
        mock_model.embed.assert_called_once_with(["warmup test"])

    @patch("qwen3_embed.TextEmbedding")
    @patch("mnemo_mcp.server._EMBEDDING_CANDIDATES", ["model-a"])
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.config.settings")
    def test_cloud_fail_falls_back_to_local(self, mock_settings, mock_init, mock_te):
        """When cloud embedding returns 0 dims, falls back to local."""
        from mnemo_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {"KEY": "val"}
        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_local_embedding_model.return_value = "local/model"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 0
        mock_init.return_value = mock_backend

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1])])
        mock_te.return_value = mock_model

        _warmup()

        mock_te.assert_called_once_with(model_name="local/model")

    @patch("mnemo_mcp.server._EMBEDDING_CANDIDATES", ["other/model"])
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.config.settings")
    def test_explicit_model_tried_first(self, mock_settings, mock_init):
        """When EMBEDDING_MODEL is set, it's tried before candidates."""
        from mnemo_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {"KEY": "val"}
        mock_settings.resolve_embedding_model.return_value = "explicit/model"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 512
        mock_init.return_value = mock_backend

        _warmup()

        # Should try the explicit model, not the candidate
        mock_init.assert_called_once_with("litellm", "explicit/model")

    @patch("qwen3_embed.TextEmbedding")
    @patch("mnemo_mcp.server._EMBEDDING_CANDIDATES", ["model-a"])
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.config.settings")
    def test_cloud_exception_falls_back_to_local(
        self, mock_settings, mock_init, mock_te
    ):
        """When cloud check_available raises, falls back to local."""
        from mnemo_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {"KEY": "val"}
        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_local_embedding_model.return_value = "local/m"

        mock_backend = MagicMock()
        mock_backend.check_available.side_effect = Exception("auth error")
        mock_init.return_value = mock_backend

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1])])
        mock_te.return_value = mock_model

        _warmup()

        mock_te.assert_called_once_with(model_name="local/m")

    @patch("qwen3_embed.TextEmbedding")
    @patch("mnemo_mcp.config.settings")
    def test_local_warmup_test_failure_prints_warning(
        self, mock_settings, mock_te, capsys
    ):
        """When local model embed returns empty, prints WARNING."""
        from mnemo_mcp.__main__ import _warmup

        mock_settings.setup_api_keys.return_value = {}
        mock_settings.resolve_local_embedding_model.return_value = "model"

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([])
        mock_te.return_value = mock_model

        _warmup()

        captured = capsys.readouterr()
        assert "WARNING" in captured.out


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
    async def test_litellm_explicit_model_success(
        self, mock_settings, mock_init, _mock_thread
    ):
        """When explicit model works, ctx is updated in-place."""
        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.resolve_embedding_model.return_value = "gemini/model"
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "litellm"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 3072
        mock_init.return_value = mock_backend

        ctx: dict = {
            "embedding_model": None,
            "embedding_dims": 768,
        }

        await _init_embedding_backend({"GEMINI_API_KEY": "key"}, ctx)

        assert ctx["embedding_model"] == "gemini/model"
        assert ctx["embedding_dims"] == 768  # DEFAULT_EMBEDDING_DIMS

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_litellm_auto_detect_candidates(
        self, mock_settings, mock_init, _mock_thread
    ):
        """Auto-detect iterates through _EMBEDDING_CANDIDATES."""
        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "litellm"

        # First candidate fails, second succeeds
        backend_fail = MagicMock()
        backend_fail.check_available.return_value = 0
        backend_ok = MagicMock()
        backend_ok.check_available.return_value = 768
        mock_init.side_effect = [backend_fail, backend_ok]

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}

        await _init_embedding_backend({"KEY": "val"}, ctx)

        assert ctx["embedding_model"] is not None
        assert ctx["embedding_dims"] == 768

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_local_fallback_when_cloud_unavailable(
        self, mock_settings, mock_init, _mock_thread
    ):
        """Falls back to local when no cloud model works."""
        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.resolve_embedding_model.return_value = "model"
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "litellm"
        mock_settings.resolve_local_embedding_model.return_value = "local/model"

        # Cloud fails, local succeeds
        cloud_backend = MagicMock()
        cloud_backend.check_available.return_value = 0
        local_backend = MagicMock()
        local_backend.check_available.return_value = 1024
        mock_init.side_effect = [cloud_backend, local_backend]

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}

        await _init_embedding_backend({"KEY": "val"}, ctx)

        assert ctx["embedding_model"] == "__local__"

    @patch(
        "mnemo_mcp.server.asyncio.to_thread",
        side_effect=lambda fn, *a, **kw: fn(*a, **kw),
    )
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.server.settings")
    async def test_direct_local_backend(self, mock_settings, mock_init, _mock_thread):
        """When backend_type is 'local', skips cloud entirely."""
        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "local/m"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 1024
        mock_init.return_value = mock_backend

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}

        await _init_embedding_backend({}, ctx)

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
        from mnemo_mcp.server import _init_embedding_backend

        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_embedding_dims.return_value = 0
        mock_settings.resolve_embedding_backend.return_value = "local"
        mock_settings.resolve_local_embedding_model.return_value = "local/m"

        mock_backend = MagicMock()
        mock_backend.check_available.side_effect = Exception("import error")
        mock_init.return_value = mock_backend

        ctx: dict = {"embedding_model": None, "embedding_dims": 768}

        await _init_embedding_backend({}, ctx)

        assert ctx["embedding_model"] is None
