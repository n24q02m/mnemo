from typing import cast

from mnemo_mcp.db import MemoryDB


def test_get_sync_state_not_found(tmp_db: MemoryDB):
    """Verify it returns None for a backend that hasn't been synced yet."""
    assert tmp_db.get_sync_state("nonexistent") is None


def test_upsert_and_get_sync_state(tmp_db: MemoryDB):
    """Verify that upsert_sync_state followed by get_sync_state correctly round-trips all fields."""
    backend = "s3"
    last_sync_at = 123456789.0
    last_commit_sha = "deadbeef"
    upload_cursor = 42

    tmp_db.upsert_sync_state(
        backend=backend,
        last_sync_at=last_sync_at,
        last_commit_sha=last_commit_sha,
        upload_cursor=upload_cursor,
    )

    state = cast(dict, tmp_db.get_sync_state(backend))
    assert state is not None
    assert state["backend"] == backend
    assert state["last_sync_at"] == last_sync_at
    assert state["last_commit_sha"] == last_commit_sha
    assert state["upload_cursor"] == upload_cursor


def test_upsert_sync_state_partial_update(tmp_db: MemoryDB):
    """Verify that passing None to upsert_sync_state preserves existing values."""
    backend = "gdrive"

    # Initial upsert
    tmp_db.upsert_sync_state(
        backend=backend, last_sync_at=100.0, last_commit_sha="initial", upload_cursor=1
    )

    # Partial update: only change upload_cursor
    tmp_db.upsert_sync_state(backend=backend, upload_cursor=2)

    state = cast(dict, tmp_db.get_sync_state(backend))
    assert state["backend"] == backend
    assert state["last_sync_at"] == 100.0
    assert state["last_commit_sha"] == "initial"
    assert state["upload_cursor"] == 2

    # Partial update: only change last_sync_at
    tmp_db.upsert_sync_state(backend=backend, last_sync_at=200.0)

    state = cast(dict, tmp_db.get_sync_state(backend))
    assert state["last_sync_at"] == 200.0
    assert state["upload_cursor"] == 2

    # Partial update: only change last_commit_sha
    tmp_db.upsert_sync_state(backend=backend, last_commit_sha="updated")

    state = cast(dict, tmp_db.get_sync_state(backend))
    assert state["last_commit_sha"] == "updated"
    assert state["last_sync_at"] == 200.0


def test_get_sync_state_missing_table(tmp_path):
    """Verify it handles missing sync_state table gracefully by returning None."""
    db_path = tmp_path / "missing.db"
    db = MemoryDB(db_path, embedding_dims=0)

    # Drop the table to simulate missing table
    db._conn.execute("DROP TABLE sync_state")
    db._conn.commit()

    # Now it should return None due to OperationalError (handled by try-except)
    state = db.get_sync_state("s3")
    assert state is None

    db.close()


def test_get_sync_state_non_row_factory(tmp_path):
    """Verify it handles cases where row_factory might not be set (though it should be)."""
    db_path = tmp_path / "norowfactory.db"
    db = MemoryDB(db_path, embedding_dims=0)

    # Temporarily unset row_factory to exercise the fallback in get_sync_state
    original_factory = db._conn.row_factory
    db._conn.row_factory = None

    try:
        db.upsert_sync_state(
            "s3", last_sync_at=1.0, last_commit_sha="sha", upload_cursor=1
        )
        state = cast(dict, db.get_sync_state("s3"))
        assert isinstance(state, dict)
        assert state["backend"] == "s3"
        assert state["last_sync_at"] == 1.0
        assert state["last_commit_sha"] == "sha"
        assert state["upload_cursor"] == 1
    finally:
        db._conn.row_factory = original_factory
        db.close()
