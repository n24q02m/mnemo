import os
from pathlib import Path
from unittest.mock import patch

import pytest

from mnemo_mcp.token_store import (
    load_token,
    load_token_for_sub,
    save_token_for_sub,
)


@pytest.fixture
def mock_settings(tmp_path):
    """Provide a temporary data directory for tests."""
    with patch("mnemo_mcp.token_store.settings") as m:
        m.get_data_dir.return_value = tmp_path
        yield m


class TestTokenStoreCoverage:
    """Explicitly test all error paths in token_store.py to reach 100% coverage."""

    def test_load_token_json_decode_error(self, mock_settings, tmp_path):
        token_dir = tmp_path / "tokens"
        token_dir.mkdir(parents=True, exist_ok=True)
        path = token_dir / "test_provider.json"
        path.write_text("invalid { json", encoding="utf-8")

        # Verify it returns None
        result = load_token("test_provider")
        assert result is None

    def test_load_token_os_error_read_text(self, mock_settings, tmp_path):
        token_dir = tmp_path / "tokens"
        token_dir.mkdir(parents=True, exist_ok=True)
        path = token_dir / "test_provider.json"
        path.write_text("{}", encoding="utf-8")

        with patch.object(Path, "read_text", side_effect=OSError("Read error")):
            result = load_token("test_provider")
        assert result is None

    def test_load_token_os_error_exists(self, mock_settings, tmp_path):
        with patch.object(Path, "exists", side_effect=OSError("Exists failure")):
            result = load_token("test_provider")
        assert result is None

    def test_load_token_for_sub_json_decode_error(self, mock_settings, tmp_path):
        from mnemo_mcp.token_store import get_token_path_for_sub

        path = get_token_path_for_sub("sub123", "test_provider")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("invalid { json", encoding="utf-8")

        result = load_token_for_sub("sub123", "test_provider")
        assert result is None

    def test_load_token_for_sub_os_error_read_text(self, mock_settings, tmp_path):
        from mnemo_mcp.token_store import get_token_path_for_sub

        path = get_token_path_for_sub("sub123", "test_provider")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

        with patch.object(Path, "read_text", side_effect=OSError("Read error")):
            result = load_token_for_sub("sub123", "test_provider")
        assert result is None

    def test_load_token_for_sub_os_error_exists(self, mock_settings, tmp_path):
        with patch.object(Path, "exists", side_effect=OSError("Exists failure")):
            result = load_token_for_sub("sub123", "test_provider")
        assert result is None

    def test_save_token_for_sub_chmod_errors_swallowed(self, mock_settings, tmp_path):
        if os.name == "nt":
            pytest.skip("POSIX-only chmod path")

        # Dir chmod error
        with patch.object(Path, "chmod", side_effect=OSError("chmod denied")):
            save_token_for_sub("sub1", "test", {"access_token": "abc"})

        # fchmod error
        with patch("os.fchmod", side_effect=OSError("fchmod failed")):
            save_token_for_sub("sub2", "test", {"access_token": "abc"})

        # Fallback Path.chmod error
        with patch("os.open", side_effect=OSError("open failed")):
            with patch.object(Path, "chmod", side_effect=OSError("final chmod failed")):
                save_token_for_sub("sub3", "test", {"access_token": "abc"})
