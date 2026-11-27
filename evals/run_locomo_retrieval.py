"""Authentic LoCoMo retrieval eval runner (snap-research/locomo).

Evaluates Mnemo's deterministic 0-LLM retrieval pipeline (``operations.capture``
+ ``operations.recall`` over FTS5-backed ``MemoryDB``) on the real LoCoMo
multi-session conversation benchmark (``locomo10.json``, 10 conversations,
1,536 answerable QA queries with dialogue-turn ``evidence`` ground truth).

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

LOCOMO_URL = (
    "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
)
DEFAULT_CACHE_PATH = Path(__file__).with_name(".cache") / "locomo10.json"
REPORT_PATH = Path(__file__).with_name("locomo_retrieval_report.json")

_CATEGORY_NAMES: dict[int, str] = {
    1: "multi_hop",
    2: "temporal",
    3: "open_domain",
    4: "single_hop",
    5: "adversarial",
}


def _parse_locomo_datetime(raw: str) -> str | None:
    """Parse strings like ``'1:56 pm on 8 May, 2023'`` to ISO-8601 UTC."""
    if not raw:
        return None
    cleaned = re.sub(r"\s+", " ", raw.strip())
    for fmt in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y", "%d %B, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return None


def _session_numbers(conv_obj: dict[str, Any]) -> list[int]:
    return sorted(
        int(k.split("_")[1])
        for k in conv_obj
        if k.startswith("session_")
        and not k.endswith("_date_time")
        and k.split("_")[1].isdigit()
    )


def run_eval(
    dataset_path: Path | None = None,
    *,
    limit: int = 0,
    k: int = 10,
    with_llm_judge: bool = False,
    judge_limit: int = 100,
    include_adversarial: bool = False,
    work_root: Path | None = None,
) -> dict[str, Any]:
    """Run LoCoMo retrieval benchmark against ``dataset_path`` (auto-cached if omitted)."""
    resolved_path = dataset_path or ensure_cached_dataset(
        LOCOMO_URL, DEFAULT_CACHE_PATH
    )
    conversations: list[dict[str, Any]] = json.loads(
        resolved_path.read_text(encoding="utf-8")
    )

    latencies_ms: list[float] = []
    total_queries = 0
    hits_at_1 = 0
    hits_at_5 = 0
    hits_at_10 = 0
    rr_sum_5 = 0.0
    rr_sum_10 = 0.0
    total_turns = 0
    skipped_turns = 0
    adversarial_skipped = 0
    by_cat: dict[str, dict[str, Any]] = {}
    judge_samples: list[tuple[str, str, list[str]]] = []

    with tempfile.TemporaryDirectory() as tmp:
        root = work_root or Path(tmp)
        root.mkdir(parents=True, exist_ok=True)
        template_db = create_template_db(root / "_template.sqlite")

        for conv in conversations:
            if limit > 0 and total_queries >= limit:
                break
            sid = str(conv["sample_id"])
            db = open_cloned_db(template_db, root / f"{sid}.sqlite")
            try:
                mid_to_dia: dict[str, str] = {}
                cobj = conv["conversation"]
                for sn in _session_numbers(cobj):
                    dt_raw = str(cobj.get(f"session_{sn}_date_time", ""))
                    dt_iso = _parse_locomo_datetime(dt_raw)
                    for turn in cobj[f"session_{sn}"]:
                        speaker = str(turn.get("speaker", "speaker"))
                        raw_text = str(turn.get("text", "")).strip()
                        if not raw_text:
                            continue
                        total_turns += 1
                        prefix = f"[{dt_raw}] {speaker}: " if dt_raw else f"{speaker}: "
                        for part in chunk_text(prefix + raw_text, 4200):
                            env = operations.capture(db, sid, part)
                            if not env.get("ok"):
                                skipped_turns += 1
                                continue
                            mid = env["data"]["id"]
                            mid_to_dia[mid] = str(turn.get("dia_id", ""))
                            if dt_iso:
                                with db.connection() as conn:
                                    conn.execute(
                                        "UPDATE memories SET valid_from = ?, created_at = ? WHERE id = ?",
                                        (dt_iso, dt_iso, mid),
                                    )
                                    conn.commit()

                for qa in conv.get("qa", []):
                    if limit > 0 and total_queries >= limit:
                        break
                    cat_id = int(qa.get("category", 0))
                    if cat_id == 5 and not include_adversarial:
                        adversarial_skipped += 1
                        continue
                    evidence = {str(e) for e in (qa.get("evidence") or []) if e}
                    if not evidence:
                        continue
                    question = str(qa.get("question", "")).strip()
                    if not question:
                        continue

                    total_queries += 1
                    t0 = time.perf_counter()
                    res = operations.recall(
                        db, sid, question, k=max(k, 10), rewrite=True
                    )
                    latencies_ms.append((time.perf_counter() - t0) * 1000.0)

                    matches = res["data"]["matches"] if res.get("ok") else []
                    dias = [mid_to_dia.get(m["id"], "") for m in matches]
                    rank = next(
                        (i + 1 for i, d in enumerate(dias) if d in evidence),
                        None,
                    )

                    cat_name = _CATEGORY_NAMES.get(cat_id, f"cat_{cat_id}")
                    bucket = by_cat.setdefault(
                        cat_name,
                        {
                            "queries": 0,
                            "hits_at_1": 0,
                            "hits_at_5": 0,
                            "hits_at_10": 0,
                            "rr5": 0.0,
                        },
                    )
                    bucket["queries"] += 1

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
                        gold = str(
                            qa.get("answer") or qa.get("adversarial_answer") or ""
                        )
                        ctxs = [str(m.get("content", "")) for m in matches[:5]]
                        judge_samples.append((question, gold, ctxs))
            finally:
                db.close()

    cat_summary = {
        name: {
            "queries": b["queries"],
            "recall_at_1": round(b["hits_at_1"] / b["queries"], 4),
            "recall_at_5": round(b["hits_at_5"] / b["queries"], 4),
            "recall_at_10": round(b["hits_at_10"] / b["queries"], 4),
            "mrr_at_5": round(b["rr5"] / b["queries"], 4),
        }
        for name, b in sorted(by_cat.items())
    }

    report: dict[str, Any] = {
        "eval": "locomo-retrieval",
        "dataset": "snap-research/locomo (locomo10.json)",
        "source_url": LOCOMO_URL,
        "deterministic": not with_llm_judge,
        "with_llm_judge": with_llm_judge,
        "paid_calls": 0,
        "cost_usd": 0.0,
        "conversations": len(conversations),
        "total_turns_ingested": total_turns,
        "skipped_turns": skipped_turns,
        "adversarial_qa_excluded": adversarial_skipped,
        "total_queries": total_queries,
        "hits_at_1": hits_at_1,
        "hits_at_5": hits_at_5,
        "hits_at_10": hits_at_10,
        "recall_at_1": round(hits_at_1 / total_queries, 4) if total_queries else 0.0,
        "recall_at_5": round(hits_at_5 / total_queries, 4) if total_queries else 0.0,
        "recall_at_10": round(hits_at_10 / total_queries, 4) if total_queries else 0.0,
        "mrr_at_5": round(rr_sum_5 / total_queries, 4) if total_queries else 0.0,
        "mrr_at_10": round(rr_sum_10 / total_queries, 4) if total_queries else 0.0,
        "latency_ms": summarize_latencies(latencies_ms),
        "by_category": cat_summary,
        "reproduce_cmd": "uv run python -m evals.run_locomo_retrieval",
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
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--with-llm-judge", action="store_true")
    parser.add_argument("--judge-limit", type=int, default=100)
    parser.add_argument("--include-adversarial", action="store_true")
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    quiet_eval_logs()
    args = parse_args(argv)
    report = run_eval(
        dataset_path=args.dataset_path,
        limit=args.limit,
        k=args.k,
        with_llm_judge=args.with_llm_judge,
        judge_limit=args.judge_limit,
        include_adversarial=args.include_adversarial,
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
