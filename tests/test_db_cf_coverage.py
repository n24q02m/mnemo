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


# --- JSONL export / import (parity with db.MemoryDB, scoped to self.sub) ------


def test_export_jsonl_scopes_to_sub(fake_d1_http, fake_vectorize_http):
    """Export emits only the calling sub's rows, one canonical JSON object each."""
    import json as _json

    a = _db(fake_d1_http, fake_vectorize_http, sub="user1")
    a.add("alpha note", category="fact", tags=["x"])
    a.add("beta note", category="pref")
    # A second sub sharing the same D1 must not bleed into user1's export.
    _db(fake_d1_http, fake_vectorize_http, sub="user2").add("other-sub note")

    jsonl, count = a.export_jsonl()
    assert count == 2
    objs = [_json.loads(line) for line in jsonl.strip().split("\n")]
    assert {o["content"] for o in objs} == {"alpha note", "beta note"}
    # Canonical field set (no `sub` leaked into the payload); tags re-parsed to list.
    assert set(objs[0]) == {
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
    assert any(o["tags"] == ["x"] for o in objs)


def test_import_jsonl_merge_inserts_then_skips_existing(
    fake_d1_http, fake_vectorize_http
):
    db = _db(fake_d1_http, fake_vectorize_http)
    rows = [
        {"id": "m1", "content": "first imported", "category": "fact"},
        {"id": "m2", "content": "second imported", "category": "plan"},
    ]
    r1 = db.import_jsonl(rows, mode="merge")
    assert r1 == {"imported": 2, "skipped": 0, "rejected": 0}
    assert db.stats()["total_memories"] == 2
    # Re-importing the same ids in merge mode skips them (INSERT OR IGNORE).
    r2 = db.import_jsonl(rows, mode="merge")
    assert r2 == {"imported": 0, "skipped": 2, "rejected": 0}
    assert db.stats()["total_memories"] == 2


def test_import_jsonl_injects_caller_sub_not_payload(fake_d1_http, fake_vectorize_http):
    """A `sub` embedded in the payload is ignored; rows land under the importer."""
    importer = _db(fake_d1_http, fake_vectorize_http, sub="owner")
    importer.import_jsonl(
        [{"id": "p1", "content": "claimed by other", "sub": "intruder"}]
    )
    assert importer.stats()["total_memories"] == 1
    # The intruder sub must see nothing.
    assert (
        _db(fake_d1_http, fake_vectorize_http, sub="intruder").stats()["total_memories"]
        == 0
    )


def test_import_jsonl_replace_clears_sub_first(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    db.add("stale memory", category="fact")
    res = db.import_jsonl(
        [{"id": "n1", "content": "fresh memory", "category": "fact"}], mode="replace"
    )
    assert res["imported"] == 1
    stats = db.stats()
    assert stats["total_memories"] == 1
    assert db.search("fresh", limit=5)[0]["content"] == "fresh memory"
    assert db.search("stale", limit=5) == []


def test_import_jsonl_rejects_oversized_and_empty(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    res = db.import_jsonl(
        [
            {"id": "ok", "content": "fine"},
            {"id": "big", "content": "x" * 5001},
            {"id": "empty", "content": ""},
        ]
    )
    assert res == {"imported": 1, "skipped": 0, "rejected": 2}
    assert db.stats()["total_memories"] == 1


def test_import_jsonl_string_preserves_fields_and_is_searchable(
    fake_d1_http, fake_vectorize_http
):
    db = _db(fake_d1_http, fake_vectorize_http)
    line = (
        '{"id": "s1", "content": "polars beats pandas", "category": "preference", '
        '"tags": ["python"], "created_at": "2026-02-12T00:00:00", "importance": 0.9}'
    )
    res = db.import_jsonl(line)
    assert res["imported"] == 1
    got = db.get("s1")
    assert got["category"] == "preference"
    assert got["created_at"] == "2026-02-12T00:00:00"
    assert got["importance"] == 0.9
    # Trigger-maintained FTS makes the imported row immediately keyword-searchable.
    assert any(m["id"] == "s1" for m in db.search("polars", limit=5))


def test_export_then_import_roundtrips_into_fresh_sub(
    fake_d1_http, fake_vectorize_http
):
    src = _db(fake_d1_http, fake_vectorize_http, sub="src")
    src.add("portable memory one", category="fact", tags=["t1"])
    src.add("portable memory two", category="plan")
    jsonl, count = src.export_jsonl()

    dst = _db(fake_d1_http, fake_vectorize_http, sub="dst")
    res = dst.import_jsonl(jsonl)
    assert res["imported"] == count == 2
    assert dst.stats()["total_memories"] == 2
    assert any(
        m["content"] == "portable memory one" for m in dst.search("portable", limit=5)
    )


def test_import_jsonl_single_dict_input(fake_d1_http, fake_vectorize_http):
    """A bare dict (not wrapped in a list) imports as one row."""
    db = _db(fake_d1_http, fake_vectorize_http)
    res = db.import_jsonl({"id": "d1", "content": "lone dict memory"})
    assert res["imported"] == 1
    assert db.get("d1")["content"] == "lone dict memory"


def test_import_jsonl_string_counts_malformed_lines_as_rejected(
    fake_d1_http, fake_vectorize_http
):
    # A blank line is skipped (not counted); two malformed lines are rejected.
    data = '{"id": "g1", "content": "good"}\n\nnot-json\n{bad json}'
    res = _db(fake_d1_http, fake_vectorize_http).import_jsonl(data)
    assert res["imported"] == 1
    assert res["rejected"] == 2


def test_import_jsonl_unsupported_type_imports_nothing(
    fake_d1_http, fake_vectorize_http
):
    """A non-str/list/dict payload parses to no items (and skips the insert)."""
    db = _db(fake_d1_http, fake_vectorize_http)
    res = db.import_jsonl(12345)  # type: ignore[arg-type]
    assert res == {"imported": 0, "skipped": 0, "rejected": 0}


def test_import_jsonl_non_dict_item_is_rejected(fake_d1_http, fake_vectorize_http):
    """A list element that is not a mapping is rejected, not fatal."""
    db = _db(fake_d1_http, fake_vectorize_http)
    res = db.import_jsonl([{"id": "ok", "content": "fine"}, "not-a-dict", 99])
    assert res["imported"] == 1
    assert res["rejected"] == 2


def test_import_jsonl_accepts_prestringified_tags(fake_d1_http, fake_vectorize_http):
    """Tags already serialized as a JSON string pass through unchanged."""
    db = _db(fake_d1_http, fake_vectorize_http)
    res = db.import_jsonl([{"id": "pt", "content": "tagged", "tags": '["a", "b"]'}])
    assert res["imported"] == 1
    assert db.get("pt")["tags"] == '["a", "b"]'


def test_import_jsonl_bulk_stays_under_d1_param_limit(
    fake_d1_http, fake_vectorize_http
):
    """A bulk import must never bind more than D1's 100-parameter-per-query
    ceiling. Regression: D1Backend.executemany chunks by ROW (default 100), so a
    wide-row batch (11 cols) overflowed D1's wire limit and disconnected the
    container live -- the in-memory FakeD1Http does not enforce it, so this spies
    on the wire params directly. import_jsonl must pre-chunk to stay safe.
    """
    import json as _json

    max_params = {"n": 0}
    original = fake_d1_http.request

    def spy(method, url, data=None, headers=None):
        if data and url.endswith("/query"):
            params = _json.loads(data.decode()).get("params", [])
            max_params["n"] = max(max_params["n"], len(params))
        return original(method, url, data=data, headers=headers)

    fake_d1_http.request = spy
    db = _db(fake_d1_http, fake_vectorize_http)
    rows = [{"id": f"m{i}", "content": f"bulk memory number {i}"} for i in range(25)]
    res = db.import_jsonl(rows)
    assert res["imported"] == 25
    assert max_params["n"] <= 100, (
        f"a single D1 query bound {max_params['n']} params (> 100 ceiling)"
    )
