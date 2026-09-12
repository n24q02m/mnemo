"""MN-4 paid eval runner: bounded cited reflect through a real provider.

Runs the MN-4 corpus with a live ``BoundedReflectProvider`` (Cohere
command-r7b-12-2024 via the Cloudflare AI Gateway OpenRouter route) and
scores the corpus contract on the PAID path:

- ``reflect_answer_contains``: exactly one model call, complete receipt, and
  the answer must contain the corpus needle (groundedness: the model must
  copy from the notes, not invent);
- ``reflect_abstains``: zero model calls;
- ``error_code``: taxonomy preserved;
- session spend must stay within the hard cap.

Credentials come from the environment (CF_AIG_TOKEN / CF_AIG_BASE per the
mcp-secret-routing manifest; optional OPENROUTER_API_KEY without a gateway).
Set MNEMO_REFLECT_CAP_USD to override the $5.00 default cap.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from mnemo_core import operations
from mnemo_mcp.db import MemoryDB
from mnemo_mcp.providers import BoundedReflectProvider

CORPUS_PATH = Path(__file__).parent / "mn4_reflect_corpus.json"
REPORT_PATH = Path(__file__).parent / "mn4_paid_baseline.json"
MODEL = os.getenv("MNEMO_REFLECT_MODEL", "cohere/command-r7b-12-2024")


def _provider() -> BoundedReflectProvider:
    api_base = os.getenv("CF_AIG_BASE")
    api_key = os.getenv("CF_AIG_TOKEN") or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit(
            "no provider key: set CF_AIG_TOKEN (+CF_AIG_BASE) or OPENROUTER_API_KEY"
        )
    return BoundedReflectProvider(
        model=MODEL,
        api_key=api_key,
        api_base=api_base,
        cap_usd=float(os.getenv("MNEMO_REFLECT_CAP_USD", "5.00")),
    )


def _score(case: dict, envelope: dict) -> tuple[bool, str]:
    """Return (pass, detail) against the corpus expectation."""
    exp = case["expect"]
    exp_type = exp["type"]
    if not envelope["ok"]:
        code = envelope["error"]["code"]
        return (exp_type == "error_code" and code == exp.get("code"), f"error:{code}")
    data = envelope["data"]
    cost = data["cost"]
    if exp_type == "reflect_abstains":
        return (data["abstained"] is True and cost["model_calls"] == 0, "")
    if exp_type == "reflect_answer_contains":
        answer = (data.get("answer") or "").lower()
        good = (
            data["abstained"] is False
            and bool(answer)
            and cost["model_calls"] == 1
            and cost["prompt_tokens"] > 0
            and exp["needle"].lower() in answer
        )
        return (good, "" if good else f"needle missing: {answer[:80]!r}")
    return (False, f"unknown expectation {exp_type}")


def run_eval() -> dict:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    provider = _provider()
    latencies: list[float] = []
    results_out: list[dict] = []
    failed: list[str] = []

    for case in corpus["cases"]:
        with tempfile.TemporaryDirectory() as tmp:
            db = MemoryDB(Path(tmp) / "db.sqlite", embedding_dims=0)
            try:
                for step in case.get("setup", []):
                    if step["op"] == "capture":
                        operations.capture(
                            db,
                            step.get("subject", "alice"),
                            step["args"]["content"],
                            tags=step["args"].get("tags"),
                            category=step["args"].get("category", "general"),
                        )
                probe = case["probe"]
                start = time.perf_counter()
                envelope = operations.reflect(
                    db,
                    probe.get("subject", "alice"),
                    probe["args"]["query"],
                    k=probe["args"].get("k", 5),
                    provider=provider,
                )
                latencies.append(time.perf_counter() - start)
                good, detail = _score(case, envelope)
                if not good:
                    failed.append(f"{case['id']}: {detail}")
                data = envelope.get("data", {})
                results_out.append(
                    {
                        "id": case["id"],
                        "verdict": "pass" if good else "fail",
                        "abstained": data.get("abstained"),
                        "answer_preview": (data.get("answer") or "")[:120],
                        "cost": data.get("cost"),
                        "detail": detail,
                    }
                )
            finally:
                db.close()

    report = {
        "tier": "mn4-paid",
        "model": MODEL,
        "hard_cap_usd": provider.cap_usd,
        "deterministic": True,
        "paid_calls": provider.calls,
        "session_spent_usd": round(provider.spent_usd, 6),
        "accuracy": round(1.0 - len(failed) / max(len(corpus["cases"]), 1), 4),
        "failed_cases": failed,
        "latency_ms": {
            "p50": round(sorted(latencies)[len(latencies) // 2] * 1000, 1)
            if latencies
            else 0,
            "p95": round(
                sorted(latencies)[min(int(len(latencies) * 0.95), len(latencies) - 1)]
                * 1000,
                1,
            )
            if latencies
            else 0,
        },
        "cases": results_out,
    }
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    report = run_eval()
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))
    return 0 if not report["failed_cases"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
