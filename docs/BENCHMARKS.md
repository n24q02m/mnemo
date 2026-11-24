# Benchmarks

This document tracks Mnemo performance baselines and targets.

## Phase 1 baseline (v1.27.0-beta.2)

| Metric | Baseline |
|---|---|
| Capture latency p95 (no compression) | 0.784 ms measured (100-row WAL benchmark, `embedding_dims=0`) |
| Search recall@5 (`mn1` dataset, FTS5 hybrid pilot) | 1.000 (`13/13`, p50 `0.898 ms`, p95 `2.189 ms`, `cost_usd=0.0`) |
| Cold start (clean install, FTS5-only mode) | <500 ms |
| Cold start (with Qwen3 ONNX local) | First-run: ~30s download (~570 MB) |

## Phase 2 targets

| Metric | Target | Rationale |
|---|---|---|
| Compression ratio | >=3x reduction | Design target |
| Fact retention after compression | >=0.90 | Design target |
| Compression latency p95 | <500 ms | Design target |
| Capture latency p95 (with compression) | <600 ms (= baseline + 500ms compression budget) | Baseline capture + 500ms compression |

## How to measure

Compression ratio + fact retention need a curated fixture
(`tests/fixtures/compression/conversations.jsonl` 500 turns + a
ground-truth fact set). The fixture infrastructure ships with the
compression feature; the actual ratio + retention numbers are populated
as the curated dataset matures.

## Phase 2 measured baselines

(0-LLM deterministic baseline metrics; LLM-powered semantic compression is gated on `[models.chat]` API credentials and omitted in 0-LLM runs.)

| Metric | Measured |
|---|---|
| Compact disclosure payload reduction | 2.44x character reduction (`compact=True` vs `compact=False`, k=5) |
| Deterministic defense TP/FP accuracy (`mn2-defense`) | 1.000 (`24/24` total: `7/7` secret TP, `0` FP on 17 benign, `5/5` prompt-injection block, `0` poison FP, `0.122 ms` probe) |
| Capture latency p95 (no compression, WAL SQLite) | 0.784 ms |

## Phase 1 vs Phase 2 retrieval drift

Phase 2 must stay within +/-10% of Phase 1 on retrieval metrics.
Compression is content-rewrite, not column-rewrite,
so FTS5 + vec scores stay anchored to the rewritten text. Fact
retention >=0.90 plus the explicit prompt to preserve identifiers
keeps semantic recall comparable; concrete drift numbers populate as
the eval set lands.

## Phase 3 targets (v2.0.0)

Temporal knowledge graph performance gate.

| Metric | Target | Rationale |
|---|---|---|
| Bitemporal query p95 | <200 ms | Time-travel queries — `memories_as_of` must stay snappy on a 10k-row DB. Indexed via `idx_memories_updated` + COALESCE on `valid_from`. |
| Entity resolution precision | ≥0.85 | Dedup accuracy — over a 200-pair eval (100 same-entity, 100 different) the embedding+name dedup must avoid false-merge ≥85% of the time. |
| Entity resolution recall | ≥0.80 | Dedup coverage — at the same threshold, must catch ≥80% of true duplicates. |
| Capture latency p95 (KG_AUTO_ENABLED=true) | <800 ms | Baseline capture + LLM extract round-trip (~200 ms) + KG store overhead. |
| Bundle size growth (Phase 3 vs Phase 2, 10k memories) | ≤2x | KG sections add roughly N entities + 2N edges + N links to the bundle. AES-GCM compression overhead is constant. |

## Phase 3 & Phase 4 measured baselines

(measured on migrated schema `head=mem_007_confidence` with `0` paid LLM calls)

| Metric | Measured |
|---|---|
| Bitemporal query p95 (`memories_as_of`) | 0.519 ms (50 iterations on 100-row migrated DB) |
| Entity resolution P/R (`link_entities_with_fastretrieval`) | 1.00 P / 1.00 R on alias dedup & bilingual evolution probe (`locomo-retrieval-0llm`: `4/4`, `5.495 ms`) |
| Capture latency p95 (with Phase 4 poison & contradiction gate) | 0.784 ms (0-LLM Stage-1 regex/lexical path; external KG extraction requires `[models.chat]`) |
| Store size at 100 migrated memories | 212.0 KB (including FTS5 + bitemporal + KG tables) |
| LongMemEval-0LLM retrieval (`run_longmemeval_retrieval`) | Recall@5 `1.000` (`4/4`), MRR@5 `1.000`, p95 latency `6.079 ms`, `cost_usd=0.0` |

## Phase 2 vs Phase 3 retrieval drift

Phase 3 retrieval must stay within +/-10% of Phase 2 on the existing
hybrid recall metrics. Bitemporal filter is additive (an extra
`AND valid_to IS NULL` clause); entity-graph boost is opt-in and
defaults to off so v2.0.0 ships with no recall regression for callers
that ignore the new actions.
