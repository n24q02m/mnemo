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
        "MNEMO_DB_PATH",
        "LOG_LEVEL",
        "MCP_RELAY_URL",
        "QWEN3_EMBED_CACHE_PATH",
        "COMPRESSION_ENABLED",
        "COMPRESSION_PROVIDER",
        "COMPRESSION_MODEL",
        "LOCAL_EMBEDDING_MODEL",
        "LOCAL_RERANK_MODEL",
        "LOCAL_EMBEDDING_POOLING",
        "LOCAL_EMBEDDING_DIM",
        "LOCAL_EMBEDDING_NORMALIZE",
        "LOCAL_EMBEDDING_MODEL_FILE",
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
    def test_explicit_models_chain(self):
        s = Settings(embedding_models="custom/model")
        assert s.embedding_primary() == "custom/model"
        assert s.embedding_chain() == ["custom/model"]

    def test_sdk_mode_returns_default_chain(self):
        """Default chain keeps only models whose provider key is configured.

        A GOOGLE/GEMINI key yields the gemini default (jina/openai/cohere
        models are dropped — no key for them).
        """
        s = Settings(api_keys="GOOGLE_API_KEY:key")
        assert s.embedding_primary() == "gemini/gemini-embedding-001"

    def test_sdk_mode_default_filters_to_keyed_models(self):
        """With a Jina key, the jina default model leads the chain."""
        s = Settings(api_keys="JINA_AI_API_KEY:key")
        assert s.embedding_primary() == "jina_ai/jina-embeddings-v5-text-small"

    def test_no_keys_returns_empty(self):
        s = Settings()
        assert s.embedding_chain() == []
        assert s.embedding_primary() is None

    def test_explicit_overrides_default(self):
        """Explicit EMBEDDING_MODELS takes priority over the default chain."""
        s = Settings(
            embedding_models="custom/model",
            api_keys="GOOGLE_API_KEY:key",
        )
        assert s.embedding_primary() == "custom/model"

    def test_legacy_singular_folded_into_chain(self):
        """Deprecated EMBEDDING_MODEL is honored as a single-element chain."""
        s = Settings(embedding_model="custom/model")
        assert s.embedding_chain() == ["custom/model"]


class TestEmbeddingDims:
    def test_explicit_dims(self):
        s = Settings(embedding_dims=512)
        assert s.resolve_embedding_dims() == 512

    def test_default_zero(self):
        """Without explicit EMBEDDING_DIMS, returns 0 (auto-detect at runtime)."""
        s = Settings()
        assert s.resolve_embedding_dims() == 0


class TestEmbeddingBackend:
    def test_deprecated_litellm(self):
        """Deprecated EMBEDDING_BACKEND='litellm' maps to 'cloud'."""
        s = Settings(embedding_backend="litellm")
        assert s.resolve_embedding_backend() == "cloud"

    def test_deprecated_local(self):
        s = Settings(embedding_backend="local")
        assert s.resolve_embedding_backend() == "local"

    def test_inferred_cloud_with_chain(self):
        """Non-empty chain (sdk mode) infers 'cloud'."""
        s = Settings(api_keys="GOOGLE_API_KEY:key")
        assert s.resolve_embedding_backend() == "cloud"

    def test_inferred_local_no_chain(self):
        """Empty chain (no keys) infers 'local'."""
        s = Settings()
        assert s.resolve_embedding_backend() == "local"

    def test_inferred_cloud_with_explicit_models(self):
        """Explicit EMBEDDING_MODELS infers 'cloud' even without API keys."""
        s = Settings(embedding_models="jina_ai/jina-embeddings-v5-text-small")
        assert s.resolve_embedding_backend() == "cloud"

    def test_deprecated_backend_overrides_inference(self):
        """Deprecated explicit backend takes priority over inference."""
        s = Settings(embedding_backend="litellm")
        assert s.resolve_embedding_backend() == "cloud"

    def test_unavailable_when_local_disabled_and_no_chain(self, monkeypatch):
        """DISABLE_LOCAL_EMBED + empty chain -> 'unavailable' (NOT forced)."""
        for v in (
            "EMBEDDING_MODELS",
            "JINA_AI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
            "COHERE_API_KEY",
        ):
            monkeypatch.delenv(v, raising=False)
        s = Settings(
            embedding_backend="", embedding_models="", disable_local_embed=True
        )
        assert s.resolve_embedding_backend() == "unavailable"

    def test_cloud_wins_even_when_local_disabled(self):
        """A configured cloud chain still resolves to 'cloud' with local disabled."""
        s = Settings(
            embedding_models="gemini/gemini-embedding-001", disable_local_embed=True
        )
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

    def test_resolve_rerank_backend_deprecated_litellm(self):
        s = Settings(rerank_backend="litellm")
        assert s.resolve_rerank_backend() == "cloud"

    def test_resolve_rerank_backend_deprecated_custom(self):
        """Deprecated rerank_backend returns custom backend if set."""
        s = Settings(rerank_backend="custom")
        assert s.resolve_rerank_backend() == "custom"

    def test_resolve_rerank_backend_models_set(self):
        s = Settings(rerank_models="custom/reranker")
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

    def test_resolve_rerank_unavailable_when_local_disabled(self, monkeypatch):
        """DISABLE_LOCAL_RERANK + empty chain (rerank enabled) -> 'unavailable'."""
        for v in ("RERANK_MODELS", "JINA_AI_API_KEY", "COHERE_API_KEY"):
            monkeypatch.delenv(v, raising=False)
        s = Settings(
            rerank_enabled=True,
            rerank_backend="",
            rerank_models="",
            disable_local_rerank=True,
        )
        assert s.resolve_rerank_backend() == "unavailable"

    def test_resolve_rerank_disabled_overrides_toggle(self):
        s = Settings(rerank_enabled=False, disable_local_rerank=True)
        assert s.resolve_rerank_backend() == ""

    def test_rerank_chain_explicit(self):
        s = Settings(rerank_models="custom/reranker")
        assert s.rerank_chain() == ["custom/reranker"]
        assert s.rerank_primary() == "custom/reranker"

    def test_rerank_chain_legacy_singular_folded(self):
        s = Settings(rerank_model="custom/reranker")
        assert s.rerank_chain() == ["custom/reranker"]

    def test_rerank_chain_sdk_mode_default(self, monkeypatch):
        # Cohere key -> only the cohere default reranker survives the filter
        # (jina is dropped: no Jina key).
        monkeypatch.setenv("COHERE_API_KEY", "test-key")
        s = Settings()
        assert s.rerank_primary() == "cohere/rerank-v3.5"

    def test_rerank_chain_jina_key_leads(self, monkeypatch):
        monkeypatch.setenv("JINA_AI_API_KEY", "test-key")
        s = Settings()
        assert s.rerank_primary() == "jina_ai/jina-reranker-v3"

    def test_rerank_chain_empty_no_keys(self):
        s = Settings()
        assert s.rerank_chain() == []
        assert s.rerank_primary() is None

    def test_rerank_chain_disabled_returns_empty(self):
        s = Settings(rerank_enabled=False, rerank_models="custom/reranker")
        assert s.rerank_chain() == []

    def test_resolve_rerank_backend_non_rerank_key_infers_local(self):
        """A non-rerank key (OpenAI) leaves the rerank default chain empty
        (no Jina/Cohere key) -> 'local', so reranking still works via ONNX."""
        s = Settings(api_keys="OPENAI_API_KEY:test-key")
        assert s.rerank_chain() == []
        assert s.resolve_rerank_backend() == "local"

    def test_resolve_local_rerank_model(self):
        s = Settings()
        model = s.resolve_local_rerank_model()
        # Should return ONNX or GGUF depending on environment
        assert "Qwen3-Reranker-0.6B" in model

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


class TestGoogleDriveCredentials:
    def test_default_is_empty(self, monkeypatch):
        """Default should not ship hardcoded credentials."""
        monkeypatch.delenv("GOOGLE_DRIVE_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_DRIVE_CLIENT_SECRET", raising=False)
        s = Settings()
        assert s.google_drive_client_id == ""
        assert s.google_drive_client_secret == ""

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv(
            "GOOGLE_DRIVE_CLIENT_ID", "123456.apps.googleusercontent.com"
        )
        monkeypatch.setenv("GOOGLE_DRIVE_CLIENT_SECRET", "test-secret")
        s = Settings()
        assert s.google_drive_client_id == "123456.apps.googleusercontent.com"
        assert s.google_drive_client_secret == "test-secret"


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
        _detect_gpu.cache_clear()
        mock_ort = MagicMock()
        mock_ort.get_available_providers.return_value = [
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]
        with patch.dict(sys.modules, {"onnxruntime": mock_ort}):
            assert _detect_gpu() is True

    def test_dml_available(self):
        _detect_gpu.cache_clear()
        mock_ort = MagicMock()
        mock_ort.get_available_providers.return_value = [
            "DmlExecutionProvider",
            "CPUExecutionProvider",
        ]
        with patch.dict(sys.modules, {"onnxruntime": mock_ort}):
            assert _detect_gpu() is True

    def test_no_gpu_provider(self):
        _detect_gpu.cache_clear()
        mock_ort = MagicMock()
        mock_ort.get_available_providers.return_value = ["CPUExecutionProvider"]
        with patch.dict(sys.modules, {"onnxruntime": mock_ort}):
            assert _detect_gpu() is False

    def test_import_error(self):
        _detect_gpu.cache_clear()
        with patch.dict(sys.modules, {"onnxruntime": None}):
            assert _detect_gpu() is False

    def test_runtime_exception(self):
        _detect_gpu.cache_clear()
        mock_ort = MagicMock()
        mock_ort.get_available_providers.side_effect = Exception("Runtime error")
        with patch.dict(sys.modules, {"onnxruntime": mock_ort}):
            assert _detect_gpu() is False


class TestHasGGUFSupport:
    def test_llama_cpp_installed(self):
        _has_gguf_support.cache_clear()
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            assert _has_gguf_support() is True

    def test_llama_cpp_missing(self):
        _has_gguf_support.cache_clear()
        with patch("importlib.util.find_spec", return_value=None):
            assert _has_gguf_support() is False
            assert _has_gguf_support() is False


@pytest.fixture(autouse=True)
def clear_caches():
    _detect_gpu.cache_clear()
    _has_gguf_support.cache_clear()


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


class TestCompressionSettings:
    """Phase 2: COMPRESSION_ENABLED / PROVIDER / MODEL settings surface."""

    def test_compression_defaults(self):
        s = Settings()
        assert s.compression_enabled is True
        assert s.compression_provider == ""
        assert s.compression_model == ""

    def test_compression_enabled_false_via_env(self, monkeypatch):
        monkeypatch.setenv("COMPRESSION_ENABLED", "false")
        s = Settings()
        assert s.compression_enabled is False

    def test_compression_provider_override_via_env(self, monkeypatch):
        monkeypatch.setenv("COMPRESSION_PROVIDER", "anthropic")
        s = Settings()
        assert s.compression_provider == "anthropic"

    def test_compression_model_override_via_env(self, monkeypatch):
        monkeypatch.setenv("COMPRESSION_MODEL", "gemini-2.5-flash")
        s = Settings()
        assert s.compression_model == "gemini-2.5-flash"


def test_embedding_models_chain_primary_and_fallbacks(monkeypatch):
    monkeypatch.setenv(
        "EMBEDDING_MODELS",
        "jina_ai/jina-embeddings-v5-text-small,gemini/gemini-embedding-001",
    )
    s = Settings()
    assert s.embedding_chain() == [
        "jina_ai/jina-embeddings-v5-text-small",
        "gemini/gemini-embedding-001",
    ]
    assert s.embedding_primary() == "jina_ai/jina-embeddings-v5-text-small"
    assert s.resolve_embedding_backend() == "cloud"


def test_embedding_empty_falls_back_to_local(monkeypatch):
    for v in (
        "EMBEDDING_MODELS",
        "EMBEDDING_MODEL",
        "JINA_AI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "COHERE_API_KEY",
        "CO_API_KEY",
        "XAI_API_KEY",
    ):
        monkeypatch.delenv(v, raising=False)
    s = Settings()
    assert s.embedding_chain() == []
    assert s.resolve_embedding_backend() == "local"


def test_legacy_singular_embedding_model_honored_with_warning(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODELS", raising=False)
    monkeypatch.setenv("EMBEDDING_MODEL", "gemini/gemini-embedding-001")
    s = Settings()
    assert s.embedding_chain() == ["gemini/gemini-embedding-001"]
    assert s.resolve_embedding_backend() == "cloud"


def test_rerank_models_chain(monkeypatch):
    monkeypatch.setenv("RERANK_MODELS", "jina_ai/jina-reranker-v3,cohere/rerank-v3.5")
    s = Settings()
    assert s.rerank_chain() == ["jina_ai/jina-reranker-v3", "cohere/rerank-v3.5"]
    assert s.rerank_primary() == "jina_ai/jina-reranker-v3"


def test_llm_models_chain_default_preserved(monkeypatch):
    monkeypatch.delenv("LLM_MODELS", raising=False)
    s = Settings()
    assert s.llm_chain()[0] == "gemini/gemini-3-flash-preview"
