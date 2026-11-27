"""Keyword ranking over decrypted rows, for stores encrypted at rest.

A plaintext store answers keyword queries from its FTS5 index. An encrypted
store keeps that index empty, because an FTS5 index stores every token in
plaintext. Instead, ``MemoryDB`` decrypts the candidate rows in memory and
ranks them here with the same query tiers and the same bm25 formula that
FTS5 uses, so callers see the same result shape and, on the same rows, the
same order.

Query tiers mirror ``mnemo.db._build_fts_queries``:

* one word: the word as a phrase, prefix-matched on its last token;
* several words: all tokens as one exact phrase, then every word
  (prefix-matched) present, then any word present.

The first tier with a hit wins. Ranking is FTS5 bm25 (k1 = 1.2, b = 0.75)
with the ``content`` column weighted 1.0 and ``tags`` weighted 5.0, and the
IDF floored at 1e-6 the way FTS5 floors it.

Known differences from the FTS5 path, all deliberate:

* There is no Porter stemming. A word matches tokens that start with it in
  the prefix tiers and equal tokens in the phrase tier.
* Diacritics are always folded (NFKD, combining marks dropped, case folded).
  FTS5 ``unicode61`` keeps letters that carry two marks, such as Vietnamese
  "ớ", so this path matches a superset of what FTS5 matches.
* The document count, per-term hit counts and average length come from the
  candidate rows that passed the metadata filters, not from the whole
  table. With no filters and no archived or superseded rows the two agree.
* Cost is linear in the number of candidate rows on every query.
"""

from __future__ import annotations

import math
import operator
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

K1 = 1.2
B = 0.75
CONTENT_WEIGHT = 1.0
TAGS_WEIGHT = 5.0
MIN_IDF = 1e-6

_TOKEN_RE = re.compile(r"[^\W_]+")


def fold(text: str) -> str:
    """Lower-case ``text`` and strip every diacritic."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


def tokenize(text: str) -> list[str]:
    """Split ``text`` into folded tokens: runs of letters and digits."""
    return _TOKEN_RE.findall(fold(text))


@dataclass(frozen=True, slots=True)
class Phrase:
    """A token sequence that must appear contiguously within one column."""

    tokens: tuple[str, ...]
    prefix: bool

    def count(self, doc_tokens: Sequence[str]) -> int:
        """Number of positions in ``doc_tokens`` where the phrase starts."""
        size = len(self.tokens)
        last = size - 1
        hits = 0
        for start in range(len(doc_tokens) - size + 1):
            for offset, token in enumerate(self.tokens):
                candidate = doc_tokens[start + offset]
                if offset == last and self.prefix:
                    if not candidate.startswith(token):
                        break
                elif candidate != token:
                    break
            else:
                hits += 1
        return hits


@dataclass(frozen=True, slots=True)
class Tier:
    """One query tier: its phrases and whether every phrase must match."""

    phrases: tuple[Phrase, ...]
    require_all: bool


def build_tiers(query: str) -> list[Tier]:
    """Translate ``query`` into the PHRASE, AND and OR tiers.

    A word that holds no letters or digits contributes no tokens and is
    dropped from the AND and OR tiers, as FTS5 drops an empty phrase.
    """
    words = query.split()
    if not words:
        return []
    terms = [tuple(tokenize(word)) for word in words]
    if len(terms) == 1:
        return [Tier((Phrase(terms[0], prefix=True),), True)] if terms[0] else []

    tiers: list[Tier] = []
    phrase = tuple(token for term in terms for token in term)
    if phrase:
        tiers.append(Tier((Phrase(phrase, prefix=False),), True))
    parts = tuple(Phrase(term, prefix=True) for term in terms if term)
    if parts:
        tiers.append(Tier(parts, True))
        tiers.append(Tier(parts, False))
    return tiers


def rank(
    query: str, docs: Sequence[tuple[str, str]], limit: int
) -> list[tuple[int, float]]:
    """Rank ``docs`` against ``query`` and return the best ``limit`` hits.

    Args:
        query: Free-text query, as passed to ``MemoryDB.search``.
        docs: ``(content, tags)`` pairs of decrypted candidate rows, where
            ``tags`` is the stored JSON text.
        limit: Maximum number of hits returned.

    Returns:
        ``(index into docs, bm25 score)`` pairs, best first. Equal scores
        keep the order of ``docs``. Empty when no tier matches.
    """
    tiers = build_tiers(query)
    if not tiers or not docs or limit < 1:
        return []

    tokenized = [(tokenize(content), tokenize(tags)) for content, tags in docs]
    lengths = [len(content) + len(tags) for content, tags in tokenized]
    total = len(tokenized)
    avgdl = sum(lengths) / total

    for tier in tiers:
        freqs = [
            [
                CONTENT_WEIGHT * phrase.count(content)
                + TAGS_WEIGHT * phrase.count(tags)
                for phrase in tier.phrases
            ]
            for content, tags in tokenized
        ]
        match = all if tier.require_all else any
        hits = [i for i, row in enumerate(freqs) if match(f > 0 for f in row)]
        if not hits:
            continue

        idf = []
        for column in range(len(tier.phrases)):
            n_hit = sum(1 for row in freqs if row[column] > 0)
            value = math.log((total - n_hit + 0.5) / (n_hit + 0.5))
            idf.append(value if value > 0.0 else MIN_IDF)

        scored: list[tuple[int, float]] = []
        for i in hits:
            length = lengths[i]
            score = 0.0
            for column, f in enumerate(freqs[i]):
                score += idf[column] * (
                    (f * (K1 + 1.0)) / (f + K1 * (1 - B + B * length / avgdl))
                )
            scored.append((i, score))
        scored.sort(key=operator.itemgetter(1), reverse=True)
        return scored[:limit]
    return []
