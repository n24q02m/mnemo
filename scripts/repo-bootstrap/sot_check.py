"""Project SOT check: required files, line budgets, shared-dump directories.

Modes: warn reports only; gate fails on any finding not frozen in
.sot-baseline.json, and on frozen debt that grew. --freeze records current
debt the first time and afterwards may only shrink it. Stdlib only: this file
is copied byte-identical into the repo-bootstrap runtime.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ("README.md", "AGENTS.md")
LINE_BUDGETS = {"AGENTS.md": 200, "MEMORY.md": 200}
SUSPECT_DIRS = ("utils", "common", "helpers", "core/shared")
CODE_SUFFIXES = {".py", ".ts", ".js", ".go"}
BASELINE_NAME = ".sot-baseline.json"
SKIP_DIRS = {".git", ".claude", "node_modules", ".venv", "dist", "build", "vendor", "target"}


@dataclass(frozen=True)
class Finding:
    key: str
    message: str
    value: int = 0


def _dirs(repo: Path):
    # Prune while walking: rglob would still descend into node_modules and
    # .claude/worktrees (full repo copies) and only filter the results after.
    for root, names, _ in os.walk(repo):
        names[:] = [n for n in names if n not in SKIP_DIRS]
        for name in names:
            path = Path(root, name)
            yield path, path.relative_to(repo).as_posix()


def scan(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    for name in REQUIRED:
        if not (repo / name).is_file():
            findings.append(Finding(f"missing:{name}", f"{name} is required"))
    for name, budget in LINE_BUDGETS.items():
        path = repo / name
        if path.is_file():
            lines = len(path.read_text(encoding="utf-8").splitlines())
            if lines > budget:
                findings.append(Finding(f"budget:{name}", f"{name} has {lines} lines > {budget}", lines))
    for path, rel in _dirs(repo):
        if rel == "core/shared" or rel.endswith("/core/shared") or path.name in SUSPECT_DIRS:
            count = sum(1 for f in path.iterdir() if f.is_file() and f.suffix in CODE_SUFFIXES)
            if count:
                findings.append(Finding(f"suspect:{rel}", f"{rel} holds {count} code files; name the domain instead", count))
    return sorted(findings, key=lambda f: f.key)


def load_baseline(repo: Path) -> dict[str, int] | None:
    path = repo / BASELINE_NAME
    if not path.is_file():
        return None
    return {k: int(v) for k, v in json.loads(path.read_text(encoding="utf-8"))["debt"].items()}


def classify(findings, baseline, mode):
    if mode == "warn":
        return [("WARN", f) for f in findings]
    debt = baseline or {}
    return [("DEBT" if f.key in debt and f.value <= debt[f.key] else "FAIL", f) for f in findings]


def _write_baseline(repo: Path, debt: dict[str, int]) -> None:
    text = json.dumps({"version": 1, "debt": dict(sorted(debt.items()))}, indent=2) + "\n"
    (repo / BASELINE_NAME).write_text(text, encoding="utf-8")


def freeze(repo: Path) -> tuple[int, list[str]]:
    current = {f.key: f.value for f in scan(repo)}
    old = load_baseline(repo)
    if old is None:
        _write_baseline(repo, current)
        return 0, [f"sot: froze {len(current)} findings"]
    new_keys = sorted(set(current) - set(old))
    if new_keys:
        return 1, [f"FAIL freeze cannot add new debt: {k}" for k in new_keys]
    _write_baseline(repo, {k: min(old[k], v) for k, v in current.items()})
    return 0, [f"sot: baseline now {len(current)} findings (was {len(old)})"]


def run(repo: Path, mode: str, do_freeze: bool) -> tuple[int, list[str]]:
    if do_freeze:
        return freeze(repo)
    rows = classify(scan(repo), load_baseline(repo), mode)
    lines = [f"{level} {f.key} {f.message}" for level, f in rows]
    counts = {lvl: sum(1 for level, _ in rows if level == lvl) for lvl in ("FAIL", "DEBT", "WARN")}
    lines.append(f"sot: {counts['FAIL']} fail, {counts['DEBT']} debt, {counts['WARN']} warn")
    return (1 if counts["FAIL"] else 0), lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", type=Path, default=Path("."))
    p.add_argument("--mode", choices=("warn", "gate"), default="warn")
    p.add_argument("--freeze", action="store_true")
    args = p.parse_args(argv)
    code, lines = run(args.repo.resolve(), args.mode, args.freeze)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
