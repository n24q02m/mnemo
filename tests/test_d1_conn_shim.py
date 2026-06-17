"""D1Connection shim contract: a sqlite3.Connection-like surface over D1Backend.

graph.py / temporal/queries.py / temporal/store.py / sync/delta.py all take a
raw sqlite3.Connection (db._conn) and call .execute()/.executemany()/.cursor()/
.commit() directly. The shim lets them run unchanged on D1. These tests pin the
slice of the sqlite3 surface those consumers use; the FakeD1Http (in conftest_cf)
backs each call with a real in-memory sqlite running the D1 DDL, so read-after-
write holds.
"""

from mcp_core.storage import D1Backend

from mnemo_mcp._d1_conn import D1Connection


def test_shim_executes_and_returns_rowlike(fake_d1_http):
    backend = D1Backend(base_url="http://d1.internal", http=fake_d1_http)
    conn = D1Connection(backend, sub="user1")
    conn.execute(
        "INSERT INTO memories (id, content, created_at, updated_at, last_accessed) "
        "VALUES (?, ?, ?, ?, ?)",
        ("m1", "hello world", "2026-01-01", "2026-01-01", "2026-01-01"),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT id, content FROM memories WHERE id = ?", ("m1",)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["id"] == "m1" and rows[0]["content"] == "hello world"


def test_shim_cursor_surface(fake_d1_http):
    backend = D1Backend(base_url="http://d1.internal", http=fake_d1_http)
    conn = D1Connection(backend, sub="user1")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO memory_entities (id, name, entity_type, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("e1", "Python", "tool", "2026-01-01", "2026-01-01"),
    )
    conn.commit()
    out = cur.execute(
        "SELECT name FROM memory_entities WHERE id = ?", ("e1",)
    ).fetchall()
    assert out[0]["name"] == "Python"


def test_shim_executemany(fake_d1_http):
    backend = D1Backend(base_url="http://d1.internal", http=fake_d1_http)
    conn = D1Connection(backend, sub="u")
    conn.executemany(
        "INSERT INTO memory_entity_links (memory_id, entity_id) VALUES (?, ?)",
        [("m1", "e1"), ("m1", "e2")],
    )
    conn.commit()
    rows = conn.execute("SELECT entity_id FROM memory_entity_links", ()).fetchall()
    assert {r["entity_id"] for r in rows} == {"e1", "e2"}


def test_shim_fetchone(fake_d1_http):
    backend = D1Backend(base_url="http://d1.internal", http=fake_d1_http)
    conn = D1Connection(backend, sub="u")
    assert (
        conn.execute("SELECT id FROM memories WHERE id = ?", ("absent",)).fetchone()
        is None
    )
