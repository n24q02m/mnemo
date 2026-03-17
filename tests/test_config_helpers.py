"""Tests for mnemo_mcp.config helper functions (GPU detection, GGUF support)."""

import sys
from unittest.mock import MagicMock, patch

from mnemo_mcp.config import _detect_gpu, _has_gguf_support, _resolve_local_model


class TestDetectGPU:
    def test_cuda_available(self):
        mock_ort = MagicMock()
        mock_ort.get_available_providers.return_value = [
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]
        with patch.dict(sys.modules, {"onnxruntime": mock_ort}):
            assert _detect_gpu() is True

    def test_dml_available(self):
        mock_ort = MagicMock()
        mock_ort.get_available_providers.return_value = [
            "DmlExecutionProvider",
            "CPUExecutionProvider",
        ]
        with patch.dict(sys.modules, {"onnxruntime": mock_ort}):
            assert _detect_gpu() is True

    def test_no_gpu_provider(self):
        mock_ort = MagicMock()
        mock_ort.get_available_providers.return_value = ["CPUExecutionProvider"]
        with patch.dict(sys.modules, {"onnxruntime": mock_ort}):
            assert _detect_gpu() is False

    def test_import_error(self):
        with patch.dict(sys.modules, {"onnxruntime": None}):
            assert _detect_gpu() is False

    def test_runtime_exception(self):
        mock_ort = MagicMock()
        mock_ort.get_available_providers.side_effect = Exception("Runtime error")
        with patch.dict(sys.modules, {"onnxruntime": mock_ort}):
            assert _detect_gpu() is False


class TestHasGGUFSupport:
    def test_llama_cpp_installed(self):
        mock_llama = MagicMock()
        with patch.dict(sys.modules, {"llama_cpp": mock_llama}):
            assert _has_gguf_support() is True

    def test_llama_cpp_missing(self):
        with patch.dict(sys.modules, {"llama_cpp": None}):
            assert _has_gguf_support() is False

    def test_llama_cpp_import_error(self):
        import builtins

        orig_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "llama_cpp":
                raise ImportError("Mocked ImportError")
            return orig_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            # Ensure sys.modules does not prevent the import call
            with patch.dict(sys.modules):
                if "llama_cpp" in sys.modules:
                    del sys.modules["llama_cpp"]
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
