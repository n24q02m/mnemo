"""Edge case tests for mnemo_mcp.temporal.resolve."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest
import sqlite_vec

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.temporal.resolve import (
    find_similar_entity,
)

# Skip all tests in this module when SQLite was compiled without
# loadable-extensions support (macOS default).
_test_conn = sqlite3.connect(":memory:")
_HAS_LOAD_EXT = hasattr(_test_conn, "enable_load_extension")
_test_conn.close()
if _HAS_LOAD_EXT:
    try:
        _test_conn = sqlite3.connect(":memory:")
        _test_conn.enable_load_extension(True)
        _test_conn.close()
    except (AttributeError, sqlite3.NotSupportedError):
        _HAS_LOAD_EXT = False

pytestmark = pytest.mark.skipif(
    not _HAS_LOAD_EXT,
    reason="SQLite loadable extensions not enabled (macOS default).",
)


def _setup_vec(db: MemoryDB) -> None:
    db._conn.enable_load_extension(True)
    sqlite_vec.load(db._conn)
    db._conn.enable_load_extension(False)
    db._conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS memory_entities_vec "
        "USING vec0(embedding float[768])"
    )
    db._conn.commit()


@pytest.fixture
def db_with_vec(tmp_path):
    db = MemoryDB(tmp_path / "test.db", embedding_dims=768)
    _setup_vec(db)
    yield db
    db.close()


class TestFindSimilarEntityEdgeCases:
    def test_find_similar_returns_none_when_vec_table_empty(
        self, db_with_vec: MemoryDB
    ):
        # Stage 1 miss
        # Stage 2: vec table exists but is empty
        v = [0.1] * 768
        result = find_similar_entity(db_with_vec._conn, "Unknown", "concept", v)
        assert result is None

    def test_find_similar_returns_none_on_knn_exception(self, db_with_vec: MemoryDB):
        v = [0.1] * 768

        # Create a mock that wraps the real connection
        mock_conn = MagicMock(wraps=db_with_vec._conn)

        # Override execute to raise an exception when querying memory_entities_vec
        def mock_execute(sql, *args):
            if "FROM memory_entities_vec" in sql:
                raise Exception("SIMULATED KNN FAILURE")
            return db_with_vec._conn.execute(sql, *args)

        mock_conn.execute.side_effect = mock_execute

        result = find_similar_entity(mock_conn, "Something", "concept", v)
        assert result is None

    def test_find_similar_returns_none_when_rowid_missing_in_entities(
        self, db_with_vec: MemoryDB
    ):
        v = [0.1] * 768
        # Manually insert into memory_entities_vec a rowid that doesn't exist in memory_entities
        import struct

        def _serialize(vec):
            # Pad or truncate to 768
            v_pad = vec[:768] + [0.0] * (768 - len(vec))
            return struct.Struct("768f").pack(*v_pad)

        db_with_vec._conn.execute(
            "INSERT INTO memory_entities_vec (rowid, embedding) VALUES (?, ?)",
            (9999, _serialize(v)),
        )
        db_with_vec._conn.commit()

        # This should find rowid 9999 in memory_entities_vec, but fail to find it in memory_entities
        result = find_similar_entity(
            db_with_vec._conn, "Unknown", "concept", v, threshold=0.0
        )
        assert result is None
