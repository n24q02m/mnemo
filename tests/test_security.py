import pytest

from mnemo_mcp.db import MemoryDB


def test_tag_filtering_security(tmp_db: MemoryDB):
    # Setup
    tmp_db.add("memory 1", tags=["tag1", "tag2"])
    tmp_db.add("memory 2", tags=["tag3"])

    # Test normal tag filtering
    results = tmp_db.search("memory", tags=["tag1"])
    assert len(results) == 1
    assert results[0]["content"] == "memory 1"

    # Test multiple tags (OR behavior)
    results = tmp_db.search("memory", tags=["tag1", "tag3"])
    assert len(results) == 2

    # Test non-matching tags
    results = tmp_db.search("memory", tags=["nonexistent"])
    assert len(results) == 0


def test_max_tags_limit(tmp_db: MemoryDB):
    # This will test our new limit
    large_tags = [f"tag{i}" for i in range(51)]
    with pytest.raises(ValueError, match="Maximum of 50 tags allowed in search filter"):
        tmp_db.search("memory", tags=large_tags)
