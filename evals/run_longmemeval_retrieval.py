"""Authentic LongMemEval retrieval eval runner (xiaowu0162/longmemeval-cleaned).

Evaluates Mnemo's deterministic 0-LLM retrieval pipeline (``operations.capture``
+ ``operations.recall`` over FTS5-backed ``MemoryDB``) on the real LongMemEval
dataset (``longmemeval_oracle.json``, 500 queries across 6 categories: 470
answerable + 30 ``_abs`` abstention cases; ``--variant s`` also supports
``longmemeval_s_cleaned.json``).

Optional ``--with-llm-judge`` invokes the configured ``[models.chat]`` cell
to judge whether top-k retrieved contexts support the reference answer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from evals._common import (
    chunk_text,
    create_template_db,
    ensure_cached_dataset,
    llm_judge_retrieval,
    open_cloned_db,
    quiet_eval_logs,
    summarize_latencies,
)
from mnemo_core import operations

HF_BASE_URL = (
    "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main"
)
VARIANT_FILES: dict[str, str] = {
    "oracle": "longmemeval_oracle.json",
    "s": "longmemeval_s_cleaned.json",
}
CACHE_DIR = Path(__file__).with_name(".cache")
REPORT_PATH = Path(__file__).with_name("longmemeval_retrieval_report.json")


def _parse_lme_datetime(raw: str) -> str | None:
    """Parse strings like ``'2023/05/20 (Sat) 02:21'`` to ISO-8601 UTC."""
    if not raw:
        return None
    m = re.match(r"(\d{4})/(\d{2})/(\d{2}).*?(\d{2}):(\d{2})", raw.strip())
    if m:
        y, mo, d, hh, mm = m.groups()
        try:
            dt = datetime(int(y), int(mo), int(d), int(hh), int(mm))
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return None
    return None


def run_eval(
    dataset_path: Path | None = None,
    *,
    variant: str = "oracle",
    limit: int = 0,
    k: int = 10,
    with_llm_judge: bool = False,
    judge_limit: int = 100,
    work_root: Path | None = None,
) -> dict[str, Any]:
    """Run LongMemEval retrieval benchmark against ``dataset_path`` (auto-cached if omitted)."""
    if variant not in VARIANT_FILES:
        raise ValueError(
            f"Unknown variant {variant!r}; expected {sorted(VARIANT_FILES)}"
        )

    filename = VARIANT_FILES[variant]
    source_url = f"{HF_BASE_URL}/{filename}"
    resolved_path = dataset_path or ensure_cached_dataset(
        source_url, CACHE_DIR / filename
    )
    items: list[dict[str, Any]] = json.loads(resolved_path.read_text(encoding="utf-8"))
    if limit > 0:
        items = items[:limit]

    latencies_ms: list[float] = []
    answerable_queries = 0
    abstention_cases = 0
    hits_at_1 = 0
    hits_at_5 = 0
    hits_at_10 = 0
    session_hits_at_5 = 0
    rr_sum_5 = 0.0
    rr_sum_10 = 0.0
    total_turns = 0
    skipped_turns = 0
    by_type: dict[str, dict[str, Any]] = {}
    judge_samples: list[tuple[str, str, list[str]]] = []

    with tempfile.TemporaryDirectory() as tmp:
        root = work_root or Path(tmp)
        root.mkdir(parents=True, exist_ok=True)
        template_db = create_template_db(root / "_template.sqlite")

        for idx, item in enumerate(items):
            qid = str(item["question_id"])
            qtype = str(item.get("question_type", "unknown"))
            is_abs = qid.endswith("_abs")
            db = open_cloned_db(template_db, root / f"q_{idx}.sqlite")
            try:
                answer_mids: set[str] = set()
                mid_to_sid: dict[str, str] = {}
                answer_sids = {str(s) for s in (item.get("answer_session_ids") or [])}

                for sess_id, sess_dt, turns in zip(
                    item.get("haystack_session_ids", []),
                    item.get("haystack_dates", []),
                    item.get("haystack_sessions", []),
                    strict=False,
                ):
                    dt_iso = _parse_lme_datetime(str(sess_dt))
                    for turn in turns:
                        role = str(turn.get("role", "user"))
                        content = str(turn.get("content", "")).strip()
                        if not content:
                            continue
                        total_turns += 1
                        prefix = f"[{sess_dt}] {role}: " if sess_dt else f"{role}: "
                        for part in chunk_text(content, 4100):
                            env = operations.capture(db, qid, prefix + part)
                            if not env.get("ok"):
                                skipped_turns += 1
                                continue
                            mid = env["data"]["id"]
                            mid_to_sid[mid] = str(sess_id)
                            if turn.get("has_answer"):
                                answer_mids.add(mid)
                            if dt_iso:
                                with db.connection() as conn:
                                    conn.execute(
                                        "UPDATE memories SET valid_from = ?, created_at = ? WHERE id = ?",
                                        (dt_iso, dt_iso, mid),
                                    )
                                    conn.commit()

                if is_abs or not answer_mids:
                    abstention_cases += 1
                    continue

                answerable_queries += 1
                t0 = time.perf_counter()
                res = operations.recall(
                    db, qid, str(item["question"]), k=max(k, 10), rewrite=True
                )
                latencies_ms.append((time.perf_counter() - t0) * 1000.0)

                matches = res["data"]["matches"] if res.get("ok") else []
                rank = next(
                    (i + 1 for i, m in enumerate(matches) if m["id"] in answer_mids),
                    None,
                )
                sess_hit_5 = any(
                    mid_to_sid.get(m["id"]) in answer_sids for m in matches[:5]
                )

                bucket = by_type.setdefault(
                    qtype,
                    {
                        "queries": 0,
                        "hits_at_1": 0,
                        "hits_at_5": 0,
                        "hits_at_10": 0,
                        "session_hits_at_5": 0,
                        "rr5": 0.0,
                    },
                )
                bucket["queries"] += 1
                if sess_hit_5:
                    session_hits_at_5 += 1
                    bucket["session_hits_at_5"] += 1

                if rank is not None:
                    if rank <= 1:
                        hits_at_1 += 1
                        bucket["hits_at_1"] += 1
                    if rank <= 5:
                        hits_at_5 += 1
                        rr_sum_5 += 1.0 / rank
                        bucket["hits_at_5"] += 1
                        bucket["rr5"] += 1.0 / rank
                    if rank <= 10:
                        hits_at_10 += 1
                        rr_sum_10 += 1.0 / rank
                        bucket["hits_at_10"] += 1

                if with_llm_judge and len(judge_samples) < judge_limit:
                    ctxs = [str(m.get("content", "")) for m in matches[:5]]
                    judge_samples.append(
                        (str(item["question"]), str(item.get("answer", "")), ctxs)
                    )
            finally:
                db.close()

    type_summary = {
        qtype: {
            "queries": b["queries"],
            "recall_at_1": round(b["hits_at_1"] / b["queries"], 4),
            "recall_at_5": round(b["hits_at_5"] / b["queries"], 4),
            "recall_at_10": round(b["hits_at_10"] / b["queries"], 4),
            "session_recall_at_5": round(b["session_hits_at_5"] / b["queries"], 4),
            "mrr_at_5": round(b["rr5"] / b["queries"], 4),
        }
        for qtype, b in sorted(by_type.items())
    }

    report: dict[str, Any] = {
        "eval": "longmemeval-retrieval",
        "dataset": f"xiaowu0162/longmemeval-cleaned ({filename})",
        "variant": variant,
        "source_url": source_url,
        "deterministic": not with_llm_judge,
        "with_llm_judge": with_llm_judge,
        "paid_calls": 0,
        "cost_usd": 0.0,
        "total_items": len(items),
        "total_queries": answerable_queries,
        "abstention_cases": abstention_cases,
        "total_turns_ingested": total_turns,
        "skipped_turns": skipped_turns,
        "hits_at_1": hits_at_1,
        "hits_at_5": hits_at_5,
        "hits_at_10": hits_at_10,
        "recall_at_1": round(hits_at_1 / answerable_queries, 4)
        if answerable_queries
        else 0.0,
        "recall_at_5": round(hits_at_5 / answerable_queries, 4)
        if answerable_queries
        else 0.0,
        "recall_at_10": round(hits_at_10 / answerable_queries, 4)
        if answerable_queries
        else 0.0,
        "session_recall_at_5": round(session_hits_at_5 / answerable_queries, 4)
        if answerable_queries
        else 0.0,
        "mrr_at_5": round(rr_sum_5 / answerable_queries, 4)
        if answerable_queries
        else 0.0,
        "mrr_at_10": round(rr_sum_10 / answerable_queries, 4)
        if answerable_queries
        else 0.0,
        "latency_ms": summarize_latencies(latencies_ms),
        "by_question_type": type_summary,
        "reproduce_cmd": f"uv run python -m evals.run_longmemeval_retrieval --variant {variant}",
    }

    if with_llm_judge:

        async def _run_judge() -> dict[str, Any]:
            judged = 0
            judge_yes = 0
            model_name = ""
            for q_text, gold, ctxs in judge_samples:
                res = await llm_judge_retrieval(q_text, gold, ctxs)
                judged += 1
                model_name = res["model"]
                if res["passed"]:
                    judge_yes += 1
            return {
                "judge_model": model_name,
                "judged_queries": judged,
                "judge_pass": judge_yes,
                "judge_accuracy": round(judge_yes / judged, 4) if judged else 0.0,
            }

        judge_out = asyncio.run(_run_judge())
        report["llm_judge"] = judge_out
        report["paid_calls"] = judge_out["judged_queries"]

    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-path", type=Path, default=None)
    parser.add_argument("--variant", choices=("oracle", "s"), default="oracle")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--with-llm-judge", action="store_true")
    parser.add_argument("--judge-limit", type=int, default=100)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    quiet_eval_logs()
    args = parse_args(argv)
    report = run_eval(
        dataset_path=args.dataset_path,
        variant=args.variant,
        limit=args.limit,
        k=args.k,
        with_llm_judge=args.with_llm_judge,
        judge_limit=args.judge_limit,
    )
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "eval",
                    "total_queries",
                    "recall_at_1",
                    "recall_at_5",
                    "recall_at_10",
                    "mrr_at_5",
                    "paid_calls",
                    "cost_usd",
                )
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["total_queries"] >= 100 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
