"""MN-5 eval runner: standing questions / knowledge pages (dry).

Mirrors the MN-1/MN-4 runner contracts: one fresh DB per case;
deterministic scoring only (exact substring in the materialized answer,
staleness verdicts, error-taxonomy codes). The ``hard_delete_sources``
setup op removes non-standing rows directly at the SQLite layer to
exercise the missing-source verdict (the pilot tier itself has no
delete op). Every read is bounded by construction: zero model calls.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from mnemo_core import operations, standing
from mnemo_mcp.db import MemoryDB

CORPUS_PATH = Path(__file__).with_name("mn5_standing_corpus.json")
REPORT_PATH = Path(__file__).with_name("mn5_standing_baseline.json")

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
    if name == "standing_refresh":
        return standing.standing_refresh(
            db, subject, args["key"], args["question"], k=args.get("k", 5)
        )
    if name == "standing_invalidate":
        return standing.standing_invalidate(db, subject, args["key"])
    if name == "standing_read":
        return standing.standing_read(db, subject, args["key"])
    if name == "hard_delete_sources":
        conn = sqlite3.connect(db._db_path)  # noqa: SLF001 - eval-only backdoor
        try:
            conn.execute("DELETE FROM memories WHERE category != '_standing'")
            conn.commit()
        finally:
            conn.close()
        return {"ok": True, "data": {}}
    raise ValueError(f"unknown op: {name}")


def _check(expect: dict[str, Any], envelope: dict[str, Any]) -> tuple[bool, str | None]:
    etype = expect["type"]
    if etype == "standing_fresh":
        if not envelope.get("ok"):
            return False, "envelope not ok"
        data = envelope["data"]
        if data.get("tombstone"):
            return False, "unexpected tombstone"
        if data.get("staleness") != "fresh":
            return False, f"staleness {data.get('staleness')!r} != fresh"
        if data.get("cost") != _ZERO_COST:
            return False, "non-zero cost receipt"
        return expect["answer_contains"] in (data.get("answer") or ""), None
    if etype == "standing_stale":
        data = envelope.get("data", {})
        return (
            envelope.get("ok") is True and data.get("staleness") == expect["reason"]
        ), None
    if etype == "standing_tombstone":
        data = envelope.get("data", {})
        return (
            envelope.get("ok") is True
            and data.get("tombstone") is True
            and data.get("staleness") == "invalidated"
            and data.get("cost") == _ZERO_COST
        ), None
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
    report = run_eval(Path(__file__).parent / "mn5_run")
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["accuracy"] == 1.0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
