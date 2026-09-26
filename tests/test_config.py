"""Tests for mnemo_mcp.config — product-local Settings after the de-host.

Provider/auth/cell configuration moved to hull-core (~/.mnemo/config.toml,
see tests for runtime); only env-driven product fields live here.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mnemo_mcp.config import (
    Settings,
    _detect_gpu,
    _has_gguf_support,
    _resolve_local_model,
)


@pytest.fixture(autouse=True)
def clear_caches():
    _detect_gpu.cache_clear()
    yield
    _detect_gpu.cache_clear()


class TestSettingsDefaults:
    def test_defaults(self):
        s = Settings()
        assert s.db_path == ""
        assert s.embedding_dims == 0
        assert s.rerank_enabled is True
        assert s.rerank_top_n == 10
        assert s.compression_enabled is True
        assert s.log_level == "INFO"
        assert s.archive_enabled is True
        assert s.archive_after_days == 90
        assert s.dedup_threshold == 0.9
        assert s.recency_half_life_days == 7
        assert s.kg_auto_enabled is False
        assert s.temporal_supersession_enabled is True


class TestDbPath:
    def test_default_path(self):
        s = Settings()
        expected = Path.home() / ".mnemo" / "memories.db"
        assert s.get_db_path() == expected

    def test_custom_path(self):
        s = Settings(db_path="/tmp/custom.db")
        assert s.get_db_path() == Path("/tmp/custom.db")

    def test_expanduser(self):
        s = Settings(db_path="~/test.db")
        assert s.get_db_path() == Path.home() / "test.db"

    def test_data_dir(self):
        s = Settings(db_path="/tmp/data/test.db")
        assert s.get_data_dir() == Path("/tmp/data")

    def test_data_dir_default(self):
        s = Settings()
        assert s.get_data_dir() == Path.home() / ".mnemo"

    def test_db_path_env(self, monkeypatch):
        """DB_PATH env var is honored (backward-compat)."""
        monkeypatch.setenv("DB_PATH", "/tmp/db_path.db")
        s = Settings()
        assert s.get_db_path() == Path("/tmp/db_path.db")

    def test_mnemo_db_path_env(self, monkeypatch):
        """MNEMO_DB_PATH env var is honored (matches alembic migrations)."""
        monkeypatch.setenv("MNEMO_DB_PATH", "/tmp/x.db")
        s = Settings()
        assert s.get_db_path() == Path("/tmp/x.db")


class TestEmbeddingDims:
    def test_explicit_dims(self):
        s = Settings(embedding_dims=512)
        assert s.resolve_embedding_dims() == 512

    def test_default_zero(self):
        """Without explicit EMBEDDING_DIMS, returns 0 (runtime default)."""
        s = Settings()
        assert s.resolve_embedding_dims() == 0


class TestLocalModels:
    def test_local_embedding_model_override(self, monkeypatch):
        monkeypatch.setenv("LOCAL_EMBEDDING_MODEL", "Org/custom-embed")
        s = Settings()
        assert s.resolve_local_embedding_model() == "Org/custom-embed"

    def test_local_rerank_model_override(self, monkeypatch):
        monkeypatch.setenv("LOCAL_RERANK_MODEL", "Org/custom-reranker")
        s = Settings()
        assert s.resolve_local_rerank_model() == "Org/custom-reranker"

    def test_local_rerank_model_default_is_yesno(self):
        """No override keeps the YesNo ONNX default (~598MB vs ~12GB)."""
        with (
            patch("mnemo_mcp.config._detect_gpu", return_value=False),
            patch("mnemo_mcp.config._has_gguf_support", return_value=False),
        ):
            s = Settings()
            assert (
                s.resolve_local_rerank_model()
                == "n24q02m/Qwen3-Reranker-0.6B-ONNX-YesNo"
            )

    def test_returns_onnx_by_default_settings(self):
        """Returns ONNX model when no GPU or no GGUF support (via Settings)."""
        with (
            patch("mnemo_mcp.config._detect_gpu", return_value=False),
            patch("mnemo_mcp.config._has_gguf_support", return_value=False),
        ):
            s = Settings()
            model = s.resolve_local_embedding_model()
            assert "ONNX" in model

    def test_returns_gguf_with_gpu_and_llama_settings(self):
        """Returns GGUF model when GPU is available and llama-cpp is installed."""
        with (
            patch("mnemo_mcp.config._detect_gpu", return_value=True),
            patch("mnemo_mcp.config._has_gguf_support", return_value=True),
        ):
            s = Settings()
            model = s.resolve_local_embedding_model()
            assert "GGUF" in model


class TestDetectGPU:
    def test_pynvml_with_devices(self):
        _detect_gpu.cache_clear()
        mock_pynvml = MagicMock()
        mock_pynvml.nvmlDeviceGetCount.return_value = 2
        with patch.dict(sys.modules, {"pynvml": mock_pynvml}):
            assert _detect_gpu() is True

    def test_pynvml_zero_devices(self):
        _detect_gpu.cache_clear()
        mock_pynvml = MagicMock()
        mock_pynvml.nvmlDeviceGetCount.return_value = 0
        with patch.dict(sys.modules, {"pynvml": mock_pynvml}):
            assert _detect_gpu() is False

    def test_torch_mps_only(self):
        _detect_gpu.cache_clear()
        mock_torch = MagicMock()
        mock_torch.backends.mps.is_available.return_value = True
        with patch.dict(sys.modules, {"pynvml": None, "torch": mock_torch}):
            assert _detect_gpu() is True

    def test_no_gpu_provider(self):
        _detect_gpu.cache_clear()
        mock_torch = MagicMock()
        mock_torch.backends.mps.is_available.return_value = False
        with patch.dict(sys.modules, {"pynvml": None, "torch": mock_torch}):
            assert _detect_gpu() is False

    def test_import_error(self):
        _detect_gpu.cache_clear()
        with patch.dict(sys.modules, {"pynvml": None, "torch": None}):
            assert _detect_gpu() is False

    def test_runtime_exception(self):
        _detect_gpu.cache_clear()
        mock_pynvml = MagicMock()
        mock_pynvml.nvmlDeviceGetCount.side_effect = Exception("Runtime error")
        with patch.dict(sys.modules, {"pynvml": mock_pynvml, "torch": None}):
            assert _detect_gpu() is False


class TestHasGGUFSupport:
    def test_llama_cpp_installed(self):
        with patch.dict(sys.modules, {"llama_cpp": MagicMock()}):
            assert _has_gguf_support() is True

    def test_llama_cpp_missing(self):
        with patch.dict(sys.modules, {"llama_cpp": None}):
            assert _has_gguf_support() is False


class TestResolveLocalModel:
    def test_gpu_and_gguf(self):
        with (
            patch("mnemo_mcp.config._detect_gpu", return_value=True),
            patch("mnemo_mcp.config._has_gguf_support", return_value=True),
        ):
            assert _resolve_local_model("onnx-model", "gguf-model") == "gguf-model"

    def test_gpu_no_gguf(self):
        with (
            patch("mnemo_mcp.config._detect_gpu", return_value=True),
            patch("mnemo_mcp.config._has_gguf_support", return_value=False),
        ):
            assert _resolve_local_model("onnx-model", "gguf-model") == "onnx-model"

    def test_no_gpu(self):
        with (
            patch("mnemo_mcp.config._detect_gpu", return_value=False),
            patch("mnemo_mcp.config._has_gguf_support", return_value=True),
        ):
            assert _resolve_local_model("onnx-model", "gguf-model") == "onnx-model"
