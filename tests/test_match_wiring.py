"""C14 + C12 + C13 — the deterministic match gate, wired through every consumer.

C14 — an eBay item and a supplier item are the same product only when
      engine/match.py scores them at or above threshold. `match_score` is
      COMPUTED, never a constant and never the LLM's confidence.
        >= 0.65 verified    shown as a confirmed match
        >= 0.45 unverified  shown, labelled "not confirmed", never gates
        <  0.45 no_match    the row MUST be dropped, never displayed
C12 — at most 7 suppliers (config.MAX_SUPPLIERS). A ceiling, never a target:
      two qualifying rows means TWO rows, never seven.
C13 — a missing or unknown value renders as unverified/blank, never verified;
      0.0 shipping_cost is UNKNOWN, not "free".

This file tests the WIRING — the gate as each consumer CALLS it:

  * deep_search._gate_suppliers          (Deep Search full, Deep Search fast / Bulk)
  * analysis_pipeline._score_supplier    (Analyze, URL-hunt)
  * pipeline._match_gate                 (Pipeline / CLI)
  * hunter.supplier_lookup._first_valid  (Category Hunter)

engine/match.py's own units (thresholds, vetoes, pHash, tokenise,
attribute conflicts) are already covered by tests/test_match.py (184 tests)
and are deliberately NOT repeated here; this file only proves each consumer
really routes through the gate and that a dropped row cannot escape.

scrapers/availability.py's parsing units are out of scope too — item 5 here
asserts only that the six P4 fields a scraper produced SURVIVE the pipeline
into the consumer result, and that an unread field stays unread.

ZERO NETWORK — an autouse fixture kills every ``requests`` call; every
collaborator a path can reach is stubbed with monkeypatch, so an unstubbed
call fails loudly instead of reaching eBay.
"""

import csv
import io
import json

import pytest

import analysis_pipeline as ap
import deep_search as ds
import pipeline as pl
from config import MAX_SUPPLIERS
from engine.match import (
    MATCH_METHOD,
    THRESHOLD_UNVERIFIED,
    THRESHOLD_VERIFIED,
    TIER_NO_MATCH,
    TIER_UNVERIFIED,
    TIER_VERIFIED,
    compute_match,
    filter_matches,
)
from hunter.category_scan import CategoryProduct
from hunter.supplier_lookup import _first_valid
from scrapers.base import DemandData, ScrapedProduct
from scrapers.ebay import EbayScraper
from scrapers.ebay_sold import EbaySoldData, EbaySoldItem, EbaySoldScraper

# One product, one reference title. Every fixture below scores against this,
# so the tiers a test asserts are the tiers the matcher computed for it.
REF_TITLE = "Bosch PSB 1800 LI-2 Cordless Combi Drill 18V"
REF_PRICE = 24.99

# A row that scores above the verified floor (same product, sane source price).
TITLE_MATCH = REF_TITLE
# A row that clears the unverified floor but not the verified one: a correct
# product described in words that share only part of the eBay title.
TITLE_WEAK = "Cordless Combi Drill 18V Black"
# A row the matcher must reject — a different product entirely.
TITLE_JUNK = "Cotton Bed Sheet Double Size"
# A different power tool that shares most words and a model number, so the
# veto path (not just the score path) is what rejects it.
TITLE_OTHER_MODEL = "DeWalt DCD778 Cordless Combi Drill 18V"

# C13's four provenance tiers — the only values a stamp may ever carry.
FOUR_TIERS = {"verified", "estimated", "unverified", "ai_insight"}

# The six P4 availability fields scrapers/availability.py produces.
AVAILABILITY_FIELDS = (
    "in_stock", "stock_raw", "availability_url",
    "shipping_cost", "shipping_days", "shipping_raw",
)


# ---------------------------------------------------------------------------
# Offline guarantees
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _zero_network(monkeypatch):
    """C14 scoring is a pure function of two titles — enforce offline here.

    A path that reaches a scraper or a supplier page without its own stub
    dies here instead of quietly issuing a request to eBay."""
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("network call attempted — this file runs offline")

    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)
    monkeypatch.setattr(requests.Session, "get", _blocked)
    monkeypatch.setattr(requests.Session, "post", _blocked)


@pytest.fixture(autouse=True)
def _pristine_range(monkeypatch, tmp_path):
    """Pin the ACTIVE price band to the config defaults (£5-£35) so the
    in-band choices below cannot drift with whoever last edited the UI."""
    import utils.filters as uf

    target = tmp_path / "custom_filters.json"
    target.write_text(json.dumps({"active": {}, "presets": {}}))
    monkeypatch.setattr(uf, "FILTERS_FILE", target)
    uf._cache["mtime"] = None
    uf._cache["data"] = None
    yield
    uf._cache["mtime"] = None
    uf._cache["data"] = None


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

class _Stub:
    """Stand-in for a collaborator method: records the call, then returns
    ``result`` or raises ``error``.

    Patched onto the CLASS it is not a descriptor, so it receives the call
    arguments only (no ``self``) — calls are recorded either way."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


class _FakeAnalyzer:
    """Stand-in for llm.analyzer.ProductAnalyzer — no Ollama, no 45s hang."""

    async def analyze(self, *args, **kwargs):
        return None

    async def close(self):
        return None


class _FakeSupplierScraper:
    """Minimal async supplier scraper for pipeline._search_suppliers."""

    def __init__(self, name, products):
        self._name = name
        self._products = products
        self.calls = []

    async def search(self, query):
        self.calls.append(query)
        return list(self._products)


def _product(title, price=9.99, source="supplier", **kwargs):
    """A ScrapedProduct as a scraper would return it — unscored (C14)."""
    return ScrapedProduct(
        source=source, title=title, price=price,
        url=f"https://supplier.example/{source}", condition="New", **kwargs
    )


def _row(title, price=9.99, name="supplier.example", **kwargs):
    """A Deep Search supplier dict — the shape _gate_suppliers is handed."""
    row = {
        "name": name,
        "full_name": name,
        "price": price,
        "url": f"https://{name}/p/1",
        "supplier_type": "dropshipper",
        "product_title": title,
        "provenance": "verified",
        "provenance_label": "Verified",
        "source_url": f"https://{name}/p/1",
        "source_name": name,
    }
    row.update(kwargs)
    return row


def _titles(kept):
    return [r.get("product_title") or r.get("title") for r in kept]


def _field(row, name):
    """One match field from a dict row (Deep Search) or an attribute row
    (Analyze / Pipeline / Hunter) — the gates write onto both shapes."""
    return row[name] if isinstance(row, dict) else getattr(row, name)


def _assert_scored(row):
    """C14 — the gate every surviving row must clear before it is shown.

    A survivor must carry a computed score with a real tier, a computed
    method and a human-readable basis. None of it may be blank, because blank
    means "never scored" and unscored is not a pass (C12)."""
    score = _field(row, "match_score")
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0
    assert THRESHOLD_UNVERIFIED <= score
    tier = _field(row, "match_tier")
    assert tier in {TIER_VERIFIED, TIER_UNVERIFIED}
    assert tier != TIER_NO_MATCH
    assert _field(row, "match_method") == MATCH_METHOD
    assert _field(row, "match_basis")
    # C13/C14 — where the row shape carries it, the provenance tier may
    # never sit above the match tier.
    if not _has(row, "match_provenance"):
        return  # attribute rows carry no provenance field of their own
    provenance = _field(row, "match_provenance")
    if provenance is not None:
        assert provenance == (
            "verified" if tier == TIER_VERIFIED else "unverified"
        )
        assert provenance != "ai_insight"


def _has(row, name):
    """Whether a row shape carries this key/attribute at all."""
    if isinstance(row, dict):
        return name in row
    return hasattr(row, name)


def _sold_items(n=4):
    return [
        EbaySoldItem(
            title=REF_TITLE, price=REF_PRICE,
            url=f"https://www.ebay.co.uk/itm/{i}", seller=f"store_{i:02d}",
            seller_url="", sold_date="", condition="New",
        )
        for i in range(n)
    ]


def _sold_data():
    """Sold data whose average price is the reference price, so the gate
    scores against a price the matcher can reason about."""
    return EbaySoldData(
        product_name=REF_TITLE, query=REF_TITLE,
        total_sold_30d=42, total_sold_7d=9,
        price_min=15.0, price_max=REF_PRICE, price_avg=REF_PRICE,
        price_median=REF_PRICE, top_sellers=[], items=_sold_items(),
    )


def _ebay_product():
    # seller=None: the store-discovery fallback must not invent a store out
    # of the analysed listing itself.
    return ScrapedProduct(
        source="ebay_uk", title=REF_TITLE, price=REF_PRICE,
        url="https://www.ebay.co.uk/itm/1", condition="New",
        seller=None, verified=True,
    )


def _demand():
    """A DemandData shape the Analyze pipeline can read — real eBay demand,
    so the run reaches Step 3 (suppliers) instead of stopping early."""
    return DemandData(
        sold_count_30d=42, sold_count_7d=9, avg_sold_price=REF_PRICE,
        lowest_sold_price=15.0, highest_sold_price=REF_PRICE,
        verified=True, top_sellers=[],
    )


# ---------------------------------------------------------------------------
# A. Deep Search full — _gate_suppliers as the full path calls it
# ---------------------------------------------------------------------------

class TestDeepSearchFullGate:
    """C14 — the gate the full Deep Search path runs after verification."""

    def test_no_match_row_never_reaches_the_result_and_the_match_survives(self):
        rows = [_row(TITLE_MATCH), _row(TITLE_JUNK), _row(TITLE_WEAK)]

        kept = ds._gate_suppliers(rows, REF_TITLE, ebay_price=REF_PRICE)

        assert TITLE_JUNK not in _titles(kept)
        assert len(kept) == 2
        for row in kept:
            _assert_scored(row)

    def test_a_no_match_row_is_absent_from_the_row_list(self):
        # C14/C12 — the row must be GONE, not carried with a flag a later
        # consumer could ignore. "Shown as absent" is the constraint's wording.
        rows = [_row(TITLE_JUNK), _row(TITLE_JUNK, name="other.example")]

        assert ds._gate_suppliers(rows, REF_TITLE, ebay_price=REF_PRICE) == []

    def test_conflicting_model_number_is_rejected_however_good_it_looks(self):
        # Same drill family, different model number: the veto caps it below
        # the unverified floor, so a near-identical title cannot sneak through.
        rows = [_row(TITLE_OTHER_MODEL, price=9.99)]

        assert ds._gate_suppliers(rows, REF_TITLE, ebay_price=REF_PRICE) == []

    def test_score_is_computed_not_a_constant(self):
        rows = [_row(TITLE_MATCH), _row(TITLE_WEAK), _row("Cordless Combi Drill")]

        kept = ds._gate_suppliers(rows, REF_TITLE, ebay_price=REF_PRICE)

        scores = [r["match_score"] for r in kept]
        # Three different titles, three different computed numbers — a
        # hardcoded constant would collapse these to one value.
        assert len(set(scores)) == len(scores) == 3
        assert all(isinstance(s, float) for s in scores)

    def test_score_matches_compute_match_exactly(self):
        kept = ds._gate_suppliers([_row(TITLE_MATCH), _row(TITLE_WEAK)],
                                  REF_TITLE, ebay_price=REF_PRICE)

        for row in kept:
            expected = compute_match(
                REF_TITLE, row["product_title"],
                ebay_price=REF_PRICE, candidate_price=row["price"],
            )
            assert row["match_score"] == expected.score
            assert row["match_tier"] == expected.tier

    def test_a_pre_seeded_llm_confidence_is_overwritten_not_trusted(self):
        # C14 — nothing upstream may write the score. A row arriving already
        # claiming 0.99 / verified must be re-scored, and must be DROPPED if
        # the matcher disagrees.
        rows = [
            _row(TITLE_JUNK, match_score=0.99, match_tier="verified",
                 match_provenance="verified", match_label="verified match"),
            _row(TITLE_MATCH, match_score=0.01, match_tier="no_match",
                 match_provenance="unverified"),
        ]

        kept = ds._gate_suppliers(rows, REF_TITLE, ebay_price=REF_PRICE)

        assert _titles(kept) == [TITLE_MATCH]
        # The surviving row's own pre-seeded claim was replaced, not kept.
        assert kept[0]["match_score"] == compute_match(
            REF_TITLE, TITLE_MATCH, ebay_price=REF_PRICE, candidate_price=9.99
        ).score
        assert kept[0]["match_score"] > 0.01


# ---------------------------------------------------------------------------
# B. Deep Search full — end to end through deep_search_product
# ---------------------------------------------------------------------------

def _llm_json(**overrides):
    """What the LLM returns. Callers add a fabricated `suppliers` block to
    prove nothing it supplies can become a row."""
    payload = {
        "product_name": REF_TITLE,
        "product_category": "Power Tools",
        "ebay_avg_price": REF_PRICE,
        "brand_name": "",
        "supplier_candidates": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


def _stub_full_path(monkeypatch, verified_rows, llm_json=None):
    """Every collaborator of deep_search_product, offline.

    _verify_supplier_candidates is replaced wholesale: it fetches supplier
    pages, which is a network concern owned by test_provenance.py. What is
    under test here is the gate the fetched rows go through next."""
    monkeypatch.setattr(EbaySoldScraper, "get_sold_data",
                        _Stub(result=_sold_data()))
    monkeypatch.setattr(ds, "_web_search", lambda *a, **k: [])
    monkeypatch.setattr(ds, "_fetch_page_text", lambda *a, **k: "")
    monkeypatch.setattr(ds, "_ollama_generate",
                        lambda *a, **k: llm_json or _llm_json())
    monkeypatch.setattr(ds, "_verify_supplier_candidates",
                        lambda query, cands, deadline=None:
                        [dict(r) for r in verified_rows])
    monkeypatch.setattr(ds.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(EbayScraper, "search", _Stub(result=[]))


class TestDeepSearchFullEndToEnd:
    """C14/C13 — the same gate, driven through the real entry point."""

    def test_no_match_row_cannot_reach_a_deep_search_result(self, monkeypatch):
        _stub_full_path(monkeypatch, [_row(TITLE_MATCH), _row(TITLE_JUNK)])

        result = ds.deep_search_product(REF_TITLE)

        assert TITLE_JUNK not in _titles(result.suppliers)
        assert TITLE_MATCH in _titles(result.suppliers)
        for row in result.suppliers:
            _assert_scored(row)

    def test_an_unverified_match_is_kept_and_labelled_not_confirmed(
            self, monkeypatch):
        _stub_full_path(monkeypatch, [_row(TITLE_WEAK, price=9.99)])

        result = ds.deep_search_product(REF_TITLE)

        assert len(result.suppliers) == 1
        row = result.suppliers[0]
        assert row["match_tier"] == TIER_UNVERIFIED
        assert row["match_label"] == "not confirmed"
        # C13 + C14 — an unconfirmed identity is never stamped verified.
        assert row["match_provenance"] == "unverified"

    def test_a_verified_match_carries_the_verified_tier(self, monkeypatch):
        _stub_full_path(monkeypatch, [_row(TITLE_MATCH)])

        result = ds.deep_search_product(REF_TITLE)

        row = result.suppliers[0]
        # C14 — the tier written onto the row agrees with the score written
        # onto the row; a consumer may read either without finding a
        # contradiction.
        assert row["match_score"] >= THRESHOLD_VERIFIED
        assert row["match_tier"] == TIER_VERIFIED
        assert row["match_provenance"] == "verified"

    def test_llm_supplied_suppliers_never_become_rows(self, monkeypatch):
        # C12/C13/C14 — the model is not a source of supplier rows. A
        # fabricated block, including fabricated match fields, must be
        # discarded rather than scored into the result.
        _stub_full_path(
            monkeypatch,
            [_row(TITLE_MATCH)],
            llm_json=_llm_json(suppliers=[{
                "name": "Totally Invented Wholesale",
                "price": 1.0,
                "url": "https://invented.example/p/1",
                "match_score": 0.99,
                "match_tier": "verified",
                "match_provenance": "verified",
            }]),
        )

        result = ds.deep_search_product(REF_TITLE)

        assert "Totally Invented Wholesale" not in [
            r.get("name") for r in result.suppliers]
        assert all(r["price"] != 1.0 for r in result.suppliers)
        for row in result.suppliers:
            _assert_scored(row)

    def test_an_unconfirmed_match_says_so_in_the_notes(self, monkeypatch):
        # C14 — profit is computed from the cheapest supplier; when that
        # supplier is only an unconfirmed match, the run must say so.
        _stub_full_path(monkeypatch, [_row(TITLE_WEAK, price=9.99)])

        result = ds.deep_search_product(REF_TITLE)

        assert "unconfirmed product match" in result.notes


# ---------------------------------------------------------------------------
# C. Deep Search fast / Bulk — _gate_suppliers as the fast path calls it
# ---------------------------------------------------------------------------

def _stub_fast_path(monkeypatch, per_source):
    """deep_search_fast = the Bulk path: sold data plus three supplier
    scrapes, no LLM, no web search. ``per_source`` maps source name to the
    ScrapedProduct list that source's scraper returns."""
    from scrapers.aliexpress import AliExpressScraper
    from scrapers.amazon_uk import AmazonUKScraper
    from scrapers.cjdropshipping import CJDropshippingScraper

    monkeypatch.setattr(EbaySoldScraper, "get_sold_data",
                        _Stub(result=_sold_data()))

    async def _search(self, query):
        return list(per_source.get(self._source_name(), []))

    for cls, name in ((CJDropshippingScraper, "CJ Dropshipping"),
                      (AliExpressScraper, "AliExpress"),
                      (AmazonUKScraper, "Amazon UK")):
        cls._source_name = staticmethod(lambda name=name: name)
        monkeypatch.setattr(cls, "search", _search)


class TestDeepSearchFastGate:
    """C14/C12 — Bulk runs this path once per line; the gate is not optional."""

    def test_no_match_row_never_reaches_a_bulk_result(self, monkeypatch):
        _stub_fast_path(monkeypatch, {
            "CJ Dropshipping": [
                _product(TITLE_MATCH, source="cjdropshipping"),
                _product(TITLE_JUNK, source="cjdropshipping"),
            ],
        })

        result = ds.deep_search_fast(REF_TITLE)

        assert TITLE_JUNK not in _titles(result.suppliers)
        assert len(result.suppliers) == 1
        for row in result.suppliers:
            _assert_scored(row)

    def test_all_three_suppliers_route_through_the_same_gate(self, monkeypatch):
        _stub_fast_path(monkeypatch, {
            "CJ Dropshipping": [
                _product(TITLE_MATCH, source="cjdropshipping"),
                _product(TITLE_JUNK, source="cjdropshipping"),
            ],
            "AliExpress": [
                _product(TITLE_WEAK, price=9.99, source="aliexpress"),
            ],
            "Amazon UK": [
                _product(TITLE_JUNK, source="amazon_uk"),
            ],
        })

        result = ds.deep_search_fast(REF_TITLE)

        assert sorted(_titles(result.suppliers)) == sorted([TITLE_MATCH, TITLE_WEAK])
        for row in result.suppliers:
            _assert_scored(row)

    def test_best_supplier_price_comes_from_a_scored_row(self, monkeypatch):
        # The cheapest row is only allowed to set the profit input if it
        # cleared the gate — a dropped row must not price the analysis.
        _stub_fast_path(monkeypatch, {
            "CJ Dropshipping": [
                _product(TITLE_JUNK, price=1.0, source="cjdropshipping"),
                _product(TITLE_MATCH, price=9.99, source="cjdropshipping"),
            ],
        })

        result = ds.deep_search_fast(REF_TITLE)

        assert result.best_supplier_price == 9.99

    def test_nothing_qualifying_leaves_no_supplier_and_no_price(self, monkeypatch):
        _stub_fast_path(monkeypatch, {
            "CJ Dropshipping": [
                _product(TITLE_JUNK, price=1.0, source="cjdropshipping"),
            ],
        })

        result = ds.deep_search_fast(REF_TITLE)

        assert result.suppliers == []
        assert result.best_supplier_price == 0.0
        # C13 — no rows means the block reads unverified, and says why.
        stamp = result.field_provenance["suppliers"]
        assert stamp["provenance"] == "unverified"
        assert stamp.get("reason") or stamp.get("method")


# ---------------------------------------------------------------------------
# D. Analyze / URL-hunt — _score_supplier
# ---------------------------------------------------------------------------

class TestAnalyzeSupplierGate:
    """C14 — the per-row gate, plus the C12 cap applied to its output."""

    def test_no_match_row_is_rejected_and_the_match_accepted(self):
        good = _product(TITLE_MATCH)
        junk = _product(TITLE_JUNK)

        assert ap._score_supplier(good, REF_TITLE, REF_PRICE) is True
        assert ap._score_supplier(junk, REF_TITLE, REF_PRICE) is False

    def test_the_rejected_row_is_written_on_before_it_is_dropped(self):
        # C12 — the caller drops on False, so the reason for the drop has to
        # be recorded on the row itself; a silent drop cannot be reviewed.
        junk = _product(TITLE_JUNK)

        ap._score_supplier(junk, REF_TITLE, REF_PRICE)

        assert junk.match_tier == TIER_NO_MATCH
        assert junk.match_label == "no confirmed match"
        assert junk.match_basis
        assert junk.match_method == MATCH_METHOD

    def test_an_unverified_row_is_accepted_but_not_called_confirmed(self):
        row = _product(TITLE_WEAK)

        assert ap._score_supplier(row, REF_TITLE, REF_PRICE) is True
        assert row.match_tier == TIER_UNVERIFIED
        assert row.match_label == "not confirmed"

    def test_score_is_computed_per_row_not_assigned(self):
        rows = [_product(TITLE_MATCH), _product(TITLE_WEAK),
                _product("Cordless Combi Drill")]

        for row in rows:
            ap._score_supplier(row, REF_TITLE, REF_PRICE)

        scores = {r.title: r.match_score for r in rows}
        assert len(set(scores.values())) == 3
        assert scores[TITLE_MATCH] == compute_match(
            REF_TITLE, TITLE_MATCH, ebay_price=REF_PRICE, candidate_price=9.99
        ).score

    def test_brand_is_empty_here_so_the_score_is_title_driven(self):
        # Supplier search runs before the LLM, so no brand is known yet. An
        # unknown brand must score neutrally, not veto the row.
        row = _product(TITLE_MATCH)
        assert row.brand is None

        assert ap._score_supplier(row, REF_TITLE, REF_PRICE) is True
        with_brand = compute_match(
            REF_TITLE, TITLE_MATCH, brand="Bosch",
            ebay_price=REF_PRICE, candidate_price=9.99,
        )
        assert row.match_score == with_brand.score


def _run_analysis(monkeypatch, supplier_rows):
    """Drive run_analysis_pipeline end-to-end with collaborators stubbed.

    Step 1 (eBay product), Step 2 (demand), Step 3 (7 supplier scrapers),
    Step 4 (LLM) and the purchase-history override are replaced; engine code
    (price gate, condition gate, the match gate, verdict) runs for real,
    because that is what the gate has to survive."""
    async def _suppliers(query, progress=None):
        return list(supplier_rows)

    monkeypatch.setattr(ap, "apply_purchase_history",
                        lambda demand, url, db=None: demand)
    monkeypatch.setattr(ap, "search_all_suppliers", _suppliers)
    monkeypatch.setattr(ap, "ProductAnalyzer", _FakeAnalyzer)
    monkeypatch.setattr(EbayScraper, "search", _Stub(result=[_ebay_product()]))
    monkeypatch.setattr(EbayScraper, "get_details", _Stub(result=_ebay_product()))
    monkeypatch.setattr(EbayScraper, "get_sold_data", _Stub(result=_demand()))
    return ap.run_async(ap.run_analysis_pipeline(REF_TITLE, is_url=False))


class TestAnalyzeEndToEnd:
    """C14/C12 — the gate and the cap, through the real Analyze entry point."""

    def test_no_match_row_never_reaches_supplier_matches(self, monkeypatch):
        rows = [_product(TITLE_MATCH, source="cjdropshipping"),
                _product(TITLE_JUNK, source="aliexpress")]

        results = _run_analysis(monkeypatch, rows)

        kept = results["supplier_matches"]
        assert TITLE_JUNK not in [s.title for s in kept]
        assert TITLE_MATCH in [s.title for s in kept]
        for row in kept:
            _assert_scored(row)

    def test_url_hunt_applies_the_same_gate(self, monkeypatch):
        async def _suppliers(query, progress=None):
            return [_product(TITLE_JUNK, source="aliexpress"),
                    _product(TITLE_MATCH, source="amazon_uk")]

        monkeypatch.setattr(ap, "apply_purchase_history",
                            lambda demand, url, db=None: demand)
        monkeypatch.setattr(ap, "search_all_suppliers", _suppliers)
        monkeypatch.setattr(ap, "ProductAnalyzer", _FakeAnalyzer)
        monkeypatch.setattr(EbayScraper, "get_details",
                            _Stub(result=_ebay_product()))
        monkeypatch.setattr(EbayScraper, "get_sold_data", _Stub(result=_demand()))

        results = ap.run_async(ap.run_analysis_pipeline(
            "https://www.ebay.co.uk/itm/1", is_url=True))

        kept = results["supplier_matches"]
        assert TITLE_JUNK not in [s.title for s in kept]
        assert len(kept) == 1
        _assert_scored(kept[0])

    def test_more_than_seven_qualifying_rows_are_capped_at_seven(self, monkeypatch):
        # C12 — nine real matches come back; seven are kept and the two
        # lowest-ranked are cut. A cap that padded would invent rows.
        rows = [_product(TITLE_MATCH, price=9.99 + i, source=f"supplier_{i}")
                for i in range(9)]

        results = _run_analysis(monkeypatch, rows)

        kept = results["supplier_matches"]
        assert len(kept) == MAX_SUPPLIERS == 7
        for row in kept:
            _assert_scored(row)

    def test_the_cap_ranks_by_sourcing_score_not_price_alone(self, monkeypatch):
        # The sourcing policy weighs total cost above match score, so a cheaper
        # unverified row can outrank a dearer verified one. Match strength is
        # still a component and the no-match gate is unchanged.
        rows = [
            _product(TITLE_WEAK, price=5.0, source="cheap_weak"),
            _product(TITLE_MATCH, price=19.99, source="dearer_strong"),
        ]

        results = _run_analysis(monkeypatch, rows)

        kept = results["supplier_matches"]
        assert [s.source for s in kept] == ["cheap_weak", "dearer_strong"]

    def test_two_qualifying_rows_stay_two_and_are_never_padded(self, monkeypatch):
        # C12 — "fewer is correct". The result must be exactly two rows.
        rows = [_product(TITLE_MATCH, source="cjdropshipping"),
                _product(TITLE_WEAK, source="aliexpress"),
                _product(TITLE_JUNK, source="amazon_uk"),
                _product(TITLE_OTHER_MODEL, source="joybuy")]

        results = _run_analysis(monkeypatch, rows)

        kept = results["supplier_matches"]
        assert len(kept) == 2
        assert sorted(s.source for s in kept) == ["aliexpress", "cjdropshipping"]


# ---------------------------------------------------------------------------
# E. Pipeline / CLI — _match_gate and _search_suppliers
# ---------------------------------------------------------------------------

class TestPipelineMatchGate:
    """C14 — the gate the CLI's pipeline runs per scraper."""

    def test_no_match_rows_are_dropped_and_the_match_survives(self):
        good = _product(TITLE_MATCH)
        junk = _product(TITLE_JUNK)

        kept = pl._match_gate([good, junk], REF_TITLE, REF_PRICE)

        assert kept == [good]
        assert good.match_tier == TIER_VERIFIED
        assert good.match_score == compute_match(
            REF_TITLE, TITLE_MATCH, ebay_price=REF_PRICE, candidate_price=9.99
        ).score
        assert junk.match_tier == TIER_NO_MATCH

    def test_zero_and_missing_prices_are_skipped_before_scoring(self):
        # A row with no usable price cannot be a sourcing option at all,
        # matched or not.
        free = _product(TITLE_MATCH, price=0.0)
        none = _product(TITLE_MATCH, price=None)
        good = _product(TITLE_MATCH, price=9.99)

        kept = pl._match_gate([free, none, good], REF_TITLE, REF_PRICE)

        assert kept == [good]

    def test_no_surviving_row_is_left_unscored(self):
        rows = [_product(TITLE_MATCH), _product(TITLE_WEAK),
                _product(TITLE_JUNK), _product(TITLE_OTHER_MODEL)]

        kept = pl._match_gate(rows, REF_TITLE, REF_PRICE)

        assert kept
        for row in kept:
            # "" would mean "never scored", which C12 does not accept as a
            # pass — the gate must leave every row it returns fully stamped.
            assert row.match_tier != ""
            assert row.match_score >= THRESHOLD_UNVERIFIED
            assert row.match_basis and row.match_method == MATCH_METHOD


def _pipeline_with(scrapers):
    """A real Pipeline instance with only its supplier scrapers swapped.

    __new__ skips Pipeline.__init__, which would construct a browser-backed
    eBay scraper, an LLM client and seven Playwright scrapers."""
    instance = pl.Pipeline.__new__(pl.Pipeline)
    instance._supplier_instances = scrapers
    return instance


def _pipeline_result():
    return pl.PipelineResult()


def _run_supplier_search(monkeypatch, per_source):
    instance = _pipeline_with({
        name: _FakeSupplierScraper(name, rows)
        for name, rows in per_source.items()
    })
    result = _pipeline_result()
    out = ap.run_async(instance._search_suppliers(
        REF_TITLE, result,
        reference_title=REF_TITLE, ebay_price=REF_PRICE,
    ))
    flat = [p for rows in out.values() for p in rows]
    return flat, result


class TestPipelineSupplierSearchEndToEnd:
    """C14/C12 — the CLI path: gate per scraper, then one C12 cap across all."""

    def test_no_match_rows_never_reach_the_pipeline_result(self, monkeypatch):
        flat, result = _run_supplier_search(monkeypatch, {
            "cjdropshipping": [_product(TITLE_MATCH, source="cjdropshipping"),
                               _product(TITLE_JUNK, source="cjdropshipping")],
            "aliexpress": [_product(TITLE_JUNK, source="aliexpress")],
            "amazon_uk": [_product(TITLE_MATCH, source="amazon_uk")],
        })

        assert TITLE_JUNK not in [p.title for p in flat]
        assert len(flat) == 2
        assert result.errors == []
        for row in flat:
            assert row.match_tier in {TIER_VERIFIED, TIER_UNVERIFIED}
            assert row.match_score >= THRESHOLD_UNVERIFIED

    def test_a_failing_scraper_does_not_smuggle_an_unscored_row_in(
            self, monkeypatch):
        # A scraper that raises returns no rows at all — the gate must never
        # be bypassed by making the scraper fail.
        class _Boom:
            async def search(self, query):
                raise RuntimeError("scraper exploded")

        instance = _pipeline_with({
            "cjdropshipping": _Boom(),
            "aliexpress": _FakeSupplierScraper(
                "aliexpress", [_product(TITLE_MATCH, source="aliexpress")]),
        })
        result = _pipeline_result()

        out = ap.run_async(instance._search_suppliers(
            REF_TITLE, result,
            reference_title=REF_TITLE, ebay_price=REF_PRICE,
        ))
        flat = [p for rows in out.values() for p in rows]

        assert [p.source for p in flat] == ["aliexpress"]
        assert any("aliexpress" in e or "cjdropshipping" in e
                   for e in result.errors)
        for row in flat:
            assert row.match_tier != ""

    def test_more_than_seven_qualifying_rows_are_capped_at_seven(
            self, monkeypatch):
        flat, _ = _run_supplier_search(monkeypatch, {
            f"supplier_{i}": [
                _product(TITLE_MATCH, price=9.99 + i, source=f"supplier_{i}")
            ]
            for i in range(9)
        })

        assert len(flat) == MAX_SUPPLIERS == 7

    def test_two_qualifying_rows_stay_two_across_every_supplier(
            self, monkeypatch):
        flat, _ = _run_supplier_search(monkeypatch, {
            "cjdropshipping": [_product(TITLE_MATCH, source="cjdropshipping"),
                               _product(TITLE_JUNK, source="cjdropshipping")],
            "aliexpress": [_product(TITLE_WEAK, source="aliexpress")],
            "amazon_uk": [_product(TITLE_JUNK, source="amazon_uk")],
        })

        assert len(flat) == 2
        assert sorted(p.source for p in flat) == ["aliexpress", "cjdropshipping"]

    def test_nothing_qualifying_gives_no_rows_at_all(self, monkeypatch):
        flat, _ = _run_supplier_search(monkeypatch, {
            "cjdropshipping": [_product(TITLE_JUNK, source="cjdropshipping")],
            "aliexpress": [_product(TITLE_OTHER_MODEL, source="aliexpress")],
        })

        assert flat == []


# ---------------------------------------------------------------------------
# F. Category Hunter — _first_valid
# ---------------------------------------------------------------------------

class TestHunterPicksBestMatch:
    """C14/C12 — the Hunter picks the best MATCH, not the cheapest row."""

    def test_a_cheaper_row_is_ranked_first_when_sourcing_cost_differs(self):
        weak = _product(TITLE_WEAK, price=5.0)
        strong = _product(TITLE_MATCH, price=19.99)

        best = _first_valid([weak, strong], REF_TITLE, REF_PRICE)

        assert best is weak
        assert best.price < strong.price
        assert weak.match_score < strong.match_score

    def test_the_cheapest_row_wins_only_when_the_match_strength_ties(self):
        # Equal score -> price decides, which is the documented tie-break.
        cheap = _product(TITLE_MATCH, price=6.0)
        dear = _product(TITLE_MATCH, price=19.99)

        assert _first_valid([dear, cheap], REF_TITLE, REF_PRICE) is cheap

    def test_a_no_match_row_is_skipped_entirely(self):
        junk = _product(TITLE_JUNK, price=1.0)
        good = _product(TITLE_MATCH, price=19.99)

        best = _first_valid([junk, good], REF_TITLE, REF_PRICE)

        assert best is good
        # The rejected row is skipped before it is stamped, so it is left
        # unscored rather than given a passing tier — either way it cannot
        # read as a match to a consumer that looks at the row.
        assert junk.match_tier not in {TIER_VERIFIED, TIER_UNVERIFIED}
        assert junk.match_score == 0.0

    def test_zero_and_missing_prices_are_skipped(self):
        free = _product(TITLE_MATCH, price=0.0)
        none = _product(TITLE_MATCH, price=None)
        good = _product(TITLE_MATCH, price=19.99)

        assert _first_valid([free, none, good], REF_TITLE, REF_PRICE) is good

    def test_nothing_clearing_the_threshold_returns_none(self):
        # C12 — showing no supplier is correct; showing the wrong one is not.
        rows = [_product(TITLE_JUNK, price=1.0),
                _product(TITLE_OTHER_MODEL, price=2.0)]

        assert _first_valid(rows, REF_TITLE, REF_PRICE) is None

    def test_an_empty_candidate_list_returns_none(self):
        assert _first_valid([], REF_TITLE, REF_PRICE) is None

    def test_the_winner_carries_the_computed_score_and_label(self):
        best = _first_valid([_product(TITLE_WEAK, price=9.99)],
                            REF_TITLE, REF_PRICE)

        expected = compute_match(REF_TITLE, TITLE_WEAK,
                                 ebay_price=REF_PRICE, candidate_price=9.99)
        assert best.match_score == expected.score
        assert best.match_tier == expected.tier
        assert best.match_label == "not confirmed"
        assert best.match_method == MATCH_METHOD
        assert best.match_basis


class TestHunterSupplierLookupEndToEnd:
    """C14 — the rows _first_valid picks are what the report is built from."""

    @pytest.fixture(autouse=True)
    def _no_live_discovery(self, monkeypatch):
        """Stop discovery reaching the network.

        `_lookup_single_supplier` tries SerpApi discovery FIRST and only then
        the scrapers. These tests stub the scrapers but never discovery, so
        they were asserting against live SerpApi results. That made them
        intermittently wrong in BOTH directions: when Google happened to
        return a matching B&Q or Toolstation row for the reference title,
        `test_nothing_matching_yields_no_supplier_at_all` saw a supplier and
        failed even though the code under test was correct.

        Defaulting discovery to "found nothing" makes the suite deterministic
        and leaves each test's own assertion intact. Discovery has its own
        tests in the serpapi suite.
        """
        from scrapers import serpapi_discovery as sd
        from scrapers.aliexpress import AliExpressScraper

        monkeypatch.setattr(sd, "discover", lambda *a, **k: [])

        # _lookup_single_supplier falls through to AliExpress when discovery
        # and CJ find nothing, and that was a LIVE ~60s browser call. It was
        # the real source of the flake: whenever AliExpress happened to return
        # a matching drill, "nothing matching yields no supplier" failed while
        # the code under test was correct.
        async def _no_aliexpress(self, query):
            return []

        monkeypatch.setattr(AliExpressScraper, "search", _no_aliexpress)

    def test_the_report_row_comes_from_a_scored_hit(self, monkeypatch):
        from scrapers.cjdropshipping import CJDropshippingScraper
        from hunter.supplier_lookup import _lookup_single_supplier

        async def _search(self, query):
            return [_product(TITLE_JUNK, price=1.0, source="cjdropshipping"),
                    _product(TITLE_MATCH, price=9.99, source="cjdropshipping")]

        monkeypatch.setattr(CJDropshippingScraper, "search", _search)
        product = CategoryProduct(title=REF_TITLE, price=REF_PRICE,
                                  url="https://www.ebay.co.uk/itm/1")

        row = ap.run_async(_lookup_single_supplier(product))

        assert row is not None
        assert row["product_title"] == TITLE_MATCH
        assert row["price"] == 9.99
        assert row["match_tier"] in {TIER_VERIFIED, TIER_UNVERIFIED}
        assert row["match_score"] >= THRESHOLD_UNVERIFIED
        assert row["match_label"]

    def test_nothing_matching_yields_no_supplier_at_all(self, monkeypatch):
        from scrapers.cjdropshipping import CJDropshippingScraper
        from hunter.supplier_lookup import _lookup_single_supplier

        async def _search(self, query):
            return [_product(TITLE_JUNK, price=1.0, source="cjdropshipping")]

        monkeypatch.setattr(CJDropshippingScraper, "search", _search)
        product = CategoryProduct(title=REF_TITLE, price=REF_PRICE,
                                  url="https://www.ebay.co.uk/itm/1")

        assert ap.run_async(_lookup_single_supplier(product)) is None

    def test_batch_lookup_mirrors_the_verdict_onto_the_product_row(
            self, monkeypatch):
        from hunter import supplier_lookup as sl

        async def _lookup(product, marketplace="EBAY_GB"):
            return {"name": "CJ Dropshipping", "price": 9.99,
                    "url": "https://supplier.example/p/1",
                    "match_score": compute_match(
                        REF_TITLE, TITLE_WEAK, ebay_price=REF_PRICE,
                        candidate_price=9.99).score,
                    "match_tier": TIER_UNVERIFIED,
                    "match_label": "not confirmed"}

        monkeypatch.setattr(sl, "_lookup_single_supplier", _lookup)
        products = [CategoryProduct(title=REF_TITLE, price=REF_PRICE,
                                    url="https://www.ebay.co.uk/itm/1")]

        kept, excluded = sl.batch_supplier_lookup(products)

        assert len(kept) == 1 and excluded == 0
        row = kept[0]
        assert row.supplier_match_tier == TIER_UNVERIFIED
        assert row.supplier_match_label == "not confirmed"
        assert row.supplier_match_score >= THRESHOLD_UNVERIFIED


# ---------------------------------------------------------------------------
# G. Unscored is not a pass
# ---------------------------------------------------------------------------

class TestUnscoredIsNotAPass:
    """C12/C14 — "" means "never scored", and never scored is not a pass."""

    def test_a_fresh_scraped_row_is_unscored_by_default(self):
        row = _product(TITLE_MATCH)

        assert row.match_tier == ""
        assert row.match_score == 0.0
        assert row.match_method == ""
        assert row.match_basis == ""

    def test_a_fresh_category_product_is_unscored_by_default(self):
        product = CategoryProduct(title=REF_TITLE, price=REF_PRICE,
                                  url="https://www.ebay.co.uk/itm/1")

        assert product.supplier_match_tier == ""
        assert product.supplier_match_score == 0.0
        assert product.supplier_match_label == ""

    @pytest.mark.parametrize("bad_score", [None, "", "high", {}, [], "0.65x"])
    def test_filter_matches_drops_a_row_it_cannot_parse_as_a_float(self, bad_score):
        # C12 — a row whose score cannot be read was never scored. Passing it
        # through would let an unmeasured row into a list C12 says is gated.
        rows = [{"name": "unscored", "match_score": bad_score},
                {"name": "scored", "match_score": 0.8}]

        kept = filter_matches(rows, THRESHOLD_UNVERIFIED)

        assert [r["name"] for r in kept] == ["scored"]

    def test_a_row_with_no_score_key_at_all_is_dropped(self):
        rows = [{"name": "no score"}, {"name": "scored", "match_score": 0.5}]

        assert filter_matches(rows, THRESHOLD_UNVERIFIED) == [
            {"name": "scored", "match_score": 0.5}]

    def test_a_real_zero_score_is_a_score_and_is_still_dropped(self):
        # 0.0 is a computed score, not an absence — but it is below the
        # unverified floor, so it must not survive.
        assert filter_matches([{"match_score": 0.0}], THRESHOLD_UNVERIFIED) == []

    def test_no_consumer_returns_a_row_it_left_unscored(self, monkeypatch):
        # The three gates that score rows must leave every row they return
        # stamped. A "" tier escaping one of them is a hole in the gate.
        deep = ds._gate_suppliers([_row(TITLE_MATCH), _row(TITLE_JUNK)],
                                  REF_TITLE, ebay_price=REF_PRICE)
        analyze_ok = ap._score_supplier(_product(TITLE_WEAK), REF_TITLE, REF_PRICE)
        pipeline_kept = pl._match_gate(
            [_product(TITLE_MATCH), _product(TITLE_JUNK)], REF_TITLE, REF_PRICE)

        assert analyze_ok is True
        for row in deep:
            assert row["match_tier"] != ""
        for row in pipeline_kept:
            assert row.match_tier != ""
            assert row.match_score != 0.0


# ---------------------------------------------------------------------------
# H. The six availability fields survive the pipeline
# ---------------------------------------------------------------------------

class _ExportResult:
    """A deep-search-shaped object carrying suppliers — only the attributes
    export/format.py and export/csv_export.py actually read."""

    def __init__(self, suppliers):
        self.product_name = REF_TITLE
        self.product_category = "Power Tools"
        self.ebay_items_sold_month = "100 items"
        self.ebay_top_sellers = []
        self.ebay_price_min = 15.0
        self.ebay_price_max = REF_PRICE
        self.ebay_avg_price = REF_PRICE
        self.ebay_price_median = REF_PRICE
        self.ebay_total_sold_30d = 100
        self.ebay_total_sold_7d = 25
        self.suppliers = suppliers
        self.best_supplier_price = 9.99
        self.verdict = "PENDING"
        self.field_provenance = {}
        self.ebay_stores = []


class TestAvailabilityFieldsSurvive:
    """P4 + C1/C13 — what the scraper read is what the consumer shows.

    shipping_cost 0.0 means UNKNOWN, never "free": the display layers must
    print it blank and let shipping_raw tell free from unread."""

    def test_a_read_row_carries_all_six_fields_into_the_fast_result(
            self, monkeypatch):
        _stub_fast_path(monkeypatch, {
            "CJ Dropshipping": [_product(
                TITLE_MATCH, source="cjdropshipping",
                in_stock="low_stock", stock_raw="Only 3 left",
                availability_url="https://supplier.example/cjdropshipping",
                shipping_cost=3.99, shipping_days=7,
                shipping_raw="Delivery £3.99, 5-7 working days",
            )],
        })

        result = ds.deep_search_fast(REF_TITLE)

        assert len(result.suppliers) == 1
        row = result.suppliers[0]
        for name in AVAILABILITY_FIELDS:
            assert name in row
        assert row["in_stock"] == "low_stock"
        assert row["stock_raw"] == "Only 3 left"
        assert row["availability_url"] == "https://supplier.example/cjdropshipping"
        assert row["shipping_cost"] == 3.99
        assert row["shipping_days"] == 7
        assert row["shipping_raw"] == "Delivery £3.99, 5-7 working days"
        # The gate must not disturb the P4 block it rides alongside.
        _assert_scored(row)

    def test_the_json_export_passes_the_six_fields_through(self):
        from export.format import format_to_schema

        row = _row(TITLE_MATCH)
        ds._gate_suppliers([row], REF_TITLE, ebay_price=REF_PRICE)
        row.update({
            "in_stock": "in_stock", "stock_raw": "In stock",
            "availability_url": "https://supplier.example/p/1",
            "shipping_cost": 0.0, "shipping_days": 2,
            "shipping_raw": "Free delivery",
        })

        out = format_to_schema(_ExportResult([row]))["suppliers"][0]

        assert out["in_stock"] == "in_stock"
        assert out["stock_raw"] == "In stock"
        assert out["availability_url"] == "https://supplier.example/p/1"
        assert out["shipping_cost"] == 0.0
        assert out["shipping_days"] == 2
        assert out["shipping_raw"] == "Free delivery"
        assert out["match_tier"] == TIER_VERIFIED

    def test_zero_shipping_cost_stays_zero_and_prints_blank(self):
        # C1 — a 0.0 shipping cost is UNKNOWN (or an explicitly stated
        # "free"), and either way it may never print as "£0.00".
        from export.csv_export import export_to_csv

        row = _row(TITLE_MATCH)
        ds._gate_suppliers([row], REF_TITLE, ebay_price=REF_PRICE)
        row.update({"shipping_cost": 0.0, "shipping_raw": "Free delivery"})

        rows = list(csv.reader(io.StringIO(
            export_to_csv(_ExportResult([row])))))
        header, cells = rows[0], rows[1]

        cost_col = header.index("Supplier 1 Shipping Cost")
        assert cells[cost_col] == ""
        # The source text is what distinguishes free from unread.
        raw_col = header.index("Supplier 1 Shipping (source text)")
        assert cells[raw_col] == "Free delivery"

    def test_an_unread_availability_field_is_blank_not_a_guess(self):
        # C1/C13 — nothing was read, so nothing may be invented: no stock
        # state, no postage figure, no lead time.
        from export.csv_export import export_to_csv

        row = _row(TITLE_MATCH)
        ds._gate_suppliers([row], REF_TITLE, ebay_price=REF_PRICE)

        rows = list(csv.reader(io.StringIO(
            export_to_csv(_ExportResult([row])))))
        header, cells = rows[0], rows[1]

        for column in ("Stock", "Shipping Cost", "Shipping Days",
                       "Stock (source text)", "Shipping (source text)"):
            assert cells[header.index(f"Supplier 1 {column}")] == ""

    def test_unknown_stock_is_not_promoted_to_in_stock_by_the_export(self):
        from export.format import format_to_schema

        row = _row(TITLE_MATCH)
        ds._gate_suppliers([row], REF_TITLE, ebay_price=REF_PRICE)
        # A scorer/tier block must not imply the row was read.
        row["provenance"] = "verified"

        out = format_to_schema(_ExportResult([row]))

        supplier = out["suppliers"][0]
        assert supplier["in_stock"] == ""
        assert supplier["availability_url"] == ""
        # C13 — an unread field is stamped unverified with a reason, never
        # verified just because the row it rides on was verified.
        fields = out["provenance"]["fields"]
        for name in AVAILABILITY_FIELDS:
            assert fields[name]["provenance"] == "unverified"
            assert fields[name]["reason"]

    def test_a_read_field_is_not_replaced_by_an_unread_one(self):
        # C1 — the stamp for a field comes from the first row that actually
        # carried a value, so one read row is enough to stop the block
        # reading "nobody read this".
        from export.format import format_to_schema

        read = _row(TITLE_MATCH)
        ds._gate_suppliers([read], REF_TITLE, ebay_price=REF_PRICE)
        read.update({"in_stock": "in_stock", "stock_raw": "In stock"})
        unread = _row(TITLE_MATCH, name="second.example")
        ds._gate_suppliers([unread], REF_TITLE, ebay_price=REF_PRICE)

        out = format_to_schema(_ExportResult([read, unread]))
        fields = out["provenance"]["fields"]

        assert fields["in_stock"]["provenance"] == "verified"
        assert fields["shipping_cost"]["provenance"] == "unverified"


# ---------------------------------------------------------------------------
# I. Provenance is never overclaimed
# ---------------------------------------------------------------------------

class TestProvenanceNeverOverclaimed:
    """C13 + C14 — the badge may never sit above the evidence."""

    def test_an_unverified_match_is_stamped_unverified_in_the_block(self):
        from export.format import format_to_schema

        row = _row(TITLE_WEAK)
        ds._gate_suppliers([row], REF_TITLE, ebay_price=REF_PRICE)

        out = format_to_schema(_ExportResult([row]))

        assert out["suppliers"][0]["match_tier"] == TIER_UNVERIFIED
        # One unconfirmed score makes the whole match block unconfirmed.
        fields = out["provenance"]["fields"]
        for name in ("match_score", "match_tier", "match_label"):
            assert fields[name]["provenance"] == "unverified"
            assert fields[name]["reason"]

    def test_a_fully_verified_block_still_carries_reasons_for_the_rest(self):
        # One confirmed match stamps the match fields verified; the P4
        # availability fields nobody read stay unverified in the same map —
        # a verified match says nothing about whether anyone read the stock.
        from export.format import format_to_schema

        row = _row(TITLE_MATCH)
        ds._gate_suppliers([row], REF_TITLE, ebay_price=REF_PRICE)

        out = format_to_schema(_ExportResult([row]))

        fields = out["provenance"]["fields"]
        assert fields["match_score"]["provenance"] == "verified"
        assert fields["shipping_cost"]["provenance"] == "unverified"
        assert fields["shipping_cost"]["reason"]

    def test_an_unscored_supplier_block_reads_unverified_with_a_reason(self):
        from export.format import format_to_schema

        out = format_to_schema(_ExportResult([_row(TITLE_MATCH)]))

        fields = out["provenance"]["fields"]
        assert fields["match_score"]["provenance"] == "unverified"
        assert "scored" in fields["match_score"]["reason"]

    def test_no_provenance_block_is_ever_an_empty_dict(self, monkeypatch):
        # C13 — a badge that renders as nothing must never be mistaken for
        # one that renders "Verified". Every section and field entry carries
        # an explicit tier.
        from api.provenance_block import build_provenance_block

        _stub_full_path(monkeypatch, [_row(TITLE_WEAK, price=9.99),
                                      _row(TITLE_MATCH)])
        result = ds.deep_search_product(REF_TITLE)

        block = build_provenance_block(result.to_dict())

        for section in ("demand", "top_eBay_sellers", "suppliers",
                        "ebay_stores", "profit_analysis"):
            assert block[section], f"{section} block is empty"
            # C13's four tiers — nothing else may appear, and none of them
            # is ever left as a missing key.
            assert block[section]["provenance"] in FOUR_TIERS
            assert block[section]["label"]
        for name, stamp in block["fields"].items():
            assert isinstance(stamp, dict) and stamp, f"{name} stamp is empty"
            assert stamp["provenance"] in FOUR_TIERS
            assert stamp["label"]
        # C13 — an unverified stamp always says why.
        for section in ("demand", "suppliers", "ebay_stores"):
            if block[section]["provenance"] == "unverified":
                assert block[section]["reason"]

    def test_the_ai_insight_tier_can_never_reach_a_match_field(self):
        # C13 — a row whose own origin stamp claims to be model analysis
        # must not promote anything: the match block stays on the matcher's
        # verdict, and normalize_stamp demotes ai_insight wherever a stamp
        # is read (block stamps, field stamps).
        from export.format import format_to_schema

        row = _row(TITLE_WEAK)
        ds._gate_suppliers([row], REF_TITLE, ebay_price=REF_PRICE)
        row["provenance"] = "ai_insight"
        row["in_stock"] = "in_stock"
        row["stock_raw"] = "In stock"

        out = format_to_schema(_ExportResult([row]))
        fields = out["provenance"]["fields"]

        # The unverified match tier is unchanged by the row's own stamp.
        assert fields["match_score"]["provenance"] == "unverified"
        # The availability field's stamp is demoted to unverified, never
        # read as a confirmed fact because the row claimed model analysis.
        assert fields["in_stock"]["provenance"] == "unverified"
        assert fields["in_stock"]["reason"]

    def test_an_ai_insight_row_never_lets_the_supplier_block_read_verified(self):
        from api.provenance_block import build_provenance_block

        row = _row(TITLE_MATCH)
        ds._gate_suppliers([row], REF_TITLE, ebay_price=REF_PRICE)
        row["provenance"] = "ai_insight"

        block = build_provenance_block({"suppliers": [row]})

        # C13 — a row that is not a confirmed source keeps the block
        # unconfirmed, whatever the row's own stamp claims.
        assert block["suppliers"]["provenance"] == "unverified"
        assert block["suppliers"]["reason"]

    def test_llm_supplied_match_fields_are_overwritten_at_every_gate(self):
        # C14 — whatever a candidate row claims about its own match, the
        # gates replace it with the computed verdict.
        row = _row(TITLE_JUNK, match_score=0.97, match_tier="verified",
                   match_provenance="verified", match_label="verified match",
                   match_method="llm confidence")

        assert ds._gate_suppliers([row], REF_TITLE, ebay_price=REF_PRICE) == []