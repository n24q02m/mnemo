"""Thread-safety cover for the one shared ``MemoryDB`` connection.

``MemoryDB`` opens a single ``sqlite3`` connection with
``check_same_thread=False`` and the server reaches it from every
``asyncio.to_thread`` worker as well as from the event-loop thread. Without
serialization the statements of concurrent callers interleave on that one
connection: a ``commit()`` or ``rollback()`` from one thread lands in the
middle of another thread's transaction, and concurrent use of the connection
surfaces as ``sqlite3.InterfaceError: bad parameter or other API misuse``.
Six concurrent ``add_memory`` calls over HTTP lost a row that way.

The hammer test drives that path with many threads and a tiny GIL switch
interval. The static guards keep the fix from eroding: every ``self._conn``
use in ``MemoryDB`` must sit inside ``with self._lock``, and no module outside
``db.py`` may reach for ``._conn`` directly.

The lock alone is not enough: transaction state must not outlive it either.
pysqlite opens a transaction before the first write and keeps it open until
someone commits or rolls back, so a write that raises part-way, or that finds
nothing to change and returns, would leave its transaction open for the next
caller on any thread to commit. The rollback and no-op tests cover that.
"""

from __future__ import annotations

import ast
import inspect
import sqlite3
import sys
import textwrap
import threading
from collections.abc import Generator
from pathlib import Path

import pytest

from mnemo import db as db_module
from mnemo.db import MemoryDB
from mnemo.temporal.store import store_kg_with_memory_id

THREADS = 8
ADDS_PER_THREAD = 150

HALF_WRITTEN = "half-written memory"
UNRELATED = "unrelated committed write"
EMBEDDING = [0.1, 0.2, 0.3, 0.4]
TIMESTAMP = "2026-01-01T00:00:00+00:00"


def _hammer(workers: list) -> list[BaseException]:
    """Run every worker on its own thread at once and collect their errors."""
    barrier = threading.Barrier(len(workers))
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def run(worker) -> None:
        barrier.wait()
        try:
            worker()
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assert
            with errors_lock:
                errors.append(exc)

    threads = [threading.Thread(target=run, args=(w,)) for w in workers]
    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(previous)
    return errors


def _committed_count(path: Path, where: str = "1 = 1", table: str = "memories") -> int:
    """Count rows through a separate connection, so only committed rows show."""
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
    finally:
        conn.close()


def _in_transaction(db: MemoryDB) -> bool:
    """Whether the shared connection has a transaction open, read under the lock."""
    with db._lock:
        return db._conn.in_transaction


def _commit_from_another_thread(db: MemoryDB) -> None:
    """Run an unrelated committing write on another thread.

    Whatever a failed call left pending on the shared connection would ride
    along with this commit and become durable.
    """
    thread = threading.Thread(target=db.add, args=(UNRELATED,))
    thread.start()
    thread.join()
    assert _committed_count(db._db_path, f"content = '{UNRELATED}'") == 1


def _fail_on(db: MemoryDB, event: str) -> None:
    """Make every statement that fires the trigger ``event`` abort."""
    with db.connection() as conn:
        conn.execute(
            f"CREATE TEMP TRIGGER injected_failure {event} "
            "BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )


def _boom(*_args, **_kwargs):
    raise RuntimeError("injected")


def _search_a_hit(db: MemoryDB) -> list[dict]:
    """Search for a row that exists, so search() updates its access stats."""
    db.add("anchor")
    return db.search("anchor")


@pytest.fixture
def vec_db(tmp_path: Path) -> Generator[MemoryDB]:
    """A MemoryDB that writes vectors, into a plain stand-in table.

    sqlite-vec does not load on every CI platform, and the paths under test
    only insert into and delete from ``memories_vec``, so a regular table with
    the same columns stands in for the vec0 one, as in test_db_vec_coverage.
    """
    db = MemoryDB(tmp_path / "vec.db", embedding_dims=len(EMBEDDING))
    with db.connection() as conn:
        conn.execute("DROP TABLE IF EXISTS memories_vec")
        conn.execute("CREATE TABLE memories_vec (id TEXT PRIMARY KEY, embedding BLOB)")
    db._vec_enabled = True
    yield db
    db.close()


class TestConcurrentWrites:
    def test_concurrent_adds_all_persist(self, tmp_path: Path):
        path = tmp_path / "hammer.db"
        db = MemoryDB(path, embedding_dims=0)
        try:

            def adder(n: int):
                def work() -> None:
                    for i in range(ADDS_PER_THREAD):
                        db.add(f"thread {n} memory {i}", category="hammer")

                return work

            errors = _hammer([adder(n) for n in range(THREADS)])

            assert errors == []
            assert _committed_count(path) == THREADS * ADDS_PER_THREAD
        finally:
            db.close()

    def test_mixed_writers_and_readers_stay_consistent(self, tmp_path: Path):
        """Adds, updates, deletes and searches racing on one connection."""
        path = tmp_path / "mixed.db"
        db = MemoryDB(path, embedding_dims=0)
        try:
            seeded = [db.add(f"seed memory {i}", category="seed") for i in range(40)]
            deleted: list[str] = []

            def adder(n: int):
                def work() -> None:
                    for i in range(ADDS_PER_THREAD):
                        db.add(f"mixed {n} item {i}", category="mixed")

                return work

            def updater() -> None:
                for i, mid in enumerate(seeded[:20]):
                    assert db.update(mid, content=f"seed memory {i} revised")

            def deleter() -> None:
                for mid in seeded[20:]:
                    assert db.delete(mid)
                    deleted.append(mid)

            def searcher() -> None:
                for _ in range(ADDS_PER_THREAD):
                    db.search("memory", limit=5)

            errors = _hammer(
                [adder(n) for n in range(THREADS - 3)] + [updater, deleter, searcher]
            )

            assert errors == []
            assert len(deleted) == 20
            mixed = _committed_count(path, "category = 'mixed'")
            assert mixed == (THREADS - 3) * ADDS_PER_THREAD
            # 20 revised successors stay live; the 20 originals they replaced
            # and the 20 deleted rows are closed.
            assert (
                _committed_count(path, "category = 'seed' AND valid_to IS NULL") == 20
            )
            assert _committed_count(path, "category = 'seed'") == 60
        finally:
            db.close()


class TestEntryPoints:
    def test_connection_commits_on_success(self, tmp_db: MemoryDB):
        mid = tmp_db.add("entry point", category="fact")
        with tmp_db.connection() as conn:
            conn.execute("UPDATE memories SET category = 'moved' WHERE id = ?", (mid,))
        assert tmp_db._conn.in_transaction is False
        row = tmp_db.get(mid)
        assert row is not None
        assert row["category"] == "moved"

    def test_connection_rolls_back_on_error(self, tmp_db: MemoryDB):
        mid = tmp_db.add("entry point", category="fact")
        try:
            with tmp_db.connection() as conn:
                conn.execute(
                    "UPDATE memories SET category = 'lost' WHERE id = ?", (mid,)
                )
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert tmp_db._conn.in_transaction is False
        row = tmp_db.get(mid)
        assert row is not None
        assert row["category"] == "fact"

    def test_run_passes_connection_and_arguments(self, tmp_db: MemoryDB):
        mid = tmp_db.add("run helper", category="fact")

        def read_category(conn, memory_id, *, column):
            return conn.execute(
                f"SELECT {column} FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()[0]

        assert tmp_db.run(read_category, mid, column="category") == "fact"


class TestFailedWritesRollBack:
    """A write that raises part-way must not leave its earlier statements pending.

    Each test makes a later statement of one write fail, checks that no
    transaction is open once the call has raised, then commits an unrelated
    write from another thread -- the commit that would make a half-applied
    write durable -- and reads the committed state through a separate
    connection.
    """

    @pytest.mark.parametrize(
        "write",
        [
            pytest.param(
                lambda db: db.add(HALF_WRITTEN, embedding=EMBEDDING), id="add"
            ),
            pytest.param(
                lambda db: db.add_with_context_type(
                    HALF_WRITTEN, context_type="fact", embedding=EMBEDDING
                ),
                id="add_with_context_type",
            ),
        ],
    )
    def test_add_rolls_back_when_the_vector_insert_fails(
        self, vec_db: MemoryDB, monkeypatch, write
    ):
        monkeypatch.setattr(db_module, "_serialize_f32", _boom)
        with pytest.raises(RuntimeError, match="injected"):
            write(vec_db)
        assert _in_transaction(vec_db) is False
        _commit_from_another_thread(vec_db)
        assert _committed_count(vec_db._db_path, f"content = '{HALF_WRITTEN}'") == 0

    def test_write_vector_keeps_the_old_vector_when_the_insert_fails(
        self, vec_db: MemoryDB, monkeypatch
    ):
        mid = vec_db.add("anchor", embedding=EMBEDDING)
        monkeypatch.setattr(db_module, "_serialize_f32", _boom)
        with pytest.raises(RuntimeError, match="injected"):
            vec_db.write_vector(mid, EMBEDDING)
        assert _in_transaction(vec_db) is False
        _commit_from_another_thread(vec_db)
        assert (
            _committed_count(vec_db._db_path, f"id = '{mid}'", table="memories_vec")
            == 1
        )

    def test_update_keeps_the_predecessor_when_the_successor_vector_fails(
        self, vec_db: MemoryDB, monkeypatch
    ):
        mid = vec_db.add("anchor")
        monkeypatch.setattr(db_module, "_serialize_f32", _boom)
        with pytest.raises(RuntimeError, match="injected"):
            vec_db.update(mid, content=HALF_WRITTEN, embedding=EMBEDDING)
        assert _in_transaction(vec_db) is False
        _commit_from_another_thread(vec_db)
        path = vec_db._db_path
        assert _committed_count(path, f"id = '{mid}' AND valid_to IS NULL") == 1
        assert _committed_count(path, f"content = '{HALF_WRITTEN}'") == 0

    def test_delete_keeps_the_row_live_when_the_vector_delete_fails(
        self, vec_db: MemoryDB
    ):
        mid = vec_db.add("anchor", embedding=EMBEDDING)
        _fail_on(vec_db, "BEFORE DELETE ON memories_vec")
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            vec_db.delete(mid)
        assert _in_transaction(vec_db) is False
        _commit_from_another_thread(vec_db)
        assert (
            _committed_count(vec_db._db_path, f"id = '{mid}' AND valid_to IS NULL") == 1
        )

    def test_replace_import_keeps_the_store_when_a_record_fails_to_bind(
        self, tmp_db: MemoryDB
    ):
        for i in range(3):
            tmp_db.add(f"seeded {i}")
        records = [
            {"content": HALF_WRITTEN},
            # Not a scalar: sqlite3 refuses to bind it, after the replace-mode
            # clear and the first record have already run.
            {"content": "unbindable", "source": {"nested": True}},
        ]
        with pytest.raises(sqlite3.ProgrammingError):
            tmp_db.import_jsonl(records, mode="replace")
        assert _in_transaction(tmp_db) is False
        _commit_from_another_thread(tmp_db)
        path = tmp_db._db_path
        assert _committed_count(path, "content LIKE 'seeded %'") == 3
        assert _committed_count(path, f"content = '{HALF_WRITTEN}'") == 0

    def test_legacy_restore_stays_archived_when_the_side_table_delete_fails(
        self, tmp_db: MemoryDB
    ):
        with tmp_db.connection() as conn:
            conn.execute(
                "INSERT INTO archived_memories (id, content, created_at, "
                "updated_at, last_accessed, archived_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("legacy-id", "legacy row", TIMESTAMP, TIMESTAMP, TIMESTAMP, TIMESTAMP),
            )
        _fail_on(tmp_db, "BEFORE DELETE ON archived_memories")
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            tmp_db.restore_memory("legacy-id")
        assert _in_transaction(tmp_db) is False
        _commit_from_another_thread(tmp_db)
        path = tmp_db._db_path
        assert _committed_count(path, "id = 'legacy-id'") == 0
        assert (
            _committed_count(path, "id = 'legacy-id'", table="archived_memories") == 1
        )

    @pytest.mark.parametrize(
        ("event", "write"),
        [
            pytest.param(
                "BEFORE UPDATE OF importance ON memories",
                lambda db: db.update_importance(db.add("anchor"), 0.9),
                id="update_importance",
            ),
            pytest.param(
                "BEFORE UPDATE OF access_count ON memories",
                _search_a_hit,
                id="search-access-stats",
            ),
        ],
    )
    def test_failed_single_statement_write_closes_its_transaction(
        self, tmp_db: MemoryDB, event, write
    ):
        _fail_on(tmp_db, event)
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            write(tmp_db)
        assert _in_transaction(tmp_db) is False

    def test_failed_temporal_backfill_rolls_back(self, tmp_db: MemoryDB):
        """The backfill logs and swallows its failure, so it must roll back."""
        tmp_db.add("backfill first")
        tmp_db.add("backfill poison")
        _fail_on(
            tmp_db,
            "BEFORE UPDATE OF commit_sha ON memories "
            "WHEN OLD.content = 'backfill poison'",
        )
        tmp_db._backfill_phase3_temporal()
        assert _in_transaction(tmp_db) is False
        _commit_from_another_thread(tmp_db)
        assert (
            _committed_count(
                tmp_db._db_path, "content LIKE 'backfill %' AND commit_sha IS NULL"
            )
            == 2
        )


class TestNoOpWritesCloseTheTransaction:
    """pysqlite opens a transaction before any UPDATE or DELETE, even one that
    matches no row, so a write that finds nothing to do must still close it."""

    @pytest.mark.parametrize(
        ("call", "expected"),
        [
            pytest.param(lambda db: db.delete("missing"), False, id="delete"),
            pytest.param(
                lambda db: db.archive_old_memories(), 0, id="archive_old_memories"
            ),
            pytest.param(lambda db: db.archive_by_score(), 0, id="archive_by_score"),
            pytest.param(
                lambda db: db.restore_memory("missing"), False, id="restore_memory"
            ),
            pytest.param(
                lambda db: db.update("missing", content="x"), None, id="update"
            ),
            pytest.param(
                lambda db: db.update_importance("missing", 0.9),
                False,
                id="update_importance",
            ),
        ],
    )
    def test_write_with_nothing_to_do_leaves_no_transaction_open(
        self, tmp_db: MemoryDB, call, expected
    ):
        # A fresh, unarchived row: nothing old enough to archive, nothing to restore.
        tmp_db.add("fresh memory")
        assert call(tmp_db) == expected
        assert _in_transaction(tmp_db) is False

    def test_kg_store_without_relations_commits_its_writes(self, tmp_db: MemoryDB):
        mid = tmp_db.add("Alice reviews the release")
        extracted = {"entities": [{"name": "Alice", "type": "person"}], "relations": []}
        with tmp_db._lock:
            result = store_kg_with_memory_id(tmp_db._conn, mid, extracted)
            assert tmp_db._conn.in_transaction is False
        assert result == {"entities": 1, "edges": 0, "links": 1}
        assert _committed_count(tmp_db._db_path, table="memory_entity_links") == 1


class TestStaticGuards:
    def test_every_connection_access_holds_the_lock(self):
        tree = ast.parse(textwrap.dedent(inspect.getsource(MemoryDB)))
        unlocked: list[str] = []

        def holds_lock(node: ast.With) -> bool:
            return any(
                isinstance(item.context_expr, ast.Attribute)
                and item.context_expr.attr == "_lock"
                for item in node.items
            )

        def visit(node: ast.AST, locked: bool, where: str) -> None:
            if isinstance(node, ast.FunctionDef):
                where = node.name
                locked = False
            if isinstance(node, ast.With) and holds_lock(node):
                locked = True
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "_conn"
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and not locked
            ):
                unlocked.append(f"{where}:{node.lineno}")
            for child in ast.iter_child_nodes(node):
                visit(child, locked, where)

        visit(tree, False, "<class>")
        assert unlocked == []

    def test_no_connection_access_outside_db_module(self):
        package = Path(inspect.getfile(MemoryDB)).parent
        offenders: list[str] = []
        for path in sorted(package.rglob("*.py")):
            if path.name == "db.py" and path.parent == package:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "_conn":
                    rel = path.relative_to(package).as_posix()
                    offenders.append(f"{rel}:{node.lineno}")
        assert offenders == []
