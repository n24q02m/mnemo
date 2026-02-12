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


class TestEffectiveSyncFolder:
    def test_default_path(self):
        """Empty DB_PATH produces a deterministic hash suffix."""
        s = Settings(api_keys=None)
        folder = s.get_effective_sync_folder()
        assert folder.startswith("mnemo-mcp/")
        assert len(folder.split("/")[-1]) == 8  # 8-char hex hash

    def test_custom_path(self):
        """Different DB_PATH yields a different hash suffix."""
        s1 = Settings(api_keys=None)  # db_path=""
        s2 = Settings(db_path="/data/memories.db", api_keys=None)
        assert s1.get_effective_sync_folder() != s2.get_effective_sync_folder()

    def test_same_path_same_hash(self):
        """Same DB_PATH always produces the same hash (deterministic)."""
        s1 = Settings(db_path="/data/memories.db", api_keys=None)
        s2 = Settings(db_path="/data/memories.db", api_keys=None)
        assert s1.get_effective_sync_folder() == s2.get_effective_sync_folder()

    def test_custom_sync_folder(self):
        """Custom SYNC_FOLDER is used as prefix."""
        s = Settings(sync_folder="my-sync", api_keys=None)
        assert s.get_effective_sync_folder().startswith("my-sync/")
