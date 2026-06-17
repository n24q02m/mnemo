"""Per-sub sync_state on D1 -- the (sub, backend) PK fixes the mem_002 collision.

mem_002 created sync_state with PK=backend only, so two users sharing a D1 would
overwrite each other's gdrive cursor. The D1 schema PK is (sub, backend); these
helpers carry sub so concurrent users keep independent sync cursors.
"""

from mcp_core.storage import D1Backend, VectorizeBackend

from mnemo_mcp.db_cf import MemoryDBD1


def _db(fake_d1_http, fake_vectorize_http, sub):
    return MemoryDBD1(
        d1=D1Backend(base_url="http://d1.internal", http=fake_d1_http),
        vectorize=VectorizeBackend(
            base_url="http://vectorize.internal", idx="i", http=fake_vectorize_http
        ),
        sub=sub,
        embedding_dims=0,
    )


def test_sync_state_no_cross_sub_collision(fake_d1_http, fake_vectorize_http):
    db1 = _db(fake_d1_http, fake_vectorize_http, "user1")
    db2 = _db(fake_d1_http, fake_vectorize_http, "user2")  # same D1
    db1.upsert_sync_state("gdrive", last_sync_at=100.0, upload_cursor=5)
    db2.upsert_sync_state("gdrive", last_sync_at=200.0, upload_cursor=9)
    assert db1.get_sync_state("gdrive")["upload_cursor"] == 5  # no collision
    assert db2.get_sync_state("gdrive")["upload_cursor"] == 9


def test_sync_state_partial_upsert_preserves_existing(
    fake_d1_http, fake_vectorize_http
):
    db = _db(fake_d1_http, fake_vectorize_http, "user1")
    db.upsert_sync_state("gdrive", last_sync_at=100.0, upload_cursor=5)
    db.upsert_sync_state("gdrive", last_commit_sha="abc")  # only sha changes
    state = db.get_sync_state("gdrive")
    assert state["upload_cursor"] == 5 and state["last_commit_sha"] == "abc"


def test_sync_state_missing_returns_none(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http, "user1")
    assert db.get_sync_state("never") is None
