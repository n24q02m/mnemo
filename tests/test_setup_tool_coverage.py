import os
from pathlib import Path
from unittest.mock import patch

from mnemo_mcp.setup_tool import clear_model_cache


def test_clear_model_cache_none_if_not_exists(tmp_path):
    """Test clear_model_cache returns None when the cache directory does not exist."""
    with patch.dict(os.environ, {"QWEN3_EMBED_CACHE_PATH": str(tmp_path)}):
        result = clear_model_cache("some/model")
        assert result is None


def test_clear_model_cache_removes_dir(tmp_path):
    """Test clear_model_cache removes the directory and returns the path."""
    cache_dir = tmp_path
    model_name = "org/model"
    safe_name = model_name.replace("/", "--")
    model_cache = cache_dir / f"models--{safe_name}"
    model_cache.mkdir(parents=True)

    with patch.dict(os.environ, {"QWEN3_EMBED_CACHE_PATH": str(tmp_path)}):
        result = clear_model_cache(model_name)
        assert result == str(model_cache)
        assert not model_cache.exists()


def test_clear_model_cache_respects_env_var(tmp_path):
    """Test clear_model_cache uses the path from QWEN3_EMBED_CACHE_PATH."""
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


def test_clear_model_cache_fallback_to_temp(tmp_path):
    """Test clear_model_cache falls back to default temp dir if env var is missing."""
    # We mock tempfile.gettempdir to point to our tmp_path to avoid polluting real temp
    with patch("tempfile.gettempdir", return_value=str(tmp_path)):
        # Ensure env var is NOT set
        with patch.dict(os.environ, {}, clear=True):
            model_name = "fallback/model"
            safe_name = model_name.replace("/", "--")

            # The expected fallback path is tmp_path / "qwen3_embed_cache" / "models--fallback--model"
            default_cache_dir = Path(tmp_path) / "qwen3_embed_cache"
            model_cache = default_cache_dir / f"models--{safe_name}"
            model_cache.mkdir(parents=True)

            result = clear_model_cache(model_name)
            assert result == str(model_cache)
            assert not model_cache.exists()
