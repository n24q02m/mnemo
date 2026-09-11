"""MN-6 eval: multilingual + public domain corpus must pass fully."""

from __future__ import annotations

import json
from pathlib import Path

from evals.run_mn6_multilingual import CORPUS_PATH, REPORT_PATH, run_eval

EXPECTED_CATEGORIES = {
    "vi_roundtrip",
    "diacritic_folding",
    "vi_reflect",
    "vi_standing",
    "public_domain",
}


def test_corpus_is_wellformed() -> None:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    ids = [c["id"] for c in corpus["cases"]]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    assert {c["category"] for c in corpus["cases"]} == EXPECTED_CATEGORIES
    assert all(c["lang"] == "vi" for c in corpus["cases"])
    gaps = " ".join(corpus["known_gaps"])
    assert "single non-diacritic token" in gaps and "no HTTP/SDK" in gaps


def test_baseline_all_cases_pass(tmp_path: Path) -> None:
    report = run_eval(tmp_path / "run")
    assert report["total_cases"] >= 10
    assert report["failed_cases"] == [], f"failed: {report['failed_cases']}"
    assert report["accuracy"] == 1.0
    assert report["paid_calls"] == 0
    assert report["cost_usd"] == 0.0
    assert report["per_case_stores"] is True


def test_diacritic_gap_is_pinned_not_failed(tmp_path: Path) -> None:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    gap_cases = [c for c in corpus["cases"] if c["category"] == "diacritic_folding"]
    assert len(gap_cases) == 2
    folding = {c["id"]: c["expect"]["type"] for c in gap_cases}
    assert folding["mn6-vi-query-no-diacritics-two-words"] == "contains"
    assert folding["mn6-vi-single-token-no-diacritics"] == "absent_all"
    report = run_eval(tmp_path / "run")
    assert report["accuracy"] == 1.0, "pinned gap must still pass"


def test_determinism_across_runs(tmp_path: Path) -> None:
    first = run_eval(tmp_path / "a")
    second = run_eval(tmp_path / "b")
    assert first["accuracy"] == second["accuracy"]
    assert first["passed"] == second["passed"]
    assert first["failed_cases"] == second["failed_cases"]


def test_main_report_written(tmp_path: Path) -> None:
    report = run_eval(tmp_path / "run")
    out = tmp_path / "mn6_multilingual_baseline.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["deterministic"] is True
    assert saved["known_gaps"]
    assert REPORT_PATH.name == "mn6_multilingual_baseline.json"
