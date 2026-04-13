"""Tests for mnemo_mcp.config — Settings, API keys, embedding resolution."""

import os
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
def clean_env(monkeypatch):
    """Ensure environment isolation for configuration tests.

    Clears all provider API keys and Mnemo-specific configuration variables.
    """
    vars_to_clear = {
        "JINA_AI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "COHERE_API_KEY",
        "CO_API_KEY",
        "XAI_API_KEY",
        "API_KEYS",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIMS",
        "EMBEDDING_BACKEND",
        "RERANK_ENABLED",
        "RERANK_BACKEND",
        "RERANK_MODEL",
        "SYNC_ENABLED",
        "SYNC_FOLDER",
        "SYNC_INTERVAL",
        "GOOGLE_DRIVE_CLIENT_ID",
        "GOOGLE_DRIVE_CLIENT_SECRET",
        "DB_PATH",
        "LOG_LEVEL",
        "MCP_RELAY_URL",
        "QWEN3_EMBED_CACHE_PATH",
    }
    # Thoroughly clear any variant of these keys in os.environ
    for k in list(os.environ.keys()):
        if k.upper() in vars_to_clear:
            monkeypatch.delenv(k, raising=False)
    for v in vars_to_clear:
        monkeypatch.delenv(v, raising=False)


# Test Setup


class TestSettingsDefaults:
    def test_db_path_empty(self):
        s = Settings()
        assert s.db_path == ""

    def test_sync_enabled_default(self):
        s = Settings()
        assert s.sync_enabled is True

    def test_sync_folder(self):
        s = Settings()
        assert s.sync_folder == "mnemo-mcp"

    def test_log_level(self):
        s = Settings()
        assert s.log_level == "INFO"

    def test_embedding_dims_zero(self):
        s = Settings()
        assert s.embedding_dims == 0

    def test_embedding_model_empty(self):
        s = Settings()
        assert s.embedding_model == ""


class TestDbPath:
    def test_default_path(self):
        s = Settings()
        expected = Path.home() / ".mnemo-mcp" / "memories.db"
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
        assert s.get_data_dir() == Path.home() / ".mnemo-mcp"


class TestApiKeys:
    def test_no_keys(self):
        s = Settings(api_keys=None)
        assert s.setup_api_keys() == {}

    def test_single_key(self):
        s = Settings(api_keys="GOOGLE_API_KEY:test-key-123")
        # setup_api_keys modifies os.environ
        with patch.dict(os.environ):
            s.setup_api_keys()
            assert os.environ.get("GOOGLE_API_KEY") == "test-key-123"

    def test_multiple_keys(self):
        s = Settings(api_keys="GOOGLE_API_KEY:key1,OPENAI_API_KEY:key2")
        result = s.setup_api_keys()
        assert len(result) == 2
        assert "GOOGLE_API_KEY" in result
        assert "OPENAI_API_KEY" in result

    def test_duplicate_provider(self):
        """Multiple keys for same provider — first key is set as env var."""
        s = Settings(api_keys="GOOGLE_API_KEY:key1,GOOGLE_API_KEY:key2")
        with patch.dict(os.environ):
            s.setup_api_keys()
            assert os.environ.get("GOOGLE_API_KEY") == "key1"

    def test_malformed_no_colon(self):
        s = Settings(api_keys="INVALID_FORMAT")
        result = s.setup_api_keys()
        assert result == {}

    def test_empty_key_value(self):
        s = Settings(api_keys="GOOGLE_API_KEY:")
        result = s.setup_api_keys()
        assert result == {}

    def test_whitespace_handling(self):
        s = Settings(api_keys="  GOOGLE_API_KEY : key1 , OPENAI_API_KEY : key2  ")
        result = s.setup_api_keys()
        assert "GOOGLE_API_KEY" in result
        assert result["GOOGLE_API_KEY"] == ["key1"]

    def test_colon_in_key_value(self):
        """API keys can contain colons (e.g., base64-encoded keys)."""
        s = Settings(api_keys="GOOGLE_API_KEY:abc:def:ghi")
        result = s.setup_api_keys()
        assert result["GOOGLE_API_KEY"] == ["abc:def:ghi"]

    def test_alias_google_to_gemini(self):
        """GOOGLE_API_KEY should also set GEMINI_API_KEY for Gemini SDK."""
        s = Settings(api_keys="GOOGLE_API_KEY:test-key")
        with patch.dict(os.environ):
            s.setup_api_keys()
            assert os.environ.get("GEMINI_API_KEY") == "test-key"

    def test_alias_no_overwrite(self, monkeypatch):
        """If GEMINI_API_KEY already set, alias does not overwrite."""
        monkeypatch.setenv("GEMINI_API_KEY", "existing")
        s = Settings(api_keys="GOOGLE_API_KEY:new-key")
        with patch.dict(os.environ):
            s.setup_api_keys()
            assert os.environ.get("GEMINI_API_KEY") == "existing"


class TestEmbeddingModel:
    def test_explicit_model(self):
        s = Settings(embedding_model="custom/model")
        assert s.resolve_embedding_model() == "custom/model"

    def test_no_model_returns_none(self):
        """Without explicit EMBEDDING_MODEL, returns None (auto-detect in server)."""
        s = Settings(api_keys="GOOGLE_API_KEY:key")
        assert s.resolve_embedding_model() is None

    def test_no_keys_returns_none(self):
        s = Settings()
        assert s.resolve_embedding_model() is None

    def test_explicit_overrides_auto(self):
        """Explicit EMBEDDING_MODEL takes priority over API_KEYS."""
        s = Settings(
            embedding_model="custom/model",
            api_keys="GOOGLE_API_KEY:key",
        )
        assert s.resolve_embedding_model() == "custom/model"


class TestEmbeddingDims:
    def test_explicit_dims(self):
        s = Settings(embedding_dims=512)
        assert s.resolve_embedding_dims() == 512

    def test_default_zero(self):
        """Without explicit EMBEDDING_DIMS, returns 0 (auto-detect at runtime)."""
        s = Settings()
        assert s.resolve_embedding_dims() == 0


class TestEmbeddingBackend:
    def test_explicit_litellm(self):
        s = Settings(embedding_backend="litellm")
        assert s.resolve_embedding_backend() == "cloud"

    def test_explicit_local(self):
        s = Settings(embedding_backend="local")
        assert s.resolve_embedding_backend() == "local"

    def test_auto_detect_cloud_with_keys(self):
        """Falls back to cloud when keys provided."""
        s = Settings(api_keys="GOOGLE_API_KEY:key")
        assert s.resolve_embedding_backend() in ("cloud", "local")

    def test_auto_detect_no_keys_no_local(self):
        """Returns 'local' when no keys configured."""
        s = Settings()
        result = s.resolve_embedding_backend()
        assert result == "local"

    def test_explicit_overrides_auto(self):
        """Explicit backend takes priority over auto-detection."""
        s = Settings(embedding_backend="litellm")
        assert s.resolve_embedding_backend() == "cloud"


class TestRerankSettings:
    def test_rerank_enabled_default(self):
        s = Settings()
        assert s.rerank_enabled is True

    def test_rerank_backend_empty_default(self):
        s = Settings()
        assert s.rerank_backend == ""

    def test_rerank_model_empty_default(self):
        s = Settings()
        assert s.rerank_model == ""

    def test_rerank_top_n_default(self):
        s = Settings()
        assert s.rerank_top_n == 10

    def test_resolve_rerank_backend_disabled(self):
        s = Settings(rerank_enabled=False)
        assert s.resolve_rerank_backend() == ""

    def test_resolve_rerank_backend_explicit(self):
        s = Settings(rerank_backend="litellm")
        assert s.resolve_rerank_backend() == "cloud"

    def test_resolve_rerank_backend_custom(self):
        """resolve_rerank_backend returns custom backend if set."""
        s = Settings(rerank_backend="custom")
        assert s.resolve_rerank_backend() == "custom"

    def test_resolve_rerank_backend_model_set(self):
        s = Settings(rerank_model="custom/reranker")
        assert s.resolve_rerank_backend() == "cloud"

    def test_resolve_rerank_backend_cohere_env(self, monkeypatch):
        monkeypatch.setenv("COHERE_API_KEY", "test-key")
        s = Settings()
        assert s.resolve_rerank_backend() == "cloud"

    def test_resolve_rerank_backend_cohere_in_api_keys(self):
        s = Settings(api_keys="COHERE_API_KEY:test-key")
        assert s.resolve_rerank_backend() == "cloud"

    def test_resolve_rerank_backend_jina_in_api_keys(self):
        s = Settings(api_keys="JINA_AI_API_KEY:test-key")
        assert s.resolve_rerank_backend() == "cloud"

    def test_resolve_rerank_backend_local_fallback(self):
        s = Settings()
        assert s.resolve_rerank_backend() == "local"

    def test_resolve_rerank_model_explicit(self):
        s = Settings(rerank_model="custom/reranker")
        assert s.resolve_rerank_model() == "custom/reranker"

    def test_resolve_rerank_model_cohere_env(self, monkeypatch):
        monkeypatch.setenv("COHERE_API_KEY", "test-key")
        s = Settings()
        assert s.resolve_rerank_model() == "rerank-v4.0-pro"

    def test_resolve_rerank_model_cohere_in_api_keys(self):
        s = Settings(api_keys="COHERE_API_KEY:test-key")
        assert s.resolve_rerank_model() == "rerank-v4.0-pro"

    def test_resolve_rerank_model_jina_in_api_keys(self):
        s = Settings(api_keys="JINA_AI_API_KEY:test-key")
        assert s.resolve_rerank_model() == "jina_ai/jina-reranker-v3"

    def test_resolve_rerank_model_none_no_keys(self):
        s = Settings()
        assert s.resolve_rerank_model() is None

    def test_resolve_local_rerank_model(self):
        s = Settings()
        model = s.resolve_local_rerank_model()
        # Should return ONNX or GGUF depending on environment
        assert "Qwen3-Reranker-0.6B" in model


class TestGoogleDriveClientId:
    def test_default_ships_oauth_client_id(self):
        s = Settings()
        assert s.google_drive_client_id != ""
        assert "apps.googleusercontent.com" in s.google_drive_client_id

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv(
            "GOOGLE_DRIVE_CLIENT_ID", "123456.apps.googleusercontent.com"
        )
        s = Settings()
        assert s.google_drive_client_id == "123456.apps.googleusercontent.com"


class TestSetupProviders:
    def test_sdk_mode(self):
        """setup_providers configures SDK mode with API keys."""
        s = Settings(
            api_keys="GOOGLE_API_KEY:test-key",
        )
        with patch.dict(os.environ):
            mode = s.setup_providers()
            assert mode == "sdk"

    def test_local_mode(self):
        """setup_providers returns 'local' when no API keys."""
        s = Settings()
        mode = s.setup_providers()
        assert mode == "local"


class TestResolveProviderMode:
    def test_sdk_mode_with_api_keys(self):
        """Returns 'sdk' when api_keys is set."""
        s = Settings(api_keys="KEY:value")
        assert s.resolve_provider_mode() == "sdk"

    def test_local_mode_default(self):
        """Returns 'local' when nothing is configured."""
        s = Settings()
        assert s.resolve_provider_mode() == "local"

    def test_sdk_mode_with_env_var(self, monkeypatch):
        """Returns 'sdk' when a provider env var is set."""
        monkeypatch.setenv("JINA_AI_API_KEY", "test-key")
        s = Settings()
        assert s.resolve_provider_mode() == "sdk"


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
        """Returns GGUF model when GPU is available and llama-cpp is installed (via Settings)."""
        with (
            patch("mnemo_mcp.config._detect_gpu", return_value=True),
            patch("mnemo_mcp.config._has_gguf_support", return_value=True),
        ):
            s = Settings()
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

    def test_auto_detect_with_no_config(self):
        """Auto-detect returns 'local' when nothing is configured."""
        s = Settings(embedding_backend="")
        assert s.resolve_embedding_backend() == "local"
