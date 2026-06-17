"""graph.py runs unchanged against MemoryDBD1._conn (the D1Connection shim).

The knowledge-graph helpers take a raw connection and emit SQL; on D1 every
graph table carries `sub`, so the helpers must inject it when the connection is
the shim (and stay byte-for-byte sub-less on the local sqlite path). These tests
exercise upsert -> relate -> link -> recursive-CTE traverse through the shim and
prove cross-sub graph isolation (DECISION D3).
"""

from mcp_core.storage import D1Backend, VectorizeBackend

from mnemo_mcp.db_cf import MemoryDBD1
from mnemo_mcp.graph import (
    create_relations,
    find_related_memory_ids,
    link_memory_entities,
    upsert_entities,
)


def _db(fake_d1_http, fake_vectorize_http, sub="u1"):
    return MemoryDBD1(
        d1=D1Backend(base_url="http://d1.internal", http=fake_d1_http),
        vectorize=VectorizeBackend(
            base_url="http://vectorize.internal", idx="i", http=fake_vectorize_http
        ),
        sub=sub,
        embedding_dims=0,
    )


def test_graph_upsert_link_traverse_via_shim(fake_d1_http, fake_vectorize_http):
    db = _db(fake_d1_http, fake_vectorize_http)
    m1 = db.add("Python project uses pytest")
    m2 = db.add("pytest runs the test suite")
    conn = db._conn  # D1Connection shim
    ids = upsert_entities(
        conn,
        [
            {"name": "Python", "type": "tool"},
            {"name": "pytest", "type": "tool"},
        ],
    )
    assert len(ids) == 2
    create_relations(
        conn,
        [{"source": "Python", "target": "pytest", "type": "uses"}],
        {"Python": ids[0], "pytest": ids[1]},
    )
    link_memory_entities(conn, m1, [ids[0]])
    link_memory_entities(conn, m2, [ids[1]])
    related = find_related_memory_ids(conn, m1, max_depth=2)
    assert m2 in related  # traversed Python -uses-> pytest -> m2


def test_graph_per_sub_isolation(fake_d1_http, fake_vectorize_http):
    """user2's graph traversal must not see user1's entity links (shared D1)."""
    db1 = _db(fake_d1_http, fake_vectorize_http, sub="user1")
    db2 = _db(fake_d1_http, fake_vectorize_http, sub="user2")
    m1 = db1.add("u1 mem A")
    m1b = db1.add("u1 mem B")
    ids = upsert_entities(db1._conn, [{"name": "Shared", "type": "tool"}])
    link_memory_entities(db1._conn, m1, ids)
    link_memory_entities(db1._conn, m1b, ids)
    # user1 sees the sibling via the shared entity.
    assert m1b in find_related_memory_ids(db1._conn, m1, max_depth=2)
    # user2 has no links at all -> empty traversal, no cross-sub bleed.
    assert find_related_memory_ids(db2._conn, m1, max_depth=2) == []
