from __future__ import annotations

from scripts.backfill_embeddings import backfill


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.written = []

    def rows_without_vectors(self, limit):
        return self.rows[:limit]

    def write_vector(self, memory_id, vector):
        self.written.append((memory_id, vector))


class _FakeEmbedder:
    def embed(self, texts):
        return [[0.1] * 768 for _ in texts]


def test_backfill_embeds_every_row_without_a_vector():
    db = _FakeDB([{"id": "a", "content": "x"}, {"id": "b", "content": "y"}])

    result = backfill(db, _FakeEmbedder(), batch_size=32)

    assert result == {"scanned": 2, "embedded": 2, "skipped": 0, "failed": 0}
    assert [memory_id for memory_id, _ in db.written] == ["a", "b"]


def test_backfill_skips_rows_with_empty_content():
    db = _FakeDB([{"id": "a", "content": ""}, {"id": "b", "content": "y"}])

    result = backfill(db, _FakeEmbedder(), batch_size=32)

    assert result["scanned"] == 2
    assert result["skipped"] == 1
    assert result["embedded"] == 1
    assert result["failed"] == 0


def test_backfill_counts_embedding_failures_without_writing_partial_batch():
    class _FailingEmbedder:
        def embed(self, texts):
            raise RuntimeError("provider unavailable")

    db = _FakeDB([{"id": "a", "content": "x"}, {"id": "b", "content": "y"}])

    result = backfill(db, _FailingEmbedder(), batch_size=32)

    assert result == {"scanned": 2, "embedded": 0, "skipped": 0, "failed": 2}
    assert db.written == []
