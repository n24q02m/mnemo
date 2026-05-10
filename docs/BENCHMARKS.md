# Benchmarks

This document tracks Mnemo performance baselines + Phase 2 targets per
spec `2026-04-19-mnemo-v2-design.md` section 3.

## Phase 1 baseline (v1.27.0-beta.2)

| Metric | Baseline |
|---|---|
| Capture latency p95 (no compression) | <100 ms (FTS5 + dedup probe + insert) |
| Search recall@5 (mem_001 dataset, hybrid FTS+vec) | TBD (Phase 1 retrieval polish) |
| GDrive sync push (whole-DB copy, ~1k rows) | ~3-5s (network-bound) |
| Cold start (clean install, FTS5-only mode) | <500 ms |
| Cold start (with Qwen3 ONNX local) | First-run: ~30s download (~570 MB) |

## Phase 2 targets

| Metric | Target | Rationale |
|---|---|---|
| Compression ratio | >=3x reduction | Spec section 3 |
| Fact retention after compression | >=0.90 | Spec section 3 |
| Compression latency p95 | <500 ms | Spec section 3 |
| Capture latency p95 (with compression) | <600 ms (= baseline + 500ms compression budget) | Composition of Phase 1 + 500ms compression |
| Delta upload p95 (10k store, 1% delta) | <2s | Spec section 3 |
| Full sync cold boot (10k store) | <15s | Spec section 3 |

## How to measure

Compression ratio + fact retention need a curated fixture
(`tests/fixtures/compression/conversations.jsonl` 500 turns + a
ground-truth fact set). Phase 2 baseline release ships the fixture
infrastructure; the actual ratio + retention numbers are populated as
the curated dataset matures (initial 50 entries from public AI Studio
exports + Claude Code transcripts, expanded across follow-up patches).

Sync metrics are measured against the moto S3 backend (offline,
deterministic) for delta latency and against a real R2 bucket for full
sync cold boot. Real-bucket benchmarks live behind the `integration`
pytest marker (skipped by default per pyproject.toml addopts).

## Phase 2 measured baselines

(populated once the curated fixture lands + benchmark suite runs)

| Metric | Measured |
|---|---|
| Compression ratio | tbd |
| Fact retention | tbd |
| Compression latency p95 | tbd |
| Delta upload p95 | tbd |
| Full sync cold boot | tbd |

## Phase 1 vs Phase 2 retrieval drift

Phase 2 must stay within +/-10% of Phase 1 on retrieval metrics
(spec section 3). Compression is content-rewrite, not column-rewrite,
so FTS5 + vec scores stay anchored to the rewritten text. Fact
retention >=0.90 plus the explicit prompt to preserve identifiers
keeps semantic recall comparable; concrete drift numbers populate as
the eval set lands.

## Phase 3 targets (v2.0.0)

Spec section 3 Phase 3 row + Phase 3 plan Task 11 Step 4 regression
gate.

| Metric | Target | Rationale |
|---|---|---|
| Bitemporal query p95 | <200 ms | Spec section 3 — `memories_as_of` must stay snappy on a 10k-row DB. Indexed via `idx_memories_updated` + COALESCE on `valid_from`. |
| Entity resolution precision | ≥0.85 | Spec section 3 — over a 200-pair eval (100 same-entity, 100 different) the embedding+name dedup must avoid false-merge ≥85% of the time. |
| Entity resolution recall | ≥0.80 | Spec section 3 — at the same threshold, must catch ≥80% of true duplicates. |
| Capture latency p95 (KG_AUTO_ENABLED=true) | <800 ms | Phase 1+2 baseline + LLM extract round-trip (~200 ms) + Phase 3 store overhead. |
| Bundle size growth (Phase 3 vs Phase 2, 10k memories) | ≤2x | KG sections add roughly N entities + 2N edges + N links to the bundle. AES-GCM compression overhead is constant. |

## Phase 3 measured baselines

(populated as the entity-resolution eval fixture lands + benchmark
suite runs against the migrated DB)

| Metric | Measured |
|---|---|
| Bitemporal query p95 | tbd |
| Entity resolution P/R | tbd |
| Capture latency p95 (KG_AUTO_ENABLED=true) | tbd |
| Bundle size growth | tbd |

## Phase 2 vs Phase 3 retrieval drift

Phase 3 retrieval must stay within +/-10% of Phase 2 on the existing
hybrid recall metrics. Bitemporal filter is additive (an extra
`AND valid_to IS NULL` clause); entity-graph boost is opt-in and
defaults to off so v2.0.0 ships with no recall regression for callers
that ignore the new actions.
