"""Tests for Phase 1 retrieval polish (spec section 4.2).

Covers:
- ``MemoryDB.rrf_fuse`` static helper combines two ranked id lists with
  smoothing constant ``k`` (default 60).
- Cross-encoder rerank exposes a top-50-candidates -> top-N pattern via the
  new ``candidate_pool`` argument and survives backend failures via
  :class:`FallbackChainReranker`.
- Temporal decay raises the score of recently-updated memories.
- Importance boost raises the score of higher-importance rows.
- Filter args (``context_type`` / ``since`` / ``until`` / ``min_importance``)
  short-circuit through both the FTS and vec paths.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from mnemo_mcp.db import MemoryDB
from mnemo_mcp.reranker import (
    CloudReranker,
    FallbackChainReranker,
    Qwen3Reranker,
    build_default_rerank_chain,
)

# ---------------------------------------------------------------------------
# RRF helper
# ---------------------------------------------------------------------------


def test_rrf_fuse_combines_ranked_lists():
    fts = ["a", "b", "c"]
    vec = ["b", "a", "d"]

    fused = MemoryDB.rrf_fuse(fts, vec)
    fused_ids = [mid for mid, _ in fused]

    # Ids appearing in both lists should outrank single-list candidates.
    assert set(fused_ids[:2]) == {"a", "b"}
    # Single-list candidates still appear in the fused output.
    assert "c" in fused_ids
    assert "d" in fused_ids


def test_rrf_k_default_60():
    """Default k=60 matches Cormack 2009 baseline."""
    fts = ["a"]
    vec = ["a"]
    fused = MemoryDB.rrf_fuse(fts, vec)
    assert fused == [("a", 1.0 / 61 + 1.0 / 61)]


def test_rrf_custom_k_changes_score():
    fts = ["a"]
    vec = ["a"]
    expected = 1.0 / (10 + 1) + 1.0 / (10 + 1)
    fused = MemoryDB.rrf_fuse(fts, vec, k=10)
    assert fused == [("a", expected)]


def test_rrf_empty_inputs():
    assert MemoryDB.rrf_fuse([], []) == []


# ---------------------------------------------------------------------------
# Cross-encoder rerank top-50 -> top-N pattern
# ---------------------------------------------------------------------------


def test_rerank_candidate_pool_returns_more_than_limit(tmp_db: MemoryDB):
    """``candidate_pool=50`` should return up to 50 hybrid-scored rows."""
    for i in range(20):
        tmp_db.add(f"meeting note {i} about the deploy", category="work")

    results = tmp_db.search("meeting note deploy", limit=5, candidate_pool=20)

    assert len(results) > 5, (
        "candidate_pool should expand the slice beyond limit so the "
        "reranker can pick winners from a larger window"
    )


def test_rerank_top_50_to_top_10(tmp_db: MemoryDB):
    """End-to-end: db.search(candidate_pool=50) feeds reranker, return top-10."""
    for i in range(60):
        tmp_db.add(f"alpha record {i}", category="x")

    pool = tmp_db.search("alpha record", limit=10, candidate_pool=50)
    # cap at min(pool, scored_len) so this is at most 50.
    assert 10 < len(pool) <= 50

    # Simulate a reranker that returns the first 10 in reverse order.
    ranked = [(i, float(50 - i)) for i in range(min(10, len(pool)))]
    top = [pool[idx] for idx, _ in ranked][:10]
    assert len(top) == 10


def test_fallback_chain_returns_first_successful():
    good = MagicMock(spec=CloudReranker)
    good.rerank.return_value = [(0, 0.9), (1, 0.5)]

    bad = MagicMock(spec=CloudReranker)
    bad.rerank.side_effect = RuntimeError("api 500")

    chain = FallbackChainReranker([bad, good])
    out = chain.rerank("q", ["a", "b"], top_n=2)

    assert out == [(0, 0.9), (1, 0.5)]
    bad.rerank.assert_called_once()
    good.rerank.assert_called_once()


def test_fallback_chain_all_fail_returns_empty():
    bad1 = MagicMock(spec=CloudReranker)
    bad1.rerank.side_effect = RuntimeError("first")
    bad2 = MagicMock(spec=CloudReranker)
    bad2.rerank.side_effect = RuntimeError("second")

    chain = FallbackChainReranker([bad1, bad2])
    assert chain.rerank("q", ["a"], top_n=1) == []


def test_fallback_chain_skips_empty_result_and_tries_next():
    empty = MagicMock(spec=CloudReranker)
    empty.rerank.return_value = []

    good = MagicMock(spec=CloudReranker)
    good.rerank.return_value = [(0, 0.7)]

    chain = FallbackChainReranker([empty, good])
    out = chain.rerank("q", ["x"], top_n=1)

    assert out == [(0, 0.7)]
    empty.rerank.assert_called_once()
    good.rerank.assert_called_once()


def test_fallback_chain_check_available_true_if_any():
    bad = MagicMock(spec=CloudReranker)
    bad.check_available.return_value = False
    good = MagicMock(spec=CloudReranker)
    good.check_available.return_value = True

    chain = FallbackChainReranker([bad, good])
    assert chain.check_available() is True


def test_fallback_chain_requires_at_least_one_backend():
    with pytest.raises(ValueError):
        FallbackChainReranker([])


def test_build_default_rerank_chain_local_first(monkeypatch):
    monkeypatch.delenv("JINA_AI_API_KEY", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    monkeypatch.delenv("CO_API_KEY", raising=False)

    chain = build_default_rerank_chain()
    assert isinstance(chain, FallbackChainReranker)
    assert isinstance(chain._backends[0], Qwen3Reranker)


def test_build_default_rerank_chain_includes_jina_then_cohere(monkeypatch):
    monkeypatch.setenv("JINA_AI_API_KEY", "stub-jina")
    monkeypatch.setenv("COHERE_API_KEY", "stub-cohere")

    chain = build_default_rerank_chain()
    backends = chain._backends

    # Local first, then Jina, then Cohere — order matters for the cascade.
    assert isinstance(backends[0], Qwen3Reranker)
    cloud = [b for b in backends if isinstance(b, CloudReranker)]
    assert len(cloud) == 2
    assert "jina" in cloud[0].model.lower()
    assert "rerank-v4" in cloud[1].model.lower()


def test_build_default_rerank_chain_prefer_local_false_swaps_order(monkeypatch):
    monkeypatch.setenv("JINA_AI_API_KEY", "stub-jina")
    chain = build_default_rerank_chain(prefer_local=False)
    backends = chain._backends

    assert isinstance(backends[0], CloudReranker)
    assert isinstance(backends[-1], Qwen3Reranker)


# ---------------------------------------------------------------------------
# Temporal decay
# ---------------------------------------------------------------------------


def test_temporal_decay_recent_higher_score(tmp_db: MemoryDB):
    """Recent memory should outscore an equally-relevant aged memory."""
    recent_id = tmp_db.add("python programming language", category="tech")
    old_id = tmp_db.add("python programming language", category="tech")

    # Age the second row by 60 days.
    aged_at = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    tmp_db._conn.execute(
        "UPDATE memories SET updated_at = ?, last_accessed = ? WHERE id = ?",
        (aged_at, aged_at, old_id),
    )
    tmp_db._conn.commit()

    results = tmp_db.search("python programming", limit=5)
    ids = [r["id"] for r in results]
    assert ids[0] == recent_id, f"Recent memory should rank first; got order {ids}"


def test_temporal_decay_half_life_param_affects_score(tmp_path):
    """Shorter half-life makes the same age decay further."""
    db_short = MemoryDB(tmp_path / "short.db", recency_half_life_days=1.0)
    db_long = MemoryDB(tmp_path / "long.db", recency_half_life_days=30.0)
    try:
        ts = (datetime.now(UTC) - timedelta(days=7)).isoformat()
        score_short = db_short._calc_recency(ts, datetime.now(UTC))
        score_long = db_long._calc_recency(ts, datetime.now(UTC))
        assert score_short < score_long
    finally:
        db_short.close()
        db_long.close()


# ---------------------------------------------------------------------------
# Importance boost
# ---------------------------------------------------------------------------


def test_importance_boost_high_importance_higher(tmp_db: MemoryDB):
    low_id = tmp_db.add("python is great for ml", category="tech")
    high_id = tmp_db.add("python is great for ml", category="tech")

    tmp_db.update_importance(low_id, 0.0)
    tmp_db.update_importance(high_id, 1.0)

    results = tmp_db.search("python ml", limit=5)
    ids = [r["id"] for r in results]
    assert ids[0] == high_id, f"High importance should rank first; got {ids}"


# ---------------------------------------------------------------------------
# Filter args
# ---------------------------------------------------------------------------


def test_filter_context_type(tmp_db: MemoryDB):
    fact_id = tmp_db.add_with_context_type(
        "users prefer light theme", context_type="fact"
    )
    pref_id = tmp_db.add_with_context_type(
        "users prefer light theme", context_type="preference"
    )

    fact_only = tmp_db.search("users light theme", context_type="fact", limit=10)
    fact_ids = {r["id"] for r in fact_only}
    assert fact_id in fact_ids
    assert pref_id not in fact_ids


def test_filter_since_until_dates(tmp_db: MemoryDB):
    old_id = tmp_db.add("alpha bravo charlie")
    mid_id = tmp_db.add("alpha bravo charlie delta")

    old_ts = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    mid_ts = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    tmp_db._conn.execute(
        "UPDATE memories SET updated_at = ? WHERE id = ?", (old_ts, old_id)
    )
    tmp_db._conn.execute(
        "UPDATE memories SET updated_at = ? WHERE id = ?", (mid_ts, mid_id)
    )
    tmp_db._conn.commit()

    cutoff = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    recent_only = tmp_db.search("alpha bravo", since=cutoff, limit=10)
    recent_ids = {r["id"] for r in recent_only}
    assert mid_id in recent_ids
    assert old_id not in recent_ids

    until_cutoff = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    older_only = tmp_db.search("alpha bravo", until=until_cutoff, limit=10)
    older_ids = {r["id"] for r in older_only}
    assert old_id in older_ids
    assert mid_id not in older_ids


def test_filter_min_importance(tmp_db: MemoryDB):
    low_id = tmp_db.add("project status update")
    high_id = tmp_db.add("project status update important")
    tmp_db.update_importance(low_id, 0.1)
    tmp_db.update_importance(high_id, 0.9)

    important_only = tmp_db.search("project status", min_importance=0.5, limit=10)
    important_ids = {r["id"] for r in important_only}
    assert high_id in important_ids
    assert low_id not in important_ids


def test_filter_excludes_archived_default(tmp_db: MemoryDB):
    """Archived rows (archived_at IS NOT NULL) should not appear by default."""
    keep_id = tmp_db.add("yellow submarine project")
    archive_id = tmp_db.add("yellow submarine project")

    tmp_db._conn.execute(
        "UPDATE memories SET archived_at = ? WHERE id = ?",
        (datetime.now(UTC).isoformat(), archive_id),
    )
    tmp_db._conn.commit()

    out = tmp_db.search("yellow submarine", limit=10)
    out_ids = {r["id"] for r in out}
    assert keep_id in out_ids
    assert archive_id not in out_ids


def test_include_archived_true_returns_archived_rows(tmp_db: MemoryDB):
    keep_id = tmp_db.add("octopus shaped balloon")
    archive_id = tmp_db.add("octopus shaped balloon")

    tmp_db._conn.execute(
        "UPDATE memories SET archived_at = ? WHERE id = ?",
        (datetime.now(UTC).isoformat(), archive_id),
    )
    tmp_db._conn.commit()

    out = tmp_db.search("octopus balloon", include_archived=True, limit=10)
    out_ids = {r["id"] for r in out}
    assert keep_id in out_ids
    assert archive_id in out_ids


# ---------------------------------------------------------------------------
# Server-level reranker integration smoke
# ---------------------------------------------------------------------------


async def test_handle_search_passes_candidate_pool_when_reranker_active(
    mock_ctx,
):
    """Reranker presence should expand the candidate pool fed to db.search."""
    from mnemo_mcp.server import _handle_search

    ctx, db = mock_ctx
    for i in range(20):
        db.add(f"reindex job {i}")

    fake_reranker = MagicMock()
    fake_reranker.rerank.return_value = [(0, 0.9), (1, 0.7)]

    with patch("mnemo_mcp.reranker.get_reranker", return_value=fake_reranker):
        with patch.object(db, "search", wraps=db.search) as wrapped:
            await _handle_search(ctx, query="reindex job", limit=5)

    call_kwargs = wrapped.call_args.kwargs
    assert call_kwargs.get("candidate_pool") is not None
    assert call_kwargs["candidate_pool"] >= 50
