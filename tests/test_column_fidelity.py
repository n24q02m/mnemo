"""``db.MEMORY_COLUMNS`` must track the live ``memories`` schema.

Export and import serialize a row through that one tuple, so a migration that
adds a column without updating it would make export/import drop the column and
still report success.
"""

from mnemo.db import MEMORY_COLUMNS, MemoryDB


def test_memory_columns_match_live_schema(tmp_db: MemoryDB) -> None:
    """Order and membership equal ``PRAGMA table_info(memories)`` at head."""
    rows = tmp_db._conn.execute("PRAGMA table_info(memories)").fetchall()

    assert tuple(row[1] for row in rows) == MEMORY_COLUMNS
