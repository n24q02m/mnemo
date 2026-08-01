"""Transactional-safety cover for ``MemoryDB.update()``.

``update()`` supersedes a memory: it closes the predecessor row and writes a
successor row. That is two writes that must land together or not at all, on a
connection opened in legacy autocommit-by-statement mode
(``isolation_level=""``), where any DML implicitly opens a transaction that
only the next ``commit()``/``rollback()`` closes.

Three distinct failure modes are covered here, each reproduced deterministically:

1. The successor INSERT fails. Without a rollback the predecessor stays closed
   against a successor that was never written, and the next unrelated
   ``commit()`` makes that state durable -- the memory is unreachable.
2. ``update()`` is called with an id that does not resolve. The supersede
   statement is an ``UPDATE``, and pysqlite opens a write transaction for an
   ``UPDATE`` even when it matches zero rows, so returning early without a
   rollback leaves that transaction open and locks out every other writer.
   This is an ordinary path, not a rare one: ``update()`` is id-changing, so
   reusing the previous id reaches it.
3. A competing writer supersedes the same row in between the check and the
   write. The check and the write are one statement guarded by
   ``valid_to IS NULL``; deleting that guard produces two live rows and a
   broken supersession chain.

Plus the feature floor the single-statement form depends on: ``RETURNING``
requires SQLite >= 3.35.0.
"""

import sqlite3
import uuid

import pytest

from mnemo_mcp import db as db_module
from mnemo_mcp.db import MemoryDB


class TestFailedSuccessorInsert:
    """Failure mode 1: the successor INSERT aborts mid-supersession."""

    def test_failed_insert_leaves_predecessor_live(self, tmp_db: MemoryDB):
        mid = tmp_db.add("ORIGINAL CONTENT do-not-lose", category="fact", tags=["t1"])

        # Abort the successor INSERT inside SQLite, the way a constraint
        # violation or a broken FTS trigger would.
        tmp_db._conn.execute(
            "CREATE TRIGGER abort_insert BEFORE INSERT ON memories "
            "BEGIN SELECT RAISE(ABORT, 'simulated successor insert failure'); END"
        )
        tmp_db._conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            tmp_db.update(mid, content="NEW CONTENT")

        assert tmp_db._conn.in_transaction is False

        row = tmp_db._conn.execute(
            "SELECT valid_to, superseded_by FROM memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row["valid_to"] is None
        assert row["superseded_by"] is None
        assert tmp_db.get(mid) is not None

    def test_later_write_does_not_commit_a_dangling_pointer(self, tmp_db: MemoryDB):
        """The damage is only durable once something else commits -- check that."""
        mid = tmp_db.add("ORIGINAL CONTENT do-not-lose")

        tmp_db._conn.execute(
            "CREATE TRIGGER abort_insert BEFORE INSERT ON memories "
            "BEGIN SELECT RAISE(ABORT, 'simulated successor insert failure'); END"
        )
        tmp_db._conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            tmp_db.update(mid, content="NEW CONTENT")

        tmp_db._conn.execute("DROP TRIGGER abort_insert")
        tmp_db.add("some later unrelated memory")  # commits

        probe = sqlite3.connect(str(tmp_db._db_path))
        probe.row_factory = sqlite3.Row
        try:
            durable = probe.execute(
                "SELECT valid_to, superseded_by FROM memories WHERE id = ?", (mid,)
            ).fetchone()
            assert durable["valid_to"] is None
            assert durable["superseded_by"] is None
            successors = probe.execute(
                "SELECT COUNT(*) FROM memories WHERE id = ?",
                (durable["superseded_by"],),
            ).fetchone()[0]
            assert successors == 0
        finally:
            probe.close()


class TestNotFoundBranch:
    """Failure mode 2: the early return must not leak a write transaction."""

    def test_unknown_id_leaves_no_open_transaction(self, tmp_db: MemoryDB):
        tmp_db.add("seed")
        assert tmp_db._conn.in_transaction is False

        assert tmp_db.update(uuid.uuid4().hex, content="x") is None
        assert tmp_db._conn.in_transaction is False

    def test_stale_id_leaves_no_open_transaction(self, tmp_db: MemoryDB):
        """``update()`` is id-changing, so reusing the old id is the ordinary
        way callers reach the not-found branch."""
        mid = tmp_db.add("seed content alpha")
        new_id = tmp_db.update(mid, content="v2")
        assert new_id is not None

        assert tmp_db.update(mid, content="v3") is None
        assert tmp_db._conn.in_transaction is False

        # Read traffic does not release a leaked write transaction either.
        tmp_db.get(new_id)
        tmp_db.search("alpha", limit=3)
        tmp_db.list_memories(limit=3)
        assert tmp_db._conn.in_transaction is False

    def test_unknown_id_does_not_lock_out_other_writers(self, tmp_db: MemoryDB):
        assert tmp_db.update(uuid.uuid4().hex, content="x") is None

        other = sqlite3.connect(str(tmp_db._db_path), timeout=1.0)
        try:
            other.execute("INSERT INTO store_meta (key, value) VALUES ('probe', '1')")
            other.commit()
        finally:
            other.close()

    def test_unknown_id_does_not_block_wal_checkpoint(self, tmp_db: MemoryDB):
        tmp_db.add("seed")
        assert tmp_db.update(uuid.uuid4().hex, content="x") is None

        busy, _, _ = tmp_db._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        assert busy == 0, "checkpoint blocked -- a write transaction is still open"


class _FireOnceProxy:
    """Connection wrapper that runs ``hook`` once, immediately before the
    supersede statement -- the exact window a competing writer would land in.
    Everything else forwards to the real connection untouched.
    """

    def __init__(self, real, hook):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_hook", hook)
        object.__setattr__(self, "_fired", False)

    def execute(self, sql, params=()):
        if not object.__getattribute__(self, "_fired") and sql.lstrip().startswith(
            "UPDATE memories SET valid_to"
        ):
            object.__setattr__(self, "_fired", True)
            object.__getattribute__(self, "_hook")()
        return object.__getattribute__(self, "_real").execute(sql, params)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_real"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_real"), name, value)


class TestSupersedeGuard:
    """Failure mode 3: regression cover for the ``valid_to IS NULL`` guard.

    Deleting ``AND valid_to IS NULL`` from the supersede statement must make
    this fail -- that guard is the whole reason the check and the write have
    to be one statement.
    """

    def test_refuses_a_row_a_competitor_already_closed(
        self, tmp_db: MemoryDB, monkeypatch
    ):
        mid = tmp_db.add("v1 original", category="fact")
        tmp_db._conn.commit()
        competitor_id = uuid.uuid4().hex

        def competitor() -> None:
            """A second connection supersedes the same row and commits."""
            conn = sqlite3.connect(str(tmp_db._db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT * FROM memories WHERE id = ?", (mid,)
                ).fetchone()
                successor = dict(row)
                successor["id"] = competitor_id
                successor["content"] = "v2-COMPETITOR"
                successor["valid_to"] = None
                successor["superseded_by"] = None
                conn.execute(
                    "UPDATE memories SET valid_to = ?, superseded_by = ? "
                    "WHERE id = ? AND valid_to IS NULL",
                    ("2026-01-01T00:00:00+00:00", competitor_id, mid),
                )
                cols = list(successor)
                conn.execute(
                    f"INSERT INTO memories ({', '.join(cols)}) "
                    f"VALUES ({', '.join('?' * len(cols))})",
                    [successor[c] for c in cols],
                )
                conn.commit()
            finally:
                conn.close()

        # monkeypatch restores the real connection at teardown; the assertions
        # below go through ``real`` directly either way.
        real = tmp_db._conn
        monkeypatch.setattr(tmp_db, "_conn", _FireOnceProxy(real, competitor))
        loser = tmp_db.update(mid, content="v2-LOSER")

        assert loser is None, "supersede must refuse an already-closed row"

        live = [
            r["id"]
            for r in real.execute(
                "SELECT id FROM memories WHERE valid_to IS NULL"
            ).fetchall()
        ]
        assert live == [competitor_id], "the race left more than one live row"

        closed = real.execute(
            "SELECT superseded_by FROM memories WHERE id = ?", (mid,)
        ).fetchone()
        assert closed["superseded_by"] == competitor_id, "supersession chain broken"


class TestSqliteFeatureFloor:
    """``UPDATE ... RETURNING`` needs SQLite >= 3.35.0.

    A Python linked against an older library fails at the first ``update()``
    call with a syntax error, not at install time, so the check belongs at
    open with a message that names the requirement.
    """

    def test_open_refuses_sqlite_without_returning(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db_module.sqlite3, "sqlite_version_info", (3, 34, 0))
        monkeypatch.setattr(db_module.sqlite3, "sqlite_version", "3.34.0")

        with pytest.raises(RuntimeError, match=r"3\.35\.0"):
            MemoryDB(tmp_path / "old_sqlite.db", embedding_dims=0)

    def test_open_accepts_the_minimum_supported_version(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            db_module.sqlite3, "sqlite_version_info", db_module.MIN_SQLITE_VERSION
        )

        db = MemoryDB(tmp_path / "min_sqlite.db", embedding_dims=0)
        db.close()
