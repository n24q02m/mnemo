import os
from unittest.mock import patch

from mnemo_mcp.setup_tool import clear_model_cache


def test_clear_model_cache_none_if_not_exists(tmp_path):
    """Test clear_model_cache returns None when the cache directory does not exist."""
    with patch.dict(os.environ, {"FASTRETRIEVAL_CACHE_PATH": str(tmp_path)}):
        result = clear_model_cache("some/model")
        assert result is None


def test_clear_model_cache_removes_dir(tmp_path):
    """Test clear_model_cache removes the directory and returns the path."""
    cache_dir = tmp_path
    model_name = "org/model"
    safe_name = model_name.replace("/", "--")
    model_cache = cache_dir / f"models--{safe_name}"
    model_cache.mkdir(parents=True)

    with patch.dict(os.environ, {"FASTRETRIEVAL_CACHE_PATH": str(tmp_path)}):
        result = clear_model_cache(model_name)
        assert result == str(model_cache)
        assert not model_cache.exists()


def test_clear_model_cache_respects_env_var(tmp_path):
    """Test clear_model_cache still reads the old cache env name."""
    custom_cache = tmp_path / "custom_cache"
    custom_cache.mkdir()
    model_name = "test/model"
    safe_name = model_name.replace("/", "--")
    model_cache = custom_cache / f"models--{safe_name}"
    model_cache.mkdir()

    with patch.dict(os.environ, {"QWEN3_EMBED_CACHE_PATH": str(custom_cache)}):
        result = clear_model_cache(model_name)
        assert result == str(model_cache)
        assert not model_cache.exists()


def test_clear_model_cache_fallback_to_fastretrieval_default(tmp_path):
    """Use fastretrieval's default cache when no compatibility env is set."""
    with patch.dict(os.environ, {}, clear=True):
        model_name = "fallback/model"
        safe_name = model_name.replace("/", "--")
        default_cache_dir = tmp_path / "fastretrieval"
        model_cache = default_cache_dir / f"models--{safe_name}"
        model_cache.mkdir(parents=True)

        with patch(
            "fastretrieval.define_cache_dir",
            return_value=default_cache_dir,
        ):
            result = clear_model_cache(model_name)

        assert result == str(model_cache)
        assert not model_cache.exists()
