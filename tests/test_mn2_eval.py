"""MN-2 defense eval must stay perfect and honest on every run."""

from __future__ import annotations

from pathlib import Path

from evals.run_mn2_defense import run_eval


def test_mn2_eval_all_pass_with_zero_false_positives(tmp_path: Path) -> None:
    report = run_eval(tmp_path / "run")
    assert report["failed_cases"] == [], f"TP failures: {report['failed_cases']}"
    assert report["fp_violations"] == [], f"FP violations: {report['fp_violations']}"
    assert report["tp_cases"] == 6
    assert report["tp_passed"] == 6
    assert report["fp_cases"] >= 13  # every MN-1 corpus content line
    assert report["accuracy"] == 1.0
    assert report["paid_calls"] == 0
    assert report["cost_usd"] == 0.0
    assert report["deterministic"] is True


def test_mn2_eval_deterministic_across_runs(tmp_path: Path) -> None:
    first = run_eval(tmp_path / "a")
    second = run_eval(tmp_path / "b")
    assert first["passed"] == second["passed"]
    assert first["accuracy"] == second["accuracy"]
    assert first["fp_violations"] == second["fp_violations"]
    assert first["failed_cases"] == second["failed_cases"]
