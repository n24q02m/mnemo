"""Tests for token_store.py -- POSIX secure file creation path.

Targets: save_token Unix path with os.open/os.fdopen/os.fchmod,
fchmod OSError path, os.open OSError fallback path.
"""

import json
from unittest.mock import patch


class TestSaveTokenPosixSecure:
    """Test the Unix-specific secure file creation path (lines 79-92)."""

    def test_posix_secure_write(self, tmp_path):
        """On POSIX, save_token uses os.open with 0600 mode."""
        from mnemo_mcp.token_store import save_token

        token = {"access_token": "secure_token", "token_type": "Bearer"}

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "posix"),
        ):
            m.get_data_dir.return_value = tmp_path
            save_token("drive", token)

        saved = json.loads((tmp_path / "tokens" / "drive.json").read_text())
        assert saved["access_token"] == "secure_token"

    def test_posix_fchmod_oserror(self, tmp_path):
        """fchmod OSError is silently caught (line 83-84)."""
        from mnemo_mcp.token_store import save_token

        token = {"access_token": "fchmod_fail"}

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "posix"),
            patch(
                "mnemo_mcp.token_store.os.fchmod",
                side_effect=OSError("Permission denied"),
            ),
        ):
            m.get_data_dir.return_value = tmp_path
            save_token("drive", token)

        saved = json.loads((tmp_path / "tokens" / "drive.json").read_text())
        assert saved["access_token"] == "fchmod_fail"

    def test_posix_os_open_oserror_fallback(self, tmp_path):
        """When os.open fails, falls back to path.write_text (lines 87-92)."""
        from mnemo_mcp.token_store import save_token

        token = {"access_token": "fallback_token"}

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "posix"),
            patch("mnemo_mcp.token_store.os.open", side_effect=OSError("Cannot open")),
        ):
            m.get_data_dir.return_value = tmp_path
            save_token("drive", token)

        saved = json.loads((tmp_path / "tokens" / "drive.json").read_text())
        assert saved["access_token"] == "fallback_token"

    def test_posix_fallback_chmod_oserror(self, tmp_path):
        """Fallback path chmod OSError is silently caught (lines 90-92)."""
        from pathlib import Path

        from mnemo_mcp.token_store import save_token

        token = {"access_token": "fallback_chmod_fail"}

        original_chmod = Path.chmod

        def mock_chmod(self, mode):
            if self.suffix == ".json":
                raise OSError("Permission denied for file")
            return original_chmod(self, mode)

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch("mnemo_mcp.token_store.os.name", "posix"),
            patch("mnemo_mcp.token_store.os.open", side_effect=OSError("Cannot open")),
            patch.object(Path, "chmod", side_effect=mock_chmod, autospec=True),
        ):
            m.get_data_dir.return_value = tmp_path
            save_token("drive", token)

        saved = json.loads((tmp_path / "tokens" / "drive.json").read_text())
        assert saved["access_token"] == "fallback_chmod_fail"


class TestLoadTokenOSError:
    """Test load_token when path.read_text raises OSError."""

    def test_load_oserror(self, tmp_path):
        from pathlib import Path

        from mnemo_mcp.token_store import load_token

        # Create token dir and file
        token_dir = tmp_path / "tokens"
        token_dir.mkdir()
        token_file = token_dir / "drive.json"
        token_file.write_text('{"access_token": "test"}')

        original_read_text = Path.read_text

        def mock_read_text(self, **kwargs):
            if self.name == "drive.json":
                raise OSError("Permission denied")
            return original_read_text(self, **kwargs)

        with (
            patch("mnemo_mcp.token_store.settings") as m,
            patch.object(Path, "read_text", side_effect=mock_read_text, autospec=True),
        ):
            m.get_data_dir.return_value = tmp_path
            result = load_token("drive")

        assert result is None
