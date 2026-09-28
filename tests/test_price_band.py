"""Price-range gate tests — CONSTRAINTS_PRICING.md PR-1..PR-7 (amended Sept 2026).

Seams (pre-agreed):
  1. engine.price_gate pure functions
  2. engine.decisions.DecisionEngine.evaluate
  3. export.format.format_to_schema
  4. TestClient write gates live in tests/test_range_storage.py

Expected values are literals from the spec (default range £5.00–£35.00
inclusive), not recomputed from the implementation. Supplier prices are
never range-gated (PR-1); the range is user-adjustable with those defaults
(PR-5/PR-7).
"""

import json
from types import SimpleNamespace

import pytest

from engine.decisions import DecisionEngine
from engine.price_gate import clamp_band, excluded_note, filter_dicts, in_band, over_band_reason
from export.format import format_to_schema
from scrapers.base import DemandData, ScrapedProduct


@pytest.fixture(autouse=True)
def _pristine_range(monkeypatch, tmp_path):
    """Point the active-range store at an empty file so every test runs
    against the config defaults regardless of the repo's live state."""
    import utils.filters as uf
    target = tmp_path / "custom_filters.json"
    target.write_text(json.dumps({"active": {}, "presets": {}}))
    monkeypatch.setattr(uf, "FILTERS_FILE", target)
    uf._cache["mtime"] = None
    uf._cache["data"] = None
    yield
    uf._cache["mtime"] = None
    uf._cache["data"] = None


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
    return DemandData(sold_count_30d=40, sold_count_7d=10, verified=True)


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

    def test_active_custom_range_drives_the_gate(self, monkeypatch, tmp_path):
        import utils.filters as uf
        (tmp_path / "custom_filters.json").write_text(
            json.dumps({"active": {"price_min": 2.0, "price_max": 50.0}, "presets": {}})
        )
        uf._cache["mtime"] = None
        uf._cache["data"] = None
        assert in_band(45.00) is True
        assert in_band(1.50) is False
        assert in_band(55.00) is False


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
        assert excluded_note("sold listings", 0) == ""

    def test_note_counts_exclusions_and_names_the_band(self):
        note = excluded_note("sold listings", 4)
        assert "4" in note
        assert "sold listings" in note
        assert "£5.00" in note and "£35.00" in note


class TestClampBand:
    def test_invalid_range_falls_back_to_defaults(self):
        out = clamp_band({"price_min": 50, "price_max": 10})
        assert out["price_min"] == 5.0
        assert out["price_max"] == 35.0

    def test_non_numeric_range_falls_back_to_defaults(self):
        out = clamp_band({"price_min": "abc", "price_max": 35})
        assert out["price_min"] == 5.0
        assert out["price_max"] == 35.0

    def test_valid_user_range_is_kept(self):
        # PR-7 amended: the range is user-adjustable; defaults are 5–35.
        out = clamp_band({"price_min": 2.0, "price_max": 50.0})
        assert out["price_min"] == 2.0
        assert out["price_max"] == 50.0

    def test_partial_dict_keeps_non_price_filter_keys(self):
        out = clamp_band({"margin_min": 30.0})
        assert out["demand_min_30d"] == 30
        assert out["demand_min_7d"] == 8
        assert out["margin_min"] == 30.0

    def test_none_yields_full_default_filters(self):
        out = clamp_band(None)
        assert out["price_min"] == 5.0
        assert out["price_max"] == 35.0
        assert out["demand_min_30d"] == 30


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

    def test_valid_custom_range_is_honoured_by_the_engine(self):
        verdict = DecisionEngine({"price_min": 2.0, "price_max": 50.0}).evaluate(
            _product(40.00), _demand(), 6.0
        )
        pf = _price_filter(verdict)
        assert pf.passed is True
        assert pf.expected == "£2.00–£50.00"
        assert verdict.verdict == "pass"

    def test_invalid_range_in_partial_dict_falls_back_to_defaults(self):
        verdict = DecisionEngine({"price_min": 99, "price_max": 10}).evaluate(
            _product(40.00), _demand(), 6.0
        )
        pf = _price_filter(verdict)
        assert pf.passed is False
        assert pf.expected == "£5.00–£35.00"
        assert verdict.verdict == "fail"


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

    def test_supplier_prices_are_never_dropped_or_nulled(self):
        # PR-1 amended: supplier rows pass through in full.
        out = format_to_schema(_result(
            best_supplier_price=45.0,
            suppliers=[
                {"name": "cheap", "price": 3.0, "url": "a"},
                {"name": "pricey", "price": 45.0, "url": "b"},
            ],
        ))
        assert [s["name"] for s in out["suppliers"]] == ["cheap", "pricey"]
        assert out["profit_analysis"]["total_cost"] >= 45.0
        assert "supplier" not in (out.get("band_notes") or "")

    def test_missing_price_exports_as_null_without_crashing(self):
        out = format_to_schema(_result(ebay_avg_price=None, best_supplier_price=None))
        assert out["eBay_price_range"]["avg"] is None
        assert out["suppliers"]


class TestSingleRangeSource:
    """Range-store regression tests (amended PR-5/PR-7).

    config.py holds the defaults; custom_filters.json may carry a VALID
    user-adjusted range (the active gate) — but an invalid or poisoned
    range can never load, and unknown/stale keys are dropped so old rules
    cannot resurface.
    """

    @staticmethod
    def _write(tmp_path, active: dict) -> None:
        import utils.filters as uf
        (tmp_path / "custom_filters.json").write_text(json.dumps({
            "active": active,
            "presets": {},
        }))
        uf._cache["mtime"] = None
        uf._cache["data"] = None

    def test_poisoned_inverted_range_cannot_load(self, monkeypatch, tmp_path):
        import utils.filters as uf
        monkeypatch.setattr(uf, "FILTERS_FILE", tmp_path / "custom_filters.json")
        self._write(tmp_path, {"price_min": 99.0, "price_max": 10.0})
        loaded = uf.load_filters()
        assert loaded["price_min"] == 5.0
        assert loaded["price_max"] == 35.0

    def test_non_numeric_range_cannot_load(self, monkeypatch, tmp_path):
        import utils.filters as uf
        monkeypatch.setattr(uf, "FILTERS_FILE", tmp_path / "custom_filters.json")
        self._write(tmp_path, {"price_min": "abc", "price_max": 35.0})
        loaded = uf.load_filters()
        assert loaded["price_min"] == 5.0
        assert loaded["price_max"] == 35.0

    def test_valid_custom_range_loads_and_gates(self, monkeypatch, tmp_path):
        import utils.filters as uf
        monkeypatch.setattr(uf, "FILTERS_FILE", tmp_path / "custom_filters.json")
        self._write(tmp_path, {"price_min": 2.0, "price_max": 50.0})
        loaded = uf.load_filters()
        assert loaded["price_min"] == 2.0
        assert loaded["price_max"] == 50.0
        assert in_band(45.0) is True

    def test_stale_unknown_keys_are_dropped(self, monkeypatch, tmp_path):
        import utils.filters as uf
        monkeypatch.setattr(uf, "FILTERS_FILE", tmp_path / "custom_filters.json")
        self._write(tmp_path, {"demand_strong_30d": 30, "delivery_exception_max": 25})
        loaded = uf.load_filters()
        assert "demand_strong_30d" not in loaded
        assert "delivery_exception_max" not in loaded

    def test_non_price_user_filters_still_pass_through(self, monkeypatch, tmp_path):
        import utils.filters as uf
        monkeypatch.setattr(uf, "FILTERS_FILE", tmp_path / "custom_filters.json")
        self._write(tmp_path, {"demand_min_30d": 15})
        loaded = uf.load_filters()
        assert loaded["demand_min_30d"] == 15

    def test_save_keeps_a_valid_range_and_strips_an_invalid_one(self, monkeypatch, tmp_path):
        import utils.filters as uf
        monkeypatch.setattr(uf, "FILTERS_FILE", tmp_path / "custom_filters.json")

        uf.save_filters({"price_min": 2.0, "price_max": 50.0, "margin_min": 30.0})
        saved = json.loads((tmp_path / "custom_filters.json").read_text())
        assert saved["active"]["price_min"] == 2.0
        assert saved["active"]["price_max"] == 50.0
        assert saved["active"]["margin_min"] == 30.0

        uf.save_filters({"price_min": 99.0, "price_max": 10.0, "margin_min": 30.0})
        saved = json.loads((tmp_path / "custom_filters.json").read_text())
        assert "price_min" not in saved["active"]
        assert "price_max" not in saved["active"]
