"""C1 + amended rules: one money rule, one verdict rule — table-driven, no network.

Every feature adapts evidence to engine.decisions.DecisionEngine and
engine.profit.calculate_profit; none re-derives the rules.

Spec (CONSTRAINTS.md, reviewed Sept 2026): fees 13.5% + 0.03% listing +
20% VAT on fees + 3% returns buffer; demand >=30/30d and >=8/7d; price
range default GBP 5-35 (user-adjustable, invalid falls back); supplier
prices never gated; delivery advisory; brand = VeRO check.
"""

import json

import pytest

from config import PROFIT_CONFIG
from engine.decisions import DecisionEngine
from engine.profit import calculate_profit
from scrapers.base import DemandData, ScrapedProduct


@pytest.fixture(autouse=True)
def _pristine_range(monkeypatch, tmp_path):
    import utils.filters as uf
    target = tmp_path / "custom_filters.json"
    target.write_text(json.dumps({"active": {}, "presets": {}}))
    monkeypatch.setattr(uf, "FILTERS_FILE", target)
    uf._cache["mtime"] = None
    uf._cache["data"] = None
    yield
    uf._cache["mtime"] = None
    uf._cache["data"] = None


def _product(price=12.0, delivery_days_max=5, condition="New", brand=None):
    return ScrapedProduct(
        source="ebay_uk",
        title="Generic widget",
        price=price,
        url="https://www.ebay.co.uk/itm/1",
        condition=condition,
        delivery_days_max=delivery_days_max,
        brand=brand,
        verified=True,
    )


def _demand(d30=40, d7=10, verified=True):
    return DemandData(sold_count_30d=d30, sold_count_7d=d7, verified=verified)


def _filter(verdict, name):
    return next(f for f in verdict.filters if f.name == name)


class TestVerdictLadder:
    def test_all_rules_met_is_pass(self):
        v = DecisionEngine().evaluate(_product(), _demand(), 6.0)
        assert v.verdict == "pass"

    def test_known_demand_failure_is_fail_not_pending(self):
        # A verified failure must not be masked by unverified rows (brand).
        v = DecisionEngine().evaluate(_product(), _demand(d30=5, d7=1), 6.0)
        assert v.verdict == "fail"
        assert _filter(v, "Demand (30d)").passed is False
        assert _filter(v, "Demand (30d)").verified is True

    def test_seven_day_threshold_is_eight(self):
        v = DecisionEngine().evaluate(_product(), _demand(d7=7), 6.0)
        row = _filter(v, "Demand (7d)")
        assert row.passed is False
        assert row.expected == "≥8 sold"
        assert v.verdict == "fail"

    def test_unknown_demand_is_pending_when_profitable(self):
        v = DecisionEngine().evaluate(
            _product(), _demand(d30=None, d7=None, verified=False), 6.0
        )
        assert v.verdict == "pending"

    def test_unverified_7d_estimate_never_passes(self, monkeypatch):
        # C4: a 7-day figure without purchase history holds the verdict at
        # PENDING even when every threshold is met.
        v = DecisionEngine().evaluate(_product(), _demand(d7=12, verified=False), 6.0)
        row = _filter(v, "Demand (7d)")
        assert row.passed is True
        assert row.verified is False
        assert v.verdict == "pending"

    def test_purchase_history_capture_unblocks_the_pass(self):
        # P5: verified_7d (from a capture) makes the 7-day row verified while
        # the 30-day side stays estimate-grade — the verdict can pass.
        d = _demand(d7=12, verified=False)
        d.verified_7d = True
        v = DecisionEngine().evaluate(_product(), d, 6.0)
        assert _filter(v, "Demand (7d)").verified is True
        assert v.verdict == "pass"

    def test_negative_profit_is_fail(self):
        # fees ≈ 19.24% of sale → £12 sale with £11.90 cost is a loss
        v = DecisionEngine().evaluate(_product(), _demand(), 11.90)
        assert v.verdict == "fail"

    def test_out_of_range_ebay_price_fails(self):
        v = DecisionEngine().evaluate(_product(price=35.01), _demand(), 6.0)
        assert _filter(v, "Price").passed is False
        assert v.verdict == "fail"


class TestDeliveryIsAdvisory:
    def test_slow_delivery_shows_but_never_fails(self):
        v = DecisionEngine().evaluate(_product(delivery_days_max=18), _demand(), 6.0)
        row = _filter(v, "Delivery (advisory)")
        assert row.advisory is True
        assert row.passed is False
        assert v.verdict == "pass"

    def test_missing_delivery_is_advisory_not_pending(self):
        v = DecisionEngine().evaluate(_product(delivery_days_max=None), _demand(), 6.0)
        row = _filter(v, "Delivery (advisory)")
        assert row.advisory is True
        assert row.actual == "Unknown"
        assert v.verdict == "pass"

    def test_shows_ebay_and_supplier_side_by_side(self):
        v = DecisionEngine().evaluate(_product(), _demand(), 6.0, supplier_delivery_days=25)
        row = _filter(v, "Delivery (advisory)")
        assert "eBay 5d" in row.actual
        assert "Supplier 25d" in row.actual


class TestSupplierNeverGated:
    def test_no_supplier_price_row_exists(self):
        v = DecisionEngine().evaluate(_product(), _demand(), 36.0)
        assert not any(f.name == "Supplier Price" for f in v.filters)

    def test_cheap_supplier_passes_and_wins_on_margin(self):
        # GBP 3 supplier for a GBP 12 listing — the advantage PR-1 protects.
        v = DecisionEngine().evaluate(_product(), _demand(), 3.0)
        assert v.verdict == "pass"
        assert v.profit > 6.0

    def test_expensive_supplier_fails_on_margin_not_on_range(self):
        # GBP 40 supplier on a GBP 12 listing: negative profit decides.
        v = DecisionEngine().evaluate(_product(), _demand(), 40.0)
        margin_row = _filter(v, "Margin")
        assert margin_row.passed is False
        assert v.verdict == "fail"


class TestMoneySingleSource:
    def test_the_default_split_is_the_published_card(self):
        # What runs today: Everything Else at 12.9%, the 40p per-order fee,
        # 0.35% regulatory operating fee, 20% VAT on those fees, and the 3%
        # returns buffer. The card charges per listing, not a percent of the
        # sale, so listing_fee is absent (None) - not a zero (C1).
        calc = calculate_profit(100.0, 50.0)
        assert calc["ebay_fee"] == 12.90
        assert calc["listing_fee"] is None
        assert calc["vat_on_fees"] == 2.73  # (12.90 + 0.40 + 0.35) * 20%
        assert calc["returns_buffer"] == 3.00
        assert calc["total_fees"] == 19.38
        assert calc["profit"] == 30.62
        assert calc["margin"] == 30.6

    def test_the_retired_v1_split_stays_reproducible(self):
        from engine import fees

        calc = calculate_profit(100.0, 50.0, fee_table=fees.V1_STATIC_TABLE)
        assert calc["ebay_fee"] == 13.50
        assert calc["listing_fee"] == 0.03
        assert calc["vat_on_fees"] == 2.71  # (13.50 + 0.03) * 20%
        assert calc["returns_buffer"] == 3.00
        assert calc["total_fees"] == 19.24
        assert calc["profit"] == 30.76
        assert calc["margin"] == 30.8

    def test_profit_config_matches_spec(self):
        assert PROFIT_CONFIG["ebay_fee_percent"] == 13.5
        assert PROFIT_CONFIG["listing_fee_percent"] == 0.03
        assert PROFIT_CONFIG["vat_on_fees_percent"] == 20.0
        assert PROFIT_CONFIG["returns_buffer_percent"] == 3.0

    def test_verdict_profit_comes_from_same_calc(self):
        v = DecisionEngine().evaluate(_product(), _demand(), 6.0)
        assert v.profit == calculate_profit(12.0, 6.0)["profit"]


class TestBrandVero:
    @staticmethod
    def _status(monkeypatch, status):
        import utils.vero as uv
        monkeypatch.setattr(uv, "check_vero", lambda name: status)

    def test_registered_brand_is_verified_fail(self, monkeypatch):
        self._status(monkeypatch, "registered")
        v = DecisionEngine().evaluate(_product(brand="SomeBrand"), _demand(), 6.0)
        row = _filter(v, "Brand")
        assert row.passed is False
        assert row.verified is True
        assert v.verdict == "fail"

    def test_unregistered_brand_name_passes(self, monkeypatch):
        self._status(monkeypatch, "not_registered")
        v = DecisionEngine().evaluate(_product(brand="SomeBrand"), _demand(), 6.0)
        assert _filter(v, "Brand").passed is True
        assert v.verdict == "pass"

    def test_unknown_vero_status_is_pending(self, monkeypatch):
        self._status(monkeypatch, "unknown")
        v = DecisionEngine().evaluate(_product(brand="SomeBrand"), _demand(), 6.0)
        row = _filter(v, "Brand")
        assert row.passed is False
        assert row.verified is False
        assert v.verdict == "pending"

    def test_no_brand_name_passes_unverified(self):
        v = DecisionEngine().evaluate(_product(brand=None), _demand(), 6.0)
        row = _filter(v, "Brand")
        assert row.passed is True
        assert row.verified is False
        assert v.verdict == "pass"


class TestHunterAdapter:
    def _category_product(self, d30=40, d7=10, supplier="B&Q", condition="New"):
        from hunter.category_scan import CategoryProduct
        return CategoryProduct(
            title="Generic widget",
            price=12.0,
            url="https://www.ebay.co.uk/itm/1",
            sold_30d=d30,
            sold_7d=d7,
            supplier_price=6.0,
            supplier_name=supplier,
            # C10: the category scanner only emits rows that passed its
            # New-only query, so a scanned row always carries a condition.
            condition=condition,
        )

    @staticmethod
    def _stub_capture(monkeypatch, verified):
        import analysis_pipeline as ap

        def _apply(demand, url, db=None):
            if verified:
                demand.verified_7d = True
            return demand

        monkeypatch.setattr(ap, "apply_purchase_history", _apply)

    def test_all_rules_met_is_pass_with_engine_money(self, monkeypatch):
        # C4: PASS additionally needs a purchase-history capture for the
        # 7-day figure — sold-search counts alone never verify it.
        from hunter.profit_calc import _calc_single
        self._stub_capture(monkeypatch, verified=True)
        p = self._category_product()
        _calc_single(p, None)
        assert p.verdict == "PASS"
        assert p.profit == calculate_profit(12.0, 6.0)["profit"]

    def test_without_capture_seven_day_holds_at_pending(self, monkeypatch):
        from hunter.profit_calc import _calc_single
        self._stub_capture(monkeypatch, verified=False)
        p = self._category_product()
        _calc_single(p, None)
        assert p.verdict == "PENDING"
        assert p.profit == calculate_profit(12.0, 6.0)["profit"]  # money still shown

    def test_known_demand_failure_is_fail(self, monkeypatch):
        from hunter.profit_calc import _calc_single
        self._stub_capture(monkeypatch, verified=True)
        p = self._category_product(d30=5, d7=1)
        _calc_single(p, None)
        assert p.verdict == "FAIL"

    def test_missing_supplier_is_pending(self, monkeypatch):
        from hunter.profit_calc import _calc_single
        self._stub_capture(monkeypatch, verified=True)
        p = self._category_product()
        p.supplier_price = 0.0
        _calc_single(p, None)
        assert p.verdict == "PENDING"


class TestDeepSearchAdapter:
    def _result(self, **overrides):
        from deep_search import DeepSearchResult
        base = dict(
            product_name="Generic widget",
            ebay_avg_price=12.5,
            best_supplier_price=6.0,
            ebay_total_sold_30d=40,
            ebay_total_sold_7d=10,
            suppliers=[{"name": "CJ", "price": 6.0, "url": "x", "delivery_days": "3-7 days"}],
        )
        base.update(overrides)
        return DeepSearchResult(**base)

    def test_engine_rules_and_money_are_used(self):
        from deep_search import _calculate_profit_and_verdict
        r = self._result()
        _calculate_profit_and_verdict(r, filters={})
        # C4: the 7-day side here is a sold-search estimate (verified=False),
        # so the engine holds the verdict at PENDING — never PASS.
        assert r.verdict == "PENDING"
        names = [f["name"] for f in r.filters_passed]
        assert "Price" in names and "Margin" in names and "Demand (7d)" in names
        assert "Supplier Price" not in names  # PR-1: supplier never gated
        d7 = next(f for f in r.filters_passed if f["name"] == "Demand (7d)")
        assert d7["passed"] is True and d7["verified"] is False
        assert r.profit == calculate_profit(12.5, 6.0)["profit"]

    def test_missing_supplier_is_pending_with_data_row(self):
        from deep_search import _calculate_profit_and_verdict
        r = self._result(best_supplier_price=0.0)
        _calculate_profit_and_verdict(r, filters={})
        assert r.verdict == "PENDING"
        assert r.filters_passed[0]["name"] == "Data"

    def test_caller_filters_are_honoured(self):
        # Regression: deep search used to ignore the caller's filter set.
        from deep_search import _calculate_profit_and_verdict
        r = self._result()
        _calculate_profit_and_verdict(r, filters={"margin_min": 90.0})
        margin = next(f for f in r.filters_passed if f["name"] == "Margin")
        assert margin["passed"] is False


class TestConditionGate:
    """C10 — New-only is a hard gate, not an advisory row."""

    def _condition_row(self, product, filters=None):
        v = DecisionEngine(filters).evaluate(product, DemandData(verified=False))
        return next(f for f in v.filters if f.name == "Condition")

    @pytest.mark.parametrize("bad", ["Used", "Pre-owned", "Refurbished",
                                     "Seller Refurbished", "For parts or not working",
                                     "Open box", "Damaged"])
    def test_non_new_is_a_verified_failure(self, bad):
        # A KNOWN non-New condition must fail hard (step 1 of the ladder),
        # never be softened to PENDING.
        row = self._condition_row(_product(condition=bad))
        assert row.passed is False
        assert row.expected == "New"

    @pytest.mark.parametrize("good", ["New", "New with tags", "Brand New", "New (Other)"])
    def test_new_variants_pass(self, good):
        assert self._condition_row(_product(condition=good)).passed is True

    def test_blank_condition_is_reported_unverified(self):
        # C1: we never claim to know a condition we couldn't read, so the
        # row is flagged Unverified even though it does not pass.
        row = self._condition_row(_product(condition=""))
        assert row.passed is False
        assert row.verified is False

    def test_used_listing_cannot_pass_even_with_every_other_rule_met(self):
        demand = DemandData(sold_count_30d=40, sold_count_7d=10,
                            verified=True, verified_7d=True)
        v = DecisionEngine(None).evaluate(
            _product(price=12.0, condition="Used"), demand, supplier_price=6.0
        )
        assert v.verdict == "fail"

    def test_hunter_row_with_used_condition_fails(self, monkeypatch):
        import analysis_pipeline as ap

        def _apply(demand, url, db=None):
            demand.verified_7d = True
            return demand

        monkeypatch.setattr(ap, "apply_purchase_history", _apply)
        from hunter.profit_calc import _calc_single
        p = TestHunterAdapter()._category_product(condition="Used")
        _calc_single(p, None)
        assert p.verdict == "FAIL"

    def test_query_time_filters_carry_new_only(self):
        # The very string eBay receives — if this drifts, Used listings
        # return and the post-filter is the only thing left holding.
        from engine.condition_gate import api_condition_filter, html_condition_param
        assert api_condition_filter() == "conditions:{NEW}"
        assert html_condition_param() == "&LH_ItemCondition=1000"

    def test_silent_default_of_missing_condition_is_gone(self):
        # Regression: a missing condition used to be written as "New",
        # which let Used listings pass the Condition row by omission.
        from scrapers.base import ScrapedProduct
        p = ScrapedProduct(source="ebay_uk", title="x", price=10.0, url="u")
        assert p.condition != "New"
        assert self._condition_row(p).passed is False
