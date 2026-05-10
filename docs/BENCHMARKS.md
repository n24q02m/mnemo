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
