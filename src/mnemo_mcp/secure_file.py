"""Secure local-file persistence primitives."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def write_owner_only(path: str | os.PathLike[str], content: bytes) -> None:
    """Write bytes to a 0600 file without truncating before permission checks.

    The file is opened without ``O_TRUNC`` so an existing file remains intact
    when the POSIX permission check fails. Truncation happens only after the
    descriptor has been restricted to the owner; all errors are propagated so
    callers cannot mistake an insecure write for a successful save.
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    mode = stat.S_IRUSR | stat.S_IWUSR
    fd = os.open(file_path, os.O_CREAT | os.O_WRONLY, mode)
    handed_to_file = False
    try:
        if os.name != "nt":
            os.fchmod(fd, mode)
        os.ftruncate(fd, 0)
        with os.fdopen(fd, "wb") as stream:
            handed_to_file = True
            stream.write(content)
    except BaseException:
        if not handed_to_file:
            os.close(fd)
        raise
