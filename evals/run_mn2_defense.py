"""MN-2 eval: memory defense TP/FP, deterministic, zero paid calls.

True-positive side: each pattern kind must round-trip capture -> fetch
with the secret replaced by its [REDACTED:*] marker, and the raw secret
must not exist anywhere in the store file bytes.
False-positive side: every benign content line of the MN-1 corpus must
produce zero findings — redaction must not corrupt normal memories.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mnemo_core import operations
from mnemo_core.defense import scan
from mnemo_mcp.db import MemoryDB

MN1_CORPUS = Path(__file__).with_name("mn1_corpus.json")
REPORT_PATH = Path(__file__).with_name("mn2_defense_baseline.json")

POSITIVE_CASES = [
    {"id": "tp-aws", "kind": "aws_access_key", "secret": "AKIAIOSFODNN7EXAMPLE"},
    {
        "id": "tp-ghpat",
        "kind": "github_pat",
        "secret": "ghp_abcdefghijklmnopqrstuvwxyzabcdefghij",
    },
    {"id": "tp-slack", "kind": "slack_token", "secret": "xoxb-123456789012-abcdef"},
    {
        "id": "tp-bearer",
        "kind": "bearer_token",
        "secret": "Bearer abcdef1234567890abcdef123456",
    },
    {"id": "tp-email", "kind": "email", "secret": "mai.nguyen@example.com"},
    {"id": "tp-phone", "kind": "vn_phone", "secret": "0912345678"},
]


def _benign_lines() -> list[str]:
    corpus = json.loads(MN1_CORPUS.read_text(encoding="utf-8"))
    lines: list[str] = []
    for case in corpus["cases"]:
        for step in case["setup"]:
            if step["op"] == "capture":
                lines.append(step["args"]["content"])
    return lines


def run_eval(run_dir: Path) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    latencies: list[float] = []

    # --- True positives: round-trip with persistence + egress redaction ---
    tp_passed = 0
    failed: list[str] = []
    for case in POSITIVE_CASES:
        db_path = run_dir / f"{case['id']}.db"
        db = MemoryDB(db_path, embedding_dims=0)
        try:
            t0 = time.perf_counter()
            cap = operations.capture(
                db, "alice", f"please rotate {case['secret']} before friday"
            )
            fetched = operations.fetch(db, "alice", cap["data"]["id"])
            latencies.append((time.perf_counter() - t0) * 1000.0)
        finally:
            db.close()
        ok = (
            cap["data"]["redactions"] == [case["kind"]]
            and fetched["data"]["redactions"] == []
            and case["secret"] not in fetched["data"]["memory"]["content"]
            and f"[REDACTED:{case['kind']}]" in fetched["data"]["memory"]["content"]
        )
        # raw bytes check: the secret must not survive in the store file
        blob = db_path.read_bytes()
        ok = ok and case["secret"].encode() not in blob
        if ok:
            tp_passed += 1
        else:
            failed.append(case["id"])

    # --- False positives: every MN-1 benign line must scan clean ---
    benign = _benign_lines()
    fp_lines = [line for line in benign if scan(line)]
    t0 = time.perf_counter()
    fp_scan = [scan(line) for line in benign]
    probe_ms = (time.perf_counter() - t0) * 1000.0

    total = len(POSITIVE_CASES) + len(benign)
    passed = tp_passed + (len(benign) - len(fp_lines))
    report: dict[str, Any] = {
        "eval": "mn2-defense",
        "deterministic": True,
        "paid_calls": 0,
        "per_case_stores": True,
        "total_cases": total,
        "passed": passed,
        "accuracy": round(passed / total, 4),
        "tp_cases": len(POSITIVE_CASES),
        "tp_passed": tp_passed,
        "fp_cases": len(benign),
        "fp_violations": [
            {"content": line, "findings": [f["kind"] for f in finds]}
            for line, finds in zip(benign, fp_scan, strict=False)
            if finds
        ],
        "probe_latency_ms": round(probe_ms, 3),
        "cost_usd": 0.0,
        "failed_cases": failed,
    }
    return report


def main() -> int:
    report = run_eval(REPORT_PATH.with_suffix(".run"))
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {k: report[k] for k in ("total_cases", "passed", "accuracy", "cost_usd")},
            ensure_ascii=False,
        )
    )
    return 0 if report["failed_cases"] == [] and not report["fp_violations"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
