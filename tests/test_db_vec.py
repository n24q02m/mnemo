"""Tests for mnemo_mcp.db with vector search enabled."""

import struct
from pathlib import Path

import pytest

from mnemo_mcp.db import MemoryDB


def _serialize_f32(vec: list[float]) -> bytes:
    """Serialize float list to bytes for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


@pytest.fixture
def tmp_db_vec(tmp_path: Path):
    """Temporary MemoryDB with vector search enabled."""
    db = MemoryDB(tmp_path / "test_vec.db", embedding_dims=3)
    yield db
    db.close()


class TestVecEnabled:
    def test_vec_enabled(self, tmp_db_vec):
        assert tmp_db_vec.vec_enabled is True


class TestUpdateWithVectors:
    def test_add_stores_embedding(self, tmp_db_vec):
        emb = [0.1, 0.2, 0.3]
        mid = tmp_db_vec.add("test", embedding=emb)

        row = tmp_db_vec._conn.execute(
            "SELECT embedding FROM memories_vec WHERE id = ?", (mid,)
        ).fetchone()
        assert row is not None
        assert row["embedding"] == _serialize_f32(emb)

    def test_update_replaces_embedding(self, tmp_db_vec):
        emb1 = [0.1, 0.0, 0.0]
        mid = tmp_db_vec.add("test", embedding=emb1)

        emb2 = [0.0, 1.0, 0.0]
        tmp_db_vec.update(mid, embedding=emb2)

        row = tmp_db_vec._conn.execute(
            "SELECT embedding FROM memories_vec WHERE id = ?", (mid,)
        ).fetchone()
        assert row is not None
        assert row["embedding"] == _serialize_f32(emb2)

    def test_update_preserves_embedding_when_none_provided(self, tmp_db_vec):
        emb = [0.1, 0.0, 0.0]
        mid = tmp_db_vec.add("test", embedding=emb)

        # Update content only, no embedding
        tmp_db_vec.update(mid, content="updated content")

        row = tmp_db_vec._conn.execute(
            "SELECT embedding FROM memories_vec WHERE id = ?", (mid,)
        ).fetchone()
        assert row is not None
        assert row["embedding"] == _serialize_f32(emb)

        mem = tmp_db_vec.get(mid)
        assert mem["content"] == "updated content"

    def test_update_embedding_only(self, tmp_db_vec):
        emb1 = [0.1, 0.0, 0.0]
        mid = tmp_db_vec.add("test", embedding=emb1)

        emb2 = [0.0, 0.0, 1.0]
        tmp_db_vec.update(mid, embedding=emb2)

        row = tmp_db_vec._conn.execute(
            "SELECT embedding FROM memories_vec WHERE id = ?", (mid,)
        ).fetchone()
        assert row is not None
        assert row["embedding"] == _serialize_f32(emb2)

        mem = tmp_db_vec.get(mid)
        assert mem["content"] == "test"

    def test_delete_removes_embedding(self, tmp_db_vec):
        emb = [0.1, 0.2, 0.3]
        mid = tmp_db_vec.add("test", embedding=emb)

        tmp_db_vec.delete(mid)

        row = tmp_db_vec._conn.execute(
            "SELECT embedding FROM memories_vec WHERE id = ?", (mid,)
        ).fetchone()
        assert row is None

    def test_update_ignores_empty_embedding_list(self, tmp_db_vec):
        """Passing an empty list for embedding should not trigger update logic."""
        emb = [0.1, 0.0, 0.0]
        mid = tmp_db_vec.add("test", embedding=emb)

        # Empty list is falsy, so it should behave like None
        tmp_db_vec.update(mid, embedding=[])

        row = tmp_db_vec._conn.execute(
            "SELECT embedding FROM memories_vec WHERE id = ?", (mid,)
        ).fetchone()
        assert row is not None
        assert row["embedding"] == _serialize_f32(emb)
