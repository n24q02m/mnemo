"""MN-2 memory defense: deterministic secret/PII scan + redaction.

Dry tier of the memory-defense phase (spec P2): pattern-based detection,
no ML, no network, no environment reads. ``redact`` is applied at
persistence (capture) and again at egress (recall/fetch) so secrets that
reached the store through other paths still never leave it.

Findings carry kind and offsets only — never the matched material.

Overlap rule: a finding contained inside another finding's span (e.g. a
phone-shaped digit run inside a base62 token) is dropped — the outer
secret's replacement removes the inner text anyway, and reporting the
inner span as a separate hit would corrupt span-based redaction and
inflate the false-positive metric this phase exists to measure honestly.
"""

from __future__ import annotations

import re
from typing import Any

# (kind, compiled pattern) — order matters only for reporting, not safety.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_pat", re.compile(r"gh[pousr]_[0-9A-Za-z]{36,255}")),
    ("slack_token", re.compile(r"xox[abprs]-[0-9A-Za-z-]{10,}")),
    ("bearer_token", re.compile(r"(?i)bearer\s+[a-z0-9._-]{20,}")),
    (
        "email",
        re.compile(
            r"(?<![\w.])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.])"
        ),
    ),
    # Bounded by alphanumerics so digit runs inside tokens (PAT bodies,
    # slugs, hex ids) are never misread as Vietnamese phone numbers.
    ("vn_phone", re.compile(r"(?<![0-9A-Za-z])0\d{9}(?![0-9A-Za-z])")),
]


def scan(text: str) -> list[dict[str, Any]]:
    """Return non-overlapping findings; kind + offsets only.

    When spans nest or overlap (inner text also matching a second
    pattern), only the outermost finding survives — deterministic order
    is longest span first, then pattern order.
    """
    raw: list[tuple[int, int, str]] = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            raw.append((match.start(), match.end(), kind))
    # Longest span first at equal start, then pattern order (stable).
    raw.sort(key=lambda f: (f[0], -(f[1] - f[0])))
    findings: list[dict[str, Any]] = []
    last_end = -1
    for start, end, kind in raw:
        if start < last_end:
            continue  # contained in / overlapping a kept finding
        findings.append({"kind": kind, "start": start, "end": end})
        last_end = end
    findings.sort(key=lambda f: (f["start"], f["end"]))
    return findings


def redact(text: str) -> tuple[str, list[str]]:
    """Replace every finding with ``[REDACTED:<kind>]``.

    Returns the redacted text and the ordered list of redacted kinds
    (one entry per replacement). Idempotent: already-redacted markers
    match no pattern.
    """
    findings = scan(text)
    if not findings:
        return text, []
    out: list[str] = []
    kinds: list[str] = []
    cursor = 0
    for finding in findings:
        out.append(text[cursor : finding["start"]])
        out.append(f"[REDACTED:{finding['kind']}]")
        kinds.append(finding["kind"])
        cursor = finding["end"]
    out.append(text[cursor:])
    return "".join(out), kinds
