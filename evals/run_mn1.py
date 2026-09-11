"""MN-1 eval baseline runner (offline, deterministic, zero paid calls).

Runs the ``mn1-eval-baseline`` corpus against the pilot domain core
(``mnemo_core.operations`` over ``MemoryDB`` with ``embedding_dims=0``)
and writes a baseline report JSON next to the corpus.

Scoring is mechanical and honest to the pilot surface: per-case pass/fail
by exact expectation type, plus wall-clock latency around the probe call
and a fixed zero cost (no embedder, no LLM). See the corpus ``known_gaps``
for capabilities deliberately not scored at this phase.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

from mnemo_core import operations
from mnemo_mcp.db import MemoryDB

CORPUS_PATH = Path(__file__).with_name("mn1_corpus.json")
REPORT_PATH = Path(__file__).with_name("mn1_baseline.json")


def _run_op(db: MemoryDB, op: dict[str, Any], ids: dict[str, str]) -> dict[str, Any]:
    """Execute one corpus op; ``id_ref`` substitutes captured ids."""
    name, subject, args = op["op"], op["subject"], dict(op.get("args", {}))
    if "id_ref" in args:
        args["memory_id"] = ids[args["id_ref"]]
    if name == "capture":
        return operations.capture(
            db,
            subject,
            args["content"],
            tags=args.get("tags"),
            category=args.get("category", "general"),
            source=args.get("source"),
        )
    if name == "recall":
        return operations.recall(db, subject, args["query"], k=args.get("k", 5))
    if name == "fetch":
        return operations.fetch(db, subject, args["memory_id"])
    raise ValueError(f"unknown op: {name}")


def _check(expect: dict[str, Any], envelope: dict[str, Any]) -> bool:
    etype = expect["type"]
    if etype == "contains":
        if not envelope.get("ok"):
            return False
        return any(
            expect["needle"] in m["content"] for m in envelope["data"]["matches"]
        )
    if etype == "absent_all":
        if not envelope.get("ok"):
            return False
        return len(envelope["data"]["matches"]) == 0
    if etype == "error_code":
        return (
            not envelope.get("ok")
            and envelope.get("error", {}).get("code") == expect["code"]
        )
    raise ValueError(f"unknown expectation: {etype}")


def run_eval(db_path: Path, corpus_path: Path = CORPUS_PATH) -> dict[str, Any]:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    db = MemoryDB(db_path, embedding_dims=0)
    results_by_cat: dict[str, list[dict[str, Any]]] = {}
    try:
        for case in corpus["cases"]:
            ids: dict[str, str] = {}
            for step in case["setup"]:
                env = _run_op(db, step, ids)
                if not env.get("ok"):
                    raise RuntimeError(f"{case['id']}: setup failed: {env}")
                if step["op"] == "capture":
                    ids[f"{step['subject']}:{step['args']['content']}"] = env["data"][
                        "id"
                    ]
            t0 = time.perf_counter()
            envelope = _run_op(db, case["probe"], ids)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            passed = _check(case["expect"], envelope)
            results_by_cat.setdefault(case["category"], []).append(
                {
                    "id": case["id"],
                    "lang": case["lang"],
                    "passed": passed,
                    "latency_ms": latency_ms,
                }
            )
    finally:
        db.close()

    cases = [c for rows in results_by_cat.values() for c in rows]
    latencies = [c["latency_ms"] for c in cases]
    report: dict[str, Any] = {
        "corpus": corpus["name"],
        "corpus_version": corpus["version"],
        "deterministic": True,
        "paid_calls": 0,
        "total_cases": len(cases),
        "passed": sum(1 for c in cases if c["passed"]),
        "accuracy": round(sum(1 for c in cases if c["passed"]) / len(cases), 4),
        "latency_ms_p50": round(statistics.median(latencies), 3),
        "latency_ms_p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 3),
        "cost_usd": 0.0,
        "known_gaps": corpus["known_gaps"],
        "categories": {
            cat: {
                "cases": len(rows),
                "passed": sum(1 for r in rows if r["passed"]),
                "accuracy": round(sum(1 for r in rows if r["passed"]) / len(rows), 4),
            }
            for cat, rows in sorted(results_by_cat.items())
        },
        "failed_cases": [
            c["id"] for rows in results_by_cat.values() for c in rows if not c["passed"]
        ],
    }
    return report


def main() -> int:
    report = run_eval(REPORT_PATH.with_suffix(".run.db"))
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {k: report[k] for k in ("total_cases", "passed", "accuracy", "cost_usd")},
            ensure_ascii=False,
        )
    )
    return 0 if report["failed_cases"] == [] else 1


if __name__ == "__main__":
    raise SystemExit(main())
