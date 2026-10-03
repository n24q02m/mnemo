"""Tests for secure local-file persistence primitives (write_owner_only).

The security contract under test: an existing file must remain intact when
the write path fails, and the successful write must end up owner-only.
"""

import os
import stat
from pathlib import Path

import pytest

from mnemo.secure_file import write_owner_only


def test_creates_nested_file_with_content(tmp_path: Path):
    """Parent directories are auto-created and bytes land on disk."""
    target = tmp_path / "secrets" / "nested" / "token.bin"
    write_owner_only(target, b"payload")
    assert target.read_bytes() == b"payload"


def test_successful_write_is_owner_only_on_posix(tmp_path: Path):
    """On POSIX the resulting file mode is 0600 (owner read/write only)."""
    if os.name == "nt":
        pytest.skip("POSIX permission bits not enforced on Windows")
    target = tmp_path / "token.bin"
    write_owner_only(target, b"payload")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_overwrite_truncates_stale_tail(tmp_path: Path):
    """Rewriting with shorter content must not leave bytes of the old one."""
    target = tmp_path / "token.bin"
    write_owner_only(target, b"long-content-that-must-not-leak")
    write_owner_only(target, b"short")
    assert target.read_bytes() == b"short"


def test_failed_open_leaves_existing_file_intact(tmp_path: Path, monkeypatch):
    """An os.open failure propagates and never truncates the old content."""
    target = tmp_path / "token.bin"
    write_owner_only(target, b"original")

    real_open = os.open

    def failing_open(path, flags, mode=0o777):  # noqa: ANN001, ANN202
        if Path(path) == target:
            raise OSError("open refused")
        return real_open(path, flags, mode)

    monkeypatch.setattr(os, "open", failing_open)
    with pytest.raises(OSError, match="open refused"):
        write_owner_only(target, b"replacement")
    assert target.read_bytes() == b"original"


def test_failed_before_fdopen_closes_fd(tmp_path: Path, monkeypatch):
    """A failure before the fd is handed to a file object closes the fd."""
    target = tmp_path / "token.bin"
    write_owner_only(target, b"original")

    closed: list[int] = []
    real_close = os.close
    monkeypatch.setattr(os, "close", lambda fd: (closed.append(fd), real_close(fd)))

    def failing_ftruncate(fd, length):  # noqa: ANN001, ANN202
        raise OSError("ftruncate refused")

    monkeypatch.setattr(os, "ftruncate", failing_ftruncate)
    with pytest.raises(OSError, match="ftruncate refused"):
        write_owner_only(target, b"replacement")
    # The descriptor was closed exactly once by the error path (no leak).
    assert len(closed) == 1
    # And the pre-existing content survived the failed write.
    assert target.read_bytes() == b"original"
