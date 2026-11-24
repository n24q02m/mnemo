"""Deterministic bilingual (VI-EN) coreference, query rewrite, and temporal parser.

Zero LLM calls: resolves anaphoric pronouns against caller-supplied session
context, expands known VI<->EN domain synonyms when cross-lingual matching is
needed, and extracts explicit/relative date bounds cleanly without mutating FTS5
single-token diacritic behavior.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

# Deterministic coreference pronouns (lowercased).
_PRONOUNS_EN = frozenset(
    {"it", "its", "that", "this", "they", "them", "their", "he", "him", "she", "her"}
)
_PRONOUNS_VI = (
    "cái đó",
    "việc đó",
    "vấn đề đó",
    "anh ấy",
    "chị ấy",
    "của nó",
    "họ",
    "nó",
)

# Bidirectional technical/memory synonym map (VI <-> EN).
_VI_EN_PAIRS: tuple[tuple[str, str], ...] = (
    ("mật khẩu", "password"),
    ("mat khau", "password"),
    ("cấu hình", "config"),
    ("cau hinh", "config"),
    ("triển khai", "deploy"),
    ("trien khai", "deploy"),
    ("cơ sở dữ liệu", "database"),
    ("co so du lieu", "database"),
    ("bảo mật", "security"),
    ("bao mat", "security"),
    ("hiệu năng", "performance"),
    ("hieu nang", "performance"),
    ("bộ nhớ", "memory"),
    ("tìm kiếm", "search"),
    ("người dùng", "user"),
    ("dự án", "project"),
    ("kế hoạch", "plan"),
    ("máy chủ", "server"),
    ("may chu", "server"),
    ("tài khoản", "account"),
    ("tai khoan", "account"),
    ("quy trình", "workflow"),
    ("kiểm thử", "test"),
    ("lịch họp", "schedule"),
    ("xác thực", "authentication"),
    ("xac thuc", "authentication"),
)

_EN_TO_VI: dict[str, list[str]] = {}
_VI_TO_EN: dict[str, list[str]] = {}
for _vi, _en in _VI_EN_PAIRS:
    _VI_TO_EN.setdefault(_vi, []).append(_en)
    if _en not in _EN_TO_VI:
        _EN_TO_VI[_en] = [_vi]

_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "with",
        "about",
        "what",
        "when",
        "where",
        "who",
        "which",
        "how",
        "why",
        "and",
        "or",
        "not",
        "do",
        "does",
        "did",
        "về",
        "là",
        "của",
        "và",
        "cho",
        "trong",
        "trên",
        "với",
        "tại",
        "khi",
        "nào",
        "gì",
        "sao",
        "ai",
        "đó",
    }
    | _PRONOUNS_EN
)

_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _extract_antecedents(context: list[str] | None) -> list[str]:
    """Extract salient noun/entity tokens from prior context turns."""
    if not context:
        return []
    candidates: list[str] = []
    for turn in reversed(context):
        if not isinstance(turn, str):
            continue
        tokens = re.findall(r"[A-Za-z0-9_.\-/À-ỹ]{2,}", turn)
        scored: list[tuple[int, int, str]] = []
        for idx, tok in enumerate(tokens):
            if tok.lower() in _STOPWORDS:
                continue
            is_camel = any(c.isupper() for c in tok[1:])
            is_ident = "-" in tok or "_" in tok or "/" in tok or "." in tok
            is_mid_proper = idx > 0 and tok[0].isupper()
            if is_camel or is_ident:
                priority = 0
            elif is_mid_proper:
                priority = 1
            elif tok[0].isupper() or len(tok) >= 4:
                priority = 2
            else:
                continue
            scored.append((priority, idx, tok))
        scored.sort(key=lambda item: (item[0], item[1]))
        for _, _, tok in scored[:4]:
            if tok not in candidates:
                candidates.append(tok)
        if len(candidates) >= 4:
            break
    return candidates


def parse_temporal_hint(
    query: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Extract deterministic date bounds and temporal mode from a query."""
    ref = now or datetime.now(UTC)
    low = query.lower()

    m = _ISO_DATE_RE.search(query)
    if m:
        day = m.group(1)
        return {
            "since": f"{day}T00:00:00",
            "until": f"{day}T23:59:59",
            "prefer_recent": False,
            "matched": day,
        }

    if "yesterday" in low or "hôm qua" in low or "hom qua" in low:
        target = (ref - timedelta(days=1)).date().isoformat()
        return {
            "since": f"{target}T00:00:00",
            "until": f"{target}T23:59:59",
            "prefer_recent": False,
            "matched": "yesterday",
        }

    if "today" in low or "hôm nay" in low or "hom nay" in low:
        target = ref.date().isoformat()
        return {
            "since": f"{target}T00:00:00",
            "until": None,
            "prefer_recent": True,
            "matched": "today",
        }

    if "last week" in low or "tuần trước" in low or "tuan truoc" in low:
        start = (ref - timedelta(days=14)).date().isoformat()
        end = (ref - timedelta(days=1)).date().isoformat()
        return {
            "since": f"{start}T00:00:00",
            "until": f"{end}T23:59:59",
            "prefer_recent": True,
            "matched": "last_week",
        }

    if "this week" in low or "tuần này" in low or "last 7 days" in low:
        start = (ref - timedelta(days=7)).date().isoformat()
        return {
            "since": f"{start}T00:00:00",
            "until": None,
            "prefer_recent": True,
            "matched": "last_7_days",
        }

    if "this month" in low or "tháng này" in low:
        start = ref.replace(day=1).date().isoformat()
        return {
            "since": f"{start}T00:00:00",
            "until": None,
            "prefer_recent": True,
            "matched": "this_month",
        }

    if any(
        cue in low
        for cue in ("latest", "recent", "currently", "mới nhất", "gần đây", "hiện tại")
    ):
        return {
            "since": None,
            "until": None,
            "prefer_recent": True,
            "matched": "recent",
        }

    return {"since": None, "until": None, "prefer_recent": False, "matched": None}


def rewrite_query(
    query: str,
    *,
    context: list[str] | None = None,
    expand_bilingual: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Deterministically resolve coreference, extract temporal hints, and collect bilingual queries."""
    cleaned = " ".join(query.split())
    resolved_query = cleaned
    resolved_pronouns: list[str] = []

    antecedents = _extract_antecedents(context)
    if antecedents:
        replacement = " ".join(antecedents[:2])
        for phrase in _PRONOUNS_VI:
            if re.search(
                rf"(?<!\w){re.escape(phrase)}(?!\w)", resolved_query, re.IGNORECASE
            ):
                resolved_query = re.sub(
                    rf"(?<!\w){re.escape(phrase)}(?!\w)",
                    replacement,
                    resolved_query,
                    flags=re.IGNORECASE,
                )
                resolved_pronouns.append(phrase)
        for pro in _PRONOUNS_EN:
            if re.search(rf"\b{re.escape(pro)}\b", resolved_query, re.IGNORECASE):
                resolved_query = re.sub(
                    rf"\b{re.escape(pro)}\b",
                    replacement,
                    resolved_query,
                    flags=re.IGNORECASE,
                )
                resolved_pronouns.append(pro)
        resolved_query = " ".join(resolved_query.split())

    bilingual_queries: list[str] = []
    if expand_bilingual:
        seen_q: set[str] = {resolved_query.lower()}
        base_low = resolved_query.lower()
        for src, targets in {**_VI_TO_EN, **_EN_TO_VI}.items():
            if re.search(rf"(?<!\w){re.escape(src)}(?!\w)", base_low):
                for tgt in targets:
                    alt = re.sub(
                        rf"(?<!\w){re.escape(src)}(?!\w)",
                        tgt,
                        resolved_query,
                        flags=re.IGNORECASE,
                    )
                    alt_norm = " ".join(alt.split())
                    if alt_norm.lower() not in seen_q:
                        seen_q.add(alt_norm.lower())
                        bilingual_queries.append(alt_norm)

    temporal = parse_temporal_hint(resolved_query, now=now)
    return {
        "original": cleaned,
        "resolved": resolved_query,
        "bilingual_alternatives": bilingual_queries,
        "resolved_pronouns": resolved_pronouns,
        "temporal": temporal,
    }
