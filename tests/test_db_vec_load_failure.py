"""Tests for sqlite-vec load failure handling in MemoryDB."""

import sqlite3
from unittest.mock import patch

from mnemo_mcp.db import MemoryDB

# Some CPython builds (notably the Homebrew/python.org macOS builds used on
# GitHub Actions) are compiled without --enable-loadable-sqlite-extensions,
# so sqlite3.Connection has no `enable_load_extension` attribute. Detect
# this at runtime so we can assert on either error message (the mock-raised
# RuntimeError on extension-capable builds, or the AttributeError that
# sqlite3 itself raises on capability-missing builds).
_EXT_CAPABLE = hasattr(sqlite3.Connection, "enable_load_extension")


def test_sqlite_vec_load_failure_handled_gracefully(tmp_path):
    """Verify that MemoryDB handles sqlite-vec load failure gracefully.

    The warning message starts with "sqlite-vec load failed:" regardless of
    whether the failure originates from sqlite_vec.load() or from a missing
    enable_load_extension attribute on the runtime's sqlite3 build.
    """
    db_path = tmp_path / "test_vec_fail.db"
    with (
        patch(
            "mnemo_mcp.db.sqlite_vec.load",
            side_effect=RuntimeError("Extension load failed"),
        ),
        patch("mnemo_mcp.db.logger") as mock_logger,
    ):
        db = MemoryDB(db_path, embedding_dims=768)
        assert mock_logger.warning.called
        args, _ = mock_logger.warning.call_args
        msg = args[0]
        assert msg.startswith("sqlite-vec load failed:")
        if _EXT_CAPABLE:
            # Extension loading available -> the mocked RuntimeError is hit
            assert "Extension load failed" in msg
        else:
            # No extension loading support -> AttributeError surfaces first
            assert "enable_load_extension" in msg
        assert db.vec_enabled is False
        assert db._vec_enabled is False
        db.close()
