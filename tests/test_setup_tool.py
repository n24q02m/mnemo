"""Tests for mnemo_mcp.setup_tool -- warmup and setup_sync MCP-callable functions."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class TestClearModelCache:
    """clear_model_cache removes corrupted HF Hub cache directories."""

    def test_removes_existing_cache(self, tmp_path):
        from mnemo_mcp.setup_tool import clear_model_cache

        model_dir = tmp_path / "models--org--model"
        model_dir.mkdir(parents=True)
        (model_dir / "refs").mkdir()
        (model_dir / "blobs").mkdir()
        (model_dir / "blobs" / "abc.incomplete").touch()

        with patch.dict("os.environ", {"QWEN3_EMBED_CACHE_PATH": str(tmp_path)}):
            result = clear_model_cache("org/model")

        assert result == str(model_dir)
        assert not model_dir.exists()

    def test_returns_none_when_cache_missing(self, tmp_path):
        from mnemo_mcp.setup_tool import clear_model_cache

        with patch.dict("os.environ", {"QWEN3_EMBED_CACHE_PATH": str(tmp_path)}):
            result = clear_model_cache("nonexistent/model")

        assert result is None


class TestValidateCloudModels:
    """_validate_cloud_models checks cloud embedding availability."""

    @patch("mnemo_mcp.setup_tool._EMBEDDING_CANDIDATES", ["gemini/model-1"])
    @patch("mnemo_mcp.embedder.init_backend")
    def test_cloud_ready(self, mock_init):
        from mnemo_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = None

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init.return_value = mock_backend

        result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is True
        assert result["model"] == "gemini/model-1"
        assert result["dims"] == 768

    @patch("mnemo_mcp.setup_tool._EMBEDDING_CANDIDATES", ["model-a"])
    @patch("mnemo_mcp.embedder.init_backend")
    def test_cloud_not_ready(self, mock_init):
        from mnemo_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = None

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 0
        mock_init.return_value = mock_backend

        result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is False

    @patch("mnemo_mcp.setup_tool._EMBEDDING_CANDIDATES", ["model-a"])
    @patch("mnemo_mcp.embedder.init_backend")
    def test_explicit_model_tried_first(self, mock_init):
        from mnemo_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = "explicit/model"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 512
        mock_init.return_value = mock_backend

        result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is True
        mock_init.assert_called_once_with("cloud", "explicit/model")

    @patch("mnemo_mcp.setup_tool._EMBEDDING_CANDIDATES", ["model-a"])
    @patch("mnemo_mcp.embedder.init_backend")
    def test_cloud_exception_returns_not_ready(self, mock_init):
        from mnemo_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.resolve_embedding_model.return_value = None

        mock_init.side_effect = Exception("auth error")

        result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is False


class TestDownloadLocalEmbedding:
    """_download_local_embedding downloads and validates local model."""

    @patch("qwen3_embed.TextEmbedding")
    def test_success(self, mock_te):
        from mnemo_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "test/model"

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1, 0.2, 0.3])])
        mock_te.return_value = mock_model

        result = _download_local_embedding(mock_settings)

        assert result["status"] == "ok"
        assert result["model"] == "test/model"
        assert result["dims"] == 3

    @patch("qwen3_embed.TextEmbedding")
    def test_empty_result_returns_warning(self, mock_te):
        from mnemo_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "model"

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([])
        mock_te.return_value = mock_model

        result = _download_local_embedding(mock_settings)

        assert result["status"] == "warning"
        assert "empty" in result["message"].lower()

    @patch("mnemo_mcp.setup_tool.clear_model_cache")
    @patch("qwen3_embed.TextEmbedding")
    def test_corrupted_cache_clears_and_retries(self, mock_te, mock_clear):
        from mnemo_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "org/model"

        exc = Exception("[ONNXRuntimeError] : 3 : NO_SUCHFILE : file doesn't exist")
        mock_model_ok = MagicMock()
        mock_model_ok.embed.return_value = iter([np.array([0.1, 0.2])])
        mock_te.side_effect = [exc, mock_model_ok]

        result = _download_local_embedding(mock_settings)

        assert result["status"] == "ok"
        assert result.get("retried") is True
        mock_clear.assert_called_once_with("org/model")

    @patch("mnemo_mcp.setup_tool.clear_model_cache")
    @patch("qwen3_embed.TextEmbedding")
    def test_corrupted_cache_retry_fails(self, mock_te, mock_clear):
        from mnemo_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "org/model"

        exc = Exception("[ONNXRuntimeError] : 3 : NO_SUCHFILE : file doesn't exist")
        mock_model_retry = MagicMock()
        mock_model_retry.embed.return_value = iter([])
        mock_te.side_effect = [exc, mock_model_retry]

        result = _download_local_embedding(mock_settings)

        assert result["status"] == "warning"
        assert "cache clear" in result["message"].lower()

    @patch("qwen3_embed.TextEmbedding")
    def test_non_cache_error_re_raises(self, mock_te):
        from mnemo_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "org/model"

        mock_te.side_effect = ImportError("qwen3_embed not installed")

        with pytest.raises(ImportError, match="not installed"):
            _download_local_embedding(mock_settings)


class TestRunWarmup:
    """run_warmup() async function for MCP tool."""

    @patch("mnemo_mcp.setup_tool._EMBEDDING_CANDIDATES", ["gemini/model-1"])
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.setup_tool.settings")
    async def test_cloud_embedding_success(self, mock_settings, mock_init):
        from mnemo_mcp.setup_tool import run_warmup

        mock_settings.setup_api_keys.return_value = {"GEMINI_API_KEY": "key"}
        mock_settings.resolve_embedding_model.return_value = None

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init.return_value = mock_backend

        result = await run_warmup()

        assert result["status"] == "ok"
        assert result["mode"] == "cloud"
        assert result["embedding"]["model"] == "gemini/model-1"
        assert result["embedding"]["dims"] == 768

    @patch("qwen3_embed.TextEmbedding")
    @patch("mnemo_mcp.setup_tool.settings")
    async def test_no_api_keys_downloads_local(self, mock_settings, mock_te):
        from mnemo_mcp.setup_tool import run_warmup

        mock_settings.setup_api_keys.return_value = {}
        mock_settings.resolve_local_embedding_model.return_value = "test/model"

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1, 0.2, 0.3])])
        mock_te.return_value = mock_model

        result = await run_warmup()

        assert result["status"] == "ok"
        assert result["mode"] == "local"
        assert len(result["steps"]) == 1
        assert result["steps"][0]["status"] == "ok"

    @patch("qwen3_embed.TextEmbedding")
    @patch("mnemo_mcp.setup_tool._EMBEDDING_CANDIDATES", ["model-a"])
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.setup_tool.settings")
    async def test_cloud_fail_falls_back_to_local(
        self, mock_settings, mock_init, mock_te
    ):
        from mnemo_mcp.setup_tool import run_warmup

        mock_settings.setup_api_keys.return_value = {"KEY": "val"}
        mock_settings.resolve_embedding_model.return_value = None
        mock_settings.resolve_local_embedding_model.return_value = "local/model"

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 0
        mock_init.return_value = mock_backend

        mock_model = MagicMock()
        mock_model.embed.return_value = iter([np.array([0.1])])
        mock_te.return_value = mock_model

        result = await run_warmup()

        assert result["status"] == "ok"
        assert result["mode"] == "local"
        # Should have fallback step + local embedding step
        assert any(s.get("status") == "fallback" for s in result["steps"])


class TestRunSetupSync:
    """run_setup_sync() async function for MCP tool."""

    @patch("mnemo_mcp.token_store.get_token_path")
    @patch("mnemo_mcp.token_store.save_token")
    @patch("mnemo_mcp.sync._extract_token")
    @patch("mnemo_mcp.sync._get_rclone_path")
    async def test_success_drive(
        self, mock_get_path, mock_extract, mock_save, mock_token_path
    ):
        from mnemo_mcp.setup_tool import run_setup_sync

        mock_rclone = MagicMock()
        mock_get_path.return_value = mock_rclone

        mock_extract.return_value = '{"access_token": "abc"}'
        mock_token_path.return_value = "/home/user/.mnemo-mcp/tokens/drive.json"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='{"access_token": "abc"}'
            )
            result = await run_setup_sync("drive")

        assert result["status"] == "authenticated"
        assert result["provider"] == "drive"
        assert result["remote_name"] == "gdrive"
        mock_save.assert_called_once()

    @patch("mnemo_mcp.sync._get_rclone_path")
    @patch("mnemo_mcp.sync._download_rclone")
    async def test_rclone_download_failure(self, mock_download, mock_get_path):
        from mnemo_mcp.setup_tool import run_setup_sync

        mock_get_path.return_value = None
        mock_download.return_value = None

        result = await run_setup_sync("drive")

        assert result["status"] == "error"
        assert "download rclone" in result["error"].lower()

    @patch("mnemo_mcp.sync._get_rclone_path")
    async def test_authorize_fails(self, mock_get_path):
        from mnemo_mcp.setup_tool import run_setup_sync

        mock_get_path.return_value = MagicMock()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = await run_setup_sync("drive")

        assert result["status"] == "error"
        assert "failed" in result["error"].lower()

    @patch("mnemo_mcp.sync._extract_token")
    @patch("mnemo_mcp.sync._get_rclone_path")
    async def test_token_extraction_failure(self, mock_get_path, mock_extract):
        from mnemo_mcp.setup_tool import run_setup_sync

        mock_get_path.return_value = MagicMock()
        mock_extract.return_value = None

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="no token here")
            result = await run_setup_sync("drive")

        assert result["status"] == "error"
        assert "extract token" in result["error"].lower()

    @patch("mnemo_mcp.sync._extract_token")
    @patch("mnemo_mcp.sync._get_rclone_path")
    async def test_invalid_token_json(self, mock_get_path, mock_extract):
        from mnemo_mcp.setup_tool import run_setup_sync

        mock_get_path.return_value = MagicMock()
        mock_extract.return_value = "not valid json {"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="output")
            result = await run_setup_sync("drive")

        assert result["status"] == "error"
        assert "invalid token" in result["error"].lower()

    @patch("mnemo_mcp.token_store.get_token_path")
    @patch("mnemo_mcp.token_store.save_token")
    @patch("mnemo_mcp.sync._extract_token")
    @patch("mnemo_mcp.sync._get_rclone_path")
    async def test_non_drive_provider(
        self, mock_get_path, mock_extract, mock_save, mock_token_path
    ):
        from mnemo_mcp.setup_tool import run_setup_sync

        mock_get_path.return_value = MagicMock()
        mock_extract.return_value = '{"access_token": "xyz"}'
        mock_token_path.return_value = "/tokens/dropbox.json"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="token output")
            result = await run_setup_sync("dropbox")

        assert result["status"] == "authenticated"
        assert result["provider"] == "dropbox"
        assert result["remote_name"] == "dropbox"
        assert result["next_steps"]["SYNC_PROVIDER"] == "dropbox"

    @patch("mnemo_mcp.token_store.get_token_path")
    @patch("mnemo_mcp.token_store.save_token")
    @patch("mnemo_mcp.sync._extract_token")
    @patch("mnemo_mcp.sync._download_rclone")
    @patch("mnemo_mcp.sync._get_rclone_path")
    async def test_downloads_rclone_when_not_found(
        self, mock_get_path, mock_download, mock_extract, mock_save, mock_token_path
    ):
        from mnemo_mcp.setup_tool import run_setup_sync

        mock_get_path.return_value = None
        mock_download.return_value = MagicMock()
        mock_extract.return_value = '{"access_token": "abc"}'
        mock_token_path.return_value = "/tokens/drive.json"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="output")
            result = await run_setup_sync("drive")

        assert result["status"] == "authenticated"
        mock_download.assert_called_once()
