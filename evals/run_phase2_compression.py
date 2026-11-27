"""Phase 2 capture & progressive-disclosure compression eval runner.

Measures Mnemo's real capture and retrieval pipeline against the 500-turn
``tests/fixtures/compression/conversations.jsonl`` fixture:

1. **Write-time capture** (``mnemo.capture.capture``): wall-clock latency
   (p50/p95/mean), FTS dedup behavior, ``tiktoken cl100k_base`` token counts
   (``tokens_in`` vs ``tokens_out``), compression ratio, and ground-truth
   token retention inside the persisted memory content.
   - Default ``0-LLM`` mode sets ``COMPRESSION_ENABLED=false`` cleanly around the
     run so deterministic baseline metrics never hammer unconfigured chat pools.
   - ``--with-llm`` mode sets ``COMPRESSION_ENABLED=true`` and invokes the
     configured ``[models.chat]`` cell via ``mnemo.compression.compress``.
2. **Read-time progressive disclosure** (``mnemo_core.operations.recall`` with
   ``compact=False`` vs ``compact=True``, ``k=5``): measures full vs snippet
   payload compression (character and token ratios), retrieval ``Recall@k`` and
   ``MRR@k``, and search latency (p50/p95/mean).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from evals._common import (
    create_template_db,
    open_cloned_db,
    quiet_eval_logs,
    summarize_latencies,
)
from mnemo.capture import capture
from mnemo.compression import count_tokens
from mnemo_core import operations

DEFAULT_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "compression"
    / "conversations.jsonl"
)
REPORT_PATH = Path(__file__).with_name("phase2_compression_report.json")


def load_turns(fixture_path: Path, *, limit: int = 0) -> list[dict[str, Any]]:
    """Load non-empty JSONL turns from ``fixture_path``."""
    turns: list[dict[str, Any]] = []
    with fixture_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            raw = line.strip()
            if not raw:
                continue
            turns.append(json.loads(raw))
            if limit > 0 and len(turns) >= limit:
                break
    return turns


def _fact_tokens_retained(stored_text: str, expected_tokens: list[str]) -> bool:
    """Return True when all expected key tokens remain present in ``stored_text``."""
    if not expected_tokens:
        return True
    lowered = stored_text.lower()
    return all(str(tok).lower() in lowered for tok in expected_tokens)


def _payload_size(results: list[dict[str, Any]], *, compact: bool) -> tuple[int, int]:
    """Return total ``(chars, tokens)`` across serialized recall results."""
    field = "snippet" if compact else "content"
    joined = "\n".join(str(row.get(field) or "") for row in results)
    return len(joined), count_tokens(joined)


async def _run_eval_async(
    fixture_path: Path,
    *,
    limit: int = 0,
    k: int = 5,
    with_llm: bool = False,
    work_root: Path | None = None,
) -> dict[str, Any]:
    turns = load_turns(fixture_path, limit=limit)
    if not turns:
        raise ValueError(f"No turns found in {fixture_path}")

    prev_compression_env = os.environ.get("COMPRESSION_ENABLED")
    if with_llm:
        from mnemo.runtime import cell_configured

        if not cell_configured("chat"):
            raise RuntimeError(
                "--with-llm requires [models.chat] configuration "
                "(set HULL_CHAT_API_KEY or configure ~/.mnemo/config.toml)"
            )
        os.environ["COMPRESSION_ENABLED"] = "true"
    else:
        os.environ["COMPRESSION_ENABLED"] = "false"

    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for turn in turns:
        by_subject[str(turn.get("subject") or "default")].append(turn)

    capture_latencies_ms: list[float] = []
    search_latencies_ms: list[float] = []
    captured_turns = 0
    deduplicated_turns = 0
    compressed_turns = 0
    tokens_in_total = 0
    tokens_out_total = 0
    retained_count = 0
    retained_total = 0

    raw_chars_total = 0
    raw_tokens_total = 0
    compact_chars_total = 0
    compact_tokens_total = 0
    raw_hits = 0
    compact_hits = 0
    rr_sum = 0.0
    total_queries = 0

    try:
        with tempfile.TemporaryDirectory(
            prefix="mnemo_p2_",
            dir=str(work_root) if work_root is not None else None,
        ) as tmp_dir:
            tmp_path = Path(tmp_dir)
            template_db = create_template_db(tmp_path / "template.db")

            for idx, (_subject, subject_turns) in enumerate(by_subject.items()):
                db = open_cloned_db(template_db, tmp_path / f"subj_{idx}.db")
                try:
                    captured_ids: dict[str, str] = {}
                    for turn in subject_turns:
                        content = str(turn["content"])
                        t0 = time.perf_counter()
                        res = await capture(
                            db,
                            content,
                            context_type=str(
                                turn.get("context_type") or "conversation"
                            ),
                            category=str(turn.get("category") or "general"),
                            source=str(turn.get("id") or ""),
                        )
                        capture_latencies_ms.append((time.perf_counter() - t0) * 1000.0)

                        if res.get("deduplicated"):
                            deduplicated_turns += 1
                            continue

                        captured_turns += 1
                        mem_id = str(res["memory_id"])
                        captured_ids[str(turn["id"])] = mem_id
                        tokens_in = int(res.get("tokens_in") or count_tokens(content))
                        tokens_out = int(res.get("tokens_out") or tokens_in)
                        tokens_in_total += tokens_in
                        tokens_out_total += tokens_out
                        if res.get("compressed"):
                            compressed_turns += 1

                        row = db.get(mem_id)
                        stored_text = str(row["content"]) if row else content
                        expected_tokens = [
                            str(tok) for tok in turn.get("expected_tokens", [])
                        ]
                        retained_total += 1
                        if _fact_tokens_retained(stored_text, expected_tokens):
                            retained_count += 1

                    for turn in subject_turns:
                        query = str(turn.get("query") or "").strip()
                        turn_key = str(turn["id"])
                        if not query or turn_key not in captured_ids:
                            continue
                        target_id = captured_ids[turn_key]
                        total_queries += 1

                        t0 = time.perf_counter()
                        full_res = operations.recall(
                            db,
                            None,
                            query,
                            k=k,
                            compact=False,
                            rewrite=True,
                        )
                        search_latencies_ms.append((time.perf_counter() - t0) * 1000.0)

                        compact_res = operations.recall(
                            db,
                            None,
                            query,
                            k=k,
                            compact=True,
                            rewrite=True,
                        )

                        full_rows = (
                            full_res["data"]["matches"] if full_res.get("ok") else []
                        )
                        compact_rows = (
                            compact_res["data"]["matches"]
                            if compact_res.get("ok")
                            else []
                        )

                        r_chars, r_toks = _payload_size(full_rows, compact=False)
                        c_chars, c_toks = _payload_size(compact_rows, compact=True)
                        raw_chars_total += r_chars
                        raw_tokens_total += r_toks
                        compact_chars_total += c_chars
                        compact_tokens_total += c_toks

                        full_ids = [str(row.get("id") or "") for row in full_rows]
                        if target_id in full_ids:
                            raw_hits += 1
                            rank = full_ids.index(target_id) + 1
                            rr_sum += 1.0 / rank

                        compact_ids = [str(row.get("id") or "") for row in compact_rows]
                        if target_id in compact_ids:
                            compact_hits += 1
                finally:
                    db.close()
    finally:
        if prev_compression_env is None:
            os.environ.pop("COMPRESSION_ENABLED", None)
        else:
            os.environ["COMPRESSION_ENABLED"] = prev_compression_env

    if with_llm and captured_turns > 0 and compressed_turns == 0:
        raise RuntimeError(
            "--with-llm produced 0 compressed turns across all captured items; "
            "verify [models.chat] credentials and pool status"
        )

    capture_ratio = (
        round(tokens_in_total / tokens_out_total, 4) if tokens_out_total > 0 else 1.0
    )
    capture_savings_pct = (
        round((1.0 - (tokens_out_total / tokens_in_total)) * 100.0, 2)
        if tokens_in_total > 0
        else 0.0
    )
    compact_char_ratio = (
        round(raw_chars_total / compact_chars_total, 4)
        if compact_chars_total > 0
        else 1.0
    )
    compact_token_ratio = (
        round(raw_tokens_total / compact_tokens_total, 4)
        if compact_tokens_total > 0
        else 1.0
    )
    compact_token_savings_pct = (
        round((1.0 - (compact_tokens_total / raw_tokens_total)) * 100.0, 2)
        if raw_tokens_total > 0
        else 0.0
    )

    try:
        fixture_rel = str(
            fixture_path.resolve().relative_to(Path(__file__).resolve().parent.parent)
        ).replace("\\", "/")
    except ValueError:
        fixture_rel = str(fixture_path)

    return {
        "eval": "phase2-compression",
        "mode": "llm" if with_llm else "0llm-deterministic",
        "fixture_path": fixture_rel,
        "total_turns": len(turns),
        "subject_buckets": len(by_subject),
        "captured_turns": captured_turns,
        "deduplicated_turns": deduplicated_turns,
        "compressed_turns": compressed_turns,
        "tokens_in_total": tokens_in_total,
        "tokens_out_total": tokens_out_total,
        "capture_compression_ratio": capture_ratio,
        "capture_token_savings_pct": capture_savings_pct,
        "fact_retention": round(retained_count / retained_total, 4)
        if retained_total > 0
        else 0.0,
        "capture_latency_ms": summarize_latencies(capture_latencies_ms),
        "k": k,
        "total_queries": total_queries,
        f"raw_recall_at_{k}": round(raw_hits / total_queries, 4)
        if total_queries > 0
        else 0.0,
        f"raw_mrr_at_{k}": round(rr_sum / total_queries, 4)
        if total_queries > 0
        else 0.0,
        f"compact_recall_at_{k}": round(compact_hits / total_queries, 4)
        if total_queries > 0
        else 0.0,
        "compact_disclosure_char_ratio": compact_char_ratio,
        "compact_disclosure_token_ratio": compact_token_ratio,
        "compact_disclosure_token_savings_pct": compact_token_savings_pct,
        "raw_payload_tokens": raw_tokens_total,
        "compact_payload_tokens": compact_tokens_total,
        "search_latency_ms": summarize_latencies(search_latencies_ms),
        "paid_calls": compressed_turns if with_llm else 0,
        "cost_usd": 0.0 if not with_llm else None,
        "reproduce_cmd": (
            "uv run python -m evals.run_phase2_compression"
            + (" --with-llm" if with_llm else "")
        ),
    }


def run_eval(
    fixture_path: Path | None = None,
    *,
    limit: int = 0,
    k: int = 5,
    with_llm: bool = False,
    work_root: Path | None = None,
) -> dict[str, Any]:
    """Run Phase 2 capture & progressive-disclosure compression eval synchronously."""
    resolved = fixture_path or DEFAULT_FIXTURE_PATH
    return asyncio.run(
        _run_eval_async(
            resolved,
            limit=limit,
            k=k,
            with_llm=with_llm,
            work_root=work_root,
        )
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure Phase 2 capture & compact disclosure compression on 500-turn fixture."
    )
    parser.add_argument(
        "--fixture-path",
        type=Path,
        default=None,
        help="Path to JSONL fixture (defaults to tests/fixtures/compression/conversations.jsonl).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap number of turns evaluated (0 = all turns).",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="Top-k cutoff for recall and compact disclosure measurement.",
    )
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Enable live [models.chat] write-time LLM compression.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPORT_PATH,
        help="Output JSON report path.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    quiet_eval_logs()
    args = parse_args(argv)
    report = run_eval(
        fixture_path=args.fixture_path,
        limit=args.limit,
        k=args.k,
        with_llm=args.with_llm,
    )
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    recall_key = f"raw_recall_at_{report['k']}"
    print(
        f"Phase 2 Compression ({report['mode']}): turns={report['total_turns']}, "
        f"captured={report['captured_turns']}, dedup={report['deduplicated_turns']}, "
        f"capture_ratio={report['capture_compression_ratio']:.3f}x, "
        f"compact_token_ratio={report['compact_disclosure_token_ratio']:.3f}x "
        f"({report['compact_disclosure_token_savings_pct']:.1f}% savings), "
        f"R@{report['k']}={report[recall_key]:.4f}, "
        f"capture_p95={report['capture_latency_ms']['p95']}ms"
    )


if __name__ == "__main__":
    main()
