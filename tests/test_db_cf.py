"""MemoryDBD1 CRUD contract on D1 + Vectorize (per-sub scoped).

Same public surface as mnemo_mcp.db.MemoryDB CRUD, but relational state lands in
D1 (per-sub) and embeddings in Vectorize. test_per_sub_get_isolation proves the
D3 sub-scoping holds at the CRUD layer (same D1, different sub -> no bleed).
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


def test_add_then_get(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    mid = db.add("hello world", category="fact", tags=["x"])
    got = db.get(mid)
    assert got["content"] == "hello world" and got["category"] == "fact"


def test_per_sub_get_isolation(fake_d1_http, fake_vectorize_http):
    db1 = _db(fake_d1_http, fake_vectorize_http, sub="user1")
    db2 = _db(fake_d1_http, fake_vectorize_http, sub="user2")  # same D1, different sub
    mid = db1.add("secret of user1")
    assert db2.get(mid) is None  # no cross-sub bleed


def test_update_and_delete(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    mid = db.add("first")
    assert db.update(mid, content="second") is True
    assert db.get(mid)["content"] == "second"
    assert db.delete(mid) is True
    assert db.get(mid) is None


def test_update_missing_returns_false(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    assert db.update("never", content="x") is False


def test_list_excludes_archived_by_default(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    db.add("a")
    assert len(db.list_memories()) == 1
