"""Price-band gate tests — CONSTRAINTS_PRICING.md PR-1..PR-7.

Seams (pre-agreed):
  1. engine.price_gate pure functions
  2. engine.decisions.DecisionEngine.evaluate
  3. export.format.format_to_schema
  4. POST /api/watchlist write gate (TestClient)

Expected values are literals from the spec (£5.00–£35.00 inclusive),
not recomputed from the implementation.
"""

from types import SimpleNamespace

from engine.decisions import DecisionEngine
from engine.price_gate import clamp_band, excluded_note, filter_dicts, in_band, over_band_reason
from export.format import format_to_schema
from scrapers.base import DemandData, ScrapedProduct


def _product(price: float, delivery_days_max: int = 5) -> ScrapedProduct:
    return ScrapedProduct(
        source="ebay_uk",
        title="Generic widget",
        price=price,
        url="https://www.ebay.co.uk/itm/1",
        condition="New",
        delivery_days_max=delivery_days_max,
        verified=True,
    )


def _demand() -> DemandData:
    return DemandData(sold_count_30d=40, sold_count_7d=5, verified=True)


class TestInBand:
    def test_lower_boundary_is_inclusive(self):
        assert in_band(5.00) is True

    def test_upper_boundary_is_inclusive(self):
        assert in_band(35.00) is True

    def test_below_band_is_excluded(self):
        assert in_band(4.99) is False

    def test_above_band_is_excluded(self):
        assert in_band(35.01) is False

    def test_typical_price_is_in_band(self):
        assert in_band(12.99) is True

    def test_missing_price_is_excluded_not_error(self):
        assert in_band(None) is False

    def test_unparseable_price_is_excluded_not_error(self):
        assert in_band("£12.99") is False

    def test_zero_price_is_excluded(self):
        assert in_band(0) is False


class TestOverBandReason:
    def test_out_of_band_price_is_named_in_refusal(self):
        reason = over_band_reason(83.90)
        assert "£83.90" in reason
        assert "£5.00" in reason and "£35.00" in reason

    def test_missing_price_never_fabricates_a_figure(self):
        reason = over_band_reason(None)
        assert "£0.00" not in reason
        assert "no verified price" in reason

    def test_unparseable_price_never_fabricates_a_figure(self):
        reason = over_band_reason("n/a")
        assert "£0.00" not in reason
        assert "no verified price" in reason


class TestExcludedNote:
    def test_zero_exclusions_produces_no_note(self):
        assert excluded_note("supplier matches", 0) == ""

    def test_note_counts_exclusions_and_names_the_band(self):
        note = excluded_note("supplier matches", 4)
        assert "4" in note
        assert "supplier matches" in note
        assert "£5.00" in note and "£35.00" in note


class TestClampBand:
    def test_partial_dict_cannot_widen_the_band(self):
        out = clamp_band({"price_min": 1, "price_max": 100})
        assert out["price_min"] == 5.0
        assert out["price_max"] == 35.0

    def test_partial_dict_keeps_non_price_filter_keys(self):
        out = clamp_band({"price_min": 1, "price_max": 100})
        assert out["demand_min_30d"] == 10
        assert out["margin_min"] == 25.0

    def test_none_yields_full_default_filters(self):
        out = clamp_band(None)
        assert out["price_min"] == 5.0
        assert out["price_max"] == 35.0
        assert out["demand_min_30d"] == 10


class TestFilterDicts:
    def test_splits_rows_and_counts_exclusions(self):
        rows = [
            {"name": "in", "price": 12.0},
            {"name": "high", "price": 45.0},
            {"name": "low", "price": 2.0},
            {"name": "no-price", "price": None},
        ]
        kept, excluded = filter_dicts(rows, "price")
        assert [r["name"] for r in kept] == ["in"]
        assert excluded == 3


def _price_filter(verdict):
    return next(f for f in verdict.filters if f.name == "Price")


class TestDecisionEngine:
    def test_price_below_band_fails_with_spec_band_shown(self):
        verdict = DecisionEngine().evaluate(_product(4.99), _demand(), 6.0)
        pf = _price_filter(verdict)
        assert pf.passed is False
        assert pf.expected == "£5.00–£35.00"
        assert pf.actual == "£4.99"

    def test_price_above_band_fails_with_spec_band_shown(self):
        verdict = DecisionEngine().evaluate(_product(35.01), _demand(), 6.0)
        pf = _price_filter(verdict)
        assert pf.passed is False
        assert pf.expected == "£5.00–£35.00"

    def test_price_at_both_boundaries_passes(self):
        for price in (5.00, 35.00):
            verdict = DecisionEngine().evaluate(_product(price), _demand(), 6.0)
            assert _price_filter(verdict).passed is True, f"boundary {price}"

    def test_out_of_band_product_never_gets_a_pass_verdict(self):
        verdict = DecisionEngine().evaluate(_product(40.00), _demand(), 6.0)
        assert verdict.verdict != "pass"

    def test_all_rules_met_is_a_pass(self):
        verdict = DecisionEngine().evaluate(_product(12.00), _demand(), 6.0)
        assert verdict.verdict == "pass"


def _result(**overrides):
    """Minimal DeepSearchResult-shaped object for the export seam."""
    base = dict(
        product_name="Generic widget",
        product_category="test",
        ebay_items_sold_month="40",
        ebay_top_sellers=[{"name": "Seller", "url": "https://x"}],
        ebay_price_min=6.0,
        ebay_price_max=20.0,
        ebay_avg_price=12.5,
        ebay_price_median=11.0,
        best_supplier_price=7.0,
        suppliers=[
            {"name": "in-band", "price": 7.0, "url": "a"},
        ],
        verdict="pass",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestExportSchema:
    def test_in_band_values_are_preserved_and_no_note_is_needed(self):
        out = format_to_schema(_result())
        assert out["eBay_price_range"]["avg"] == 12.5
        assert len(out["suppliers"]) == 1
        assert "band_notes" not in out

    def test_out_of_band_avg_is_nulled_never_rewritten(self):
        out = format_to_schema(_result(ebay_avg_price=83.90))
        assert out["eBay_price_range"]["avg"] is None
        assert out["band_notes"]
        assert "83.90" in out["band_notes"]

    def test_out_of_band_supplier_is_dropped_and_counted(self):
        out = format_to_schema(_result(suppliers=[
            {"name": "in-band", "price": 7.0, "url": "a"},
            {"name": "out-of-band", "price": 45.0, "url": "b"},
        ]))
        assert [s["name"] for s in out["suppliers"]] == ["in-band"]
        assert "excluded" in out["band_notes"]

    def test_missing_price_exports_as_null_without_crashing(self):
        out = format_to_schema(_result(ebay_avg_price=None, best_supplier_price=None))
        assert out["eBay_price_range"]["avg"] is None
        assert out["suppliers"]


class TestWatchlistWriteGate:
    """POST /api/watchlist must refuse out-of-band prices (PR-6)."""

    @staticmethod
    def _client():
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)

    def test_price_above_band_is_refused_with_band_message(self):
        with self._client() as client:
            resp = client.post("/api/watchlist", json={
                "product_name": "gate-test-high",
                "ebay_price": 99.99,
                "ebay_url": "https://www.ebay.co.uk/itm/test-high",
            })
            assert resp.status_code == 422
            detail = resp.json()["detail"]
            assert "£99.99" in detail
            assert "£5.00" in detail and "£35.00" in detail

    def test_price_below_band_is_refused_with_band_message(self):
        with self._client() as client:
            resp = client.post("/api/watchlist", json={
                "product_name": "gate-test-low",
                "ebay_price": 2.50,
                "ebay_url": "https://www.ebay.co.uk/itm/test-low",
            })
            assert resp.status_code == 422
            assert "£2.50" in resp.json()["detail"]

    def test_price_inside_band_is_accepted(self):
        with self._client() as client:
            resp = client.post("/api/watchlist", json={
                "product_name": "gate-test-ok",
                "ebay_price": 12.50,
                "ebay_url": "https://www.ebay.co.uk/itm/test-ok",
            })
            assert resp.status_code == 200
            item_id = resp.json()["id"]
            cleanup = client.delete(f"/api/watchlist/{item_id}")
            assert cleanup.status_code == 200
