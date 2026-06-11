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

    @patch("mnemo_mcp.embedder.init_backend")
    def test_cloud_ready(self, mock_init):
        from mnemo_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.embedding_chain.return_value = ["gemini/model-1"]

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 768
        mock_init.return_value = mock_backend

        result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is True
        assert result["model"] == "gemini/model-1"
        assert result["dims"] == 768

    @patch("mnemo_mcp.embedder.init_backend")
    def test_cloud_not_ready(self, mock_init):
        from mnemo_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.embedding_chain.return_value = ["model-a"]

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 0
        mock_init.return_value = mock_backend

        result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is False

    @patch("mnemo_mcp.embedder.init_backend")
    def test_explicit_model_tried_first(self, mock_init):
        from mnemo_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.embedding_chain.return_value = ["explicit/model"]

        mock_backend = MagicMock()
        mock_backend.check_available.return_value = 512
        mock_init.return_value = mock_backend

        result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is True
        mock_init.assert_called_once_with("cloud", "explicit/model")

    @patch("mnemo_mcp.embedder.init_backend")
    def test_cloud_exception_returns_not_ready(self, mock_init):
        from mnemo_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.embedding_chain.return_value = ["model-a"]

        mock_init.side_effect = Exception("auth error")

        result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is False

    @patch("mnemo_mcp.embedder.init_backend")
    def test_cloud_first_candidate_fails_continues_to_next(self, mock_init):
        from mnemo_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.embedding_chain.return_value = ["fail-model", "success-model"]

        mock_backend_success = MagicMock()
        mock_backend_success.check_available.return_value = 1024

        def side_effect(mode, model):
            if model == "fail-model":
                raise Exception("Service unavailable")
            return mock_backend_success

        mock_init.side_effect = side_effect

        result = _validate_cloud_models(mock_settings)

        assert result["cloud_ready"] is True
        assert result["model"] == "success-model"
        assert result["dims"] == 1024

    @patch("mnemo_mcp.embedder.init_backend")
    def test_cloud_all_candidates_fail_returns_not_ready(self, mock_init):
        from mnemo_mcp.setup_tool import _validate_cloud_models

        mock_settings = MagicMock()
        mock_settings.embedding_chain.return_value = ["fail-1", "fail-2"]

        mock_init.side_effect = Exception("Service unavailable")

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

    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.setup_tool.settings")
    async def test_cloud_embedding_success(self, mock_settings, mock_init):
        from mnemo_mcp.setup_tool import run_warmup

        mock_settings.setup_api_keys.return_value = {"GEMINI_API_KEY": "key"}
        mock_settings.embedding_chain.return_value = ["gemini/model-1"]

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
    @patch("mnemo_mcp.embedder.init_backend")
    @patch("mnemo_mcp.setup_tool.settings")
    async def test_cloud_fail_falls_back_to_local(
        self, mock_settings, mock_init, mock_te
    ):
        from mnemo_mcp.setup_tool import run_warmup

        mock_settings.setup_api_keys.return_value = {"KEY": "val"}
        mock_settings.embedding_chain.return_value = ["model-a"]
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
    @patch("mnemo_mcp.sync.setup_google_auth", new_callable=MagicMock)
    @patch("mnemo_mcp.setup_tool.settings")
    async def test_success(self, mock_settings, mock_auth, mock_token_path):
        from unittest.mock import AsyncMock

        from mnemo_mcp.setup_tool import run_setup_sync

        mock_settings.google_drive_client_id = "client123"
        mock_auth.return_value = AsyncMock(return_value=True)()
        mock_token_path.return_value = "/home/user/.mnemo-mcp/tokens/google_drive.json"

        result = await run_setup_sync()

        assert result["status"] == "authenticated"
        assert result["provider"] == "google_drive"

    @patch("mnemo_mcp.setup_tool.settings")
    async def test_no_client_id(self, mock_settings):
        from mnemo_mcp.setup_tool import run_setup_sync

        mock_settings.google_drive_client_id = ""

        result = await run_setup_sync()

        assert result["status"] == "error"
        assert "GOOGLE_DRIVE_CLIENT_ID" in result["error"]

    @patch("mnemo_mcp.sync.setup_google_auth", new_callable=MagicMock)
    @patch("mnemo_mcp.setup_tool.settings")
    async def test_auth_failure(self, mock_settings, mock_auth):
        from unittest.mock import AsyncMock

        from mnemo_mcp.setup_tool import run_setup_sync

        mock_settings.google_drive_client_id = "client123"
        mock_auth.return_value = AsyncMock(return_value=False)()

        result = await run_setup_sync()

        assert result["status"] == "error"
        assert "failed" in result["error"].lower()
