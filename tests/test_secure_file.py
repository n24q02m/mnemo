"""Regression tests for owner-only file writes."""

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest


def test_write_owner_only_creates_restricted_file(tmp_path: Path):
    from mnemo_mcp.secure_file import write_owner_only

    path = tmp_path / "secret.bin"
    write_owner_only(path, b"new-content")

    assert path.read_bytes() == b"new-content"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == stat.S_IRUSR | stat.S_IWUSR


def test_fchmod_failure_does_not_truncate_existing_file(tmp_path: Path):
    from mnemo_mcp.secure_file import write_owner_only

    path = tmp_path / "secret.bin"
    path.write_bytes(b"previous-content")

    if os.name == "nt":
        pytest.skip("POSIX-only fchmod failure path")

    with patch("mnemo_mcp.secure_file.os.fchmod", side_effect=OSError("not supported")):
        with pytest.raises(OSError, match="not supported"):
            write_owner_only(path, b"replacement")

    assert path.read_bytes() == b"previous-content"


def test_windows_path_skips_posix_fchmod(tmp_path: Path):
    from mnemo_mcp.secure_file import write_owner_only

    path = tmp_path / "secret.bin"
    with (
        patch("mnemo_mcp.secure_file.os.name", "nt"),
        patch("mnemo_mcp.secure_file.Path", new=type(path)),
        patch("mnemo_mcp.secure_file.os.fchmod") as mock_fchmod,
    ):
        write_owner_only(path, b"windows-content")

    mock_fchmod.assert_not_called()
    assert path.read_bytes() == b"windows-content"
