"""MN-2 memory defense: deterministic scan/redact at persistence + egress."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from mnemo_core import operations, results
from mnemo_core.defense import redact, scan
from mnemo_mcp.db import MemoryDB


@pytest.fixture
def store(tmp_path: Path) -> Generator[MemoryDB]:
    db = MemoryDB(tmp_path / "defense.db", embedding_dims=0)
    yield db
    db.close()


SAMPLES = [
    ("aws", "key is AKIAIOSFODNN7EXAMPLE in prod", "[REDACTED:aws_access_key]"),
    (
        "ghpat",
        "token ghp_abcdefghijklmnopqrstuvwxyzabcdefghij leaked",
        "[REDACTED:github_pat]",
    ),
    ("slack", "webhook xoxb-123456789012-abcdef used", "[REDACTED:slack_token]"),
    (
        "bearer",
        "header: Bearer abcdef1234567890abcdef123456",
        "[REDACTED:bearer_token]",
    ),
    ("email", "contact mai.nguyen@example.com for access", "[REDACTED:email]"),
    ("phone", "goi so 0912345678 truoc 5h chieu", "[REDACTED:vn_phone]"),
]


@pytest.mark.parametrize("name,text,marker", SAMPLES, ids=[s[0] for s in SAMPLES])
def test_scan_detects_each_kind(name: str, text: str, marker: str) -> None:
    findings = scan(text)
    assert len(findings) == 1
    assert findings[0]["start"] < findings[0]["end"]


@pytest.mark.parametrize("name,text,marker", SAMPLES, ids=[s[0] for s in SAMPLES])
def test_redact_replaces_with_marker(name: str, text: str, marker: str) -> None:
    out, kinds = redact(text)
    assert marker in out
    assert len(kinds) == 1
    finding = scan(text)[0]
    assert text[finding["start"] : finding["end"]] not in out


def test_redact_is_idempotent() -> None:
    once, kinds = redact("AKIAIOSFODNN7EXAMPLE")
    twice, kinds2 = redact(once)
    assert once == twice
    assert kinds == ["aws_access_key"]
    assert kinds2 == []


def test_benign_content_untouched() -> None:
    benign = "mnemo pilot stores memories in sqlite FTS5; lien he ho tro qua channel"
    out, kinds = redact(benign)
    assert out == benign
    assert kinds == []


def test_capture_redacts_before_persistence(store: MemoryDB) -> None:
    env = operations.capture(store, "alice", "key AKIAIOSFODNN7EXAMPLE in notes")
    assert env["ok"] is True
    assert env["data"]["redactions"] == ["aws_access_key"]
    fetched = operations.fetch(store, "alice", env["data"]["id"])
    assert (
        fetched["data"]["memory"]["content"] == "key [REDACTED:aws_access_key] in notes"
    )


def test_recall_egress_redacts_legacy_rows(store: MemoryDB) -> None:
    """A secret inserted into the store via another path still never leaves."""
    operations.capture(store, "alice", "innocuous note")
    raw = "legacy blob with ghp_abcdefghijklmnopqrstuvwxyzabcdefghij inside"
    store.add(content=raw, category="general")

    env = operations.recall(store, "alice", "legacy blob")
    assert env["ok"] is True
    assert env["data"]["redactions"] == ["github_pat"]
    assert all("ghp_" not in m["content"] for m in env["data"]["matches"])


def test_redaction_never_breaks_error_taxonomy(store: MemoryDB) -> None:
    env = operations.capture(store, "alice", "   ")
    assert env == {
        "ok": False,
        "error": {"code": results.VALIDATION, "message": "content is required"},
    }
    assert (
        operations.fetch(store, "alice", "missing")["error"]["code"]
        == results.NOT_FOUND
    )


def test_overlapping_spans_collapse_to_outermost() -> None:
    """Regression: a digit-bearing PAT must yield ONE finding (outer span).

    The letters-only fixtures elsewhere dodge the overlap; this uses a
    real-shaped base62 secret whose body contains a 0+9-digit run that a
    naive vn_phone pattern would double-fire and corrupt redaction.
    """
    text = "token ghp_abcdefghijklmnopqrstuvwxyz0123456789abcd leaked"
    findings = scan(text)
    assert [f["kind"] for f in findings] == ["github_pat"]
    out, kinds = redact(text)
    assert kinds == ["github_pat"]
    assert out == "token [REDACTED:github_pat] leaked"
    assert "0123456789" not in out


def test_phone_pattern_ignores_token_interiors() -> None:
    assert scan("id0123456789x and ref=0987654321a") == []
    assert scan("call 0912345678 now")[0]["kind"] == "vn_phone"
