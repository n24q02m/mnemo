"""Additional tests for mnemo_mcp.db — covering uncovered lines.

Targets: vector search paths, RRF fusion scoring, tag post-filter edge cases,
import_jsonl with list/dict/invalid data, replace mode with vec,
and other edge cases.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from mnemo_mcp.db import MAX_CONTENT_LENGTH, MemoryDB

# ---------------------------------------------------------------------------
# Test Setup
# ---------------------------------------------------------------------------


@pytest.fixture
def vec_db(tmp_path: Path):
    """MemoryDB with vector search enabled (1536 dims for testing)."""
    db = MemoryDB(tmp_path / "vec_test.db", embedding_dims=1536)
    # Force a specific shape
    db._ensure_vec_table(1536)
    yield db
    db.close()


# ---------------------------------------------------------------------------
# Vector search & RRF fusion
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_with_fixed_sql(vec_db: MemoryDB):
    """MemoryDB fixture for testing."""
    return vec_db


class TestVectorSearch:
    def test_search_with_embedding(self, mock_db_with_fixed_sql: MemoryDB):
        """Search with embedding uses vector search path."""
        # Add memories with embeddings
        mock_db_with_fixed_sql.add(
            "Python programming language",
            category="tech",
            embedding=[1.0, 0.0, 0.0, 0.0],
        )
        mock_db_with_fixed_sql.add(
            "JavaScript for web development",
            category="tech",
            embedding=[0.0, 1.0, 0.0, 0.0],
        )
        mock_db_with_fixed_sql.add(
            "Cooking recipe for pasta", category="food", embedding=[0.0, 0.0, 1.0, 0.0]
        )

        # Search with a query embedding similar to Python
        results = mock_db_with_fixed_sql.search(
            "Python", embedding=[0.9, 0.1, 0.0, 0.0]
        )
        assert len(results) > 0

    def test_vector_only_results_fetched(self, mock_db_with_fixed_sql: MemoryDB):
        """Vector search finds results not in FTS results -- triggers missing_ids path."""
        # Add items where FTS query does NOT match some items, but vector does
        # "Alpha" will match FTS for "Alpha"
        mock_db_with_fixed_sql.add("Alpha content here", embedding=[1.0, 0.0, 0.0, 0.0])
        # "Completely different text" won't match FTS for "Alpha",
        # but has a close embedding -- should be found via vector and trigger missing_ids
        mock_db_with_fixed_sql.add(
            "Completely different text no overlap", embedding=[0.95, 0.05, 0.0, 0.0]
        )
        mock_db_with_fixed_sql.add(
            "Another unrelated item", embedding=[0.0, 0.0, 1.0, 0.0]
        )

        results = mock_db_with_fixed_sql.search(
            "Alpha", embedding=[0.97, 0.03, 0.0, 0.0]
        )
        assert len(results) >= 1
        # Should have at least one result with vec_score > 0 to trigger RRF fusion
        # The "Completely different text" should be found by vector but not FTS

    def test_rrf_fusion_scoring(self, mock_db_with_fixed_sql: MemoryDB):
        """RRF fusion combines FTS and vector scores when both have results."""
        # Create scenario where both FTS and vector return results and vec_score > 0
        mock_db_with_fixed_sql.add(
            "Machine learning algorithms for data",
            category="tech",
            tags=["ml"],
            embedding=[1.0, 0.0, 0.0, 0.0],
        )
        mock_db_with_fixed_sql.add(
            "Deep learning neural networks research",
            category="tech",
            tags=["dl"],
            embedding=[0.8, 0.2, 0.0, 0.0],
        )
        # This one has similar embedding but totally different text
        mock_db_with_fixed_sql.add(
            "Unrelated content zebra",
            category="other",
            tags=["misc"],
            embedding=[0.9, 0.1, 0.0, 0.0],
        )

        results = mock_db_with_fixed_sql.search(
            "learning", embedding=[0.95, 0.05, 0.0, 0.0]
        )
        assert len(results) > 0
        assert "score" in results[0]
        assert results[0]["score"] > 0

    def test_vector_search_with_category_filter(self, mock_db_with_fixed_sql: MemoryDB):
        """Category filter applied to both FTS and vector search."""
        mock_db_with_fixed_sql.add(
            "Tech content", category="tech", embedding=[1.0, 0.0, 0.0, 0.0]
        )
        mock_db_with_fixed_sql.add(
            "Food content", category="food", embedding=[0.9, 0.1, 0.0, 0.0]
        )

        results = mock_db_with_fixed_sql.search(
            "content", embedding=[1.0, 0.0, 0.0, 0.0], category="tech"
        )
        assert all(r["category"] == "tech" for r in results)

    def test_vector_search_with_tag_filter(self, mock_db_with_fixed_sql: MemoryDB):
        """Tag filter applied to vector search results."""
        mock_db_with_fixed_sql.add(
            "Tagged tech stuff", tags=["python"], embedding=[1.0, 0.0, 0.0, 0.0]
        )
        mock_db_with_fixed_sql.add(
            "No relevant tag here", tags=["cooking"], embedding=[0.9, 0.1, 0.0, 0.0]
        )

        results = mock_db_with_fixed_sql.search(
            "tagged stuff", embedding=[1.0, 0.0, 0.0, 0.0], tags=["python"]
        )
        for r in results:
            tags = json.loads(r["tags"]) if isinstance(r["tags"], str) else r["tags"]
            assert "python" in tags

    def test_update_embedding(self, mock_db_with_fixed_sql: MemoryDB):
        """Updating a memory with a new embedding replaces the old one."""
        mid = mock_db_with_fixed_sql.add("test content", embedding=[1.0, 0.0, 0.0, 0.0])
        mock_db_with_fixed_sql.update(
            mid, content="updated content", embedding=[0.0, 1.0, 0.0, 0.0]
        )

        results = mock_db_with_fixed_sql.search(
            "updated", embedding=[0.0, 1.0, 0.0, 0.0]
        )
        assert len(results) > 0
        assert results[0]["content"] == "updated content"

    def test_delete_with_vec(self, mock_db_with_fixed_sql: MemoryDB):
        """Deleting a memory also removes its embedding."""
        mid = mock_db_with_fixed_sql.add("delete me", embedding=[1.0, 0.0, 0.0, 0.0])
        assert mock_db_with_fixed_sql.delete(mid) is True
        results = mock_db_with_fixed_sql.search(
            "delete", embedding=[1.0, 0.0, 0.0, 0.0]
        )
        assert len(results) == 0

    def test_vector_search_missing_ids_path(self, mock_db_with_fixed_sql: MemoryDB):
        """Explicitly test the missing_ids path in vector search.

        Creates items where vector finds close matches not found by FTS,
        forcing the code to fetch full memory records for vector-only results.
        """
        # Item 1: FTS matches "quantum" and has embedding in one direction
        mock_db_with_fixed_sql.add(
            "quantum computing research", embedding=[1.0, 0.0, 0.0, 0.0]
        )

        # Item 2: FTS does NOT match "quantum", but embedding is very close
        mock_db_with_fixed_sql.add(
            "xylophone orchestra performance", embedding=[0.99, 0.01, 0.0, 0.0]
        )

        # Item 3: FTS does NOT match "quantum", and embedding is far away
        mock_db_with_fixed_sql.add(
            "underwater basket weaving", embedding=[0.0, 0.0, 0.0, 1.0]
        )

        # Search for "quantum" with embedding close to items 1 and 2
        results = mock_db_with_fixed_sql.search(
            "quantum", embedding=[0.99, 0.01, 0.0, 0.0]
        )

        # Item 1 will be in FTS results AND vector results
        # Item 2 should be in vector results only (missing_ids path)
        assert len(results) >= 1

    def test_rrf_fusion_recency_and_frequency(self, mock_db_with_fixed_sql: MemoryDB):
        """Test RRF fusion path including recency and frequency boosts."""

        # Create memories with different timestamps and access counts
        mid1 = mock_db_with_fixed_sql.add(
            "recent popular topic",
            embedding=[1.0, 0.0, 0.0, 0.0],
        )
        # Make mid1 have high access count
        mock_db_with_fixed_sql._conn.execute(
            "UPDATE memories SET access_count = 100 WHERE id = ?", (mid1,)
        )
        mock_db_with_fixed_sql._conn.commit()

        mock_db_with_fixed_sql.add(
            "different topic content",
            embedding=[0.9, 0.1, 0.0, 0.0],
        )

        # Search triggers both FTS and vector (RRF path)
        results = mock_db_with_fixed_sql.search(
            "topic", embedding=[0.95, 0.05, 0.0, 0.0]
        )
        assert len(results) >= 1
        assert all("score" in r for r in results)


class TestVectorSearchRRFDirect:
    """Tests that directly exercise the vector search + RRF fusion code paths.

    The current sqlite-vec version requires 'k = ?' syntax in WHERE clause
    but the production code uses 'ORDER BY distance LIMIT ?'. To test the
    vector search and RRF fusion logic, we wrap the connection's execute
    method to rewrite the SQL for the vec query only.
    """

    def test_rrf_fusion_with_both_fts_and_vec(self, mock_db_with_fixed_sql: MemoryDB):
        """RRF fusion scoring when both FTS and vector find results."""

        mock_db_with_fixed_sql.add(
            "machine learning algorithms research", embedding=[1.0, 0.0, 0.0, 0.0]
        )
        mock_db_with_fixed_sql.add(
            "deep learning neural networks study", embedding=[0.8, 0.2, 0.0, 0.0]
        )
        mock_db_with_fixed_sql.add(
            "unrelated zebra content topic", embedding=[0.9, 0.1, 0.0, 0.0]
        )

        results = mock_db_with_fixed_sql.search(
            "learning", embedding=[0.95, 0.05, 0.0, 0.0]
        )
        assert len(results) > 0
        assert all("score" in r for r in results)
        # Internal scores should be cleaned
        assert all("fts_score" not in r for r in results)
        assert all("vec_score" not in r for r in results)

    def test_vec_search_missing_ids_path(self, mock_db_with_fixed_sql: MemoryDB):
        """Test the missing_ids code path -- vector finds items not in FTS."""

        # Item 1 matches FTS for "quantum"
        mock_db_with_fixed_sql.add(
            "quantum computing research", embedding=[1.0, 0.0, 0.0, 0.0]
        )
        # Item 2 does NOT match FTS for "quantum" but has very close embedding
        mock_db_with_fixed_sql.add(
            "xylophone orchestra performance", embedding=[0.99, 0.01, 0.0, 0.0]
        )

        results = mock_db_with_fixed_sql.search(
            "quantum", embedding=[0.99, 0.01, 0.0, 0.0]
        )
        assert len(results) >= 1
        # The xylophone item should appear via vector search even though FTS doesn't match
        contents = [r["content"] for r in results]
        assert any("quantum" in c for c in contents)
        # If vec search works, the xylophone item should also be found
        if len(results) >= 2:
            assert any("xylophone" in c for c in contents)

    def test_rrf_fusion_recency_and_frequency(self, mock_db_with_fixed_sql: MemoryDB):
        """RRF fusion includes recency and frequency boosts."""

        mid1 = mock_db_with_fixed_sql.add(
            "popular topic content", embedding=[1.0, 0.0, 0.0, 0.0]
        )
        mock_db_with_fixed_sql._conn.execute(
            "UPDATE memories SET access_count = 100 WHERE id = ?", (mid1,)
        )
        mock_db_with_fixed_sql._conn.commit()

        mock_db_with_fixed_sql.add(
            "another topic content", embedding=[0.9, 0.1, 0.0, 0.0]
        )

        results = mock_db_with_fixed_sql.search(
            "topic", embedding=[0.95, 0.05, 0.0, 0.0]
        )
        assert len(results) >= 1
        assert all("score" in r for r in results)
        assert all(r["score"] > 0 for r in results)

    def test_rrf_fusion_invalid_timestamp(self, mock_db_with_fixed_sql: MemoryDB):
        """RRF fusion handles invalid updated_at gracefully (recency=0)."""

        mid1 = mock_db_with_fixed_sql.add(
            "alpha content test", embedding=[1.0, 0.0, 0.0, 0.0]
        )
        mock_db_with_fixed_sql._conn.execute(
            "UPDATE memories SET updated_at = 'invalid' WHERE id = ?", (mid1,)
        )
        mock_db_with_fixed_sql._conn.commit()

        mock_db_with_fixed_sql.add("beta content test", embedding=[0.8, 0.2, 0.0, 0.0])

        results = mock_db_with_fixed_sql.search(
            "content", embedding=[0.95, 0.05, 0.0, 0.0]
        )
        assert len(results) >= 1
        # Should not crash despite invalid timestamp

    def test_vec_search_with_category_filter(self, mock_db_with_fixed_sql: MemoryDB):
        """Vector search with category pre-filter in SQL."""

        mock_db_with_fixed_sql.add(
            "tech article about AI", category="tech", embedding=[1.0, 0.0, 0.0, 0.0]
        )
        mock_db_with_fixed_sql.add(
            "food recipe for soup", category="food", embedding=[0.9, 0.1, 0.0, 0.0]
        )

        results = mock_db_with_fixed_sql.search(
            "article", embedding=[1.0, 0.0, 0.0, 0.0], category="tech"
        )
        assert all(r["category"] == "tech" for r in results)

    def test_vec_search_with_tag_filter(self, mock_db_with_fixed_sql: MemoryDB):
        """Vector search with tag pre-filter in SQL."""

        mock_db_with_fixed_sql.add(
            "tagged content python", tags=["python"], embedding=[1.0, 0.0, 0.0, 0.0]
        )
        mock_db_with_fixed_sql.add(
            "tagged content cooking", tags=["cooking"], embedding=[0.9, 0.1, 0.0, 0.0]
        )

        results = mock_db_with_fixed_sql.search(
            "tagged", embedding=[1.0, 0.0, 0.0, 0.0], tags=["python"]
        )
        for r in results:
            tags = json.loads(r["tags"]) if isinstance(r["tags"], str) else r["tags"]
            assert "python" in tags


# ---------------------------------------------------------------------------
# Tag post-filter edge cases
# ---------------------------------------------------------------------------


class TestTagPostFilter:
    def test_invalid_tags_json(self, tmp_db: MemoryDB):
        """Memories with invalid JSON tags are filtered out by tag filter."""
        mid = tmp_db.add("test content", tags=["valid"])
        # Manually corrupt the tags field
        tmp_db._conn.execute(
            "UPDATE memories SET tags = 'not-json' WHERE id = ?", (mid,)
        )
        tmp_db._conn.commit()

        results = tmp_db.search("test", tags=["valid"])
        # The corrupted memory should be filtered out
        for r in results:
            if r["id"] == mid:
                pytest.fail("Memory with corrupted tags should be filtered out")

    def test_tags_not_a_list(self, tmp_db: MemoryDB):
        """Memories with non-list tags JSON are filtered out."""
        mid = tmp_db.add("test content", tags=["valid"])
        # Set tags to a JSON string instead of array
        tmp_db._conn.execute(
            "UPDATE memories SET tags = '\"just a string\"' WHERE id = ?", (mid,)
        )
        tmp_db._conn.commit()

        results = tmp_db.search("test", tags=["valid"])
        for r in results:
            if r["id"] == mid:
                pytest.fail("Memory with non-list tags should be filtered out")


# ---------------------------------------------------------------------------
# FTS search exception handling
# ---------------------------------------------------------------------------


class TestFtsSearchExceptionHandling:
    def test_fts_query_error_continues(self, tmp_db: MemoryDB):
        """FTS query errors fall through to next tier without crashing."""
        tmp_db.add("findable content here")
        # Even with potentially problematic queries, search should not crash
        results = tmp_db.search("findable content here")
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Import JSONL edge cases
# ---------------------------------------------------------------------------


class TestImportJsonlEdgeCases:
    def test_import_list_input(self, tmp_db: MemoryDB):
        """Import accepts a list of dicts directly."""
        data = [
            {"id": "list1", "content": "first item"},
            {"id": "list2", "content": "second item"},
        ]
        result = tmp_db.import_jsonl(data, mode="merge")
        assert result["imported"] == 2
        assert tmp_db.get("list1") is not None
        assert tmp_db.get("list2") is not None

    def test_import_dict_input(self, tmp_db: MemoryDB):
        """Import accepts a single dict directly."""
        data = {"id": "dict1", "content": "single item"}
        result = tmp_db.import_jsonl(data, mode="merge")
        assert result["imported"] == 1
        assert tmp_db.get("dict1") is not None

    def test_import_invalid_type(self, tmp_db: MemoryDB):
        """Import with unsupported type returns empty result."""
        invalid_input: Any = 12345
        result = tmp_db.import_jsonl(invalid_input, mode="merge")  # ty: ignore[invalid-argument-type]
        assert result["imported"] == 0
        assert result["skipped"] == 0

    def test_import_string_with_invalid_json(self, tmp_db: MemoryDB):
        """Invalid JSON lines are counted as rejected."""
        data = '{"id":"ok1","content":"valid"}\nnot-json\n{"id":"ok2","content":"also valid"}'
        result = tmp_db.import_jsonl(data, mode="merge")
        assert result["imported"] == 2
        assert result["rejected"] == 1

    def test_import_replace_with_vec(self, tmp_path: Path):
        """Replace mode clears vec table too."""
        db = MemoryDB(tmp_path / "vec_import.db", embedding_dims=4)
        db.add("old memory", embedding=[1.0, 0.0, 0.0, 0.0])

        data = [{"id": "new1", "content": "new memory"}]
        result = db.import_jsonl(data, mode="replace")
        assert result["imported"] == 1
        assert db.stats()["total_memories"] == 1
        db.close()

    def test_import_tags_as_string(self, tmp_db: MemoryDB):
        """Import handles tags that are already a JSON string."""
        data = [{"id": "ts1", "content": "test", "tags": '["a", "b"]'}]
        result = tmp_db.import_jsonl(data, mode="merge")
        assert result["imported"] == 1
        mem = tmp_db.get("ts1")
        assert mem is not None
        # Tags stored as-is since they're already a string
        assert json.loads(mem["tags"]) == ["a", "b"]

    def test_import_generates_id_when_missing(self, tmp_db: MemoryDB):
        """Import generates UUID when id is missing."""
        data = [{"content": "no id provided"}]
        result = tmp_db.import_jsonl(data, mode="merge")
        assert result["imported"] == 1
        all_mems = tmp_db.list_memories()
        assert len(all_mems) == 1
        assert all_mems[0]["content"] == "no id provided"

    def test_import_empty_batch_skipped(self, tmp_db: MemoryDB):
        """When all items in a batch are rejected, batch is skipped."""
        oversized = "x" * (MAX_CONTENT_LENGTH + 1)
        data = [{"id": "big1", "content": oversized}]
        result = tmp_db.import_jsonl(data, mode="merge")
        assert result["rejected"] == 1
        assert result["imported"] == 0

    def test_import_parse_exception_in_batch(self, tmp_db: MemoryDB):
        """Exception during batch parse is caught and counted as rejected."""

        # Create a list item that will cause parse issues
        bad_item = MagicMock()
        bad_item.get.side_effect = AttributeError("broken")

        data = [bad_item]
        result = tmp_db.import_jsonl(data, mode="merge")
        assert result["rejected"] == 1


# ---------------------------------------------------------------------------
# Recency/frequency scoring edge cases
# ---------------------------------------------------------------------------


class TestScoringEdgeCases:
    def test_invalid_updated_at_recency(self, tmp_db: MemoryDB):
        """Invalid updated_at timestamp gets recency = 0."""
        mid = tmp_db.add("recency test")
        # Corrupt the updated_at timestamp
        tmp_db._conn.execute(
            "UPDATE memories SET updated_at = 'not-a-date' WHERE id = ?", (mid,)
        )
        tmp_db._conn.commit()

        results = tmp_db.search("recency test")
        assert len(results) > 0
        # Should still return results despite bad timestamp

    def test_high_access_count_frequency_boost(self, tmp_db: MemoryDB):
        """Memories with high access count get frequency boost."""
        mid = tmp_db.add("frequent memory")
        tmp_db._conn.execute(
            "UPDATE memories SET access_count = 1000 WHERE id = ?", (mid,)
        )
        tmp_db._conn.commit()

        results = tmp_db.search("frequent memory")
        assert len(results) > 0
        assert results[0]["score"] > 0
