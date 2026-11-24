"""Zero-LLM LoCoMo-style conversational & entity-timeline retrieval eval."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from mnemo.db import MemoryDB
from mnemo.temporal.resolve import link_entities_with_fastretrieval
from mnemo_core import operations

REPORT_PATH = Path(__file__).with_name("locomo_retrieval_report.json")


def run_eval() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        db = MemoryDB(Path(tmp) / "locomo.sqlite", embedding_dims=0)
        try:
            subj = "locomo-u1"
            m1 = operations.capture(
                db, subj, "Alice started leading Platform team in 2025."
            )["data"]["id"]
            m2 = operations.capture(
                db, subj, "Alice transitioned from Platform to AI Infra in 2026."
            )["data"]["id"]
            m3 = operations.capture(
                db, subj, "Alice prefers compact response format during code reviews."
            )["data"]["id"]

            with db.connection() as conn:
                resolved = link_entities_with_fastretrieval(
                    conn,
                    [
                        {"name": "Alice", "type": "person"},
                        {"name": "alice", "type": "person"},
                        {"name": "AI Infra", "type": "project"},
                    ],
                )
                alice_id = resolved[0]["id"]
                infra_id = resolved[2]["id"]
                for mid, ts in (
                    (m1, "2025-02-01T00:00:00Z"),
                    (m2, "2026-01-15T00:00:00Z"),
                    (m3, "2026-03-10T00:00:00Z"),
                ):
                    conn.execute(
                        "UPDATE memories SET valid_from = ?, created_at = ? WHERE id = ?",
                        (ts, ts, mid),
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO memory_entity_links (memory_id, entity_id) VALUES (?, ?)",
                        (mid, alice_id),
                    )
                conn.execute(
                    "INSERT OR IGNORE INTO memory_edges (id, source_id, target_id, relation_type, created_at, memory_id) "
                    "VALUES ('edge-1', ?, ?, 'leads', '2026-01-15T00:00:00Z', ?)",
                    (alice_id, infra_id, m2),
                )
                conn.commit()

            t0 = time.perf_counter()
            tl_env = operations.timeline(db, subj, entity="Alice")
            gr_env = operations.entity_graph(db, subj, "Alice")
            cmp_env = operations.recall(db, subj, "Alice", k=5, compact=True)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            tl_ok = (
                tl_env["ok"]
                and tl_env["data"]["count"] == 3
                and [e["id"] for e in tl_env["data"]["entries"]] == [m1, m2, m3]
            )
            dedup_ok = resolved[0]["id"] == resolved[1]["id"]
            graph_ok = (
                gr_env["ok"]
                and len(gr_env["data"]["entities"]) == 1
                and len(gr_env["data"]["relations"]) == 1
                and len(gr_env["data"]["timeline"]) == 3
            )
            compact_ok = (
                cmp_env["ok"]
                and len(cmp_env["data"]["matches"]) >= 1
                and "snippet" in cmp_env["data"]["matches"][0]
                and "content" not in cmp_env["data"]["matches"][0]
            )
            checks = {
                "timeline_ordering": tl_ok,
                "entity_dedup": dedup_ok,
                "entity_graph": graph_ok,
                "compact_disclosure": compact_ok,
            }
            passed = sum(1 for v in checks.values() if v)
            return {
                "eval": "locomo-retrieval-0llm",
                "deterministic": True,
                "paid_calls": 0,
                "cost_usd": 0.0,
                "total_checks": len(checks),
                "passed": passed,
                "score": round(passed / len(checks), 4),
                "latency_ms": round(elapsed_ms, 3),
                "checks": checks,
            }
        finally:
            db.close()


def main() -> int:
    report = run_eval()
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {k: report[k] for k in ("total_checks", "passed", "score", "cost_usd")},
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] == report["total_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
