"""Phase E2 - AU Deep Search in AUD.

The run must follow one marketplace record end to end: the sold search, the
band and demand floors, the LLM prompt, the supplier bench, the currency on
every row and the store links. A USD supplier row is excluded with a sentence,
never converted, and an unready market is refused rather than run in GBP.
"""

from __future__ import annotations

import pytest

import deep_search as ds
import scrapers.ebay_sold as ebay_sold
from marketplaces import get_marketplace
from scrapers.base import ScrapedProduct
from scrapers.ebay_sold import EbaySoldData, EbaySoldItem, EbaySoldScraper


def _sold_data(currency="AUD"):
    return EbaySoldData(
        product_name="Widget",
        query="widget",
        total_sold_30d=20,
        total_sold_7d=12,
        price_min=15.0,
        price_max=25.0,
        price_avg=20.0,
        price_median=20.0,
        sold_prices=[15.0, 20.0, 25.0],
        items=[
            EbaySoldItem(
                title="Widget",
                price=20.0,
                url="https://www.ebay.com.au/itm/1",
                seller="seller",
                seller_url="https://www.ebay.com.au/usr/seller",
                sold_date="",
                condition="New",
            )
        ],
        items_source="ebay_sold_scrape",
        currency=currency,
    )


def _product(price, currency, title="Widget"):
    return ScrapedProduct(
        source="CJ Dropshipping",
        title=title,
        price=price,
        url="https://example.test/widget",
        currency=currency,
        store_name="CJ Dropshipping",
    )


class TestSoldScraperFollowsTheMarket:
    def test_au_defaults_are_aud_and_the_au_site(self):
        scraper = EbaySoldScraper("EBAY_AU")
        assert scraper.marketplace["id"] == "EBAY_AU"
        assert scraper.currency == "AUD"
        assert scraper.delivery_country == "AU"
        assert scraper.sold_url.startswith("https://www.ebay.com.au/")
        assert scraper._default_band == (0.99, 50.0)

    def test_uk_defaults_are_unchanged(self):
        scraper = EbaySoldScraper()
        assert scraper.marketplace["id"] == "EBAY_GB"
        assert scraper.currency == "GBP"
        assert scraper.delivery_country == "GB"
        assert scraper.sold_url.startswith("https://www.ebay.co.uk/")

    def test_the_browse_request_uses_au_currency_and_delivery(
        self, monkeypatch
    ):
        monkeypatch.setattr(ebay_sold, "EBAY_CLIENT_ID", "client")
        monkeypatch.setattr(ebay_sold, "EBAY_CLIENT_SECRET", "secret")
        seen: dict = {}

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"itemSummaries": []}

        def _get(url, **kwargs):
            seen["url"] = url
            seen.update(kwargs)
            return _Resp()

        monkeypatch.setattr(ebay_sold.requests, "get", _get)
        scraper = EbaySoldScraper("EBAY_AU")
        monkeypatch.setattr(scraper, "_get_token", lambda: "token")

        assert scraper._get_sold_via_api("drill") == []

        assert seen["headers"]["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_AU"
        assert "deliveryCountry:AU" in seen["params"]["filter"]
        assert "priceCurrency:AUD" in seen["params"]["filter"]
        assert "priceCurrency:GBP" not in seen["params"]["filter"]

    def test_a_foreign_storefront_is_not_observed_for_au(self):
        item = EbaySoldItem(
            title="Widget",
            price=20.0,
            url="https://www.ebay.com.au/itm/1",
            seller="seller",
            seller_url="https://www.ebay.com.au/usr/seller",
            sold_date="",
            store_url="https://www.ebay.co.uk/str/uk-shop",
        )
        from engine.stores import stores_from_items

        rows = stores_from_items(
            [item], site_base="https://www.ebay.com.au"
        )
        assert rows
        assert rows[0]["url_kind"] == "seller_profile"
        assert rows[0]["url"].startswith("https://www.ebay.com.au/usr/")

    def test_an_au_storefront_is_observed_for_au(self):
        item = EbaySoldItem(
            title="Widget",
            price=20.0,
            url="https://www.ebay.com.au/itm/1",
            seller="seller",
            seller_url="https://www.ebay.com.au/usr/seller",
            sold_date="",
            store_url="https://www.ebay.com.au/str/au-shop",
        )
        from engine.stores import stores_from_items

        rows = stores_from_items(
            [item], site_base="https://www.ebay.com.au"
        )
        assert rows
        assert rows[0]["url_kind"] == "observed"
        assert rows[0]["url"] == "https://www.ebay.com.au/str/au-shop"


class TestMarketPromptAndQueries:
    def test_au_prompt_asks_for_aud_and_the_au_market(self):
        prompt = ds._system_prompt(get_marketplace("EBAY_AU"))
        assert "AUD (A$)" in prompt
        assert "eBay Australia" in prompt
        assert "GBP (£)" not in prompt

    def test_uk_prompt_is_unchanged(self):
        market = get_marketplace("EBAY_GB")
        assert ds._system_prompt(market) == ds._SYSTEM_PROMPT

    def test_au_queries_only_use_the_au_bench(self):
        market = get_marketplace("EBAY_AU")
        queries = ds._search_queries("drill", market)
        joined = " ".join(queries)
        assert "aliexpress.com" in joined
        assert "cjdropshipping.com" in joined
        assert "diy.com" not in joined
        assert "toolstation.com" not in joined
        assert "joybuy" not in joined

    def test_uk_queries_still_cover_its_five_supplier_bench(self):
        market = get_marketplace("EBAY_GB")
        joined = " ".join(ds._search_queries("drill", market))
        for site in ("aliexpress.com", "cjdropshipping.com", "diy.com",
                     "toolstation.com", "joybuy.co.uk"):
            assert site in joined


class TestFastPathInAud:
    def test_aud_prices_and_a_usd_row_is_excluded_with_a_sentence(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            EbaySoldScraper,
            "get_sold_data",
            lambda self, query, **kwargs: _sold_data(),
        )

        async def _cj_search(self, query):
            return [_product(5.0, "AUD")]

        async def _ae_search(self, query):
            return [_product(2.0, "USD")]

        from scrapers.aliexpress import AliExpressScraper
        from scrapers.cjdropshipping import CJDropshippingScraper

        monkeypatch.setattr(CJDropshippingScraper, "search", _cj_search)
        monkeypatch.setattr(AliExpressScraper, "search", _ae_search)

        result = ds.deep_search_fast("widget", marketplace="EBAY_AU")

        assert result.marketplace == "EBAY_AU"
        assert result.currency == "AUD"
        assert result.currency_symbol == "A$"
        assert "A$15.00" in result.ebay_price_range
        assert all(s["currency"] == "AUD" for s in result.suppliers)
        assert [s["price"] for s in result.suppliers] == [5.0]
        assert "USD" in result.notes
        assert "excluded from the AUD comparison" in result.notes
        # The AU band is visible in the verdict's price row, not the GBP one.
        assert any(
            "A$0.99" in str(row.get("expected", ""))
            for row in result.filters_passed
        )

    def test_a_uk_run_still_uses_gbp(self, monkeypatch):
        monkeypatch.setattr(
            EbaySoldScraper,
            "get_sold_data",
            lambda self, query, **kwargs: _sold_data(currency="GBP"),
        )

        async def _cj_search(self, query):
            return [_product(5.0, "GBP")]

        async def _ae_search(self, query):
            return []

        from scrapers.aliexpress import AliExpressScraper
        from scrapers.cjdropshipping import CJDropshippingScraper

        monkeypatch.setattr(CJDropshippingScraper, "search", _cj_search)
        monkeypatch.setattr(AliExpressScraper, "search", _ae_search)

        result = ds.deep_search_fast("widget")
        assert result.currency == "GBP"
        assert "£15.00" in result.ebay_price_range


class TestFullPathInAud:
    def test_the_full_run_uses_the_au_prompt_and_bench(self, monkeypatch):
        monkeypatch.setattr(
            EbaySoldScraper,
            "get_sold_data",
            lambda self, query, **kwargs: _sold_data(),
        )
        seen: dict = {}

        def _web(query, num_results=8, market=None):
            seen.setdefault("queries", []).append(query)
            return []

        def _model(prompt, system=None, timeout=None):
            seen["system"] = system
            return (
                '{"product_name": "Widget", '
                '"ebay_price_range": "A$15.00 - A$25.00 (avg A$20.00)", '
                '"ebay_avg_price": 20.0, "supplier_candidates": []}'
            )

        def _discover(query, marketplace="EBAY_GB"):
            seen["discover_market"] = marketplace
            return []

        def _verify(query, cands, deadline=None, market=None):
            seen["verify_market"] = market["id"] if market else None
            return []

        monkeypatch.setattr(ds, "_web_search", _web)
        monkeypatch.setattr(ds, "_fetch_page_text", lambda *a, **k: "")
        monkeypatch.setattr(ds, "_ollama_generate", _model)
        monkeypatch.setattr(ds, "_discover_approved_suppliers", _discover)
        monkeypatch.setattr(ds, "_verify_supplier_candidates", _verify)
        monkeypatch.setattr(ds.time, "sleep", lambda seconds: None)

        result = ds.deep_search_product("widget", marketplace="EBAY_AU")

        assert result.currency == "AUD"
        assert result.currency_symbol == "A$"
        assert "AUD" in seen["system"]
        assert seen["discover_market"] == "EBAY_AU"
        assert seen["verify_market"] == "EBAY_AU"
        assert seen["queries"]
        assert all("eBay Australia" in q for q in seen["queries"][:1])


class TestVerdictUsesTheAuCardAndFloors:
    def test_au_verdict_is_priced_in_aud_with_au_floors(self):
        result = ds.DeepSearchResult(
            product_name="Widget",
            marketplace="EBAY_AU",
            currency="AUD",
            currency_symbol="A$",
        )
        result.ebay_avg_price = 20.0
        result.best_supplier_price = 5.0
        result.ebay_total_sold_30d = 20
        result.ebay_total_sold_7d = 12
        result.ebay_condition = "New"

        ds._calculate_profit_and_verdict(result, marketplace="EBAY_AU")

        assert result.currency == "AUD"
        assert result.verdict in {"PASS", "FAIL", "PENDING"}
        demand_rows = {
            row["name"]: row for row in result.filters_passed
        }
        assert demand_rows["Demand (30d)"]["expected"] == "≥15 sold"
        assert demand_rows["Demand (7d)"]["expected"] == "≥10 sold"


class TestApiCarriesTheMarket:
    def _client(self):
        from fastapi.testclient import TestClient

        from main import app

        return TestClient(app)

    def test_au_job_and_poll_are_labelled_aud(self, monkeypatch):
        import api.deep_search as api_ds

        monkeypatch.setattr(api_ds, "_spawn_job", lambda job: None)
        with self._client() as client:
            created = client.post(
                "/api/deep-search",
                json={"query": "widget"},
                headers={"X-Ebay-Marketplace": "EBAY_AU"},
            )
            assert created.status_code == 200
            body = created.json()
            assert body["marketplace"] == "EBAY_AU"
            assert body["currency"] == "AUD"
            assert body["currency_symbol"] == "A$"

            polled = client.get(
                f"/api/deep-search/jobs/{body['job_id']}"
            )
            assert polled.status_code == 200
            payload = polled.json()
            assert payload["marketplace"] == "EBAY_AU"
            assert payload["currency"] == "AUD"
            assert payload["currency_symbol"] == "A$"
            assert payload["verdict"] == "PENDING"

    def test_a_market_without_a_card_or_bench_is_still_refused(self):
        with self._client() as client:
            resp = client.post(
                "/api/deep-search",
                json={"query": "widget"},
                headers={"X-Ebay-Marketplace": "EBAY_US"},
            )
        assert resp.status_code == 422
        assert "not enabled" in resp.json()["detail"]
        assert "USD" in resp.json()["detail"]
