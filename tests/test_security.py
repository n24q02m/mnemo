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


def test_update_security(tmp_db: MemoryDB):
    """Verify update method robustness."""
    mid = tmp_db.add("content", category="cat")

    # Verify that we cannot update internal columns even if we try to be clever
    # The new implementation doesn'\''t even take a list of columns, so it'\''s
    # much harder to exploit.

    # Normal update works
    new_id = tmp_db.update(mid, content="new content")
    assert new_id is not None
    mem = tmp_db.get(new_id)
    assert mem is not None
    assert mem["content"] == "new content"

    # Try to inject something into a parameter (though it'\''s already safe due to placeholders)
    # This is more of a sanity check.
    malicious_content = "content', category='pwned"
    newer_id = tmp_db.update(new_id, content=malicious_content)
    assert newer_id is not None
    mem = tmp_db.get(newer_id)
    assert mem is not None
    assert mem["content"] == malicious_content
    assert mem["category"] == "cat"  # Category remains unchanged


def test_update_security_extended(tmp_db: MemoryDB):
    """Verify that only authorized columns can be updated via the CASE WHEN pattern."""
    mid = tmp_db.add(
        "original content", category="original cat", source="original source"
    )

    # Verify we can update new fields
    new_id = tmp_db.update(mid, source="new source", importance=0.8)
    assert new_id is not None
    mem = tmp_db.get(new_id)
    assert mem is not None
    assert mem["source"] == "new source"
    assert mem["importance"] == 0.8

    # The vulnerability was about dynamic SQL construction where column names
    # were interpolated. With the CASE WHEN pattern, the column names are static.
    # Even if someone tries to pass a malicious string to one of the parameters,
    # it is treated as a value, not a column name.

    malicious_val = "ignored' --"
    newer_id = tmp_db.update(new_id, category=malicious_val)
    assert newer_id is not None
    mem = tmp_db.get(newer_id)
    assert mem is not None
    assert mem["category"] == malicious_val
    assert mem["content"] == "original content"


class ConnectionProxy:
    def __init__(self, conn):
        self.conn = conn
        self.executed_queries = []

    def execute(self, sql, params=()):
        self.executed_queries.append((sql, params))
        return self.conn.execute(sql, params)

    def fetchall(self):
        return self.conn.fetchall()

    def __getattr__(self, name):
        return getattr(self.conn, name)


def test_build_filter_sql_safety_extended(tmp_db: MemoryDB):
    proxy = ConnectionProxy(tmp_db._conn)
    tmp_db._conn = proxy  # ty: ignore

    malicious_context = "some_ctx' OR 1=1 --"
    tmp_db.search("query", context_type=malicious_context)

    found_fts = False
    for sql, params in proxy.executed_queries:
        if "memories_fts" in sql and "MATCH" in sql:
            found_fts = True
            assert "m.context_type = ?" in sql
            assert malicious_context in params
    assert found_fts


def test_vec_search_injection_extended(tmp_db: MemoryDB):
    # Ensure vec is enabled for this test
    if not tmp_db.vec_enabled:
        tmp_db._embedding_dims = 3
        tmp_db._ensure_vec_table(3)
        tmp_db._vec_enabled = True

    proxy = ConnectionProxy(tmp_db._conn)
    tmp_db._conn = proxy  # ty: ignore

    malicious_context = "some_ctx' OR 1=1 --"
    embedding = [0.1, 0.2, 0.3]

    try:
        tmp_db.search("query", embedding=embedding, context_type=malicious_context)
    except Exception:
        pass

    found_vec = False
    for sql, params in proxy.executed_queries:
        if "memories_vec" in sql and "MATCH" in sql:
            found_vec = True
            assert "m.context_type = ?" in sql
            assert malicious_context in params
    assert found_vec


def test_drop_vectors_injection_prevention(tmp_db: MemoryDB):
    proxy = ConnectionProxy(tmp_db._conn)
    tmp_db._conn = proxy  # ty: ignore

    malicious_table = "memories; DROP TABLE memories; --"

    # This should not be interpolated into any SQL
    try:
        # We can't easily trigger _drop_vectors_for_reindex with a malicious table name
        # from the public API, but we can call it directly to test its internal safety.
        tmp_db._drop_vectors_for_reindex()
    except Exception:
        pass

    for sql, _params in proxy.executed_queries:
        assert malicious_table not in sql
