"""MN-4 eval: reflect corpus must pass fully against the dry pilot core."""

from __future__ import annotations

import json
from pathlib import Path

from evals.run_mn4_reflect import CORPUS_PATH, REPORT_PATH, run_eval

EXPECTED_CATEGORIES = {
    "citation_answer",
    "abstention",
    "subject_scope",
    "redaction_egress",
    "validation",
}


def test_corpus_is_wellformed() -> None:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    ids = [c["id"] for c in corpus["cases"]]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    assert {c["category"] for c in corpus["cases"]} == EXPECTED_CATEGORIES
    langs = {c["lang"] for c in corpus["cases"]}
    assert langs == {"en", "vi"}
    gaps = " ".join(corpus["known_gaps"])
    assert "extractive-only" in gaps and "Spend Gate" in gaps


def test_baseline_all_cases_pass(tmp_path: Path) -> None:
    report = run_eval(tmp_path / "run")
    assert report["accuracy"] == 1.0
    assert report["paid_calls"] == 0
    assert report["cost_usd"] == 0.0
    assert report["per_case_stores"] is True


def test_determinism_across_runs(tmp_path: Path) -> None:
    first = run_eval(tmp_path / "a")
    second = run_eval(tmp_path / "b")
    assert first["accuracy"] == second["accuracy"]
    assert first["passed"] == second["passed"]
    assert first["failed_cases"] == second["failed_cases"]


def test_scoring_detects_failure_by_tampering(tmp_path: Path) -> None:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    for case in corpus["cases"]:
        if case["expect"]["type"] == "reflect_answer_contains":
            case["expect"]["needle"] = "no-such-needle-xyz"
            break
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(corpus), encoding="utf-8")
    report = run_eval(tmp_path / "run", corpus_path=tampered)
    assert report["accuracy"] < 1.0
    assert len(report["failed_cases"]) == 1


def test_main_report_written(tmp_path: Path) -> None:
    report = run_eval(tmp_path / "run")
    out = tmp_path / "mn4_reflect_baseline.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["deterministic"] is True
    assert saved["known_gaps"]
    assert REPORT_PATH.name == "mn4_reflect_baseline.json"
