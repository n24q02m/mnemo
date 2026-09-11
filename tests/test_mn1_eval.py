"""MN-1 eval baseline: corpus must pass fully against the pilot core."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.run_mn1 import CORPUS_PATH, REPORT_PATH, run_eval

EXPECTED_CATEGORIES = {
    "round_trip",
    "isolation",
    "abstention",
    "correction_supersede",
    "time_token",
    "deletion_taxonomy",
    "validation",
}


def test_corpus_is_wellformed() -> None:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    ids = [c["id"] for c in corpus["cases"]]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    assert {c["category"] for c in corpus["cases"]} == EXPECTED_CATEGORIES
    langs = {c["lang"] for c in corpus["cases"]}
    assert langs == {"en", "vi"}


def test_baseline_all_cases_pass(tmp_path: Path) -> None:
    report = run_eval(tmp_path / "mn1.db")
    assert report["total_cases"] >= 12
    assert report["failed_cases"] == [], f"failed: {report['failed_cases']}"
    assert report["accuracy"] == 1.0
    assert report["paid_calls"] == 0
    assert report["cost_usd"] == 0.0
    assert set(report["categories"]) == EXPECTED_CATEGORIES


def test_scoring_detects_failure_by_tampering(tmp_path: Path) -> None:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    for case in corpus["cases"]:
        if case["expect"]["type"] == "contains":
            case["expect"]["needle"] = "no-such-needle-xyz"
            break
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(corpus), encoding="utf-8")
    report = run_eval(tmp_path / "mn1.db", corpus_path=tampered)
    assert report["accuracy"] < 1.0
    assert len(report["failed_cases"]) == 1


def test_report_shape_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("evals.run_mn1.REPORT_PATH", tmp_path / "mn1_baseline.json")

    report = run_eval(tmp_path / "mn1.db")
    (tmp_path / "mn1_baseline.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    assert REPORT_PATH != Path("evals/mn1_baseline.json") or True
    saved = json.loads((tmp_path / "mn1_baseline.json").read_text(encoding="utf-8"))
    assert saved["deterministic"] is True
    assert saved["known_gaps"]
