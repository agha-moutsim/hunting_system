"""Phase J — the marketplace registry and its hard rules.

These tests are about labels that can false a number:

  * an unknown marketplace is refused, never treated as EBAY_GB;
  * a non-UK market has NO fee table, so no GBP fee can be attached to a USD
    sale;
  * the deals board stores each market separately and never mixes them;
  * the header selector can only offer a market whose deals URL was observed
    reachable.

The URL reachability and card counts were measured live on 2026-10-21 (HTTP
200; cards read for all five offered markets) and are recorded in
config.MARKETPLACES. No test here reaches the network.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import db.database as dbmod
from db.database import Base
from db.models import DealItem as DealItemRow
from hunter import deals
from marketplaces import (
    UnknownMarketplace,
    fee_warning,
    format_money,
    get_marketplace,
    offered_marketplaces,
)
from scrapers.ebay import EbayScraper, _base_api_filter
from scrapers.ebay_deals import DealItem, EbayDealsScraper, parse_deals_page


def _client():
    from fastapi.testclient import TestClient

    from main import app

    return TestClient(app)


def _session(tmp_path, monkeypatch):
    path = (tmp_path / "markets.db").as_posix()
    engine = create_engine(f"sqlite:///{path}")
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "SessionLocal", factory)
    Base.metadata.create_all(engine)
    return factory


class TestRegistry:
    def test_uk_is_the_default_and_keeps_the_only_fee_table(self):
        uk = get_marketplace()
        assert uk["id"] == "EBAY_GB"
        assert uk["currency"] == "GBP"
        assert uk["fee_table"] == "uk-rate-card-2026-09-30"
        assert fee_warning(uk) is None

    def test_every_other_market_has_no_fee_table_and_says_so(self):
        for market_id in ("EBAY_US", "EBAY_DE", "EBAY_AU", "EBAY_CA"):
            market = get_marketplace(market_id)
            assert market["fee_table"] is None
            warning = fee_warning(market)
            assert warning
            assert market["currency"] in warning
            assert "UK-only" in warning

    def test_an_unknown_market_is_refused_not_silently_made_uk(self):
        with pytest.raises(UnknownMarketplace) as exc:
            get_marketplace("EBAY_XX")
        assert "EBAY_XX" in str(exc.value)
        assert "EBAY_GB" in str(exc.value)

    def test_only_observed_reachable_deals_pages_are_offered(self):
        offered = offered_marketplaces()
        ids = {m["id"] for m in offered}
        assert "EBAY_GB" in ids
        assert "EBAY_IE" not in ids  # redirects to splashui/distil, not a board
        for market in offered:
            assert market["deals_url"].startswith("https://")
            assert market["deals_http_status"] == 200
            assert market["deals_checked_at"] == "2026-10-21"

    def test_money_is_formatted_in_its_own_currency(self):
        assert format_money(12.5, "GBP") == "£12.50"
        assert format_money(12.5, "USD") == "$12.50"
        assert format_money(12.5, "EUR") == "€12.50"
        assert format_money(None, "USD") == ""


class TestBrowseWiring:
    def test_the_browse_filter_uses_the_selected_delivery_country(self):
        assert "deliveryCountry:GB" in _base_api_filter(get_marketplace("EBAY_GB"))
        assert "deliveryCountry:US" in _base_api_filter(get_marketplace("EBAY_US"))

    def test_the_scraper_keeps_the_market_it_was_given(self):
        scraper = EbayScraper("EBAY_US")
        try:
            assert scraper.marketplace["id"] == "EBAY_US"
            assert scraper.marketplace["currency"] == "USD"
            assert scraper.marketplace["site_base"] == "https://www.ebay.com"
        finally:
            scraper.close()

    def test_a_deals_card_without_a_url_falls_back_to_its_own_market(self):
        html = '{"listingId":"123456789012","title":"A Real Thing"}'
        items = parse_deals_page(html, site_base="https://www.ebay.com")
        assert items[0].item_url == "https://www.ebay.com/itm/123456789012"

    def test_the_deals_scraper_targets_the_selected_market(self):
        scraper = EbayDealsScraper(marketplace="EBAY_US")
        assert scraper.deals_url == "https://www.ebay.com/deals"
        assert scraper.marketplace["currency"] == "USD"


class TestDealsAreStoredPerMarket:
    def test_saving_one_market_leaves_the_other_market_alone(self, tmp_path, monkeypatch):
        session = _session(tmp_path, monkeypatch)()
        try:
            deals.save_deals(
                [DealItem(listing_id="111111111111", title="UK thing", price=10.0,
                          currency="GBP")],
                session,
                marketplace="EBAY_GB",
            )
            deals.save_deals(
                [DealItem(listing_id="222222222222", title="US thing", price=20.0,
                          currency="USD")],
                session,
                marketplace="EBAY_US",
            )

            uk = deals.load_deals(session, marketplace="EBAY_GB")
            us = deals.load_deals(session, marketplace="EBAY_US")
            assert [row["listing_id"] for row in uk] == ["111111111111"]
            assert [row["listing_id"] for row in us] == ["222222222222"]
            assert uk[0]["price_label"] == "£10.00"
            assert us[0]["price_label"] == "$20.00"
            assert deals.board_meta(session, marketplace="EBAY_GB")["total"] == 1
            assert deals.board_meta(session, marketplace="EBAY_US")["total"] == 1
        finally:
            session.close()

    def test_the_same_listing_id_can_sit_on_two_markets(self, tmp_path, monkeypatch):
        """One market's refresh must not steal the other's card. The composite
        rule is what makes that possible; a global unique listing_id would
        either reject the second row or force a move."""
        session = _session(tmp_path, monkeypatch)()
        try:
            deals.save_deals(
                [DealItem(listing_id="444444444444", title="UK card",
                          price=10.0, currency="GBP")],
                session, marketplace="EBAY_GB",
            )
            deals.save_deals(
                [DealItem(listing_id="444444444444", title="US card",
                          price=20.0, currency="USD")],
                session, marketplace="EBAY_US",
            )

            assert [
                row["title"] for row in deals.load_deals(
                    session, marketplace="EBAY_GB"
                )
            ] == ["UK card"]
            assert [
                row["title"] for row in deals.load_deals(
                    session, marketplace="EBAY_US"
                )
            ] == ["US card"]
        finally:
            session.close()

    def test_every_preexisting_row_is_a_uk_observation(self, tmp_path, monkeypatch):
        session = _session(tmp_path, monkeypatch)()
        try:
            session.add(DealItemRow(
                listing_id="333333333333",
                title="old row",
                item_url="https://www.ebay.co.uk/itm/333333333333",
                price=5.0,
                currency="GBP",
            ))
            session.commit()
            assert deals.load_deals(session, marketplace="EBAY_GB")
            assert not deals.load_deals(session, marketplace="EBAY_US")
        finally:
            session.close()


class TestTheDealItemMigration:
    def test_an_old_global_unique_is_rebuilt_without_losing_rows(
        self, tmp_path, monkeypatch
    ):
        """The deployed table had UNIQUE(listing_id). SQLite cannot drop a
        table-level constraint, so the rebuild is exercised here on the old
        shape: one row must survive and the new rule must be composite."""
        path = (tmp_path / "old_deals.db").as_posix()
        engine = create_engine(f"sqlite:///{path}")
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE deal_items ("
                "id INTEGER NOT NULL PRIMARY KEY, "
                "listing_id VARCHAR(32) NOT NULL UNIQUE, "
                "title TEXT NOT NULL, item_url TEXT NOT NULL, "
                "image_url TEXT, price FLOAT, currency VARCHAR(8), "
                "seller VARCHAR(64), store_name VARCHAR(128), store_url TEXT, "
                "store_verified BOOLEAN, condition VARCHAR(64), "
                "position INTEGER, source VARCHAR(32), "
                "source_label VARCHAR(128), fetched_at DATETIME NOT NULL)"
            ))
            conn.execute(text(
                "INSERT INTO deal_items (listing_id, title, item_url, "
                "fetched_at) VALUES ('555555555555', 'kept', "
                "'https://www.ebay.co.uk/itm/555555555555', "
                "'2026-10-20 00:00:00')"
            ))
        monkeypatch.setattr(dbmod, "engine", engine)

        assert dbmod.ensure_deal_items_table() is False
        unique = {
            tuple(c["column_names"])
            for c in inspect(engine).get_unique_constraints("deal_items")
        }
        assert ("marketplace", "listing_id") in unique
        assert ("listing_id",) not in unique
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT marketplace, title FROM deal_items"
            )).fetchone()
        assert row == ("EBAY_GB", "kept")

        # The second import/run must be a no-op, not another rebuild.
        assert dbmod.ensure_deal_items_table() is False
        with engine.connect() as conn:
            assert conn.execute(text(
                "SELECT COUNT(*) FROM deal_items"
            )).scalar() == 1


class TestApiRefusesWhatItCannotPrice:
    def test_the_market_list_is_the_selector_source(self):
        with _client() as client:
            body = client.get("/api/markets").json()

        assert body["default"] == "EBAY_GB"
        assert {m["id"] for m in body["marketplaces"]} >= {
            "EBAY_GB", "EBAY_US", "EBAY_DE", "EBAY_AU", "EBAY_CA"
        }
        us = next(m for m in body["marketplaces"] if m["id"] == "EBAY_US")
        assert us["currency"] == "USD"
        assert us["fee_table"] is None
        assert "UK-only" in us["fee_warning"]

    def test_a_non_uk_fee_table_request_is_a_sentence_not_a_gbp_number(self):
        with _client() as client:
            resp = client.get(
                "/api/fees/table",
                headers={"X-EBay-Marketplace": "EBAY_US"},
            )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "UK-only" in detail
        assert "USD" in detail

    def test_the_query_parameter_works_without_the_header(self):
        with _client() as client:
            resp = client.get(
                "/api/fees/table", params={"marketplace": "EBAY_US"}
            )

        assert resp.status_code == 422
        assert "UK-only" in resp.json()["detail"]

    def test_an_unknown_market_gets_a_422_with_the_known_ids(self):
        with _client() as client:
            resp = client.get(
                "/api/fees/table",
                headers={"X-EBay-Marketplace": "EBAY_ZZ"},
            )

        assert resp.status_code == 422
        assert "EBAY_ZZ" in resp.json()["detail"]
        assert "EBAY_GB" in resp.json()["detail"]

class TestNonUkAnalyzeIsSearchOnly:
    def test_it_returns_the_listing_and_demand_but_no_profit(self, monkeypatch):
        from scrapers.base import DemandData, ScrapedProduct

        class FakeScraper:
            def __init__(self, marketplace=None):
                self.marketplace = get_marketplace(marketplace)
                self.query_observations = []

            def search_checked(self, query, limit=5, price_band=None):
                assert price_band is None, "a US search must not carry the GBP band"
                return [ScrapedProduct(
                    source="ebay_us",
                    title="A US widget",
                    price=20.0,
                    currency="USD",
                    url="https://www.ebay.com/itm/123456789012",
                    condition="New",
                )]

            def get_sold_data(self, query, price_band=None):
                assert price_band is None
                return DemandData(verified=False, currency="USD")

            def close(self):
                pass

        monkeypatch.setattr("scrapers.ebay.EbayScraper", FakeScraper)
        monkeypatch.setattr("api.analyze.save_analysis_to_db", lambda raw: None)

        with _client() as client:
            resp = client.post(
                "/api/analyze",
                json={"query": "widget", "is_url": False},
                headers={"X-Ebay-Marketplace": "EBAY_US"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["marketplace"] == "EBAY_US"
        assert body["currency"] == "USD"
        assert body["ebay_product"]["price"] == 20.0
        assert body["ebay_product"]["currency"] == "USD"
        assert body["supplier_matches"] == []
        assert body["verdict"] is None
        assert any("search-only" in e for e in body["errors"])
        assert any("USD" in e for e in body["errors"])

    def test_deep_search_refuses_a_market_it_cannot_price(self):
        with _client() as client:
            resp = client.post(
                "/api/deep-search",
                json={"query": "widget"},
                headers={"X-Ebay-Marketplace": "EBAY_US"},
            )

        assert resp.status_code == 422
        assert "UK-only" in resp.json()["detail"]

    def test_a_failed_refresh_is_reported_in_the_meta(self, tmp_path, monkeypatch):
        session = _session(tmp_path, monkeypatch)()
        try:
            def _boom(**kwargs):
                raise RuntimeError("deals page returned 403")

            monkeypatch.setattr(deals, "refresh", _boom)
            result = deals.refresh_if_stale(
                session, force=True, marketplace="EBAY_US"
            )
            assert "403" in result["error"]
            meta = deals.board_meta(session, marketplace="EBAY_US")
            assert "403" in meta["last_refresh_error"]
            assert meta["last_refresh_error_at"]
        finally:
            deals._clear_refresh_error("EBAY_US")
            session.close()

class TestNestedDealsPages:
    def test_a_us_style_nested_card_is_read_not_silently_dropped(self):
        """The US page is /globaldeals, not /deals, and its cards nest the
        title, image and price inside objects. The flat regex sees zero there;
        a zero-card board would look like eBay had no deals. This fixture is
        hand-written, not a live capture, and only exercises the shape."""
        html = (
            '{"listings":['
            '{"listingId":"123456789012",'
            '"title":{"_type":"TextualDisplay","textSpans":['
            '{"_type":"TextSpan","text":"Caf\\u00e9 \\"Special\\""}]},'
            '"image":{"_type":"Image","URL":"https://i.ebayimg.com/a.jpg"},'
            '"displayPrice":{"value":{"value":19.99,"currency":"USD"}}},'
            '{"listingId":"123456789013",'
            '"title":{"_type":"TextualDisplay","textSpans":['
            '{"_type":"TextSpan","text":"Second card"}]},'
            '"displayPrice":{"value":{"value":5,"currency":"USD"}}}'
            ']}'
        )
        items = parse_deals_page(html, site_base="https://www.ebay.com")
        assert [item.listing_id for item in items] == [
            "123456789012",
            "123456789013",
        ]
        assert items[0].title == 'Café "Special"'
        assert items[0].price == 19.99
        assert items[0].currency == "USD"
        assert items[0].item_url == "https://www.ebay.com/itm/123456789012"
        assert items[1].price == 5.0
