"""Phase E1 - AU Analyze runs in AUD, with the AU card and AU floors.

These pins keep three boundaries apart:

  * Analyze is unlocked for AU while the standalone fee calculator is not;
  * the AUD band and demand floors are the AU values, never the GBP defaults;
  * a verdict and scorecard use the AU fee card and the A$ symbol, and a
    non-GBP market without a card refuses to price instead of borrowing the
    UK card.
"""

from __future__ import annotations

import asyncio

import pytest

import analysis_pipeline as ap
from analysis_pipeline import _supplier_currency_matches
from engine.decisions import DecisionEngine
from engine.profit import calculate_market_profit
from engine.scorecard import format_scorecard
from marketplaces import (
    analyze_ready,
    fee_calculator_ready,
    get_marketplace,
    market_filter_defaults,
    public_marketplace,
)
from scrapers.base import DemandData, ScrapedProduct


def _au_product(source: str = "ebay_au") -> ScrapedProduct:
    return ScrapedProduct(
        source=source,
        title="Insulated Water Bottle 500ml",
        price=30.0,
        currency="AUD",
        url="https://www.ebay.com.au/itm/123456789012",
        condition="New",
        verified=True,
    )


def _au_demand(sold_30d: int | None = 15, sold_7d: int | None = 10) -> DemandData:
    return DemandData(
        sold_count_30d=sold_30d,
        sold_count_7d=sold_7d,
        verified=True,
        verified_7d=True,
        currency="AUD",
    )


class TestTheTwoSwitches:
    def test_au_analyze_is_ready_while_its_calculator_is_locked(self):
        au = get_marketplace("EBAY_AU")

        assert analyze_ready(au) is True
        assert fee_calculator_ready(au) is False

        public = public_marketplace(au)
        assert public["analyze_ready"] is True
        assert public["fee_calculator_ready"] is False
        assert public["fee_table"] is None
        assert public["fee_table_registered"] == "au-rate-card-2026-10-09"

    def test_the_fee_warning_does_not_claim_analyze_is_locked(self):
        warning = public_marketplace(get_marketplace("EBAY_AU"))["fee_warning"]

        assert "not enabled" in warning
        assert "AUD" in warning
        assert "Analyze can use the card" in warning

    def test_a_market_without_a_card_or_bench_is_not_analyze_ready(self):
        assert analyze_ready(get_marketplace("EBAY_US")) is False
        assert analyze_ready(get_marketplace("EBAY_DE")) is False
        assert analyze_ready(get_marketplace("EBAY_CA")) is False


class TestTheAuBandAndFloors:
    def test_au_defaults_are_aud_and_not_the_gbp_band(self):
        defaults = market_filter_defaults(get_marketplace("EBAY_AU"))

        assert defaults["price_min"] == 0.99
        assert defaults["price_max"] == 50.0
        assert defaults["demand_min_30d"] == 15
        assert defaults["demand_min_7d"] == 10

    def test_decision_engine_uses_the_au_defaults(self):
        engine = DecisionEngine(marketplace="EBAY_AU")

        assert engine.filters["price_min"] == 0.99
        assert engine.filters["price_max"] == 50.0
        assert engine.filters["demand_min_30d"] == 15
        assert engine.filters["demand_min_7d"] == 10

    def test_a_caller_can_override_the_aud_band_without_losing_the_floors(self):
        engine = DecisionEngine(
            {"price_min": 10.0, "price_max": 40.0},
            marketplace="EBAY_AU",
        )

        assert engine.filters["price_min"] == 10.0
        assert engine.filters["price_max"] == 40.0
        assert engine.filters["demand_min_30d"] == 15

    def test_an_invalid_aud_band_falls_back_to_aud_not_gbp(self):
        engine = DecisionEngine(
            {"price_min": 80.0, "price_max": 20.0},
            marketplace="EBAY_AU",
        )

        assert engine.filters["price_min"] == 0.99
        assert engine.filters["price_max"] == 50.0


class TestTheAuVerdict:
    def test_an_au_listing_passes_the_marketplace_row_and_uses_a_dollar(self):
        verdict = DecisionEngine(marketplace="EBAY_AU").evaluate(
            _au_product(),
            _au_demand(),
            10.0,
        )

        rows = {row.name: row for row in verdict.filters}
        assert rows["Marketplace"].passed is True
        assert rows["Marketplace"].actual == "ebay_au"
        assert rows["Marketplace"].expected == "eBay Australia"
        assert rows["Price"].actual == "A$30.00"
        assert rows["Price"].expected == "A$0.99–A$50.00"
        assert verdict.verdict == "pass"

    def test_a_uk_listing_is_a_known_miss_for_the_au_market(self):
        verdict = DecisionEngine(marketplace="EBAY_AU").evaluate(
            _au_product(source="ebay_uk"),
            _au_demand(),
            10.0,
        )

        rows = {row.name: row for row in verdict.filters}
        assert rows["Marketplace"].passed is False
        assert verdict.verdict == "fail"

    def test_au_floors_are_the_au_ones(self):
        verdict = DecisionEngine(marketplace="EBAY_AU").evaluate(
            _au_product(),
            _au_demand(sold_30d=14, sold_7d=9),
            10.0,
        )

        rows = {row.name: row for row in verdict.filters}
        assert rows["Demand (30d)"].passed is False
        assert rows["Demand (7d)"].passed is False
        assert verdict.verdict == "fail"


class TestTheAuMoney:
    def test_profit_uses_the_au_card_and_the_private_branch(self):
        result = calculate_market_profit(
            30.0,
            10.0,
            market=get_marketplace("EBAY_AU"),
        )

        assert result["fee_table"]["key"] == "au-rate-card-2026-10-09"
        assert result["fee_table"]["currency"] == "AUD"
        assert result["breakdown"]["fees"]["seller"]["type"] == "private"
        assert result["breakdown"]["fees"]["seller"]["plan"] is None
        assert result["breakdown"]["fees"]["buyer_region"] == "au"
        assert result["profit"] > 0

    def test_a_market_without_a_card_refuses_to_borrow_the_uk_one(self):
        with pytest.raises(ValueError, match="No USD fee card"):
            calculate_market_profit(
                30.0,
                10.0,
                market=get_marketplace("EBAY_US"),
            )

    def test_the_scorecard_prints_a_dollars_and_the_au_card(self):
        product = _au_product()
        supplier = ScrapedProduct(
            source="aliexpress",
            title="Insulated Water Bottle 500ml",
            price=10.0,
            currency="AUD",
            url="https://www.aliexpress.com/item/1.html",
            shipping_cost=2.0,
            shipping_raw="A$2.00 shipping",
            verified=True,
        )
        verdict = DecisionEngine(marketplace="EBAY_AU").evaluate(
            product,
            _au_demand(),
            supplier.price,
        )

        text = format_scorecard(
            product,
            [supplier],
            _au_demand(),
            verdict,
            marketplace="EBAY_AU",
        )

        assert "A$30.00" in text
        assert "A$10.00" in text
        assert "au-rate-card-2026-10-09" in text
        assert "£" not in text


class TestSupplierCurrencyBoundary:
    def test_aud_rows_are_comparable_with_the_au_market(self):
        assert _supplier_currency_matches(
            ScrapedProduct(
                source="aliexpress",
                title="x",
                price=10.0,
                currency="AUD",
                url="u",
            ),
            "AUD",
        ) is True

    def test_usd_rows_are_not_relabelled_as_aud(self):
        assert _supplier_currency_matches(
            ScrapedProduct(
                source="cj_dropshipping",
                title="x",
                price=10.0,
                currency="USD",
                url="u",
            ),
            "AUD",
        ) is False

    def test_an_unstated_currency_is_only_accepted_on_the_uk_path(self):
        row = ScrapedProduct(
            source="bandq",
            title="x",
            price=10.0,
            url="u",
        )

        assert _supplier_currency_matches(row, "GBP") is True
        assert _supplier_currency_matches(row, "AUD") is False


def test_the_au_pipeline_searches_ebay_australia_with_the_aud_band(monkeypatch):
    captured = {}

    class FakeEbay:
        def __init__(self, marketplace=None):
            self.marketplace = get_marketplace(marketplace)
            self.observations = []
            self.query_observations = []

        def search(self, query, limit=5, price_band=None):
            captured["search_market"] = self.marketplace["id"]
            captured["search_band"] = price_band
            return [_au_product()]

        def get_sold_data(self, query, price_band=None):
            captured["sold_band"] = price_band
            return _au_demand()

        def close(self):
            pass

    async def _no_suppliers(query, progress=None, marketplace="EBAY_GB"):
        captured["supplier_market"] = marketplace
        return []

    monkeypatch.setattr(ap, "EbayScraper", FakeEbay)
    monkeypatch.setattr(ap, "search_all_suppliers", _no_suppliers)
    monkeypatch.setattr(
        ap,
        "apply_purchase_history",
        lambda demand, url, db=None: demand,
    )
    monkeypatch.setattr(ap, "resolve_stores", lambda **kwargs: [])

    results = asyncio.run(
        ap.run_analysis_pipeline("water bottle", marketplace="EBAY_AU")
    )

    assert captured["search_market"] == "EBAY_AU"
    assert captured["search_band"] == (0.99, 50.0)
    assert captured["sold_band"] == (0.99, 50.0)
    assert captured["supplier_market"] == "EBAY_AU"
    assert results["verdict"] is not None
    assert "A$" in results["scorecard"]
    assert "£" not in results["scorecard"]
    assert any(
        row.name == "Marketplace" and row.expected == "eBay Australia"
        for row in results["verdict"].filters
    )
