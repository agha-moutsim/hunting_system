"""C14 — the deterministic product matcher: thresholds, vetoes, pHash, and the
computed-match invariants.

C14 — an eBay item and a supplier item are the same product only when THIS
      matcher scores them at or above threshold. Below threshold the pair is
      "no confirmed match" (dropped, C12) or shown as unverified — never
      fudged. match_score is COMPUTED, never a constant; LLM confidence is
      display-only and never a substitute for the matcher.

Regression targets (both found in review, FIXED in backend/engine/match.py):
  * pack quantities were read off the token list, which can never see
    "3 pack" — tokenize drops the bare digit — so a 3-pack eBay listing
    scored attribute-neutral 0.65 -> VERIFIED against a single-unit row.
    Detection now reads the raw title via _QTY_RAW_RE.
  * the price veto called float() directly on caller-supplied prices, so
    ebay_price='£19.99' raised ValueError and ebay_price='0' raised
    ZeroDivisionError while price_plausible() tolerated both. The veto now
    reads the ratio through _price_ratio(), which returns None for
    absent/unparseable input.

ZERO NETWORK — an autouse fixture fails any test that reaches ``requests``.
pHash images are built locally with PIL/numpy from seeded bytes.
"""

import io

import numpy as np
import pytest
from PIL import Image

from engine.match import (
    MATCH_METHOD,
    THRESHOLD_UNVERIFIED,
    THRESHOLD_VERIFIED,
    TIER_NO_MATCH,
    TIER_UNVERIFIED,
    TIER_VERIFIED,
    MatchResult,
    _quantities,
    assign_match,
    attribute_score,
    brand_score,
    compute_match,
    filter_matches,
    passes_threshold,
    passes_verified,
    phash_from_bytes,
    phash_similarity,
    price_plausible,
    score_candidates,
    title_similarity,
    tokenize,
)


# ---------------------------------------------------------------------------
# Offline guarantee
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _zero_network(monkeypatch):
    """The matcher is pure code over bytes — it must never reach the network."""
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("network call attempted — this file runs offline")

    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)
    monkeypatch.setattr(requests.Session, "get", _blocked)
    monkeypatch.setattr(requests.Session, "post", _blocked)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

# Inputs tuned so compute_match lands exactly on each threshold boundary.
# (Components are rounded to 4dp then weighted, so these are exact — see the
# boundary tests below for the component breakdown of each.)
_TITLE_LONG = "Bosch PSB 1800 LI-2 Cordless Combi Drill 18V"
_TITLE_SHORT = "Bosch PSB 1800 LI-2 Cordless Combi Drill"
_UNRELATED_A = "wireless bluetooth speaker with subwoofer"
_UNRELATED_B = "garden hose reel wall mount"
# Threshold-boundary pairs. They MUST share a token: zero overlap triggers
# the "no shared title tokens" veto, which caps the score below any of
# these boundaries by design. Dice is controlled by token count —
# _EDGE_A is 4 tokens, _EDGE_B is 5 (dice 2/9), _EDGE_B_SIX is 6 (2/10).
_EDGE_A = "drill battery case tool"
_EDGE_B = "battery charger unit stand plate"
_EDGE_B_SIX = "battery charger unit stand plate fixture"


def _result_in(tier: str) -> MatchResult:
    """A real compute_match result sitting in the requested tier."""
    if tier == TIER_VERIFIED:
        return compute_match(_TITLE_LONG, _TITLE_LONG, brand="Bosch Professional")
    if tier == TIER_UNVERIFIED:
        return compute_match(_TITLE_LONG, _TITLE_SHORT, brand="Bosch Professional",
                             ebay_price=100.0, candidate_price=151.06)
    return compute_match(_UNRELATED_A, _UNRELATED_B,
                         ebay_price=100.0, candidate_price=130.6)


def _png(seed: int) -> bytes:
    """Deterministic 64x64 RGB PNG built locally — no network, no fixtures."""
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, size=(64, 64, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# A. Thresholds and tiers
# ---------------------------------------------------------------------------

class TestThresholds:
    def test_constants_are_the_c14_numbers(self):
        # C14 — the thresholds themselves are fixed by the constraint.
        assert THRESHOLD_VERIFIED == 0.65
        assert THRESHOLD_UNVERIFIED == 0.45

    def test_score_exactly_0_65_is_verified(self):
        # C14 — boundary inclusive: components {title 1.0, brand 0.0 (partial
        # brand, no veto), attrs 1.0, price 0.0} -> exactly 0.65.
        r = compute_match(_TITLE_LONG, _TITLE_LONG, brand="Bosch Professional")
        assert r.score == 0.65
        assert r.tier == TIER_VERIFIED
        assert r.is_match
        assert not r.dropped

    def test_just_under_0_65_is_unverified(self):
        # C14 — one notch below: 14/15 dice + partial brand + price ratio
        # 1.5106 (below the 1.6x veto) -> 0.6498.
        r = compute_match(_TITLE_LONG, _TITLE_SHORT, brand="Bosch Professional",
                          ebay_price=100.0, candidate_price=151.06)
        assert r.score == pytest.approx(0.6498)
        assert r.score < THRESHOLD_VERIFIED
        assert r.tier == TIER_UNVERIFIED
        assert not r.is_match
        assert not r.dropped

    def test_score_exactly_0_45_is_unverified(self):
        # C14 — the unverified floor is inclusive. Titles that DO share a
        # token (the "no shared title tokens" veto caps the score below
        # this floor by design), with the price knob tuned to land on 0.45
        # exactly: dice 2/9 -> 0.10, plus neutral brand/attributes 0.35.
        r = compute_match(_EDGE_A, _EDGE_B)
        assert r.score == 0.45
        assert r.tier == TIER_UNVERIFIED
        assert not r.dropped
        # Whatever we print is what we judge by — no 0.45 that drops.
        assert r.tier == TIER_UNVERIFIED if r.score >= THRESHOLD_UNVERIFIED else False

    def test_just_under_0_45_is_no_match(self):
        # Same pair with a sixth token (dice 0.20) and a supplier price at
        # 1.576x — inside the implausible band's edge, so no price veto.
        r = compute_match(_EDGE_A, _EDGE_B_SIX,
                          ebay_price=100.0, candidate_price=157.6)
        assert r.score == pytest.approx(0.448)
        assert r.score < THRESHOLD_UNVERIFIED
        assert r.tier == TIER_NO_MATCH
        assert r.dropped
        assert not r.is_match

    @pytest.mark.parametrize("score,verified,thresholded", [
        (0.65, True, True),
        (0.6499, False, True),
        (0.45, False, True),
        (0.4499, False, False),
        (1.0, True, True),
        (0.0, False, False),
    ])
    def test_pass_helpers_track_the_constants(self, score, verified, thresholded):
        assert passes_verified(score) is verified
        assert passes_threshold(score) is thresholded


class TestMatchResultProperties:
    @pytest.mark.parametrize("tier,label", [
        (TIER_VERIFIED, "verified match"),
        (TIER_UNVERIFIED, "not confirmed"),
        # C14 — this wording is fixed by the constraint, verbatim.
        (TIER_NO_MATCH, "no confirmed match"),
    ])
    def test_label_wording(self, tier, label):
        r = _result_in(tier)
        assert r.tier == tier
        assert r.label == label

    @pytest.mark.parametrize("tier,prov,prov_label", [
        (TIER_VERIFIED, "verified", "Verified"),
        (TIER_UNVERIFIED, "unverified", "Unverified"),
        (TIER_NO_MATCH, "unverified", "Unverified"),
    ])
    def test_provenance_is_verified_only_at_the_verified_tier(
            self, tier, prov, prov_label):
        # C14 — never "verified" below threshold.
        r = _result_in(tier)
        assert r.provenance == prov
        assert r.provenance_label == prov_label

    @pytest.mark.parametrize("tier,is_match,dropped", [
        (TIER_VERIFIED, True, False),
        (TIER_UNVERIFIED, False, False),
        (TIER_NO_MATCH, False, True),
    ])
    def test_dropped_and_is_match(self, tier, is_match, dropped):
        r = _result_in(tier)
        assert r.is_match is is_match
        assert r.dropped is dropped

    def test_reason_states_no_confirmed_match_below_threshold(self):
        r = _result_in(TIER_NO_MATCH)
        assert "no confirmed match" in r.reason
        assert "confirmed" not in r.reason.replace("no confirmed match", "")

    def test_reason_names_the_veto_first_when_vetoed(self):
        r = compute_match("Bosch PSB 1800 Cordless Drill", "Makita Something",
                          brand="Bosch")
        assert r.reason.startswith("brand mismatch; ")

    def test_method_is_recorded_on_every_result(self):
        for tier in (TIER_VERIFIED, TIER_UNVERIFIED, TIER_NO_MATCH):
            assert _result_in(tier).method == MATCH_METHOD
            assert "deterministic matcher" in MATCH_METHOD


# ---------------------------------------------------------------------------
# B. Components in isolation
# ---------------------------------------------------------------------------

class TestTokenize:
    @pytest.mark.parametrize("number", ["18v", "500", "dcd778", "1800"])
    def test_numbers_are_kept(self, number):
        # C14 — model numbers and voltages are usually the only signal.
        assert number in tokenize(f"Bosch {number} drill")

    @pytest.mark.parametrize("stop", ["a", "the", "for", "with", "of", "and"])
    def test_stopwords_dropped(self, stop):
        assert stop not in tokenize(f"drill {stop} battery")

    @pytest.mark.parametrize("ch", ["x", "s", "2"])
    def test_single_chars_dropped(self, ch):
        assert ch not in tokenize(f"drill {ch} battery")

    def test_lowercases(self):
        assert tokenize("SONY WH1000XM4") == ["sony", "wh1000xm4"]

    def test_order_preserved(self):
        assert tokenize("Cordless Drill 18V") == ["cordless", "drill", "18v"]

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_empty_input_returns_empty_list(self, raw):
        assert tokenize(raw) == []


class TestTitleSimilarity:
    def test_identical_titles_are_one(self):
        assert title_similarity(_TITLE_LONG, _TITLE_LONG) == 1.0

    def test_disjoint_titles_are_zero(self):
        assert title_similarity("alpha beta gamma", "red blue green") == 0.0

    @pytest.mark.parametrize("a,b", [
        ("", "something"),
        ("something", ""),
        (None, None),
        ("", ""),
    ])
    def test_empty_side_is_zero(self, a, b):
        assert title_similarity(a, b) == 0.0

    def test_shorter_but_correct_supplier_title_still_scores_well(self):
        # Dice over Jaccard: a concise-but-correct listing is not punished.
        sim = title_similarity(_TITLE_LONG, _TITLE_SHORT)
        assert sim == pytest.approx(14 / 15)
        assert sim >= 0.9

    @pytest.mark.parametrize("a,b", [
        (_TITLE_LONG, _TITLE_SHORT),
        ("bosch drill battery", "drill"),
        ("DeWalt 18V XR Combi Drill DCD778",
         "DeWalt DCD778 18V Brushless Combi Drill"),
    ])
    def test_symmetric_in_its_inputs(self, a, b):
        assert title_similarity(a, b) == title_similarity(b, a)


class TestBrandScore:
    def test_matching_brand_is_one(self):
        assert brand_score("Bosch", "Bosch PSB 1800 Combi Drill") == 1.0

    def test_non_matching_brand_is_zero(self):
        assert brand_score("Bosch", "Makita Something") == 0.0

    @pytest.mark.parametrize("brand", ["", None])
    def test_missing_brand_is_neutral_not_penalised(self, brand):
        # C14 — missing evidence must not drag an otherwise identical
        # product below threshold, so absence scores 1.0, not 0.0.
        assert brand_score(brand, "anything at all") == 1.0

    def test_brand_match_is_case_insensitive(self):
        assert brand_score("BOSCH", "bosch drill") == 1.0


class TestAttributeScore:
    def test_all_attributes_preserved_is_one(self):
        t = "Bosch Blue XL 12pack Drill 1800"
        assert attribute_score(t, t) == 1.0

    def test_model_preserved_vs_conflict(self):
        assert attribute_score("Drill DCD778", "DeWalt DCD778 thing") == 1.0
        assert attribute_score("Drill DCD778", "Drill DCD779") == 0.0

    def test_colour_preserved_vs_conflict(self):
        assert attribute_score("Drill Blue", "Drill Blue Case") == 1.0
        assert attribute_score("Drill Blue", "Drill Red Case") == 0.0

    def test_size_preserved_vs_conflict(self):
        assert attribute_score("T-Shirt XL", "T-Shirt XL White") == 1.0
        assert attribute_score("T-Shirt XL", "T-Shirt L White") == 0.0

    @pytest.mark.parametrize("ebay,cand", [
        ("Widget 12pack", "Widget"),
        ("Widget 3 pack", "Widget"),   # regression: the bare digit form
        ("Widget 4x", "Widget"),
        ("Widget x4", "Widget"),
    ])
    def test_quantity_conflict_detected(self, ebay, cand):
        # C14 — pack size is a classic false-match axis; "3 pack" used to
        # escape detection because tokenize drops the bare digit.
        assert attribute_score(ebay, cand) == 0.0

    def test_same_quantity_preserved(self):
        assert attribute_score("Widget 3 pack", "Widget 3 pack") == 1.0

    def test_pack_mismatch_never_reaches_verified_end_to_end(self):
        # C14 — regression: this pair used to score 0.65 (attributes neutral,
        # quantity check never fired) -> VERIFIED against a single-unit row.
        r = compute_match("Widget 3 pack", "Widget")
        assert r.score == 0.45
        assert r.tier == TIER_UNVERIFIED
        assert r.tier != TIER_VERIFIED
        assert not r.is_match

    @pytest.mark.parametrize("ebay,cand", [
        ("Wireless Mouse Ergonomic", "totally different words here"),
        ("plain words only", "other plain wording"),
        ("", "anything"),
    ])
    def test_missing_attributes_are_neutral_one(self, ebay, cand):
        # C14 — missing evidence is neutral (1.0), not a penalty (0.0).
        assert attribute_score(ebay, cand) == 1.0

    @pytest.mark.parametrize("raw,expected", [
        ("Drill 18v", set()),       # a measurement is not a quantity
        ("100mm hole", set()),
        ("5 pack", {5}),
        ("Widget 3 pack", {3}),
        ("Widget 12pack", {12}),
        ("Widget 4x", {4}),
        ("Widget x4", {4}),
    ])
    def test_quantity_extraction_off_the_raw_title(self, raw, expected):
        assert _quantities(raw) == expected


class TestPricePlausible:
    @pytest.mark.parametrize("ebay,supplier", [
        (10.0, 2.0),    # ratio 0.20 — floor of the sane band
        (10.0, 5.0),
        (10.0, 9.99),
        (10.0, 10.0),   # ratio 1.00 — ceiling of the sane band
    ])
    def test_sane_band_scores_full(self, ebay, supplier):
        assert price_plausible(ebay, supplier) == 1.0

    @pytest.mark.parametrize("ebay,supplier", [
        (10.0, 11.0), (10.0, 13.0), (10.0, 15.0),
    ])
    def test_supplier_above_ebay_falls_toward_zero(self, ebay, supplier):
        score = price_plausible(ebay, supplier)
        assert 0.0 <= score < 1.0

    @pytest.mark.parametrize("ebay,supplier", [(10.0, 16.0), (10.0, 17.0)])
    def test_supplier_at_or_past_1_6x_is_zero(self, ebay, supplier):
        assert price_plausible(ebay, supplier) == 0.0

    @pytest.mark.parametrize("ebay,supplier,expected", [
        (10.0, 1.0, pytest.approx(0.5)),
        (10.0, 0.5, pytest.approx(0.25)),
        (10.0, 0.4, pytest.approx(0.2)),
        (10.0, 0.1, pytest.approx(0.05)),
    ])
    def test_absurdly_cheap_falls_toward_zero(self, ebay, supplier, expected):
        assert price_plausible(ebay, supplier) == expected

    def test_plausibility_decreases_monotonically_as_supplier_price_climbs(self):
        values = [price_plausible(10.0, p) for p in (10, 12, 13, 14, 15, 16)]
        assert values == sorted(values, reverse=True)
        assert values[0] == 1.0
        assert values[-1] == 0.0

    @pytest.mark.parametrize("ebay,supplier", [
        (0, 10.0), (10.0, 0), (0.0, 0.0),
        (None, 10.0), (10.0, None),
        ("", 10.0), (10.0, ""),
        ("abc", 5.0), (5.0, "abc"),
        (-5.0, 5.0), (5.0, -5.0),
    ])
    def test_missing_or_unparseable_price_is_never_evidence(self, ebay, supplier):
        # C14 — an unknown price must not confirm a match: 0.0, never 1.0.
        assert price_plausible(ebay, supplier) == 0.0


class TestPhashSimilarity:
    def test_identical_hashes_are_one(self):
        assert phash_similarity(0x1234, 0x1234) == 1.0

    @pytest.mark.parametrize("a,b", [
        (1, None), (None, 1), (None, None),
    ])
    def test_unknown_hash_is_none_not_zero_or_one(self, a, b):
        # C14 — unknown is not evidence either way.
        assert phash_similarity(a, b) is None

    @pytest.mark.parametrize("distance,expected", [
        (0, 1.0),
        (1, 0.96875),
        (4, 0.875),
        (8, 0.75),
        (16, 0.5),
        (32, 0.0),
        (40, 0.0),
        (63, 0.0),
    ])
    def test_known_distance_maps_monotonically(self, distance, expected):
        assert phash_similarity(0, (1 << distance) - 1) == expected

    def test_similarity_strictly_decreases_with_distance(self):
        sims = [phash_similarity(0, (1 << d) - 1) for d in (0, 4, 8, 16, 24)]
        assert sims == sorted(sims, reverse=True)
        assert sims[0] > sims[-1]


# ---------------------------------------------------------------------------
# D. pHash over real bytes
# ---------------------------------------------------------------------------

class TestPhashFromBytes:
    @pytest.mark.parametrize("data", [
        b"", b"not an image", b"<html>nope</html>", b"\x00\x01\x02",
    ])
    def test_unreadable_bytes_return_none_without_raising(self, data):
        assert phash_from_bytes(data) is None

    @pytest.mark.parametrize("seed", [1, 2])
    def test_real_image_returns_a_63_bit_int(self, seed):
        h = phash_from_bytes(_png(seed))
        assert isinstance(h, int)
        assert 0 <= h < 2 ** 63

    def test_hash_is_deterministic_per_image(self):
        assert phash_from_bytes(_png(7)) == phash_from_bytes(_png(7))

    def test_identical_images_have_similarity_one(self):
        a = phash_from_bytes(_png(1))
        b = phash_from_bytes(_png(1))
        assert a is not None and b is not None
        assert phash_similarity(a, b) == 1.0

    def test_visibly_different_images_score_strictly_lower(self):
        a = phash_from_bytes(_png(1))
        b = phash_from_bytes(_png(2))
        assert phash_similarity(a, b) < 1.0


# ---------------------------------------------------------------------------
# C. The three hard vetoes — and the case where they must NOT fire
# ---------------------------------------------------------------------------

class TestVetoes:
    """A veto caps the score below the unverified floor (so the pair is
    'no confirmed match', never merely weak) and names the reason."""

    def test_conflicting_model_number(self):
        # THE C14 case: similar prose, different product.
        r = compute_match(
            "Bosch PSB 1800 LI-2 Cordless Combi Drill 18V",
            "Bosch GSB 18V-50 Cordless Impact Drill",
        )
        assert r.vetoed_by == "conflicting model number"
        assert r.score < THRESHOLD_UNVERIFIED
        assert r.tier == TIER_NO_MATCH
        assert r.tier != TIER_VERIFIED
        assert r.score <= 0.30
        assert r.reason.startswith("conflicting model number; ")

    def test_price_above_1_6x_is_implausible(self):
        r = compute_match("Bosch PSB 1800 Cordless Drill",
                          "Bosch PSB 1800 Cordless Drill",
                          ebay_price=10.0, candidate_price=17.0)
        assert r.vetoed_by == "price makes this pair implausible"
        assert r.score < THRESHOLD_UNVERIFIED
        assert r.tier == TIER_NO_MATCH

    def test_price_below_0_05x_is_implausible(self):
        r = compute_match("Bosch PSB 1800 Cordless Drill",
                          "Bosch PSB 1800 Cordless Drill",
                          ebay_price=100.0, candidate_price=4.0)
        assert r.vetoed_by == "price makes this pair implausible"
        assert r.score < THRESHOLD_UNVERIFIED
        assert r.tier == TIER_NO_MATCH

    def test_brand_mismatch(self):
        r = compute_match("Bosch PSB 1800 Cordless Drill", "Makita Something",
                          brand="Bosch")
        assert r.vetoed_by == "brand mismatch"
        assert r.score < THRESHOLD_UNVERIFIED
        assert r.tier == TIER_NO_MATCH
        assert not r.is_match
        assert r.label == "no confirmed match"
        assert r.provenance == "unverified"

    @pytest.mark.parametrize("ebay,cand,extra,reason", [
        ("Bosch PSB 1800 LI-2 Cordless Combi Drill 18V",
         "Bosch GSB 18V-50 Cordless Impact Drill",
         {}, "conflicting model number"),
        ("Bosch PSB 1800 Cordless Drill", "Bosch PSB 1800 Cordless Drill",
         {"ebay_price": 10.0, "candidate_price": 17.0},
         "price makes this pair implausible"),
        ("Bosch PSB 1800 Cordless Drill", "Bosch PSB 1800 Cordless Drill",
         {"ebay_price": 100.0, "candidate_price": 4.0},
         "price makes this pair implausible"),
        ("Bosch PSB 1800 Cordless Drill", "Makita Something",
         {"brand": "Bosch"}, "brand mismatch"),
        (_UNRELATED_A, _UNRELATED_B, {}, "no shared title tokens"),
    ])
    def test_every_veto_caps_below_the_unverified_floor(
            self, ebay, cand, extra, reason):
        r = compute_match(ebay, cand, **extra)
        assert r.vetoed_by == reason
        assert r.score < THRESHOLD_UNVERIFIED
        assert r.tier == TIER_NO_MATCH
        assert r.dropped
        assert not r.is_match

    def test_no_shared_tokens_cannot_ride_neutral_signals_over_the_floor(self):
        # C14/C12 — the regression this veto exists for. Brand, attributes
        # and price all score 1.0 when there is NOTHING to contradict them,
        # so an unrelated title would otherwise collect 0.45+ purely on the
        # absence of evidence: 0*0.45 + 1*0.15 + 1*0.20 + 1*0.20 = 0.55,
        # comfortably above the 0.45 floor, with zero proof of a match.
        r = compute_match(_UNRELATED_A, _UNRELATED_B,
                          ebay_price=100.0, candidate_price=50.0)
        assert r.components["brand"] == 1.0        # neutral, not a match
        assert r.components["attributes"] == 1.0   # neutral, not a match
        assert r.components["price"] == 1.0        # plausible, not a match
        assert r.components["title"] == 0.0        # nothing in common
        assert r.vetoed_by == "no shared title tokens"
        assert r.score < THRESHOLD_UNVERIFIED
        assert r.dropped

    def test_specific_veto_reason_wins_over_the_overlap_fallback(self):
        # The overlap veto is the LEAST specific reason, so when a brand
        # already explains the failure it must not overwrite it — the
        # reported reason is the actionable one.
        r = compute_match("Bosch PSB 1800 Cordless Drill", "Makita Something",
                          brand="Bosch")
        assert r.vetoed_by == "brand mismatch"

    def test_dewalt_split_across_separator_tokens_still_verifies(self):
        # The non-veto case: "DCD778" must be found even though it sits
        # apart from the brand prefix — this pair MUST stay verified.
        r = compute_match("DeWalt 18V XR Combi Drill DCD778",
                          "DeWalt DCD778 18V Brushless Combi Drill",
                          brand="DeWalt")
        assert r.vetoed_by == ""
        assert r.score >= THRESHOLD_VERIFIED
        assert r.tier == TIER_VERIFIED
        assert r.label == "verified match"

    def test_dewalt_stays_verified_with_a_sane_price_pair(self):
        r = compute_match("DeWalt 18V XR Combi Drill DCD778",
                          "DeWalt DCD778 18V Brushless Combi Drill",
                          brand="DeWalt",
                          ebay_price=49.99, candidate_price=19.99)
        assert r.vetoed_by == ""
        assert r.tier == TIER_VERIFIED

    def test_same_model_does_not_veto(self):
        r = compute_match("Bosch PSB 1800 Combi Drill",
                          "Bosch PSB 1800 Impact Drill", brand="Bosch")
        assert r.vetoed_by == ""
        assert r.tier == TIER_VERIFIED

    def test_brand_present_in_candidate_does_not_veto(self):
        r = compute_match("Bosch PSB 1800 Combi Drill",
                          "Bosch PSB 1800 Combi Drill", brand="Bosch")
        assert r.vetoed_by == ""


class TestUnparseablePricesNeverRaise:
    """Regression (fixed): the price veto used to call float() directly, so
    '£19.99' raised ValueError and '0' raised ZeroDivisionError while
    price_plausible() tolerated both."""

    @pytest.mark.parametrize("bad", ["£19.99", "0", "", None, "abc"])
    def test_bad_ebay_price_scores_normally(self, bad):
        r = compute_match("Same Thing", "Same Thing", ebay_price=bad)
        assert r.score == pytest.approx(0.8)
        assert r.tier == TIER_VERIFIED

    @pytest.mark.parametrize("bad", ["£19.99", "0", "", None, "abc"])
    def test_bad_supplier_price_scores_normally(self, bad):
        r = compute_match("Same Thing", "Same Thing", candidate_price=bad)
        assert r.score == pytest.approx(0.8)
        assert r.tier == TIER_VERIFIED

    @pytest.mark.parametrize("bad", ["£19.99", "0", "", None, "abc"])
    def test_both_sides_bad_scores_normally(self, bad):
        r = compute_match("Same Thing", "Same Thing",
                          ebay_price=bad, candidate_price=bad)
        assert r.score == pytest.approx(0.8)
        assert r.tier == TIER_VERIFIED


# ---------------------------------------------------------------------------
# H. Anti-fabrication guards
# ---------------------------------------------------------------------------

class TestAntiFabrication:
    def test_nothing_supplied_does_not_crash(self):
        r = compute_match("", "")
        assert r.score >= 0.0
        assert not r.is_match

    @pytest.mark.parametrize("ebay,cand", [
        ("Bosch PSB 1800 Cordless Combi Drill", "Premium Cotton Bath Towel Set"),
        ("Sony WH1000XM4 Noise Cancelling Headphones", "Garden Hose Reel 50m"),
        ("", "anything at all"),
    ])
    def test_unrelated_titles_never_verify(self, ebay, cand):
        # brand="", no prices, no image hashes — the weakest possible inputs.
        r = compute_match(ebay, cand)
        assert r.tier != TIER_VERIFIED
        assert not r.is_match

    @pytest.mark.parametrize("ebay,cand", [
        ("Bosch PSB 1800 Cordless Combi Drill", "Premium Cotton Bath Towel Set"),
        ("Sony WH1000XM4 Noise Cancelling Headphones", "Garden Hose Reel 50m"),
        ("", "anything at all"),
    ])
    def test_unrelated_titles_land_below_the_unverified_floor(self, ebay, cand):
        r = compute_match(ebay, cand)
        assert r.score < THRESHOLD_UNVERIFIED
        assert r.tier == TIER_NO_MATCH
        assert r.label == "no confirmed match"


# ---------------------------------------------------------------------------
# E. assign_match — match_score is computed, never a constant (C14)
# ---------------------------------------------------------------------------

class TestAssignMatch:
    @staticmethod
    def _result() -> MatchResult:
        return compute_match("Sony WH1000XM4 Headphones",
                             "Sony WH1000XM4 Wireless Headphones")

    def test_written_score_equals_the_computed_score(self):
        res = self._result()
        row = assign_match({}, res)
        assert row["match_score"] == res.score

    def test_fake_llm_confidence_is_overwritten(self):
        # C14 — LLM confidence is display-only; a row arriving with 0.97
        # must have it replaced by the matcher's own number.
        res = self._result()
        row = {"match_score": 0.97}
        out = assign_match(row, res)
        assert out["match_score"] == res.score
        assert out["match_score"] != 0.97

    def test_basis_method_and_label_are_populated(self):
        res = self._result()
        row = assign_match({}, res)
        assert row["match_basis"] == res.reason
        assert row["match_method"] == MATCH_METHOD
        assert row["match_label"] == res.label
        assert row["match_basis"]
        assert row["match_method"]

    def test_tier_provenance_and_components_written(self):
        res = self._result()
        row = assign_match({}, res)
        assert row["match_tier"] == res.tier
        assert row["match_provenance"] == res.provenance
        assert row["match_components"] == res.components

    def test_components_are_copied_not_shared(self):
        res = self._result()
        row = assign_match({}, res)
        row["match_components"]["title"] = 0.0
        assert res.components["title"] != 0.0

    def test_veto_recorded_only_when_vetoed(self):
        vetoed = assign_match({}, compute_match(
            "Bosch PSB 1800 Cordless Drill", "Makita Something", brand="Bosch"))
        assert vetoed["match_veto"] == "brand mismatch"
        clean = assign_match({}, self._result())
        assert "match_veto" not in clean

    def test_non_dict_row_is_returned_untouched(self):
        assert assign_match("not a dict", self._result()) == "not a dict"


# ---------------------------------------------------------------------------
# F. filter_matches — C12: fewer suppliers is correct
# ---------------------------------------------------------------------------

class TestFilterMatches:
    def test_keeps_rows_at_or_above_threshold_preserving_order(self):
        rows = [
            {"match_score": 0.9, "id": 1},
            {"match_score": 0.7, "id": 2},
            {"match_score": 0.45, "id": 3},   # exactly at the floor: kept
        ]
        assert [r["id"] for r in filter_matches(rows)] == [1, 2, 3]

    @pytest.mark.parametrize("score", [0.4499, 0.2, 0.0, -1.0])
    def test_below_threshold_dropped(self, score):
        rows = [{"match_score": score}, {"match_score": 0.9}]
        assert filter_matches(rows) == [{"match_score": 0.9}]

    def test_row_with_no_match_score_is_dropped(self):
        # C12 — unscanned is not passed: no score means no evidence.
        rows = [{"match_score": 0.9, "id": 1}, {"title": "never scored"}]
        assert filter_matches(rows) == [{"match_score": 0.9, "id": 1}]

    @pytest.mark.parametrize("value", [None, "", "not a number", [], {}])
    def test_unparseable_match_score_dropped_without_raising(self, value):
        rows = [{"match_score": value}, {"match_score": 0.9}]
        assert filter_matches(rows) == [{"match_score": 0.9}]

    def test_non_dict_rows_skipped_without_raising(self):
        rows = ["junk", None, 42, {"match_score": 0.8}]
        assert filter_matches(rows) == [{"match_score": 0.8}]

    @pytest.mark.parametrize("empty", [[], None])
    def test_empty_or_none_input_is_empty(self, empty):
        assert filter_matches(empty) == []

    def test_custom_threshold(self):
        rows = [{"match_score": 0.5}, {"match_score": 0.7}]
        assert filter_matches(rows, threshold=0.65) == [{"match_score": 0.7}]


# ---------------------------------------------------------------------------
# G. score_candidates
# ---------------------------------------------------------------------------

class TestScoreCandidates:
    @staticmethod
    def _candidates():
        return [
            {"title": "Sony WH1000XM4 Wireless Headphones"},
            {"title": "Random Kitchen Gadget Whisk"},
            {"title": "Sony WH1000XM4 Headphones"},
        ]

    def test_returns_every_dict_sorted_by_score_desc(self):
        out = score_candidates("Sony WH1000XM4 Headphones", self._candidates())
        assert len(out) == 3
        scores = [r["match_score"] for r in out]
        assert scores == sorted(scores, reverse=True)

    def test_match_score_is_monotonically_non_increasing(self):
        out = score_candidates("Sony WH1000XM4 Headphones", self._candidates())
        scores = [r["match_score"] for r in out]
        assert all(a >= b for a, b in zip(scores, scores[1:]))

    def test_non_dict_entries_dropped_without_raising(self):
        out = score_candidates("x y z", [
            {"title": "x y z"}, "junk", None, {"title": "x y z"},
        ])
        assert len(out) == 2
        assert all(isinstance(r, dict) for r in out)

    def test_product_title_key_is_read_in_preference_to_title(self):
        out = score_candidates("Bosch Drill", [{
            "product_title": "Bosch Drill", "title": "nonsense words",
        }])
        assert out[0]["match_score"] >= THRESHOLD_VERIFIED

    def test_row_without_any_title_is_still_returned(self):
        out = score_candidates("x", [{"price": 5.0}])
        assert len(out) == 1
        assert out[0]["match_score"] < THRESHOLD_UNVERIFIED
