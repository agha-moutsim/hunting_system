"""C1: one money rule + one verdict rule — table-driven, no network.

Every feature adapts evidence to engine.decisions.DecisionEngine and
engine.profit.calculate_profit; none re-derives the rules.
"""

from config import PROFIT_CONFIG
from engine.decisions import DecisionEngine
from engine.profit import calculate_profit
from scrapers.base import DemandData, ScrapedProduct


def _product(price=12.0, delivery_days_max=5, condition="New"):
    return ScrapedProduct(
        source="ebay_uk",
        title="Generic widget",
        price=price,
        url="https://www.ebay.co.uk/itm/1",
        condition=condition,
        delivery_days_max=delivery_days_max,
        verified=True,
    )


def _demand(d30=40, d7=5, verified=True):
    return DemandData(sold_count_30d=d30, sold_count_7d=d7, verified=verified)


def _filter(verdict, name):
    return next(f for f in verdict.filters if f.name == name)


class TestVerdictLadder:
    def test_all_rules_met_is_pass(self):
        v = DecisionEngine().evaluate(_product(), _demand(), 6.0)
        assert v.verdict == "pass"

    def test_known_demand_failure_is_fail_not_pending(self):
        # A verified failure must not be masked by unverified rows (brand).
        v = DecisionEngine().evaluate(_product(), _demand(d30=5), 6.0)
        assert v.verdict == "fail"
        assert _filter(v, "Demand (30d)").passed is False
        assert _filter(v, "Demand (30d)").verified is True

    def test_unknown_demand_is_pending_when_profitable(self):
        v = DecisionEngine().evaluate(_product(), _demand(d30=None, d7=None, verified=False), 6.0)
        assert v.verdict == "pending"

    def test_negative_profit_is_fail(self):
        v = DecisionEngine().evaluate(_product(), _demand(), 11.90)
        assert v.verdict == "fail"

    def test_known_slow_delivery_is_fail(self):
        # 18-day delivery fails the <=8 rule (demand 10 < 30, no exception).
        v = DecisionEngine().evaluate(_product(delivery_days_max=18), _demand(d30=10, d7=2), 6.0)
        assert v.verdict == "fail"
        assert _filter(v, "Delivery").passed is False

    def test_high_demand_grants_delivery_exception(self):
        # >=30 sold/month allows <=25 days (CONSTRAINTS.md).
        v = DecisionEngine().evaluate(_product(delivery_days_max=18), _demand(d30=40, d7=5), 6.0)
        assert _filter(v, "Delivery").passed is True
        assert v.verdict == "pass"

    def test_out_of_band_ebay_price_fails(self):
        v = DecisionEngine().evaluate(_product(price=35.01), _demand(), 6.0)
        assert _filter(v, "Price").passed is False
        assert v.verdict == "fail"

    def test_out_of_band_supplier_cost_fails(self):
        v = DecisionEngine().evaluate(_product(), _demand(), 36.0)
        sp = _filter(v, "Supplier Price")
        assert sp.passed is False
        assert sp.expected == "£5.00–£35.00"
        assert v.verdict == "fail"

    def test_partial_filters_dict_cannot_widen_engine(self):
        v = DecisionEngine({"price_min": 1, "price_max": 100}).evaluate(
            _product(price=40.0), _demand(), 6.0
        )
        assert _filter(v, "Price").expected == "£5.00–£35.00"
        assert v.verdict == "fail"


class TestMoneySingleSource:
    def test_fee_split_matches_spec(self):
        calc = calculate_profit(100.0, 50.0)
        assert calc["ebay_fee"] == 12.80
        assert calc["returns_buffer"] == 3.00
        assert calc["profit"] == 34.20
        assert calc["margin"] == 34.2

    def test_profit_config_matches_spec(self):
        assert PROFIT_CONFIG["ebay_fee_percent"] == 12.8
        assert PROFIT_CONFIG["returns_buffer_percent"] == 3.0

    def test_verdict_profit_comes_from_same_calc(self):
        v = DecisionEngine().evaluate(_product(), _demand(), 6.0)
        assert v.profit == calculate_profit(12.0, 6.0)["profit"]


class TestHunterAdapter:
    def _category_product(self, d30=40, d7=5, supplier="B&Q"):
        from hunter.category_scan import CategoryProduct
        return CategoryProduct(
            title="Generic widget",
            price=12.0,
            url="https://www.ebay.co.uk/itm/1",
            sold_30d=d30,
            sold_7d=d7,
            supplier_price=6.0,
            supplier_name=supplier,
        )

    def test_all_rules_met_is_pass_with_engine_money(self):
        from hunter.profit_calc import _calc_single
        p = self._category_product()
        _calc_single(p, None)
        assert p.verdict == "PASS"
        assert p.profit == calculate_profit(12.0, 6.0)["profit"]

    def test_known_demand_failure_is_fail(self):
        from hunter.profit_calc import _calc_single
        p = self._category_product(d30=5, d7=1)
        _calc_single(p, None)
        assert p.verdict == "FAIL"

    def test_missing_supplier_is_pending(self):
        from hunter.profit_calc import _calc_single
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
            best_supplier_price=7.0,
            ebay_total_sold_30d=40,
            ebay_total_sold_7d=5,
            suppliers=[{"name": "CJ", "price": 7.0, "url": "x", "delivery_days": "3-7 days"}],
        )
        base.update(overrides)
        return DeepSearchResult(**base)

    def test_engine_rules_and_money_are_used(self):
        from deep_search import _calculate_profit_and_verdict
        r = self._result()
        _calculate_profit_and_verdict(r)
        assert r.verdict == "PASS"
        names = [f["name"] for f in r.filters_passed]
        assert "Price" in names and "Supplier Price" in names and "Margin" in names
        assert r.profit == calculate_profit(12.5, 7.0)["profit"]

    def test_missing_supplier_is_pending_with_data_row(self):
        from deep_search import _calculate_profit_and_verdict
        r = self._result(best_supplier_price=0.0)
        _calculate_profit_and_verdict(r)
        assert r.verdict == "PENDING"
        assert r.filters_passed[0]["name"] == "Data"

    def test_caller_filters_are_honoured(self):
        # Regression: deep search used to ignore the caller's filter set.
        from deep_search import _calculate_profit_and_verdict
        r = self._result()
        _calculate_profit_and_verdict(r, filters={"margin_min": 90.0})
        margin = next(f for f in r.filters_passed if f["name"] == "Margin")
        assert margin["passed"] is False
        assert r.verdict == "FAIL"
