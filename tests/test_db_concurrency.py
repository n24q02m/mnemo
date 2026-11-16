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
"""

from __future__ import annotations

import ast
import inspect
import sqlite3
import sys
import textwrap
import threading
from pathlib import Path

from mnemo.db import MemoryDB

THREADS = 8
ADDS_PER_THREAD = 150


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


def _committed_count(path: Path, where: str = "1 = 1") -> int:
    """Count rows through a separate connection, so only committed rows show."""
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM memories WHERE {where}").fetchone()[
            0
        ]
    finally:
        conn.close()


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
