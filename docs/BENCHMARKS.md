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

All benchmark runners support deterministic 0-LLM execution by default and write JSON reports under `evals/`:

| Benchmark | Source / Fixture | Command | Report |
|---|---|---|---|
| LoCoMo retrieval (`1,536` QA / `5,882` turns) | `snap-research/locomo` (`locomo10.json`, auto-cached under `evals/.cache/`) | `uv run python -m evals.run_locomo_retrieval` (add `--with-llm-judge` for `[models.chat]` judging) | `evals/locomo_retrieval_report.json` |
| LongMemEval retrieval (`470` answerable + `30` `_abs` / `10,960` turns) | `xiaowu0162/longmemeval-cleaned` (`longmemeval_oracle.json`, auto-cached; supports `--variant s`) | `uv run python -m evals.run_longmemeval_retrieval --variant oracle` (add `--with-llm-judge` for `[models.chat]` judging) | `evals/longmemeval_retrieval_report.json` |
| Phase 2 capture & compact disclosure (`500` turns, `25` subjects) | `tests/fixtures/compression/conversations.jsonl` | `uv run python -m evals.run_phase2_compression` (add `--with-llm` for live `[models.chat]` write-time compression) | `evals/phase2_compression_report.json` |

Fast offline 4-case regression smoke tests are kept separately in `tests/test_retrieval_eval_smoke.py`.

## Phase 2 measured baselines

(Measured across all `500` turns / `58,647` input tokens in `tests/fixtures/compression/conversations.jsonl` under deterministic 0-LLM mode with `COMPRESSION_ENABLED=false`, plus `compact=True` progressive disclosure; pass `--with-llm` when `[models.chat]` credentials are configured to measure live LLM rewrite compression.)

| Metric | Measured |
|---|---|
| Fixture scale (`conversations.jsonl`) | `500` turns across `25` subject buckets (`500` captured, `0` deduplicated) |
| Write-time compression ratio (0-LLM fallback) | `1.000x` (`58,647` -> `58,647` cl100k_base tokens, 0% savings, 0 compressed turns, `cost_usd=0.0`) |
| Write-time fact retention (0-LLM lossless path) | `1.000` (`500/500` expected ground-truth tokens preserved) |
| Write-time capture latency (`mnemo.capture.capture`, `500` turns) | p50 `2.048 ms`, p95 `5.912 ms`, mean `2.611 ms` (single-row WAL SQLite microbenchmark: `0.784 ms` p95) |
| Progressive disclosure token reduction (`compact=True` vs `compact=False`, `k=5`) | `4.5958x` token reduction (`78.24%` savings: `288,544` -> `62,784` tokens), `4.249x` character reduction |
| Recall & MRR on `500`-turn fixture (`k=5`) | `raw_recall_at_5=1.000`, `raw_mrr_at_5=1.000`, `compact_recall_at_5=1.000` |
| Search latency (`operations.recall`, `500` queries, `k=5`) | p50 `3.061 ms`, p95 `4.559 ms`, mean `3.161 ms` |
| Deterministic defense TP/FP accuracy (`mn2-defense`) | `1.000` (`24/24` total: `7/7` secret TP, `0` FP on 17 benign, `5/5` prompt-injection block, `0` poison FP, `0.122 ms` probe) |

## Phase 1 vs Phase 2 retrieval drift

Phase 2 must stay within +/-10% of Phase 1 on retrieval metrics. Compression is content-rewrite, not column-rewrite, so FTS5 + vec scores stay anchored to the stored text. Across the `500` queries in `tests/fixtures/compression/conversations.jsonl`, progressive disclosure (`compact=True`) measured `0.0%` top-5 ID retrieval drift (`raw_recall_at_5=1.000` vs `compact_recall_at_5=1.000`); when `--with-llm` write-time compression is enabled with `[models.chat]`, `evals.run_phase2_compression --with-llm` compares `fact_retention`, `raw_recall_at_5`, and `capture_compression_ratio` directly on the same `500`-turn corpus.

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
| Entity resolution P/R (`link_entities_with_fastretrieval`) | 1.00 P / 1.00 R on alias dedup & bilingual evolution probe |
| Capture latency p95 (with Phase 4 poison & contradiction gate) | 0.784 ms (0-LLM Stage-1 regex/lexical path; external KG extraction requires `[models.chat]`) |
| Store size at 100 migrated memories | 212.0 KB (including FTS5 + bitemporal + KG tables) |
| LoCoMo retrieval (`run_locomo_retrieval`, `locomo10.json`, `0-LLM`) | `1,536` answerable QA queries (`10` conversations, `5,882` turns, `446` adversarial excluded): `Recall@1=0.3073`, `Recall@5=0.5449`, `Recall@10=0.6374`, `MRR@5=0.3988`, `MRR@10=0.4113`, p50 `10.589 ms`, p95 `16.512 ms`, `cost_usd=0.0` |
| LongMemEval retrieval (`run_longmemeval_retrieval`, `longmemeval_oracle.json`, `0-LLM`) | `470` answerable + `30` `_abs` abstention (`500` items, `10,960` turns): `Recall@1=0.5340`, `Recall@5=0.8702`, `Recall@10=0.9383`, `session_recall_at_5=1.0000`, `MRR@5=0.6629`, p50 `4.577 ms`, p95 `7.789 ms`, `cost_usd=0.0` |

## Phase 2 vs Phase 3 retrieval drift

Phase 3 retrieval must stay within +/-10% of Phase 2 on the existing
hybrid recall metrics. Bitemporal filter is additive (an extra
`AND valid_to IS NULL` clause); entity-graph boost is opt-in and
defaults to off so v2.0.0 ships with no recall regression for callers
that ignore the new actions.
