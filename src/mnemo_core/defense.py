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

import operator
import re
from typing import Any

# (kind, compiled pattern) — order matters only for reporting, not safety.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_pat", re.compile(r"gh[pousr]_[0-9A-Za-z]{36,255}")),
    (
        "anthropic_key",
        # sk-ant-apiNN- / sk-ant-adminNN- + long base62-ish body. Bounded
        # below at 40 chars so docs placeholders ("sk-ant-api03-YOUR_KEY",
        # bare "sk-ant-api03-") never match.
        re.compile(r"sk-ant-(?:api|admin)\d{2,}-[A-Za-z0-9_-]{40,}"),
    ),
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
    raw.sort(key=operator.itemgetter(1), reverse=True)
    raw.sort(key=operator.itemgetter(0))
    findings: list[dict[str, Any]] = []
    last_end = -1
    for start, end, kind in raw:
        if start < last_end:
            continue  # contained in / overlapping a kept finding
        findings.append({"kind": kind, "start": start, "end": end})
        last_end = end
    findings.sort(key=operator.itemgetter("start", "end"))  # type: ignore[arg-type]
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


# Stage-1 prompt injection and memory poisoning patterns (MNEMO-8).
_INJECTION_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "instruction_override",
        "critical",
        re.compile(
            r"(?i)(?:(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions?|rules?|prompts?)"
            r"|(?:bỏ\s+qua|phớt\s+lờ|quên\s+đi)\s+(?:tất\s+cả\s+|mọi\s+)?(?:chỉ\s+dẫn|hướng\s+dẫn|lệnh|quy\s+tắc)(?:\s+trước|\s+này)?)"
        ),
    ),
    (
        "system_prompt_hijack",
        "critical",
        re.compile(
            r"(?i)(?:new\s+system\s+prompt|you\s+are\s+now\s+(?:in\s+)?developer\s+mode|<\s*\|\s*im_start\s*\|\s*>|\[INST\]|###\s*system\s*:)"
        ),
    ),
    (
        "secret_exfiltration",
        "critical",
        re.compile(
            r"(?i)(?:exfiltrate|reveal\s+(?:the\s+|your\s+)?system\s+prompt|dump\s+all\s+(?:secrets|tokens|keys))"
        ),
    ),
    (
        "hidden_comment_directive",
        "high",
        re.compile(r"(?is)<!--.*?(?:ignore|override|system|execute|exfiltrate).*?-->"),
    ),
]


def scan_prompt_injection(text: str) -> list[dict[str, Any]]:
    """Detect deterministic Stage-1 prompt-injection / memory-poisoning markers."""
    if not text:
        return []
    hits: list[dict[str, Any]] = []
    for kind, severity, pattern in _INJECTION_PATTERNS:
        for match in pattern.finditer(text):
            hits.append(
                {
                    "kind": kind,
                    "severity": severity,
                    "start": match.start(),
                    "end": match.end(),
                }
            )
    hits.sort(key=operator.itemgetter("start", "end"))  # type: ignore[arg-type]
    return hits


def evaluate_poison_risk(
    text: str,
    source: str | None = None,
) -> tuple[bool, float, list[dict[str, Any]]]:
    """Classify trust level for Stage-1 memory-poisoning defense.

    Returns ``(blocked, confidence, findings)``.
    Critical prompt-injection payloads are blocked (``confidence=0.0``).
    Unverified external URL sources receive tempered trust (``confidence=0.7``)
    unless clean, while ordinary memories default to ``confidence=1.0``.
    """
    findings = scan_prompt_injection(text)
    if any(f["severity"] in {"critical", "high"} for f in findings):
        return True, 0.0, findings
    src = (source or "").strip().lower()
    if src.startswith(("http://", "https://")) or src in {
        "web",
        "untrusted",
        "external",
    }:
        return False, 0.7, []
    return False, 1.0, []
