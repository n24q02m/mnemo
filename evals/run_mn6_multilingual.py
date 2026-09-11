"""MN-6 eval runner: multilingual + public domain access (dry).

Mirrors the MN-1/4/5 runner contracts: one fresh DB per case;
deterministic scoring (exact substring membership, absence, abstention
flags, staleness verdicts, taxonomy codes). The diacritic-folding
behavior is PINNED as observed from the FTS5 backend, including the
asymmetric single-token gap recorded in ``known_gaps``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mnemo_core import operations, standing
from mnemo_mcp.db import MemoryDB

CORPUS_PATH = Path(__file__).with_name("mn6_multilingual_corpus.json")
REPORT_PATH = Path(__file__).with_name("mn6_multilingual_baseline.json")

_ZERO_COST = {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def _run_op(db: MemoryDB, op: dict[str, Any]) -> dict[str, Any]:
    name, subject, args = op["op"], op["subject"], dict(op.get("args", {}))
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
    if name == "reflect":
        return operations.reflect(db, subject, args["query"], k=args.get("k", 5))
    if name == "standing_refresh":
        return standing.standing_refresh(
            db, subject, args["key"], args["question"], k=args.get("k", 5)
        )
    if name == "standing_read":
        return standing.standing_read(db, subject, args["key"])
    raise ValueError(f"unknown op: {name}")


def _check(expect: dict[str, Any], envelope: dict[str, Any]) -> tuple[bool, str | None]:
    etype = expect["type"]
    if etype == "contains":
        if not envelope.get("ok"):
            return False, "envelope not ok"
        matches = [m["content"] for m in envelope["data"]["matches"]]
        return any(expect["needle"] in c for c in matches), None
    if etype == "absent_all":
        if not envelope.get("ok"):
            return False, "envelope not ok"
        return len(envelope["data"]["matches"]) == 0, None
    if etype == "reflect_answer_contains":
        if not envelope.get("ok"):
            return False, "envelope not ok"
        data = envelope["data"]
        if data["abstained"] is not False or not data["citations"]:
            return False, "unexpected abstention"
        if data["cost"] != _ZERO_COST:
            return False, "non-zero cost receipt"
        return expect["needle"] in (data["answer"] or ""), None
    if etype == "standing_fresh":
        if not envelope.get("ok"):
            return False, "envelope not ok"
        data = envelope["data"]
        if data.get("staleness") != "fresh" or data.get("tombstone"):
            return False, f"state {data.get('staleness')!r}"
        return expect["answer_contains"] in (data.get("answer") or ""), None
    raise ValueError(f"unknown expectation: {etype}")


def run_eval(run_dir: Path, corpus_path: Path = CORPUS_PATH) -> dict[str, Any]:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    run_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for case in corpus["cases"]:
        db = MemoryDB(run_dir / f"{case['id']}.db", embedding_dims=0)
        try:
            for step in case["setup"]:
                env = _run_op(db, step)
                if not env.get("ok"):
                    raise RuntimeError(f"{case['id']}: setup failed: {env}")
            t0 = time.perf_counter()
            envelope = _run_op(db, case["probe"])
            latency_ms = (time.perf_counter() - t0) * 1000.0
        finally:
            db.close()
        passed, why = _check(case["expect"], envelope)
        row: dict[str, Any] = {
            "id": case["id"],
            "lang": case["lang"],
            "passed": passed,
            "latency_ms": latency_ms,
        }
        if why:
            row["why"] = why
        rows.append(row)
    latencies = [r["latency_ms"] for r in rows]
    failed = [r["id"] for r in rows if not r["passed"]]
    return {
        "corpus": corpus["name"],
        "corpus_version": corpus["version"],
        "deterministic": True,
        "paid_calls": 0,
        "cost_usd": 0.0,
        "per_case_stores": True,
        "total_cases": len(rows),
        "passed": len(rows) - len(failed),
        "failed_cases": failed,
        "accuracy": (len(rows) - len(failed)) / len(rows) if rows else 0.0,
        "latency_ms_mean": round(sum(latencies) / len(latencies), 3),
        "latency_ms_p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 3),
        "known_gaps": corpus["known_gaps"],
    }


def main() -> int:  # pragma: no cover
    report = run_eval(Path(__file__).parent / "mn6_run")
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["accuracy"] == 1.0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
