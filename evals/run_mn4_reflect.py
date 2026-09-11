"""MN-4 eval runner: bounded cited reflect (offline, deterministic, dry).

Mirrors the MN-1 runner contract: one fresh DB per case; scoring uses
deterministic envelope outcomes only (exact substring membership in the
extractive answer, abstention flags + reasons, error-taxonomy codes) —
never prose similarity. Every reflect envelope is additionally asserted
bounded: ``cost.model_calls == 0`` (dry tier — no paid calls by
construction).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mnemo_core import operations
from mnemo_mcp.db import MemoryDB

CORPUS_PATH = Path(__file__).with_name("mn4_reflect_corpus.json")
REPORT_PATH = Path(__file__).with_name("mn4_reflect_baseline.json")

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
    if name == "reflect":
        return operations.reflect(db, subject, args["query"], k=args.get("k", 5))
    raise ValueError(f"unknown op: {name}")


def _check(expect: dict[str, Any], envelope: dict[str, Any]) -> tuple[bool, str | None]:
    etype = expect["type"]
    if etype == "reflect_answer_contains":
        if not envelope.get("ok"):
            return False, "envelope not ok"
        data = envelope["data"]
        if data["abstained"] is not False:
            return False, "unexpectedly abstained"
        if data["cost"] != _ZERO_COST:
            return False, "non-zero cost receipt in dry tier"
        if not data["citations"]:
            return False, "no citations"
        if data["answer"] not in [c["content"] for c in data["citations"]]:
            return False, "answer is not a citation (extractive contract)"
        return expect["needle"] in (data["answer"] or ""), None
    if etype == "reflect_abstains":
        if not envelope.get("ok"):
            return False, "envelope not ok"
        data = envelope["data"]
        if data["abstained"] is not True:
            return False, "expected abstention"
        if data["reason"] != expect["reason"]:
            return False, f"reason {data['reason']!r} != {expect['reason']!r}"
        if data["answer"] is not None or data["citations"]:
            return False, "abstained envelope must carry no answer/citations"
        if data["cost"] != _ZERO_COST:
            return False, "non-zero cost receipt in dry tier"
        return True, None
    if etype == "error_code":
        return (
            not envelope.get("ok")
            and envelope.get("error", {}).get("code") == expect["code"]
        ), None
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
    report: dict[str, Any] = {
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
    return report


def main() -> int:  # pragma: no cover
    report = run_eval(Path(__file__).parent / "mn4_run")
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["accuracy"] == 1.0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
