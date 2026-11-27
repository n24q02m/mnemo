"""Offline unit and artifact-contract tests for W11 benchmark eval runners."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evals import (
    run_locomo_retrieval,
    run_longmemeval_retrieval,
    run_phase2_compression,
)


def _write_mini_locomo(path: Path) -> Path:
    data = [
        {
            "sample_id": "conv-test-1",
            "conversation": {
                "speaker_a": "Alice",
                "speaker_b": "Bob",
                "session_1_date_time": "1:56 pm on 8 May, 2023",
                "session_1": [
                    {
                        "speaker": "Alice",
                        "dia_id": "D1:1",
                        "text": "I moved my studio to Kyoto after leaving Portland.",
                    },
                    {
                        "speaker": "Bob",
                        "dia_id": "D1:2",
                        "text": "Nice, let me know when the kiln arrives next week.",
                    },
                ],
                "session_2_date_time": "10:15 am on 14 June, 2023",
                "session_2": [
                    {
                        "speaker": "Alice",
                        "dia_id": "D2:1",
                        "text": "Today I finished firing the cobalt ceramic vase collection.",
                    },
                ],
            },
            "qa": [
                {
                    "question": "Where did Alice move her studio?",
                    "answer": "Kyoto",
                    "evidence": ["D1:1"],
                    "category": 4,
                },
                {
                    "question": "What did Alice finish firing in June?",
                    "answer": "cobalt ceramic vase collection",
                    "evidence": ["D2:1"],
                    "category": 2,
                },
                {
                    "question": "What secret hobby was never mentioned?",
                    "adversarial_answer": "skydiving",
                    "evidence": ["D1:2"],
                    "category": 5,
                },
            ],
        }
    ]
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _write_mini_longmemeval(path: Path) -> Path:
    data = [
        {
            "question_id": "lme-test-1",
            "question_type": "single-session-user",
            "question": "Which container registry mirror did we configure for cluster west?",
            "answer": "ghcr-west-mirror.internal",
            "haystack_session_ids": ["s1", "s2"],
            "haystack_dates": ["2024/03/01 (Fri) 09:00", "2024/03/02 (Sat) 11:00"],
            "haystack_sessions": [
                [
                    {
                        "role": "user",
                        "content": "We configured ghcr-west-mirror.internal as the registry mirror for cluster west.",
                        "has_answer": True,
                    },
                    {
                        "role": "assistant",
                        "content": "Noted that cluster west pulls via ghcr-west-mirror.internal.",
                        "has_answer": False,
                    },
                ],
                [
                    {
                        "role": "user",
                        "content": "Unrelated reminder about renewing TLS certificates.",
                        "has_answer": False,
                    }
                ],
            ],
            "answer_session_ids": ["s1"],
        },
        {
            "question_id": "lme-test-2_abs",
            "question_type": "single-session-user",
            "question": "What is my favorite color?",
            "answer": "I have no idea.",
            "haystack_session_ids": ["s3"],
            "haystack_dates": ["2024/03/03 (Sun) 10:00"],
            "haystack_sessions": [
                [{"role": "user", "content": "Hello there.", "has_answer": False}]
            ],
            "answer_session_ids": [],
        },
    ]
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _write_mini_phase2(path: Path) -> Path:
    rows = [
        {
            "id": "t-1",
            "subject": "subj-a",
            "turn_index": 1,
            "ground_truth_fact": "Maria Chen set billing-ledger timeout to 420ms under KLV-0101",
            "expected_tokens": ["KLV-0101", "420ms", "Chen"],
            "query": "What timeout did Maria Chen set for billing-ledger under KLV-0101?",
            "context_type": "conversation",
            "category": "operations",
            "content": (
                "Quick sync before standup: after comparing alternatives on staging, "
                "Maria Chen set billing-ledger timeout to 420ms under KLV-0101. "
                "Please mute Slack staging noise after hours."
            ),
        },
        {
            "id": "t-2",
            "subject": "subj-b",
            "turn_index": 2,
            "ground_truth_fact": "David Okafor locked auth-broker port to 8450 under KLV-0201",
            "expected_tokens": ["KLV-0201", "8450", "Okafor"],
            "query": "What port did David Okafor lock for auth-broker under KLV-0201?",
            "context_type": "conversation",
            "category": "architecture",
            "content": (
                "Handoff note for on-call: David Okafor locked auth-broker port "
                "to 8450 under KLV-0201 after validating the blue-green switch."
            ),
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_locomo_runner_deterministic_and_judge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ds = _write_mini_locomo(tmp_path / "locomo.json")
    first = run_locomo_retrieval.run_eval(ds, k=5, work_root=tmp_path)
    second = run_locomo_retrieval.run_eval(ds, k=5, work_root=tmp_path)

    assert first["total_queries"] == 2
    assert first["adversarial_qa_excluded"] == 1
    assert first["recall_at_5"] == 1.0
    assert first["deterministic"] is True
    assert first["paid_calls"] == 0
    assert first["recall_at_5"] == second["recall_at_5"]
    assert first["by_category"].keys() == {"single_hop", "temporal"}

    async def fake_judge(q: str, gold: str, ctxs: list[str]) -> dict[str, Any]:
        return {"passed": bool(ctxs), "model": "fake-judge", "raw": "VERDICT: YES"}

    monkeypatch.setattr(run_locomo_retrieval, "llm_judge_retrieval", fake_judge)
    judged = run_locomo_retrieval.run_eval(
        ds, k=5, with_llm_judge=True, judge_limit=2, work_root=tmp_path
    )
    assert judged["with_llm_judge"] is True
    assert judged["paid_calls"] == 2
    assert judged["llm_judge"]["judge_accuracy"] == 1.0


def test_longmemeval_runner_deterministic_and_judge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ds = _write_mini_longmemeval(tmp_path / "lme.json")
    report = run_longmemeval_retrieval.run_eval(ds, k=5, work_root=tmp_path)

    assert report["total_items"] == 2
    assert report["total_queries"] == 1
    assert report["abstention_cases"] == 1
    assert report["recall_at_1"] == 1.0
    assert report["session_recall_at_5"] == 1.0
    assert report["paid_calls"] == 0

    async def fake_judge(q: str, gold: str, ctxs: list[str]) -> dict[str, Any]:
        return {"passed": True, "model": "fake-judge", "raw": "VERDICT: YES"}

    monkeypatch.setattr(run_longmemeval_retrieval, "llm_judge_retrieval", fake_judge)
    judged = run_longmemeval_retrieval.run_eval(
        ds, k=5, with_llm_judge=True, judge_limit=1, work_root=tmp_path
    )
    assert judged["paid_calls"] == 1
    assert judged["llm_judge"]["judge_pass"] == 1


def test_phase2_runner_0llm_and_mocked_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fx = _write_mini_phase2(tmp_path / "turns.jsonl")
    baseline = run_phase2_compression.run_eval(fx, k=5, work_root=tmp_path)

    assert baseline["total_turns"] == 2
    assert baseline["captured_turns"] == 2
    assert baseline["compressed_turns"] == 0
    assert baseline["capture_compression_ratio"] == 1.0
    assert baseline["fact_retention"] == 1.0
    assert baseline["raw_recall_at_5"] == 1.0
    assert baseline["compact_disclosure_token_ratio"] > 1.0
    assert baseline["paid_calls"] == 0

    import mnemo.compression as compression_mod
    import mnemo.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "cell_configured", lambda cell: cell == "chat")

    class _FakeCell:
        model = "fake-chat-model"

    monkeypatch.setattr(runtime_mod, "model_cell", lambda cell: _FakeCell())

    async def fake_call_llm(prompt: str, **kwargs: Any) -> str:
        if "KLV-0101" in prompt:
            return "Maria Chen set billing-ledger timeout 420ms (KLV-0101)."
        return "David Okafor locked auth-broker port 8450 (KLV-0201)."

    monkeypatch.setattr(compression_mod, "call_llm", fake_call_llm)
    with_llm = run_phase2_compression.run_eval(
        fx, k=5, with_llm=True, work_root=tmp_path
    )
    assert with_llm["mode"] == "llm"
    assert with_llm["compressed_turns"] == 2
    assert with_llm["capture_compression_ratio"] > 1.5
    assert with_llm["fact_retention"] == 1.0
    assert with_llm["raw_recall_at_5"] == 1.0


def test_committed_benchmark_reports_and_fixture_meet_acceptance() -> None:
    root = Path(__file__).resolve().parent.parent

    fixture_lines = [
        line
        for line in (
            root / "tests" / "fixtures" / "compression" / "conversations.jsonl"
        )
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(fixture_lines) == 500

    locomo_report = json.loads(
        (root / "evals" / "locomo_retrieval_report.json").read_text(encoding="utf-8")
    )
    assert locomo_report["total_queries"] >= 100
    assert "locomo10.json" in locomo_report["dataset"]

    lme_report = json.loads(
        (root / "evals" / "longmemeval_retrieval_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert lme_report["total_queries"] >= 100
    assert "longmemeval" in lme_report["dataset"]

    p2_report = json.loads(
        (root / "evals" / "phase2_compression_report.json").read_text(encoding="utf-8")
    )
    assert p2_report["total_turns"] == 500
    assert p2_report["captured_turns"] >= 450
    assert p2_report["capture_latency_ms"]["p95"] > 0.0
    assert p2_report["compact_disclosure_token_ratio"] > 1.0
