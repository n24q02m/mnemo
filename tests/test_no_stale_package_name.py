"""No active references to the retired qwen3-embed package remain."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# CHANGELOG records history; this test file contains the literal patterns.
ALLOWED = {"CHANGELOG.md", Path(__file__).relative_to(ROOT).as_posix()}


def _tracked_hits(pattern: str) -> list[str]:
    result = subprocess.run(
        ["git", "grep", "-n", pattern],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return [
        line
        for line in result.stdout.splitlines()
        if line and not any(line.startswith(f"{name}:") for name in ALLOWED)
    ]


def test_no_module_reference_remains():
    hits = _tracked_hits("qwen3_embed")
    assert not hits, "stale module name:\n" + "\n".join(hits)


def test_no_distribution_reference_remains():
    hits = _tracked_hits("qwen3-embed")
    assert not hits, "stale distribution name:\n" + "\n".join(hits)
