"""Additional tests for mnemo_mcp.config — covering uncovered lines.

Targets: setup_litellm (proxy/sdk/local branches),
get_embedding_litellm_kwargs, resolve_litellm_mode.
"""

import os
from unittest.mock import patch

from mnemo_mcp.config import Settings


class TestSetupLitellm:
    def test_proxy_mode(self, monkeypatch):
        """setup_litellm configures LiteLLM for proxy mode."""
        s = Settings(
            litellm_proxy_url="http://localhost:4000",
            litellm_proxy_key="sk-test",
            api_keys=None,
        )

        with patch("litellm.use_litellm_proxy", False):
            import litellm

            mode = s.setup_litellm()
            assert mode == "proxy"
            assert os.environ.get("LITELLM_PROXY_API_BASE") == "http://localhost:4000"
            assert os.environ.get("LITELLM_PROXY_API_KEY") == "sk-test"
            assert litellm.use_litellm_proxy is True

        # Cleanup
        monkeypatch.delenv("LITELLM_PROXY_API_BASE", raising=False)
        monkeypatch.delenv("LITELLM_PROXY_API_KEY", raising=False)

    def test_sdk_mode(self, monkeypatch):
        """setup_litellm configures LiteLLM for SDK mode with API keys."""
        s = Settings(
            api_keys="GOOGLE_API_KEY:test-key",
            litellm_proxy_url="",
        )
        mode = s.setup_litellm()
        assert mode == "sdk"
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def test_local_mode(self):
        """setup_litellm returns 'local' when no API keys or proxy."""
        s = Settings(api_keys=None, litellm_proxy_url="")
        mode = s.setup_litellm()
        assert mode == "local"


class TestResolveLitellmMode:
    def test_proxy_mode_with_url(self):
        """Returns 'proxy' when litellm_proxy_url is set."""
        s = Settings(litellm_proxy_url="http://localhost:4000", api_keys=None)
        assert s.resolve_litellm_mode() == "proxy"

    def test_sdk_mode_with_api_keys(self):
        """Returns 'sdk' when api_keys is set."""
        s = Settings(api_keys="KEY:value")
        assert s.resolve_litellm_mode() == "sdk"

    def test_sdk_mode_with_embedding_api_base(self):
        """Returns 'sdk' when embedding_api_base is set."""
        s = Settings(embedding_api_base="https://api.example.com", api_keys=None)
        assert s.resolve_litellm_mode() == "sdk"

    def test_local_mode_default(self):
        """Returns 'local' when nothing is configured."""
        s = Settings(api_keys=None)
        assert s.resolve_litellm_mode() == "local"


class TestGetEmbeddingLitellmKwargs:
    def test_both_api_base_and_key(self):
        """Returns both api_base and api_key when set."""
        s = Settings(
            embedding_api_base="https://custom.api.com",
            embedding_api_key="custom-key",
            api_keys=None,
        )
        kwargs = s.get_embedding_litellm_kwargs()
        assert kwargs["api_base"] == "https://custom.api.com"
        assert kwargs["api_key"] == "custom-key"

    def test_api_base_only(self):
        """Returns api_base only when api_key is empty."""
        s = Settings(
            embedding_api_base="https://custom.api.com",
            embedding_api_key="",
            api_keys=None,
        )
        kwargs = s.get_embedding_litellm_kwargs()
        assert kwargs["api_base"] == "https://custom.api.com"
        assert "api_key" not in kwargs

    def test_neither_set(self):
        """Returns empty dict when nothing is set."""
        s = Settings(api_keys=None)
        kwargs = s.get_embedding_litellm_kwargs()
        assert kwargs == {}


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
    def test_auto_detect_with_proxy(self):
        """Auto-detect returns 'litellm' when proxy URL is set."""
        s = Settings(
            litellm_proxy_url="http://localhost:4000",
            embedding_backend="",
            api_keys=None,
        )
        assert s.resolve_embedding_backend() == "litellm"

    def test_auto_detect_with_no_config(self):
        """Auto-detect returns 'local' when nothing is configured."""
        s = Settings(embedding_backend="", api_keys=None)
        assert s.resolve_embedding_backend() == "local"
