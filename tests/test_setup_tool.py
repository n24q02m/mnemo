"""Tests for mnemo_mcp.setup_tool -- warmup MCP-callable function.

De-host rework: run_setup_sync (Google Drive auth) is gone; warmup probes the
``[models.embed]`` provider cell and falls back to the local ONNX download.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from mnemo_mcp.setup_tool import run_warmup


class TestClearModelCache:
    """clear_model_cache removes corrupted HF Hub cache directories."""

    def test_removes_existing_cache(self, tmp_path):
        from mnemo_mcp.setup_tool import clear_model_cache

        model_dir = tmp_path / "models--org--model"
        model_dir.mkdir(parents=True)
        (model_dir / "refs").mkdir()
        (model_dir / "blobs").mkdir()
        (model_dir / "blobs" / "abc.incomplete").touch()

        with patch.dict("os.environ", {"FASTRETRIEVAL_CACHE_PATH": str(tmp_path)}):
            result = clear_model_cache("org/model")

        assert result == str(model_dir)
        assert not model_dir.exists()

    def test_ignores_legacy_cache_env_and_uses_public_default(
        self, tmp_path, monkeypatch
    ):
        import fastretrieval

        from mnemo_mcp import setup_tool

        legacy_cache = tmp_path / "legacy"
        public_cache = tmp_path / "public"
        legacy_model = legacy_cache / "models--org--model"
        public_model = public_cache / "models--org--model"
        legacy_model.mkdir(parents=True)
        public_model.mkdir(parents=True)

        monkeypatch.delenv("FASTRETRIEVAL_CACHE_PATH", raising=False)
        monkeypatch.setenv("QWEN3_EMBED_CACHE_PATH", str(legacy_cache))
        public_define = MagicMock(return_value=public_cache)
        monkeypatch.setattr(
            fastretrieval, "define_cache_dir", public_define, raising=False
        )

        result = setup_tool.clear_model_cache("org/model")

        assert result == str(public_model)
        assert not public_model.exists()
        assert legacy_model.exists()
        public_define.assert_called_once_with()

    def test_returns_none_when_cache_missing(self, tmp_path):
        from mnemo_mcp.setup_tool import clear_model_cache

        with patch.dict("os.environ", {"FASTRETRIEVAL_CACHE_PATH": str(tmp_path)}):
            result = clear_model_cache("nonexistent/model")

        assert result is None

    def test_resolve_cache_dir_uses_fastretrieval_public_api(
        self, tmp_path, monkeypatch
    ):
        import fastretrieval

        from mnemo_mcp import setup_tool

        public_cache = tmp_path / "public"
        monkeypatch.delenv("FASTRETRIEVAL_CACHE_PATH", raising=False)
        monkeypatch.delenv("QWEN3_EMBED_CACHE_PATH", raising=False)

        public_define = MagicMock(return_value=public_cache)
        monkeypatch.setattr(
            fastretrieval, "define_cache_dir", public_define, raising=False
        )

        assert setup_tool._resolve_cache_dir() == public_cache
        public_define.assert_called_once_with()


class TestDownloadLocalEmbedding:
    """_download_local_embedding downloads and validates local model."""

    @patch("fastretrieval.TextEmbedding")
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

    @patch("fastretrieval.TextEmbedding")
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
    @patch("fastretrieval.TextEmbedding")
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
    @patch("fastretrieval.TextEmbedding")
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

    @patch("fastretrieval.TextEmbedding")
    def test_non_cache_error_re_raises(self, mock_te):
        from mnemo_mcp.setup_tool import _download_local_embedding

        mock_settings = MagicMock()
        mock_settings.resolve_local_embedding_model.return_value = "org/model"

        mock_te.side_effect = ImportError("fastretrieval not installed")

        with pytest.raises(ImportError, match="not installed"):
            _download_local_embedding(mock_settings)


class TestRunWarmup:
    """run_warmup() -- cell probe first, local ONNX as the fallback path.

    De-host rework: the multi-model cloud chain (``_validate_cloud_models``)
    and the Google sync setup (``run_setup_sync``) were cut; one
    ``[models.embed]`` cell is probed, and when the cell is configured a
    failed probe surfaces ``unavailable`` instead of falling back locally.
    """

    def test_cell_probe_success(self, monkeypatch):

        monkeypatch.setattr("mnemo_mcp.runtime.cell_configured", lambda task: True)
        monkeypatch.setattr(
            "mnemo_mcp.runtime.model_cell",
            lambda task: SimpleNamespace(model="cell-model"),
        )
        backend = MagicMock()
        backend.check_available = AsyncMock(return_value=768)
        mp = patch("mnemo_mcp.embedder.init_backend", return_value=backend)

        with mp:
            result = asyncio.run(run_warmup())

        assert result["status"] == "ok"
        assert result["mode"] == "cloud"
        assert result["embedding"] == {"model": "cell-model", "dims": 768}

    def test_cell_probe_failure_returns_unavailable(self, monkeypatch):
        """A configured cell whose probe reports 0 dims -> unavailable.

        No local fallback in this case: the host explicitly configured the
        cell, so silent local download would mask the misconfiguration.
        """
        monkeypatch.setattr("mnemo_mcp.runtime.cell_configured", lambda task: True)
        backend = MagicMock()
        backend.check_available = AsyncMock(return_value=0)

        with patch("mnemo_mcp.embedder.init_backend", return_value=backend):
            result = asyncio.run(run_warmup())

        assert result["status"] == "error"
        assert result["mode"] == "unavailable"
        assert result["steps"][0]["step"] == "cloud_embedding"
        assert result["steps"][0]["status"] == "error"

    def test_cell_probe_exception_returns_unavailable(self, monkeypatch):
        """init_backend raising surfaces error/unavailable with a warning."""
        monkeypatch.setattr("mnemo_mcp.runtime.cell_configured", lambda task: True)

        with (
            patch(
                "mnemo_mcp.embedder.init_backend",
                side_effect=Exception("auth error"),
            ),
            patch("mnemo_mcp.setup_tool.logger") as mock_logger,
        ):
            result = asyncio.run(run_warmup())

        assert result["status"] == "error"
        assert result["mode"] == "unavailable"
        mock_logger.warning.assert_called()

    async def test_no_cell_downloads_local(self, monkeypatch):
        """No embed cell -> local ONNX download path runs."""
        monkeypatch.setattr("mnemo_mcp.runtime.cell_configured", lambda task: False)
        monkeypatch.setattr(
            "mnemo_mcp.setup_tool._download_local_embedding",
            MagicMock(
                return_value={"step": "local_embedding", "status": "ok", "dims": 768}
            ),
        )

        result = await run_warmup()

        assert result["status"] == "ok"
        assert result["mode"] == "local"
        assert result["steps"][0]["status"] == "ok"

    async def test_local_embedding_disabled_skips_download(self, monkeypatch):
        """DISABLE_LOCAL_EMBED with no cell -> ok/unavailable, download skipped."""
        monkeypatch.setattr("mnemo_mcp.runtime.cell_configured", lambda task: False)
        from mnemo_mcp.config import settings as real_settings

        monkeypatch.setattr(real_settings, "disable_local_embed", True)
        with patch(
            "mnemo_mcp.setup_tool._download_local_embedding",
            new=AsyncMock(side_effect=AssertionError("must not download")),
        ):
            result = await run_warmup()

        assert result["status"] == "ok"
        assert result["mode"] == "unavailable"
        local_step = next(
            step for step in result["steps"] if step["step"] == "local_embedding"
        )
        assert local_step["status"] == "skipped"
        assert "disabled" in local_step["message"].lower()
