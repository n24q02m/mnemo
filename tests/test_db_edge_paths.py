"""Genuine error/edge paths in MemoryDB (identity guard, vec guards, FTS
resilience, archive fallback, migration/backfill robustness)."""

import sqlite3
from pathlib import Path

import pytest

from mnemo.db import MemoryDB


def _vec_db(path: Path, dims: int) -> MemoryDB:
    """MemoryDB with vector storage required; skips where sqlite-vec cannot
    load (macOS CI builds sqlite3 without enable_load_extension, so the vec
    table never exists and vector-backed paths run on the other legs)."""
    db = MemoryDB(path, embedding_dims=dims)
    if not db.vec_enabled:
        db.close()
        pytest.skip(
            "sqlite-vec did not load here; vector-backed path runs on other legs"
        )
    return db


# ---------------------------------------------------------------------------
# store_meta / embedding identity guard
# ---------------------------------------------------------------------------


def test_get_store_meta_survives_missing_table(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        db._conn.execute("DROP TABLE store_meta")
        db._conn.commit()
        assert db.get_store_meta("anything") is None
    finally:
        db.close()


def test_corrupted_dims_stamp_triggers_reindex(tmp_path: Path):
    """A non-numeric stored dims stamp is treated as 0 and forces a rebuild."""
    path = tmp_path / "t.db"
    db = MemoryDB(path, embedding_dims=8, embedding_model="m1")
    db.close()
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE store_meta SET value='not-a-number' WHERE key='embedding_dims'"
    )
    conn.commit()
    conn.close()

    db = MemoryDB(
        path, embedding_dims=8, embedding_model="m1", reindex_on_model_change=True
    )
    try:
        # Reindex re-stamped a clean identity.
        assert db.get_store_meta("embedding_dims") == "8"
        assert db.get_store_meta("embedding_model") == "m1"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# vector guards
# ---------------------------------------------------------------------------


def test_ensure_vec_table_adopts_detected_dims(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=8)
    try:
        db._ensure_vec_table(16)
        # Detected float[8] on disk wins over the requested 16.
        assert db._embedding_dims == 8
    finally:
        db.close()


def test_rows_without_vectors_validates_limit(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        with pytest.raises(ValueError, match="limit must be a positive integer"):
            db.rows_without_vectors(0)
    finally:
        db.close()


def test_rows_without_vectors_requires_vec_store(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        with pytest.raises(RuntimeError, match="vector storage is not enabled"):
            db.rows_without_vectors(5)
    finally:
        db.close()


def test_write_vector_requires_vec_store(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        with pytest.raises(RuntimeError, match="vector storage is not enabled"):
            db.write_vector("mem_1", [0.1] * 8)
    finally:
        db.close()


def test_write_vector_unknown_memory_raises_key_error(tmp_path: Path):
    db = _vec_db(tmp_path / "t.db", 8)
    try:
        with pytest.raises(KeyError, match="memory not found"):
            db.write_vector("does-not-exist", [0.1] * 8)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# add_with_context_type bookkeeping
# ---------------------------------------------------------------------------


def test_add_with_context_type_clamps_importance(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        mid = db.add_with_context_type("fact", importance=5.0)
        row = db.get(mid)
        assert row is not None, "get must return the stored row"
        assert row["importance"] == 1.0
    finally:
        db.close()


def test_add_with_context_type_writes_embedding(tmp_path: Path):
    db = _vec_db(tmp_path / "t.db", 8)
    try:
        mid = db.add_with_context_type(
            "vectorised fact", embedding=[0.1] * 8, context_type="fact"
        )
        stored = db._conn.execute(
            "SELECT embedding FROM memories_vec WHERE id = ?", (mid,)
        ).fetchone()
        assert stored is not None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# FTS resilience + hybrid scoring
# ---------------------------------------------------------------------------


def test_search_survives_fts_tier_failure(tmp_path: Path, monkeypatch):
    """A malformed MATCH expression logs the tier failure but never raises."""
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        monkeypatch.setattr("mnemo.db._build_fts_queries", lambda _q: ['"broken'])
        results = db.search(query="anything")
        assert results == []
    finally:
        db.close()


def test_update_access_stats_noop_for_empty_top(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        db._update_access_stats([])  # must not raise or touch the DB
    finally:
        db.close()


def test_list_memories_includes_archived_when_asked(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        mid = db.add("archivable row")
        db._conn.execute(
            "UPDATE memories SET archived_at = '2020-01-01T00:00:00' WHERE id = ?",
            (mid,),
        )
        db._conn.commit()
        assert db.list_memories() == []
        rows = db.list_memories(include_archived=True)
        assert [r["id"] for r in rows] == [mid]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# archive scoring
# ---------------------------------------------------------------------------


def _insert_stale_row(db: MemoryDB, days_old: int, importance: float | None) -> str:
    mid = db.add("stale content")
    if importance is not None:
        db.update_importance(mid, importance)
    db._conn.execute(
        "UPDATE memories SET updated_at = datetime('now', ?) WHERE id = ?",
        (f"-{days_old} days", mid),
    )
    db._conn.commit()
    return mid


def test_archive_by_score_archives_old_low_importance_row(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        mid = _insert_stale_row(db, days_old=400, importance=0.0)
        assert db.archive_by_score(archive_after_days=90) == 1
        row = db._conn.execute(
            "SELECT archived_at FROM memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row["archived_at"] is not None
    finally:
        db.close()


def test_archive_by_score_config_fallback_is_90_days(tmp_path: Path, monkeypatch):
    """An unreadable config value falls back to the 90-day default."""
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        # 100 days old at a 90-day denominator: recency_factor > 1 -> archive.
        mid = _insert_stale_row(db, days_old=100, importance=0.0)
        # The config import inside archive_by_score resolves to None ->
        # the int() probe raises and the documented 90-day fallback kicks in.
        monkeypatch.setattr("mnemo.config.settings", None)
        assert db.archive_by_score(archive_after_days=None) == 1
        row = db._conn.execute(
            "SELECT archived_at FROM memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row["archived_at"] is not None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# duplicate detection
# ---------------------------------------------------------------------------


def test_check_duplicate_empty_query_returns_none(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        assert db.check_duplicate("   ") is None
    finally:
        db.close()


def test_check_duplicate_no_results_returns_none(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        assert db.check_duplicate("unique zebra content") is None
    finally:
        db.close()


def test_check_duplicate_similar_not_identical(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        db.add("alpha beta gamma delta epsilon zeta")
        match = db.check_duplicate("alpha beta gamma delta epsilon eta")
        assert match is not None
        assert match.get("similar") is True
        assert match["similarity"] == pytest.approx(0.83, abs=0.01)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# migrations / backfill robustness
# ---------------------------------------------------------------------------


def test_migrations_skipped_without_alembic_ini(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "mnemo.db._ALEMBIC_INI_PATH", tmp_path / "no" / "alembic.ini"
    )
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)  # must not raise
    try:
        assert db._read_alembic_version() is None
    finally:
        db.close()


def test_read_alembic_version_unstamped_db(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        # A freshly migrated store IS stamped; drop the version table to
        # exercise the unstamped/OperationalError path.
        db._conn.execute("DROP TABLE alembic_version")
        db._conn.commit()
        assert db._read_alembic_version() is None
    finally:
        db.close()


def test_backup_db_file_missing_source_returns_none(tmp_path: Path):
    path = tmp_path / "t.db"
    db = MemoryDB(path, embedding_dims=0)
    db.close()
    path.unlink(missing_ok=True)
    assert db._backup_db_file() is None


def test_backfill_returns_when_memories_table_missing(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        db._conn.execute("DROP TABLE memories")
        db._conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT)")
        db._conn.commit()
        db._backfill_phase3_temporal()  # early return, no raise
    finally:
        db.close()


def test_backfill_returns_when_phase3_columns_missing(tmp_path: Path):
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        db._conn.execute("DROP TABLE memories")
        db._conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT)")
        db._conn.commit()
        db._backfill_phase3_temporal()  # column probe early return
    finally:
        db.close()


def test_backfill_survives_broken_fts_and_still_backfills(tmp_path: Path):
    """FTS rebuild failure is swallowed; legacy rows still get stamped."""
    db = MemoryDB(tmp_path / "t.db", embedding_dims=0)
    try:
        mid = db.add("legacy row")
        db._conn.execute(
            "UPDATE memories SET commit_sha = NULL, valid_from = NULL WHERE id = ?",
            (mid,),
        )
        # Maim the FTS index so the 'rebuild' command fails while the
        # triggers are gone so the batch UPDATE itself can proceed.
        db._conn.execute("DROP TRIGGER memories_au")
        db._conn.execute("DROP TABLE memories_fts_data")
        db._conn.commit()
        db._backfill_phase3_temporal()
        row = db._conn.execute(
            "SELECT commit_sha, valid_from FROM memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row["commit_sha"] is not None
        assert row["valid_from"] is not None
    finally:
        db.close()
