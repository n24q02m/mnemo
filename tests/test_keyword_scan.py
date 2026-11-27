"""Tests for the keyword ranking used by stores encrypted at rest."""

from __future__ import annotations

import json

from mnemo import keyword_scan
from mnemo.keyword_scan import Phrase, Tier, build_tiers, fold, rank, tokenize


def _doc(content: str, tags: list[str] | None = None) -> tuple[str, str]:
    return content, json.dumps(tags or [])


class TestTokenize:
    def test_fold_strips_case_and_marks(self):
        assert fold("Crème BRÛLÉE") == "creme brulee"
        assert fold("Tiếng Việt") == "tieng viet"

    def test_tokens_are_letter_and_digit_runs(self):
        assert tokenize("SQLite-vec_v0.1, hybrid!") == [
            "sqlite",
            "vec",
            "v0",
            "1",
            "hybrid",
        ]
        assert tokenize("--- ...") == []


class TestPhrase:
    def test_exact_and_prefix_counts(self):
        doc = ["alpha", "beta", "alpha", "betamax"]
        assert Phrase(("alpha", "beta"), prefix=False).count(doc) == 1
        assert Phrase(("alpha", "beta"), prefix=True).count(doc) == 2
        assert Phrase(("bet",), prefix=True).count(doc) == 2
        assert Phrase(("bet",), prefix=False).count(doc) == 0

    def test_phrase_longer_than_doc(self):
        assert Phrase(("a", "b", "c"), prefix=False).count(["a", "b"]) == 0


class TestBuildTiers:
    def test_empty_and_symbol_only_queries(self):
        assert build_tiers("") == []
        assert build_tiers("   ") == []
        assert build_tiers("!!!") == []

    def test_single_word_is_one_prefix_phrase(self):
        assert build_tiers("Postgres") == [
            Tier((Phrase(("postgres",), prefix=True),), require_all=True)
        ]

    def test_several_words_give_phrase_and_or_tiers(self):
        phrase, every, some = build_tiers("hybrid search")
        assert phrase == Tier((Phrase(("hybrid", "search"), prefix=False),), True)
        assert every.require_all and not some.require_all
        assert (
            every.phrases
            == some.phrases
            == (
                Phrase(("hybrid",), prefix=True),
                Phrase(("search",), prefix=True),
            )
        )

    def test_symbol_words_are_dropped_from_and_or_tiers(self):
        tiers = build_tiers("alpha !!")
        assert tiers[0].phrases == (Phrase(("alpha",), prefix=False),)
        assert tiers[1].phrases == (Phrase(("alpha",), prefix=True),)

    def test_only_symbol_words_give_no_tiers(self):
        assert build_tiers("!! ??") == []


class TestRank:
    def test_no_tiers_docs_or_limit(self):
        docs = [_doc("alpha")]
        assert rank("", docs, 5) == []
        assert rank("alpha", [], 5) == []
        assert rank("alpha", docs, 0) == []

    def test_no_match_in_any_tier(self):
        assert rank("zeta", [_doc("alpha beta")], 5) == []

    def test_phrase_tier_wins_over_looser_tiers(self):
        docs = [_doc("search hybrid notes"), _doc("hybrid search notes")]
        hits = rank("hybrid search", docs, 5)
        # Only the exact phrase matches in the first tier, so the other row,
        # which only has both words, is not returned at all.
        assert [index for index, _ in hits] == [1]

    def test_and_tier_then_or_tier(self):
        docs = [_doc("hybrid only"), _doc("search hybrid")]
        assert [i for i, _ in rank("hybrid search", docs, 5)] == [1]
        docs = [_doc("hybrid only"), _doc("search only"), _doc("nothing")]
        assert sorted(i for i, _ in rank("hybrid search", docs, 5)) == [0, 1]

    def test_prefix_match_on_last_token(self):
        hits = rank("postg", [_doc("postgres tuning"), _doc("mysql")], 5)
        assert [i for i, _ in hits] == [0]

    def test_tags_weigh_more_than_content(self):
        docs = [_doc("alpha in the body text here"), _doc("other text", ["alpha"])]
        hits = rank("alpha", docs, 5)
        assert [i for i, _ in hits] == [1, 0]
        assert hits[0][1] > hits[1][1] > 0

    def test_limit_and_stable_order_for_ties(self):
        docs = [_doc("alpha"), _doc("alpha"), _doc("alpha")]
        hits = rank("alpha", docs, 2)
        assert [i for i, _ in hits] == [0, 1]
        assert hits[0][1] == hits[1][1]

    def test_idf_floor_keeps_common_terms_positive(self):
        # The term is in every row, so the raw IDF is negative; FTS5 floors it.
        docs = [_doc("alpha beta"), _doc("alpha gamma"), _doc("alpha")]
        hits = rank("alpha", docs, 5)
        assert len(hits) == 3
        assert all(score > 0 for _, score in hits)
        assert all(score < keyword_scan.MIN_IDF * 10 for _, score in hits)

    def test_diacritics_are_folded(self):
        hits = rank("viet", [_doc("Tiếng Việt notes"), _doc("english")], 5)
        assert [i for i, _ in hits] == [0]
