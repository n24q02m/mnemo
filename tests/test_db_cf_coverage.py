"""MemoryDBD1 paths beyond CRUD: hybrid vector search + RRF fusion, missing-row
hydration, search filters, stats, and sync_state round-trip. These exercise the
D1+Vectorize read paths that the CRUD and parity suites do not reach.
"""

from mcp_core.storage import D1Backend, VectorizeBackend

from mnemo_mcp.db_cf import MemoryDBD1


def _db(fake_d1_http, fake_vectorize_http, sub="user1"):
    return MemoryDBD1(
        d1=D1Backend(base_url="http://d1.internal", http=fake_d1_http),
        vectorize=VectorizeBackend(
            base_url="http://vectorize.internal", idx="i", http=fake_vectorize_http
        ),
        sub=sub,
        embedding_dims=4,
    )


def test_search_hybrid_fts_and_vector(fake_d1_http, fake_vectorize_http):
    """Query text matches FTS and the embedding matches a vector -> RRF fusion."""
    db = _db(fake_d1_http, fake_vectorize_http)
    m1 = db.add("alpha beta gamma", category="fact", embedding=[1.0, 0.0, 0.0, 0.0])
    db.add("delta epsilon", category="fact", embedding=[0.0, 1.0, 0.0, 0.0])
    res = db.search("alpha", embedding=[1.0, 0.0, 0.0, 0.0], limit=5)
    assert any(r["id"] == m1 for r in res)


def test_search_vector_only_hydrates_missing_row(fake_d1_http, fake_vectorize_http):
    """A vector hit whose id is absent from the FTS results is hydrated from D1."""
    db = _db(fake_d1_http, fake_vectorize_http)
    mid = db.add("zzz unique content", category="fact", embedding=[0.0, 0.0, 1.0, 0.0])
    res = db.search("noFtsMatchHere", embedding=[0.0, 0.0, 1.0, 0.0], limit=5)
    assert any(r["id"] == mid for r in res)


def test_search_with_time_and_importance_filters(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    mid = db.add("filtered note", category="fact", embedding=[1.0, 0.0, 0.0, 0.0])
    db.update(mid, importance=0.9)
    res = db.search(
        "filtered",
        embedding=[1.0, 0.0, 0.0, 0.0],
        since="2000-01-01T00:00:00",
        until="2100-01-01T00:00:00",
        min_importance=0.1,
        limit=5,
    )
    assert any(r["id"] == mid for r in res)


def test_search_with_tags_filter(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    mid = db.add("tagged note", category="fact", tags=["red"], embedding=[1.0, 0, 0, 0])
    res = db.search("tagged", tags=["red"], limit=5)
    assert any(r["id"] == mid for r in res)


def test_search_empty_query_returns_empty(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    db.add("something")
    assert db.search("   ") == []


def test_stats_reports_cf_d1(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    db.add("a", category="fact")
    db.add("b", category="pref")
    s = db.stats()
    assert s["total_memories"] == 2
    assert s["db_path"] == "cf-d1"
    assert s["vec_enabled"] is True
    assert set(s["categories"]) == {"fact", "pref"}


def test_sync_state_roundtrip_and_partial_update(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    assert db.get_sync_state("gdrive") is None
    db.upsert_sync_state(
        "gdrive", last_sync_at=123.0, last_commit_sha="abc", upload_cursor=5
    )
    st = db.get_sync_state("gdrive")
    assert st["last_commit_sha"] == "abc" and st["upload_cursor"] == 5
    # An unset field keeps its stored value (COALESCE-via-existing branch).
    db.upsert_sync_state("gdrive", upload_cursor=9)
    st2 = db.get_sync_state("gdrive")
    assert st2["upload_cursor"] == 9 and st2["last_commit_sha"] == "abc"


def test_add_rejects_oversized_content(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    try:
        db.add("x" * 5001)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_update_rejects_oversized_content(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    mid = db.add("ok")
    try:
        db.update(mid, content="x" * 5001)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_search_rejects_too_many_tags(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    try:
        db.search("q", tags=[f"t{i}" for i in range(51)])
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_delete_missing_returns_false(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    assert db.delete("does-not-exist") is False


def test_get_store_meta_missing_returns_none(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    assert db.get_store_meta("no-such-key") is None


def test_close_is_noop_and_conn_shim_surface(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    conn = db._conn
    assert conn.cursor() is conn
    assert conn.commit() is None
    assert conn.close() is None
    conn.executescript("CREATE TABLE IF NOT EXISTS _cov_probe(x);")
    assert db.close() is None
