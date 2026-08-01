"""Regression tests: ``sync_push`` must upload a self-contained ``.db`` file.

SQLite in WAL mode keeps freshly committed pages in the ``<db>-wal`` side
file until a checkpoint folds them back into the main file. ``sync_push``
hands the ``.db`` file straight to Google Drive and Drive stores that single
object -- so without a checkpoint the backup is a page-allocated shell whose
``sqlite_master`` is empty. That is the 2026-07-31 incident: the uploaded
file had a plausible size but not a single table.

No test here touches Google Drive; every network helper is patched out.
"""

from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import mnemo_mcp.sync.gdrive as gdrive
from mnemo_mcp.sync.gdrive import sync_push


@pytest.fixture
def upload_file():
    """Patch every Drive call ``sync_push`` makes; yield the upload mock."""
    upload = AsyncMock(return_value=True)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            gdrive, "_get_valid_token", AsyncMock(return_value={"access_token": "fake"})
        )
        mp.setattr(
            gdrive, "_find_or_create_folder", AsyncMock(return_value="folder-id")
        )
        mp.setattr(gdrive, "_find_file_in_folder", AsyncMock(return_value=None))
        mp.setattr(gdrive, "_upload_file", upload)
        yield upload


def _wal_db_with_one_row(db_path: Path) -> sqlite3.Connection:
    """Create a WAL-mode DB holding one committed row, connection left open.

    While the returned connection is open the row lives in ``<db>-wal`` and
    ``db_path`` on its own has no tables at all.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=wal")
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT)")
    conn.execute("INSERT INTO memories (content) VALUES ('xin chao')")
    conn.commit()
    return conn


async def test_sync_push_uploads_a_db_the_wal_was_folded_into(tmp_path, upload_file):
    db_path = tmp_path / "memories.db"
    writer = _wal_db_with_one_row(db_path)
    drive_copy = tmp_path / "drive_copy.db"

    try:
        assert await sync_push(db_path, "folder") is True
        # Drive keeps this one object and nothing else -- reproduce that by
        # copying the uploaded file without its -wal / -shm side cars.
        shutil.copyfile(upload_file.await_args.args[1], drive_copy)
    finally:
        writer.close()

    restored = sqlite3.connect(drive_copy)
    try:
        tables = [
            row[0]
            for row in restored.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        assert "memories" in tables
        assert restored.execute("SELECT content FROM memories").fetchall() == [
            ("xin chao",)
        ]
    finally:
        restored.close()


async def test_sync_push_waits_out_a_reader_that_lets_go(tmp_path, upload_file):
    """A reader that finishes inside the busy timeout must not cost a push.

    The server keeps its own connection to the same file while auto-sync
    runs, so aborting on the first busy reply would trade "upload an empty
    DB" for "never upload again".
    """
    db_path = tmp_path / "memories.db"
    writer = _wal_db_with_one_row(db_path)
    drive_copy = tmp_path / "drive_copy.db"
    holding = threading.Event()

    def hold_a_read_snapshot_briefly():
        reader = sqlite3.connect(db_path)
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM memories").fetchall()
        holding.set()
        time.sleep(0.5)
        reader.close()

    thread = threading.Thread(target=hold_a_read_snapshot_briefly)
    thread.start()
    assert holding.wait(5.0), "reader thread never took its snapshot"

    try:
        assert await sync_push(db_path, "folder") is True
        shutil.copyfile(upload_file.await_args.args[1], drive_copy)
    finally:
        thread.join()
        writer.close()

    restored = sqlite3.connect(drive_copy)
    try:
        assert restored.execute("SELECT content FROM memories").fetchall() == [
            ("xin chao",)
        ]
    finally:
        restored.close()


async def test_sync_push_aborts_when_a_reader_blocks_the_checkpoint(
    tmp_path, upload_file
):
    """A blocked checkpoint leaves recent commits in the ``-wal`` file.

    Uploading anyway would replace a good remote backup with a stale one, so
    the push has to abort and let the next sync cycle retry.
    """
    db_path = tmp_path / "memories.db"
    writer = _wal_db_with_one_row(db_path)
    reader = sqlite3.connect(db_path)
    reader.execute("BEGIN")
    reader.execute("SELECT * FROM memories").fetchall()

    try:
        assert await sync_push(db_path, "folder") is False
        upload_file.assert_not_awaited()
    finally:
        reader.close()
        writer.close()


async def test_sync_push_refuses_a_corrupt_local_db(tmp_path, upload_file):
    db_path = tmp_path / "memories.db"
    db_path.write_bytes(b"khong phai mot file sqlite" * 200)

    assert await sync_push(db_path, "folder") is False
    upload_file.assert_not_awaited()


async def test_sync_push_does_not_invent_a_db_when_the_file_is_missing(
    tmp_path, upload_file
):
    db_path = tmp_path / "memories.db"

    assert await sync_push(db_path, "folder") is False
    upload_file.assert_not_awaited()
    assert not db_path.exists()
