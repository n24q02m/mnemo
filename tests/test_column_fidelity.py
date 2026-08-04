"""Column fidelity across every path that serializes a ``memories`` row.

``memories`` has 19 columns. Three separate hand-written column lists used to
serialize it -- ``db.py::export_jsonl`` (9), the ``db.py`` /
``db_cf.py`` import pair (10) and ``sync/delta.py::_INSERT_COLS`` (15) -- and
none of them matched the table. Exporting and re-importing through the product's
own tools therefore dropped columns and still answered ``{"imported": N}``.

Two independent alarms live here, and both must fire when a future migration
adds a column:

* :class:`TestSerializerColumnsTrackTheSchema` compares the single
  ``db.MEMORY_COLUMNS`` tuple that all serializers now share against the live
  schema of a freshly built ``MemoryDB``.
* :data:`FULL_ROW` -- the round-trip fixture -- is itself checked for
  completeness against that same schema, so the round trip cannot silently stop
  covering a column it never learned about.

``tests/test_d1_migrations.py`` already pins ``migrations/0001_init.sql``
against the SQLite lineage, so "schema" means the same thing on both backends
and is not re-derived here.
"""

from __future__ import annotations

import itertools
import json
import pathlib
import sqlite3

import pytest

# Re-use the D1 doubles rather than describing a second, possibly different
# Worker; `test_db_cf` imports `FakeVectorizeWorker` from its neighbour the same
# way.
from test_db_cf import FakeD1Worker, _cf_db

from mnemo_mcp import db as db_module
from mnemo_mcp import db_cf as db_cf_module
from mnemo_mcp.db import MemoryDB
from mnemo_mcp.db_cf import D1_MAX_BOUND_PARAMS
from mnemo_mcp.sync import delta as delta_module

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_MIGRATION = _REPO_ROOT / "migrations" / "0001_init.sql"
_MIGRATION_2 = _REPO_ROOT / "migrations" / "0002_per_sub_isolation.sql"


def _schema_table_info() -> list[tuple]:
    """``PRAGMA table_info(memories)`` as a fresh store actually builds it.

    ``MemoryDB`` runs ``_init_schema`` and then walks Alembic to head, so this
    is the end state of the whole lineage rather than any one revision.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db = MemoryDB(pathlib.Path(tmp) / "schema-probe.db", embedding_dims=0)
        try:
            rows = db._conn.execute("PRAGMA table_info(memories)").fetchall()
        finally:
            db.close()
    return [tuple(r) for r in rows]


def _schema_columns() -> tuple[str, ...]:
    """Column names of ``memories``, in declaration order."""
    return tuple(r[1] for r in _schema_table_info())


def _parse_sql_literal(raw: str | None) -> object:
    """Decode a ``PRAGMA table_info`` ``dflt_value`` into a Python value."""
    if raw is None:
        return None
    text = raw.strip()
    if text.upper() == "NULL":
        return None
    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            continue
    return text


def _schema_defaults() -> dict[str, object]:
    """Each column's schema DEFAULT, decoded. ``None`` where there is none."""
    return {r[1]: _parse_sql_literal(r[4]) for r in _schema_table_info()}


# A memory whose every column holds a value distinguishable from that column's
# schema default. A round trip that drops a column therefore shows up as a
# concrete mismatch rather than as a value that happens to equal the default.
#
# `tags` is stored as TEXT holding JSON; `export_jsonl` emits it via `json(tags)`
# as a real array and the importer re-encodes it, so its *text* is allowed to
# change (separator whitespace) while its parsed value is not. Every other
# column must survive byte-for-byte.
FULL_ROW_ID = "fidelity-001"
FULL_ROW: dict[str, object] = {
    "id": FULL_ROW_ID,
    "content": "every column of this row carries a non-default value",
    "category": "archaeology",
    "tags": '["alpha","beta"]',
    "source": "column-fidelity-test",
    "created_at": "2020-01-02T03:04:05+00:00",
    "updated_at": "2021-02-03T04:05:06+00:00",
    "access_count": 42,
    "last_accessed": "2022-03-04T05:06:07+00:00",
    "importance": 0.875,
    "context_type": "decision",
    "archived_at": "2023-04-05T06:07:08+00:00",
    "text_raw": "the uncompressed original text",
    "compressed": 1,
    "compression_provider": "zstd-test",
    "commit_sha": "0f1e2d3c4b5a69788796a5b4c3d2e1f001234567",
    "valid_from": "2024-05-06T07:08:09+00:00",
    "valid_to": "2025-06-07T08:09:10+00:00",
    "superseded_by": "fidelity-002",
}

_JSON_VALUED_COLUMNS = frozenset({"tags"})


@pytest.fixture(params=["sqlite", "cf-d1"])
def db_factory(request, tmp_path):
    """Build independent stores of one backend kind, on demand.

    A round trip needs two: the store that exports and a fresh one that
    imports. The parametrisation runs the whole scenario once per backend.
    """
    created = []
    counter = itertools.count()

    def make():
        n = next(counter)
        if request.param == "sqlite":
            db = MemoryDB(tmp_path / f"memories-{n}.db", embedding_dims=0)
        else:
            conn = sqlite3.connect(tmp_path / f"d1-{n}.sqlite", isolation_level=None)
            conn.executescript(_MIGRATION.read_text(encoding="utf-8"))
            conn.executescript(_MIGRATION_2.read_text(encoding="utf-8"))
            db = _cf_db(FakeD1Worker(conn))
        created.append(db)
        return db

    yield make
    for db in created:
        db.close()


def _insert_full_row(db, row: dict) -> None:
    """Write ``row`` with plain SQL, bypassing ``add()``.

    ``add()`` stamps its own timestamps and leaves the newer columns at their
    defaults, which is precisely the state this test must not start from.
    """
    cols = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    db._conn.execute(
        f"INSERT INTO memories ({cols}) VALUES ({placeholders})",
        tuple(row.values()),
    )
    db._conn.commit()


def _read_row(db, memory_id: str) -> dict:
    """Read a row back as a plain dict, unfiltered.

    Deliberately not ``db.get()``: the read paths seed every query with
    ``AND m.valid_to IS NULL``, and this row carries a ``valid_to``.
    """
    cursor = db._conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
    row = cursor.fetchone()
    assert row is not None, f"row {memory_id} missing"
    return dict(row)


def _diff_columns(before: dict, after: dict) -> list[str]:
    """Names of columns whose value did not survive, most useful first."""
    mismatched = []
    for col, want in before.items():
        got = after.get(col)
        if col in _JSON_VALUED_COLUMNS:
            same = json.loads(want) == json.loads(got) if got is not None else False
        else:
            same = got == want
        if not same:
            mismatched.append(f"{col}: exported {want!r} -> imported {got!r}")
    return mismatched


class TestRoundTripPreservesEveryColumn:
    """``export_memories`` then ``import_memories`` must be lossless."""

    def test_fixture_covers_every_column(self):
        """The round-trip fixture itself must not drift behind the schema.

        Without this, a migration that adds a column would leave the round trip
        quietly untested for it.
        """
        schema = set(_schema_columns())
        assert set(FULL_ROW) == schema, (
            "FULL_ROW no longer matches the `memories` schema; "
            f"missing from fixture: {sorted(schema - set(FULL_ROW))}, "
            f"unknown to schema: {sorted(set(FULL_ROW) - schema)}"
        )

    def test_export_then_import_preserves_all_columns(self, db_factory):
        source = db_factory()
        _insert_full_row(source, FULL_ROW)

        payload, count = source.export_jsonl()
        assert count == 1

        target = db_factory()
        result = target.import_jsonl(payload, mode="merge")
        assert result["imported"] == 1, result

        mismatched = _diff_columns(FULL_ROW, _read_row(target, FULL_ROW_ID))
        assert not mismatched, (
            f"{len(mismatched)} of {len(FULL_ROW)} columns lost in the "
            "export -> import round trip:\n  " + "\n  ".join(mismatched)
        )

    def test_exported_json_carries_every_column(self, db_factory):
        """The dropped columns must be absent from the payload, not just the
        target row -- otherwise the loss is blamed on the importer alone."""
        source = db_factory()
        _insert_full_row(source, FULL_ROW)

        payload, _ = source.export_jsonl()
        record = json.loads(payload.splitlines()[0])

        missing = sorted(set(FULL_ROW) - set(record))
        assert not missing, f"export_jsonl omitted {len(missing)} columns: {missing}"


class TestSerializerColumnsTrackTheSchema:
    """The drift alarm.

    This is the test that stops the defect class from coming back: a migration
    that adds a column to ``memories`` turns it red until ``MEMORY_COLUMNS``
    and the importer's default for the new column are supplied.
    """

    def test_memory_columns_match_the_live_schema(self):
        schema = _schema_columns()
        assert db_module.MEMORY_COLUMNS == schema, (
            "db.MEMORY_COLUMNS drifted from the `memories` schema.\n"
            f"  in the schema but not serialized: {[c for c in schema if c not in db_module.MEMORY_COLUMNS]}\n"
            f"  serialized but not in the schema: {[c for c in db_module.MEMORY_COLUMNS if c not in schema]}\n"
            "Add the column to MEMORY_COLUMNS (same order as the table) and give "
            "it an entry in db._IMPORT_DEFAULTS."
        )

    def test_every_serializer_uses_the_one_list(self):
        """No path may keep a private copy -- that is what drifted before."""
        assert db_cf_module._IMPORT_COLUMNS is db_module.MEMORY_COLUMNS
        assert delta_module._INSERT_COLS is db_module.MEMORY_COLUMNS

    def test_export_sql_selects_every_column(self):
        """``export_jsonl`` builds its ``json_object`` from the shared list."""
        args = db_module._EXPORT_JSON_OBJECT_ARGS
        for column in db_module.MEMORY_COLUMNS:
            assert f"'{column}'" in args, f"export omits {column}"
        assert "'tags', json(tags)" in args, "tags must export as a JSON array"

    def test_every_column_has_exactly_one_import_rule(self):
        """A new column must not silently fall through to a KeyError at import.

        The three rule sets have to partition ``MEMORY_COLUMNS``: derived
        (generated or validated), timestamp (defaults to "now"), or a static
        default.
        """
        derived = db_module._IMPORT_DERIVED_COLUMNS
        timestamps = db_module._IMPORT_TIMESTAMP_COLUMNS
        defaults = set(db_module._IMPORT_DEFAULTS)

        covered = derived | timestamps | defaults
        assert covered == set(db_module.MEMORY_COLUMNS), (
            f"no import rule for: {sorted(set(db_module.MEMORY_COLUMNS) - covered)}; "
            f"rule for unknown column: {sorted(covered - set(db_module.MEMORY_COLUMNS))}"
        )
        overlaps = (
            (derived & timestamps) | (derived & defaults) | (timestamps & defaults)
        )
        assert not overlaps, f"columns claimed by two import rules: {sorted(overlaps)}"

    def test_import_defaults_match_the_schema_defaults(self):
        """An omitted column must land on the value the schema would have used.

        Keeps the hand-written default table honest: change a DEFAULT clause in
        a migration and this fails rather than letting imports write a value the
        table never would.
        """
        schema_defaults = _schema_defaults()
        wrong = {
            column: (expected, schema_defaults[column])
            for column, expected in db_module._IMPORT_DEFAULTS.items()
            if schema_defaults[column] != expected
        }
        assert not wrong, (
            "db._IMPORT_DEFAULTS disagrees with the schema DEFAULT clauses "
            f"(column: importer -> schema): {wrong}"
        )


class TestD1StatementSizing:
    """``_IMPORT_ROWS_PER_STATEMENT`` is ``100 // len(MEMORY_COLUMNS)``.

    It recomputes itself when a column is added, but "recomputes" is not the
    same as "stays valid", so both ends are pinned.
    """

    def test_rows_per_statement_cannot_reach_zero(self):
        """Zero rows per statement would make ``import_jsonl`` a silent no-op.

        Reaching it needs ``len(MEMORY_COLUMNS) > D1_MAX_BOUND_PARAMS`` -- a
        `memories` table more than 100 columns wide, where a single row could
        not be inserted in one statement either. Asserted on the real value and
        on the headroom, so a column-adding migration that approaches the cliff
        fails here first.
        """
        assert db_cf_module._IMPORT_ROWS_PER_STATEMENT >= 1
        assert len(db_module.MEMORY_COLUMNS) <= D1_MAX_BOUND_PARAMS, (
            f"`memories` now has {len(db_module.MEMORY_COLUMNS)} columns, more than D1's "
            f"{D1_MAX_BOUND_PARAMS}-bound-parameter cap; a single-row INSERT no "
            "longer fits in one statement and the bulk import needs rethinking"
        )

    def test_widest_statement_stays_within_the_cap(self):
        widest = db_cf_module._IMPORT_ROWS_PER_STATEMENT * len(db_module.MEMORY_COLUMNS)
        assert widest <= D1_MAX_BOUND_PARAMS, (
            f"{db_cf_module._IMPORT_ROWS_PER_STATEMENT} rows x "
            f"{len(db_module.MEMORY_COLUMNS)} columns = {widest} bound parameters, over "
            f"D1's cap of {D1_MAX_BOUND_PARAMS}"
        )


class TestDeltaSyncPreservesBitemporalColumns:
    """``sync/delta.py`` dropped the four ``mem_003_temporal`` columns.

    Every read path starts from ``AND m.valid_to IS NULL``, so a superseded row
    that crossed the wire without its ``valid_to`` came back to life on the
    receiving machine.
    """

    def test_superseded_row_stays_superseded_after_sync(self, tmp_path):
        local = MemoryDB(tmp_path / "local.db", embedding_dims=0)
        try:
            memory_id = local.add("a claim about resurrection", category="general")
            local._conn.execute(
                "UPDATE memories SET updated_at = ? WHERE id = ?",
                ("2020-01-01T00:00:00+00:00", memory_id),
            )
            local._conn.commit()

            # The same row as another machine has it: superseded, and newer.
            remote = dict(_read_row(local, memory_id))
            remote.update(
                {
                    "updated_at": "2030-01-01T00:00:00+00:00",
                    "valid_to": "2030-01-01T00:00:00+00:00",
                    "superseded_by": "successor-row",
                    "commit_sha": "a" * 40,
                    "valid_from": "2019-01-01T00:00:00+00:00",
                }
            )

            assert delta_module._upsert_row_lww(local, remote) == "updated"

            applied = _read_row(local, memory_id)
            assert applied["valid_to"] == "2030-01-01T00:00:00+00:00"
            assert applied["superseded_by"] == "successor-row"
            assert applied["commit_sha"] == "a" * 40
            assert applied["valid_from"] == "2019-01-01T00:00:00+00:00"

            hits = local.search("resurrection")
            assert [h["id"] for h in hits] == [], (
                "a superseded row resurfaced in search after sync"
            )
        finally:
            local.close()
