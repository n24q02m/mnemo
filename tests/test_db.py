"""Tests for mnemo_mcp.db — CRUD, FTS5 search, scoring, export/import."""

import json
import time

from mnemo_mcp.db import MemoryDB, _build_fts_queries


class TestAdd:
    def test_returns_12char_hex_id(self, tmp_db: MemoryDB):
        mid = tmp_db.add("test content")
        assert isinstance(mid, str)
        assert len(mid) == 12
        int(mid, 16)  # Should parse as hex

    def test_default_category(self, tmp_db: MemoryDB):
        mid = tmp_db.add("test")
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["category"] == "general"

    def test_custom_category(self, tmp_db: MemoryDB):
        mid = tmp_db.add("test", category="work")
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["category"] == "work"

    def test_tags_stored_as_json(self, tmp_db: MemoryDB):
        mid = tmp_db.add("test", tags=["a", "b"])
        mem = tmp_db.get(mid)
        assert mem is not None
        assert json.loads(mem["tags"]) == ["a", "b"]

    def test_no_tags_empty_list(self, tmp_db: MemoryDB):
        mid = tmp_db.add("test")
        mem = tmp_db.get(mid)
        assert mem is not None
        assert json.loads(mem["tags"]) == []

    def test_source_stored(self, tmp_db: MemoryDB):
        mid = tmp_db.add("test", source="conversation")
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["source"] == "conversation"

    def test_source_default_none(self, tmp_db: MemoryDB):
        mid = tmp_db.add("test")
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["source"] is None

    def test_timestamps_set(self, tmp_db: MemoryDB):
        mid = tmp_db.add("test")
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["created_at"] is not None
        assert mem["updated_at"] is not None
        assert mem["last_accessed"] is not None

    def test_access_count_zero(self, tmp_db: MemoryDB):
        mid = tmp_db.add("test")
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["access_count"] == 0


class TestGet:
    def test_existing(self, tmp_db: MemoryDB):
        mid = tmp_db.add("hello world")
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["content"] == "hello world"
        assert mem["id"] == mid

    def test_nonexistent(self, tmp_db: MemoryDB):
        assert tmp_db.get("nonexistent") is None

    def test_all_fields_present(self, tmp_db: MemoryDB):
        mid = tmp_db.add("test", category="cat", tags=["t"], source="src")
        mem = tmp_db.get(mid)
        assert mem is not None
        expected_fields = {
            "id",
            "content",
            "category",
            "tags",
            "source",
            "created_at",
            "updated_at",
            "access_count",
            "last_accessed",
        }
        assert expected_fields.issubset(set(mem.keys()))


class TestUpdate:
    def test_content(self, tmp_db: MemoryDB):
        mid = tmp_db.add("original")
        assert tmp_db.update(mid, content="updated") is True
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["content"] == "updated"

    def test_category(self, tmp_db: MemoryDB):
        mid = tmp_db.add("test", category="old")
        tmp_db.update(mid, category="new")
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["category"] == "new"

    def test_tags(self, tmp_db: MemoryDB):
        mid = tmp_db.add("test", tags=["a"])
        tmp_db.update(mid, tags=["b", "c"])
        mem = tmp_db.get(mid)
        assert mem is not None
        assert json.loads(mem["tags"]) == ["b", "c"]

    def test_updates_timestamp(self, tmp_db: MemoryDB):
        mid = tmp_db.add("test")
        mem = tmp_db.get(mid)
        assert mem is not None
        old_ts = mem["updated_at"]
        time.sleep(0.01)
        tmp_db.update(mid, content="changed")
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["updated_at"] >= old_ts

    def test_nonexistent_returns_false(self, tmp_db: MemoryDB):
        assert tmp_db.update("nonexistent", content="x") is False

    def test_partial_update_preserves_fields(self, tmp_db: MemoryDB):
        """Updating category should not change content or tags."""
        mid = tmp_db.add("content", category="old", tags=["tag1"])
        tmp_db.update(mid, category="new")
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["content"] == "content"
        assert mem["category"] == "new"
        assert json.loads(mem["tags"]) == ["tag1"]


class TestDelete:
    def test_existing(self, tmp_db: MemoryDB):
        mid = tmp_db.add("to delete")
        assert tmp_db.delete(mid) is True
        assert tmp_db.get(mid) is None

    def test_nonexistent(self, tmp_db: MemoryDB):
        assert tmp_db.delete("nonexistent") is False

    def test_removes_from_fts(self, tmp_db: MemoryDB):
        """Deleted memories must not appear in FTS search results."""
        mid = tmp_db.add("unique findable xyzabc text")
        tmp_db.delete(mid)
        results = tmp_db.search("xyzabc")
        assert len(results) == 0

    def test_delete_then_readd(self, tmp_db: MemoryDB):
        """Verify DB integrity after delete + re-add."""
        mid1 = tmp_db.add("content A")
        tmp_db.delete(mid1)
        mid2 = tmp_db.add("content B")
        mem = tmp_db.get(mid2)
        assert mem is not None
        assert mem["content"] == "content B"
        assert tmp_db.stats()["total_memories"] == 1


class TestList:
    def test_all(self, tmp_db_with_data: MemoryDB):
        results = tmp_db_with_data.list_memories()
        assert len(results) == 4

    def test_by_category(self, tmp_db_with_data: MemoryDB):
        results = tmp_db_with_data.list_memories(category="tech")
        assert len(results) == 2
        assert all(r["category"] == "tech" for r in results)

    def test_nonexistent_category(self, tmp_db_with_data: MemoryDB):
        results = tmp_db_with_data.list_memories(category="nonexistent")
        assert results == []

    def test_ordered_by_updated_desc(self, tmp_db: MemoryDB):
        tmp_db.add("first")
        time.sleep(0.01)
        tmp_db.add("second")
        results = tmp_db.list_memories()
        assert results[0]["content"] == "second"

    def test_limit(self, tmp_db_with_data: MemoryDB):
        results = tmp_db_with_data.list_memories(limit=2)
        assert len(results) == 2

    def test_offset(self, tmp_db_with_data: MemoryDB):
        all_results = tmp_db_with_data.list_memories()
        offset_results = tmp_db_with_data.list_memories(offset=2)
        assert len(offset_results) == 2
        assert offset_results[0]["id"] == all_results[2]["id"]

    def test_empty_db(self, tmp_db: MemoryDB):
        assert tmp_db.list_memories() == []

    def test_returns_dicts(self, tmp_db: MemoryDB):
        tmp_db.add("test")
        results = tmp_db.list_memories()
        assert isinstance(results[0], dict)


class TestSearch:
    def test_basic_match(self, tmp_db_with_data: MemoryDB):
        results = tmp_db_with_data.search("Python programming")
        assert len(results) > 0
        assert any("Python" in r["content"] for r in results)

    def test_prefix_matching(self, tmp_db_with_data: MemoryDB):
        """FTS5 prefix matching: 'prog' should match 'programming'."""
        results = tmp_db_with_data.search("prog")
        assert len(results) > 0

    def test_or_logic(self, tmp_db_with_data: MemoryDB):
        """Multiple words should use OR: match python OR groceries."""
        results = tmp_db_with_data.search("python groceries")
        assert len(results) >= 2

    def test_category_filter(self, tmp_db_with_data: MemoryDB):
        results = tmp_db_with_data.search("Python", category="tech")
        assert all(r["category"] == "tech" for r in results)

    def test_category_filter_excludes(self, tmp_db_with_data: MemoryDB):
        """Category filter should exclude non-matching results."""
        results = tmp_db_with_data.search("Python", category="personal")
        assert len(results) == 0

    def test_tag_filter(self, tmp_db_with_data: MemoryDB):
        results = tmp_db_with_data.search("Python", tags=["python"])
        assert len(results) > 0
        for r in results:
            assert "python" in json.loads(r["tags"])

    def test_no_results(self, tmp_db_with_data: MemoryDB):
        results = tmp_db_with_data.search("xyznonexistent")
        assert len(results) == 0

    def test_updates_access_count(self, tmp_db_with_data: MemoryDB):
        results = tmp_db_with_data.search("Python")
        assert len(results) > 0
        mid = results[0]["id"]
        mem = tmp_db_with_data.get(mid)
        assert mem is not None
        assert mem["access_count"] >= 1

    def test_limit(self, tmp_db: MemoryDB):
        for i in range(10):
            tmp_db.add(f"memory about testing number {i}")
        results = tmp_db.search("testing", limit=3)
        assert len(results) <= 3

    def test_special_characters(self, tmp_db: MemoryDB):
        """Quotes and special chars in content + query."""
        tmp_db.add('Content with "double quotes" and @#$%')
        results = tmp_db.search("quotes special")
        assert len(results) > 0

    def test_unicode_search(self, tmp_db: MemoryDB):
        tmp_db.add("Tiếng Việt có dấu")
        results = tmp_db.search("Tiếng Việt")
        assert len(results) > 0

    def test_score_in_results(self, tmp_db_with_data: MemoryDB):
        results = tmp_db_with_data.search("Python")
        assert len(results) > 0
        assert "score" in results[0]
        assert results[0]["score"] > 0

    def test_internal_scores_cleaned(self, tmp_db_with_data: MemoryDB):
        """Internal scores (fts_score, vec_score, rank) must not leak."""
        results = tmp_db_with_data.search("Python")
        assert len(results) > 0
        assert "fts_score" not in results[0]
        assert "vec_score" not in results[0]

    def test_empty_query_no_crash(self, tmp_db_with_data: MemoryDB):
        """Empty query should not crash."""
        results = tmp_db_with_data.search("")
        assert isinstance(results, list)

    def test_single_word(self, tmp_db_with_data: MemoryDB):
        results = tmp_db_with_data.search("meeting")
        assert len(results) > 0
        assert any("Meeting" in r["content"] for r in results)


class TestStats:
    def test_empty_db(self, tmp_db: MemoryDB):
        s = tmp_db.stats()
        assert s["total_memories"] == 0
        assert s["categories"] == {}
        assert s["last_updated"] is None

    def test_with_data(self, tmp_db_with_data: MemoryDB):
        s = tmp_db_with_data.stats()
        assert s["total_memories"] == 4
        assert "tech" in s["categories"]
        assert s["categories"]["tech"] == 2
        assert s["vec_enabled"] is False
        assert s["db_path"] is not None

    def test_last_updated(self, tmp_db: MemoryDB):
        tmp_db.add("test")
        s = tmp_db.stats()
        assert s["last_updated"] is not None

    def test_categories_count(self, tmp_db: MemoryDB):
        tmp_db.add("a", category="x")
        tmp_db.add("b", category="x")
        tmp_db.add("c", category="y")
        s = tmp_db.stats()
        assert s["categories"] == {"x": 2, "y": 1}


class TestExportImport:
    def test_export_jsonl_format(self, tmp_db_with_data: MemoryDB):
        jsonl = tmp_db_with_data.export_jsonl()
        lines = [ln for ln in jsonl.split("\n") if ln.strip()]
        assert len(lines) == 4
        for line in lines:
            obj = json.loads(line)
            assert "id" in obj
            assert "content" in obj
            assert isinstance(obj["tags"], list)  # Tags parsed from JSON

    def test_export_empty(self, tmp_db: MemoryDB):
        assert tmp_db.export_jsonl() == ""

    def test_import_merge(self, tmp_db: MemoryDB):
        data = json.dumps({"id": "test001", "content": "imported memory"})
        result = tmp_db.import_jsonl(data, mode="merge")
        assert result["imported"] == 1
        assert result["skipped"] == 0
        mem = tmp_db.get("test001")
        assert mem is not None
        assert mem["content"] == "imported memory"

    def test_import_merge_skips_existing(self, tmp_db: MemoryDB):
        mid = tmp_db.add("original")
        data = json.dumps({"id": mid, "content": "should not replace"})
        result = tmp_db.import_jsonl(data, mode="merge")
        assert result["skipped"] == 1
        assert result["imported"] == 0
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["content"] == "original"

    def test_import_replace_clears_first(self, tmp_db: MemoryDB):
        tmp_db.add("old memory 1")
        tmp_db.add("old memory 2")
        data = json.dumps({"id": "new001", "content": "new memory"})
        result = tmp_db.import_jsonl(data, mode="replace")
        assert result["imported"] == 1
        assert tmp_db.stats()["total_memories"] == 1

    def test_roundtrip(self, tmp_db_with_data: MemoryDB, tmp_path):
        """Export → import into fresh DB → verify data matches."""
        jsonl = tmp_db_with_data.export_jsonl()

        db2 = MemoryDB(tmp_path / "db2.db", embedding_dims=0)
        result = db2.import_jsonl(jsonl, mode="merge")
        assert result["imported"] == 4

        for mem in tmp_db_with_data.list_memories():
            mem2 = db2.get(mem["id"])
            assert mem2 is not None
            assert mem2["content"] == mem["content"]
            assert mem2["category"] == mem["category"]
        db2.close()

    def test_import_multiline(self, tmp_db: MemoryDB):
        lines = [
            json.dumps({"id": "m1", "content": "first"}),
            json.dumps({"id": "m2", "content": "second"}),
            json.dumps({"id": "m3", "content": "third"}),
        ]
        result = tmp_db.import_jsonl("\n".join(lines), mode="merge")
        assert result["imported"] == 3
        assert tmp_db.stats()["total_memories"] == 3

    def test_import_preserves_metadata(self, tmp_db: MemoryDB):
        data = json.dumps(
            {
                "id": "meta1",
                "content": "test",
                "category": "special",
                "tags": ["a", "b"],
                "source": "test-suite",
                "access_count": 5,
            }
        )
        tmp_db.import_jsonl(data, mode="merge")
        mem = tmp_db.get("meta1")
        assert mem is not None
        assert mem["category"] == "special"
        assert json.loads(mem["tags"]) == ["a", "b"]
        assert mem["source"] == "test-suite"
        assert mem["access_count"] == 5

    def test_import_blank_lines_skipped(self, tmp_db: MemoryDB):
        data = (
            json.dumps({"id": "a1", "content": "first"})
            + "\n\n\n"
            + json.dumps({"id": "a2", "content": "second"})
            + "\n"
        )
        result = tmp_db.import_jsonl(data, mode="merge")
        assert result["imported"] == 2


class TestVecDisabled:
    def test_vec_disabled_with_zero_dims(self, tmp_db: MemoryDB):
        assert tmp_db.vec_enabled is False

    def test_add_with_embedding_no_crash(self, tmp_db: MemoryDB):
        """Passing embedding should not crash even if vec is disabled."""
        mid = tmp_db.add("test", embedding=[0.1, 0.2, 0.3])
        assert tmp_db.get(mid) is not None

    def test_search_without_embeddings(self, tmp_db: MemoryDB):
        """Search should work with FTS5 only when vec is disabled."""
        tmp_db.add("searchable content here")
        results = tmp_db.search("searchable content")
        assert len(results) > 0


class TestEdgeCases:
    def test_empty_content(self, tmp_db: MemoryDB):
        mid = tmp_db.add("")
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["content"] == ""

    def test_very_long_content(self, tmp_db: MemoryDB):
        content = "x" * 100_000
        mid = tmp_db.add(content)
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["content"] == content

    def test_unicode_content(self, tmp_db: MemoryDB):
        content = "日本語テスト 한국어 中文 Tiếng Việt 🎉"
        mid = tmp_db.add(content)
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["content"] == content

    def test_unique_ids(self, tmp_db: MemoryDB):
        """100 sequential adds should produce 100 unique IDs."""
        ids = {tmp_db.add(f"memory {i}") for i in range(100)}
        assert len(ids) == 100

    def test_json_in_content(self, tmp_db: MemoryDB):
        content = json.dumps({"key": "value", "nested": [1, 2, 3]})
        mid = tmp_db.add(content)
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["content"] == content

    def test_newlines_in_content(self, tmp_db: MemoryDB):
        content = "line1\nline2\nline3"
        mid = tmp_db.add(content)
        mem = tmp_db.get(mid)
        assert mem is not None
        assert mem["content"] == content

    def test_many_tags(self, tmp_db: MemoryDB):
        tags = [f"tag{i}" for i in range(50)]
        mid = tmp_db.add("test", tags=tags)
        mem = tmp_db.get(mid)
        assert mem is not None
        assert json.loads(mem["tags"]) == tags

    def test_db_path_property(self, tmp_db: MemoryDB):
        s = tmp_db.stats()
        assert "test.db" in s["db_path"]


class TestPhraseTierQueries:
    """Verify _build_fts_queries produces 3-tier PHRASE/AND/OR queries."""

    def test_single_word(self):
        queries = _build_fts_queries("python")
        assert len(queries) == 1
        assert '"python"*' in queries[0]

    def test_multi_word_three_tiers(self):
        queries = _build_fts_queries("machine learning")
        assert len(queries) == 3
        # Tier 0: PHRASE
        assert queries[0] == '"machine learning"'
        # Tier 1: AND
        assert "AND" in queries[1]
        # Tier 2: OR
        assert "OR" in queries[2]

    def test_empty_query(self):
        assert _build_fts_queries("") == []

    def test_whitespace_only(self):
        assert _build_fts_queries("   ") == []

    def test_quotes_escaped(self):
        queries = _build_fts_queries('say "hello"')
        assert len(queries) == 3
        # Double quotes should be escaped
        assert '""' in queries[0]
