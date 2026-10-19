"""Phase F - the title helper's counts are a measurement of the sample.

No network and no database: `engine/titles.py` is pure, so these tests pin the
counting rules exactly. The live sample - which listings eBay actually
returned - is evidence recorded in the phase's Shipped block, not a fixture
invented here.
"""

from __future__ import annotations

import re

import pytest

from engine.titles import STOPWORDS, analyse_titles, tokenise


# ---------------------------------------------------------------------------
# 1. Tokenisation
# ---------------------------------------------------------------------------

class TestTokenise:
    def test_lowercases_and_keeps_hyphenated_compounds(self):
        assert tokenise("Garden Hose Anti-Kink 3-Pack") == [
            "garden",
            "hose",
            "anti-kink",
            "3-pack",
        ]

    def test_keeps_model_numbers_and_decimal_sizes(self):
        assert tokenise("Bosch GSB 13 RE 18V 2.5L") == [
            "bosch",
            "gsb",
            "13",
            "re",
            "18v",
            "2.5l",
        ]

    @pytest.mark.parametrize(
        "word",
        ["the", "and", "for", "with", "new", "free", "postage", "uk"],
    )
    def test_listing_glue_is_not_counted(self, word):
        assert word not in tokenise(f"{word} garden hose")

    @pytest.mark.parametrize(
        "word",
        ["set", "kit", "pack", "bundle", "cordless", "brushless"],
    )
    def test_product_words_are_not_stop_words(self, word):
        assert word in tokenise(f"{word} garden hose")
        assert word not in STOPWORDS

    def test_empty_and_non_string_input_yields_no_tokens(self):
        assert tokenise("") == []
        assert tokenise(None) == []
        assert tokenise(123) == []

    def test_punctuation_separates_tokens(self):
        assert tokenise("hose, garden! (expandable)") == [
            "hose",
            "garden",
            "expandable",
        ]


# ---------------------------------------------------------------------------
# 2. Counting: listings, not occurrences
# ---------------------------------------------------------------------------

class TestCounts:
    def test_counts_are_listings_not_occurrences(self):
        result = analyse_titles(["hose hose hose", "garden hose"])

        counts = {row["word"]: row["count"] for row in result["unigrams"]}
        assert result["listings_analysed"] == 2
        assert counts["hose"] == 2
        assert counts["garden"] == 1
        assert all(
            row["count"] <= result["listings_analysed"]
            for row in result["unigrams"]
        )

    def test_bigrams_do_not_cross_listing_boundaries(self):
        result = analyse_titles(["garden hose", "hose garden"])

        pairs = {row["phrase"]: row["count"] for row in result["bigrams"]}
        assert pairs == {"garden hose": 1, "hose garden": 1}
        assert "hose hose" not in pairs

    def test_a_stop_word_is_not_skipped_to_invent_a_pair(self):
        result = analyse_titles(["garden hose for sale"])

        pairs = {row["phrase"] for row in result["bigrams"]}
        assert "garden hose" in pairs
        assert "hose sale" not in pairs

    def test_a_repeated_pair_counts_once_per_listing(self):
        result = analyse_titles(["garden hose garden hose"])

        pairs = {row["phrase"]: row["count"] for row in result["bigrams"]}
        assert pairs["garden hose"] == 1
        assert pairs["hose garden"] == 1

    def test_an_unusable_title_still_counts_towards_the_sample(self):
        result = analyse_titles(["", "the and for", "garden hose"])

        assert result["listings_analysed"] == 3
        words = {row["word"]: row["count"] for row in result["unigrams"]}
        assert words == {"garden": 1, "hose": 1}

    def test_ranking_is_count_then_alphabetical(self):
        result = analyse_titles(["beta alpha", "beta gamma", "beta alpha"])
        assert [row["word"] for row in result["unigrams"]] == [
            "beta",
            "alpha",
            "gamma",
        ]

        ties = analyse_titles(["beta alpha"])
        assert [row["word"] for row in ties["unigrams"]] == ["alpha", "beta"]

    def test_a_single_string_is_one_title_not_a_list_of_characters(self):
        result = analyse_titles("garden hose")

        assert result["listings_analysed"] == 1
        assert [row["word"] for row in result["unigrams"]] == [
            "garden",
            "hose",
        ]

    def test_empty_input_reports_zero_listings(self):
        assert analyse_titles([]) == {
            "listings_analysed": 0,
            "unigrams": [],
            "bigrams": [],
        }


# ---------------------------------------------------------------------------
# 3. The rule that keeps this from becoming a keyword-volume table
# ---------------------------------------------------------------------------

OUTER_FIELDS = {"listings_analysed", "unigrams", "bigrams"}
ROW_FIELDS = {
    "unigrams": {"word", "count"},
    "bigrams": {"phrase", "count"},
}
BANNED = {
    "search_volume",
    "monthly_searches",
    "volume",
    "popularity",
    "demand",
    "demand_index",
    "interest",
    "rank",
    "score",
    "trend",
    "competition",
    "keyword_difficulty",
    "cpc",
    "clicks",
    "watch_count",
    "watchers",
    "sold_count",
    "sales",
    "sales_count",
    "quantity_sold",
    "revenue",
}


def _all_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _all_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_keys(child)


def _normalise(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


class TestNoSearchVolumeCanExist:
    def test_the_output_has_only_the_sample_and_two_count_tables(self):
        result = analyse_titles(["garden hose"])

        assert set(result) == OUTER_FIELDS
        assert set(result["unigrams"][0]) == ROW_FIELDS["unigrams"]
        assert set(result["bigrams"][0]) == ROW_FIELDS["bigrams"]

    def test_no_key_can_be_mistaken_for_a_volume_claim(self):
        result = analyse_titles(["garden hose garden hose"])

        keys = {_normalise(key) for key in _all_keys(result)}
        banned = {_normalise(term) for term in BANNED}
        assert keys.isdisjoint(banned), f"volume-shaped fields: {keys & banned}"

    def test_every_count_is_bounded_by_the_sample_size(self):
        result = analyse_titles(
            ["hose hose", "garden hose", "expandable hose"]
        )

        assert result["listings_analysed"] == 3
        for table in ("unigrams", "bigrams"):
            assert all(
                0 < row["count"] <= result["listings_analysed"]
                for row in result[table]
            )
