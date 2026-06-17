"""A sqlite3.Connection-like shim over the CF D1 HTTP backend.

graph.py / temporal/queries.py / temporal/store.py / sync/delta.py all take a
raw sqlite3.Connection (db._conn) and call .execute()/.executemany()/.cursor()/
.commit() directly. To run them unchanged on D1, MemoryDBD1 exposes this shim as
._conn. The per-request JWT ``sub`` is captured at construction so the data layer
stays sub-agnostic; sub-scoping of rows is enforced by the SQL the callers emit
(MemoryDBD1 and the sub-aware graph helpers include ``sub`` in every
WHERE/INSERT), not by this shim.

D1 has no autocommit/transaction handle exposed over HTTP, so commit() is a
no-op (each D1Backend.execute is its own statement). Tests assert read-after-
write within a single FakeD1Http sqlite connection, which holds.
"""

from __future__ import annotations

from typing import Any


class _RowResult:
    """The slice of sqlite3.Cursor the consumers use: fetchall/fetchone + rowcount."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.rowcount = len(rows)

    def fetchall(self) -> list[dict]:
        return self._rows

    def fetchone(self) -> dict | None:
        return self._rows[0] if self._rows else None


class D1Connection:
    """Minimal sqlite3.Connection surface backed by D1Backend."""

    def __init__(self, backend, sub: str = "default") -> None:
        self._backend = backend
        self.sub = sub

    def execute(self, sql: str, params: tuple | list = ()) -> _RowResult:
        rows = self._backend.execute(sql, list(params))
        return _RowResult(rows)

    def executemany(self, sql: str, seq_of_params) -> _RowResult:
        self._backend.executemany(sql, [list(p) for p in seq_of_params])
        return _RowResult([])

    def executescript(self, sql: str) -> None:
        self._backend.executescript(sql)

    def cursor(self) -> D1Connection:
        # Consumers use cursor() then .execute(...).fetchall(); returning self
        # satisfies that surface (D1 statements are independent).
        return self

    def commit(self) -> None:
        return None

    def close(self) -> None:
        return None

    def __getattr__(self, name: str) -> Any:  # pragma: no cover - guard
        raise AttributeError(
            f"D1Connection does not support sqlite3.Connection.{name!r}; "
            "the CF data layer uses execute/executemany/cursor/commit only"
        )
