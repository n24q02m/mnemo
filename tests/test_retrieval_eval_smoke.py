"""Offline unit smoke tests for LoCoMo-style and LongMemEval-style retrieval.

Separated from the full benchmark runners in ``evals/run_locomo_retrieval.py``
and ``evals/run_longmemeval_retrieval.py`` so CI unit tests always validate
the 4-case synthetic contracts offline in milliseconds without masking real
multi-hundred-query benchmark metrics.
"""

from __future__ import annotations

from pathlib import Path

from mnemo.db import MemoryDB
from mnemo.temporal.resolve import link_entities_with_fastretrieval
from mnemo_core import operations

LONGMEMEVAL_SMOKE_SCENARIOS: list[dict] = [
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


def test_locomo_style_4check_smoke(tmp_path: Path) -> None:
    """4-check LoCoMo-style smoke: timeline ordering, entity dedup, graph, compact."""
    db = MemoryDB(tmp_path / "locomo_smoke.sqlite", embedding_dims=0)
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

        tl_env = operations.timeline(db, subj, entity="Alice")
        gr_env = operations.entity_graph(db, subj, "Alice")
        cmp_env = operations.recall(db, subj, "Alice", k=5, compact=True)

        assert tl_env["ok"] and tl_env["data"]["count"] == 3
        assert [e["id"] for e in tl_env["data"]["entries"]] == [m1, m2, m3]
        assert resolved[0]["id"] == resolved[1]["id"]
        assert gr_env["ok"] and len(gr_env["data"]["entities"]) == 1
        assert len(gr_env["data"]["relations"]) == 1
        assert len(gr_env["data"]["timeline"]) == 3
        assert cmp_env["ok"] and len(cmp_env["data"]["matches"]) >= 1
        assert "snippet" in cmp_env["data"]["matches"][0]
        assert "content" not in cmp_env["data"]["matches"][0]
    finally:
        db.close()


def test_longmemeval_style_4case_smoke(tmp_path: Path) -> None:
    """4-case LongMemEval-style smoke: coref, temporal, bilingual, VI coref."""
    for case in LONGMEMEVAL_SMOKE_SCENARIOS:
        db = MemoryDB(tmp_path / f"{case['id']}.sqlite", embedding_dims=0)
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
            env = operations.recall(
                db,
                case["subject"],
                case["query"],
                k=5,
                context=case.get("context"),
            )
            assert env["ok"] is True
            matches = env["data"]["matches"]
            rank = next(
                (
                    i + 1
                    for i, m in enumerate(matches)
                    if case["expect_substr"] in m["content"]
                ),
                None,
            )
            assert rank is not None, f"{case['id']} missed expected match"
            if case.get("expect_top1"):
                assert rank == 1, f"{case['id']} expected rank 1, got {rank}"
        finally:
            db.close()
