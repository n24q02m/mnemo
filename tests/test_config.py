"""Tests for mnemo_mcp.config — Settings, API keys, embedding resolution."""

import os
from pathlib import Path

from mnemo_mcp.config import Settings


class TestSettingsDefaults:
    def test_db_path_empty(self):
        s = Settings(api_keys=None)
        assert s.db_path == ""

    def test_sync_disabled(self):
        s = Settings(api_keys=None)
        assert s.sync_enabled is False

    def test_sync_folder(self):
        s = Settings(api_keys=None)
        assert s.sync_folder == "mnemo-mcp"

    def test_log_level(self):
        s = Settings(api_keys=None)
        assert s.log_level == "INFO"

    def test_embedding_dims_zero(self):
        s = Settings(api_keys=None)
        assert s.embedding_dims == 0

    def test_embedding_model_empty(self):
        s = Settings(api_keys=None)
        assert s.embedding_model == ""


class TestDbPath:
    def test_default_path(self):
        s = Settings(api_keys=None)
        expected = Path.home() / ".mnemo-mcp" / "memories.db"
        assert s.get_db_path() == expected

    def test_custom_path(self):
        s = Settings(db_path="/tmp/custom.db", api_keys=None)
        assert s.get_db_path() == Path("/tmp/custom.db")

    def test_expanduser(self):
        s = Settings(db_path="~/test.db", api_keys=None)
        assert s.get_db_path() == Path.home() / "test.db"

    def test_data_dir(self):
        s = Settings(db_path="/tmp/data/test.db", api_keys=None)
        assert s.get_data_dir() == Path("/tmp/data")

    def test_data_dir_default(self):
        s = Settings(api_keys=None)
        assert s.get_data_dir() == Path.home() / ".mnemo-mcp"


class TestApiKeys:
    def test_no_keys(self):
        s = Settings(api_keys=None)
        assert s.setup_api_keys() == {}

    def test_single_key(self, monkeypatch):
        s = Settings(api_keys="GOOGLE_API_KEY:test-key-123")
        result = s.setup_api_keys()
        assert "GOOGLE_API_KEY" in result
        assert result["GOOGLE_API_KEY"] == ["test-key-123"]
        assert os.environ.get("GOOGLE_API_KEY") == "test-key-123"
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def test_multiple_keys(self, monkeypatch):
        s = Settings(api_keys="GOOGLE_API_KEY:key1,OPENAI_API_KEY:key2")
        result = s.setup_api_keys()
        assert len(result) == 2
        assert "GOOGLE_API_KEY" in result
        assert "OPENAI_API_KEY" in result
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def test_duplicate_provider(self, monkeypatch):
        """Multiple keys for same provider — first key is set as env var."""
        s = Settings(api_keys="GOOGLE_API_KEY:key1,GOOGLE_API_KEY:key2")
        result = s.setup_api_keys()
        assert len(result["GOOGLE_API_KEY"]) == 2
        assert os.environ.get("GOOGLE_API_KEY") == "key1"
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def test_malformed_no_colon(self):
        s = Settings(api_keys="INVALID_FORMAT")
        result = s.setup_api_keys()
        assert result == {}

    def test_empty_key_value(self):
        s = Settings(api_keys="GOOGLE_API_KEY:")
        result = s.setup_api_keys()
        assert result == {}

    def test_whitespace_handling(self, monkeypatch):
        s = Settings(api_keys="  GOOGLE_API_KEY : key1 , OPENAI_API_KEY : key2  ")
        result = s.setup_api_keys()
        assert "GOOGLE_API_KEY" in result
        assert result["GOOGLE_API_KEY"] == ["key1"]
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def test_colon_in_key_value(self, monkeypatch):
        """API keys can contain colons (e.g., base64-encoded keys)."""
        s = Settings(api_keys="GOOGLE_API_KEY:abc:def:ghi")
        result = s.setup_api_keys()
        assert result["GOOGLE_API_KEY"] == ["abc:def:ghi"]
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def test_alias_google_to_gemini(self, monkeypatch):
        """GOOGLE_API_KEY should also set GEMINI_API_KEY for LiteLLM embeddings."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        s = Settings(api_keys="GOOGLE_API_KEY:test-key")
        s.setup_api_keys()
        assert os.environ.get("GEMINI_API_KEY") == "test-key"
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def test_alias_no_overwrite(self, monkeypatch):
        """If GEMINI_API_KEY already set, alias does not overwrite."""
        monkeypatch.setenv("GEMINI_API_KEY", "existing")
        s = Settings(api_keys="GOOGLE_API_KEY:new-key")
        s.setup_api_keys()
        assert os.environ.get("GEMINI_API_KEY") == "existing"
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)


class TestEmbeddingModel:
    def test_explicit_model(self):
        s = Settings(embedding_model="custom/model", api_keys=None)
        assert s.resolve_embedding_model() == "custom/model"

    def test_no_model_returns_none(self):
        """Without explicit EMBEDDING_MODEL, returns None (auto-detect in server)."""
        s = Settings(api_keys="GOOGLE_API_KEY:key")
        assert s.resolve_embedding_model() is None

    def test_no_keys_returns_none(self):
        s = Settings(api_keys=None)
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
        s = Settings(embedding_dims=512, api_keys=None)
        assert s.resolve_embedding_dims() == 512

    def test_default_zero(self):
        """Without explicit EMBEDDING_DIMS, returns 0 (auto-detect at runtime)."""
        s = Settings(api_keys=None)
        assert s.resolve_embedding_dims() == 0


class TestEmbeddingBackend:
    def test_explicit_litellm(self):
        s = Settings(embedding_backend="litellm", api_keys=None)
        assert s.resolve_embedding_backend() == "litellm"

    def test_explicit_local(self):
        s = Settings(embedding_backend="local", api_keys=None)
        assert s.resolve_embedding_backend() == "local"

    def test_auto_detect_litellm_with_keys(self):
        """Falls back to litellm when qwen3-embed not installed but keys provided."""
        s = Settings(api_keys="GOOGLE_API_KEY:key")
        assert s.resolve_embedding_backend() in ("litellm", "local")

    def test_auto_detect_no_keys_no_local(self):
        """Returns '' when no keys and no local model."""
        s = Settings(api_keys=None)
        # Only if qwen3-embed is not installed
        result = s.resolve_embedding_backend()
        assert result in ("", "local")  # local if qwen3-embed installed in env

    def test_explicit_overrides_auto(self):
        """Explicit backend takes priority over auto-detection."""
        s = Settings(embedding_backend="litellm", api_keys=None)
        assert s.resolve_embedding_backend() == "litellm"
