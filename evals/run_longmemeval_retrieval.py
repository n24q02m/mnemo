"""Zero-LLM LongMemEval-style retrieval harness (deterministic, local SQLite).

Measures Recall@5, MRR@5, coreference resolution hit-rate, and temporal
filtering precision across multi-session histories without any external API.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from mnemo.db import MemoryDB
from mnemo_core import operations

REPORT_PATH = Path(__file__).with_name("longmemeval_retrieval_report.json")

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "lme-coref-project",
        "subject": "s-coref",
        "memories": [
            {
                "content": "FastRetrieval handles hybrid FTS5 and vector search cleanly.",
                "tags": ["arch"],
            },
            {"content": "Grocery list includes apples and oat milk.", "tags": ["life"]},
        ],
        "query": "How does it handle vector search?",
        "context": ["Tell me about FastRetrieval latency."],
        "expect_substr": "FastRetrieval handles hybrid",
    },
    {
        "id": "lme-temporal-latest",
        "subject": "s-temp",
        "memories": [
            {
                "content": "Primary database was SQLite in 2024 prototype.",
                "valid_from": "2024-03-01T00:00:00Z",
            },
            {
                "content": "Primary database migrated to PostgreSQL for cluster scale in 2026.",
                "valid_from": "2026-02-01T00:00:00Z",
            },
        ],
        "query": "Primary database latest status",
        "context": None,
        "expect_substr": "PostgreSQL",
        "expect_top1": True,
    },
    {
        "id": "lme-bilingual-pref",
        "subject": "s-bi",
        "memories": [
            {
                "content": "User cài đặt cấu hình authentication bằng OAuth2 cho MCP server.",
                "tags": ["auth"],
            },
            {"content": "Theme palette uses slate blue accents.", "tags": ["ui"]},
        ],
        "query": "database or authentication setting",
        "context": None,
        "expect_substr": "authentication",
    },
    {
        "id": "lme-vi-coref",
        "subject": "s-vi",
        "memories": [
            {
                "content": "Dịch vụ Mnemo chạy cổng HTTP mặc định và lưu SQLite.",
                "tags": ["mnemo"],
            },
            {"content": "Báo cáo tuần đã gửi cho nhóm.", "tags": ["ops"]},
        ],
        "query": "Nó lưu dữ liệu ở đâu?",
        "context": ["Đang kiểm tra Mnemo service."],
        "expect_substr": "SQLite",
    },
]


def run_eval(work_root: Path | None = None) -> dict[str, Any]:
    latencies_ms: list[float] = []
    hits = 0
    rr_sum = 0.0
    failed: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        base = work_root or Path(tmp)
        base.mkdir(parents=True, exist_ok=True)
        for case in SCENARIOS:
            db_path = base / f"{case['id']}.sqlite"
            if db_path.exists():
                db_path.unlink()
            db = MemoryDB(db_path, embedding_dims=0)
            try:
                for item in case["memories"]:
                    mid = db.add(
                        content=item["content"],
                        tags=item.get("tags"),
                        subject=case["subject"],
                    )
                    if item.get("valid_from"):
                        with db.connection() as conn:
                            conn.execute(
                                "UPDATE memories SET valid_from = ?, created_at = ? WHERE id = ?",
                                (item["valid_from"], item["valid_from"], mid),
                            )
                            conn.commit()
                t0 = time.perf_counter()
                env = operations.recall(
                    db,
                    case["subject"],
                    case["query"],
                    k=5,
                    context=case.get("context"),
                )
                latencies_ms.append((time.perf_counter() - t0) * 1000.0)
                matches = env["data"]["matches"] if env.get("ok") else []
                rank = next(
                    (
                        i + 1
                        for i, m in enumerate(matches)
                        if case["expect_substr"] in m["content"]
                    ),
                    None,
                )
                ok = rank is not None and (not case.get("expect_top1") or rank == 1)
                if ok and rank is not None:
                    hits += 1
                    rr_sum += 1.0 / rank
                else:
                    failed.append(case["id"])
            finally:
                db.close()

    total = len(SCENARIOS)
    lat_sorted = sorted(latencies_ms)
    p95_idx = min(len(lat_sorted) - 1, int(len(lat_sorted) * 0.95))
    return {
        "eval": "longmemeval-retrieval-0llm",
        "deterministic": True,
        "paid_calls": 0,
        "cost_usd": 0.0,
        "total_cases": total,
        "hits_at_5": hits,
        "recall_at_5": round(hits / total, 4),
        "mrr_at_5": round(rr_sum / total, 4),
        "p95_latency_ms": round(lat_sorted[p95_idx], 3),
        "failed_cases": failed,
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        report = run_eval(Path(tmp))
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("total_cases", "recall_at_5", "mrr_at_5", "cost_usd")
            },
            ensure_ascii=False,
        )
    )
    return 0 if not report["failed_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
