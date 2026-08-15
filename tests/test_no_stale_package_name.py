"""Không còn tham chiếu tới tên gói cũ ngoài các compatibility exceptions."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# CHANGELOG ghi lại lịch sử; file scanner cũng chứa literal pattern để tự kiểm tra.
ALLOWED = {"CHANGELOG.md", Path(__file__).relative_to(ROOT).as_posix()}

# Tên biến môi trường cũ được đọc có chủ ý để cấu hình người dùng không vỡ.
ALLOWED_LINES = ("QWEN3_EMBED_CACHE_PATH",)


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
        if line
        and not any(line.startswith(f"{name}:") for name in ALLOWED)
        and not any(token in line for token in ALLOWED_LINES)
    ]


def test_no_module_reference_remains():
    hits = _tracked_hits("qwen3_embed")
    assert not hits, "stale module name:\n" + "\n".join(hits)


def test_no_distribution_reference_remains():
    hits = _tracked_hits("qwen3-embed")
    assert not hits, "stale distribution name:\n" + "\n".join(hits)
