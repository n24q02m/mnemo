"""Additional tests for mnemo_mcp.config -- covering uncovered lines.

Targets: setup_providers (sdk/local branches), resolve_provider_mode.
"""

import sys
from unittest.mock import MagicMock, patch

from mnemo_mcp.config import Settings, _detect_gpu


class TestSetupProviders:
    def test_sdk_mode(self, monkeypatch):
        """setup_providers configures SDK mode with API keys."""
        s = Settings(
            api_keys="GOOGLE_API_KEY:test-key",
        )
        mode = s.setup_providers()
        assert mode == "sdk"
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def test_local_mode(self, monkeypatch):
        """setup_providers returns 'local' when no API keys."""
        for k in (
            "JINA_AI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
            "COHERE_API_KEY",
            "CO_API_KEY",
            "XAI_API_KEY",
        ):
            monkeypatch.delenv(k, raising=False)
        s = Settings(api_keys=None)
        mode = s.setup_providers()
        assert mode == "local"


class TestResolveProviderMode:
    def test_sdk_mode_with_api_keys(self):
        """Returns 'sdk' when api_keys is set."""
        s = Settings(api_keys="KEY:value")
        assert s.resolve_provider_mode() == "sdk"

    def test_local_mode_default(self, monkeypatch):
        """Returns 'local' when nothing is configured."""
        for k in (
            "JINA_AI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
            "COHERE_API_KEY",
            "CO_API_KEY",
            "XAI_API_KEY",
        ):
            monkeypatch.delenv(k, raising=False)
        s = Settings(api_keys=None)
        assert s.resolve_provider_mode() == "local"

    def test_sdk_mode_with_env_var(self, monkeypatch):
        """Returns 'sdk' when a provider env var is set."""
        monkeypatch.setenv("JINA_AI_API_KEY", "test-key")
        s = Settings(api_keys=None)
        assert s.resolve_provider_mode() == "sdk"

    def test_sdk_mode_with_cohere_env(self, monkeypatch):
        """Returns 'sdk' when COHERE_API_KEY env var is set."""
        monkeypatch.setenv("COHERE_API_KEY", "test-key")
        s = Settings(api_keys=None)
        assert s.resolve_provider_mode() == "sdk"


class TestResolveLocalEmbeddingModel:
    def test_returns_onnx_by_default(self):
        """Returns ONNX model when no GPU or no GGUF support."""
        with (
            patch("mnemo_mcp.config._detect_gpu", return_value=False),
            patch("mnemo_mcp.config._has_gguf_support", return_value=False),
        ):
            s = Settings(api_keys=None)
            model = s.resolve_local_embedding_model()
            assert "ONNX" in model

    def test_returns_gguf_with_gpu_and_llama(self):
        """Returns GGUF model when GPU is available and llama-cpp is installed."""
        with (
            patch("mnemo_mcp.config._detect_gpu", return_value=True),
            patch("mnemo_mcp.config._has_gguf_support", return_value=True),
        ):
            s = Settings(api_keys=None)
            model = s.resolve_local_embedding_model()
            assert "GGUF" in model


class TestResolveEmbeddingBackendAuto:
    def test_auto_detect_with_api_keys(self):
        """Auto-detect returns 'cloud' when API keys are set."""
        s = Settings(
            api_keys="COHERE_API_KEY:test",
            embedding_backend="",
        )
        assert s.resolve_embedding_backend() == "cloud"

    def test_auto_detect_with_no_config(self, monkeypatch):
        """Auto-detect returns 'local' when nothing is configured."""
        for k in (
            "JINA_AI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
            "COHERE_API_KEY",
            "CO_API_KEY",
            "XAI_API_KEY",
        ):
            monkeypatch.delenv(k, raising=False)
        s = Settings(embedding_backend="", api_keys=None)
        assert s.resolve_embedding_backend() == "local"

    def test_litellm_backward_compat(self):
        """'litellm' embedding_backend maps to 'cloud'."""
        s = Settings(embedding_backend="litellm", api_keys=None)
        assert s.resolve_embedding_backend() == "cloud"

    def test_litellm_rerank_backward_compat(self):
        """'litellm' rerank_backend maps to 'cloud'."""
        s = Settings(rerank_backend="litellm", api_keys=None)
        assert s.resolve_rerank_backend() == "cloud"


class TestGpuDetectionErrorPaths:
    def test_detect_gpu_import_error(self):
        """_detect_gpu returns False when onnxruntime is not installed."""
        with patch.dict(sys.modules, {"onnxruntime": None}):
            assert _detect_gpu() is False

    def test_detect_gpu_runtime_exception(self):
        """_detect_gpu returns False when get_available_providers raises."""
        mock_ort = MagicMock()
        mock_ort.get_available_providers.side_effect = Exception("Runtime error")
        with patch.dict(sys.modules, {"onnxruntime": mock_ort}):
            assert _detect_gpu() is False
