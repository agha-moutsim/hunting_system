"""Currency-safe supplier rows and AUD price gates.

The AU market must never compare a USD supplier figure with an AUD eBay
listing. These pins cover the three paths that can produce a supplier price:

  * AliGate is asked for the market's own country/currency, so an AUD row
    arrives in AUD and passes through unchanged;
  * CJ's USD `sellPrice` is tagged USD for a non-GBP market, never converted
    through the UK's fixed 0.79 rate;
  * Google Shopping rows carry the currency of the scope they were searched
    in.

They also pin the eBay local band gate to the band's own currency rather than
the active GBP range.
"""

from __future__ import annotations

import asyncio
import time

from scrapers.base import ScrapedProduct
from scrapers.cjdropshipping import CJDropshippingScraper
from scrapers.ebay import EbayScraper
from scrapers import aliexpress as ae
from scrapers import serpapi_discovery as sd
from engine.sourcing import shipping_is_known


def test_au_aligate_is_asked_for_aud_and_keeps_the_aud_price(monkeypatch):
    captured = {}

    class FakeClient:
        api_key = "test-key"

        def __init__(self, **kwargs):
            captured.update(kwargs)

        def search_products(self, keyword, limit=30):
            return [{
                "title": "Water Bottle Insulated 500ml",
                "price": 12.99,
                "currency": "AUD",
                "url": "https://www.aliexpress.com/item/1.html",
            }]

    monkeypatch.setattr(ae, "RapidAPIAliExpress", FakeClient)
    scraper = ae.AliExpressScraper(marketplace="EBAY_AU")

    rows = scraper._search_via_rapidapi("water bottle")

    assert captured == {
        "country": "AU",
        "currency": "AUD",
        "locale": "en_AU",
    }
    assert len(rows) == 1
    assert rows[0].price == 12.99
    assert rows[0].currency == "AUD"


def test_au_aligate_row_in_another_currency_is_skipped(monkeypatch):
    class FakeClient:
        api_key = "test-key"

        def __init__(self, **kwargs):
            pass

        def search_products(self, keyword, limit=30):
            return [{
                "title": "Water Bottle Insulated 500ml",
                "price": 8.99,
                "currency": "USD",
                "url": "https://www.aliexpress.com/item/1.html",
            }]

    monkeypatch.setattr(ae, "RapidAPIAliExpress", FakeClient)
    scraper = ae.AliExpressScraper(marketplace="EBAY_AU")

    assert scraper._search_via_rapidapi("water bottle") == []


def test_au_aliexpress_browser_fallback_fails_closed(monkeypatch):
    scraper = ae.AliExpressScraper(marketplace="EBAY_AU")
    monkeypatch.setattr(scraper, "_search_via_rapidapi", lambda query: [])

    async def _must_not_fetch(url):
        raise AssertionError("AU must not scrape an unstated page currency")

    monkeypatch.setattr(scraper, "fetch", _must_not_fetch)

    assert asyncio.run(scraper.search("water bottle")) == []


def test_uk_aligate_keeps_its_historical_scope(monkeypatch):
    captured = {}

    class FakeClient:
        api_key = "test-key"

        def __init__(self, **kwargs):
            captured.update(kwargs)

        def search_products(self, keyword, limit=30):
            return [{
                "title": "Water Bottle Insulated 500ml",
                "price": 8.99,
                "currency": "USD",
                "url": "https://www.aliexpress.com/item/1.html",
            }]

    monkeypatch.setattr(ae, "RapidAPIAliExpress", FakeClient)
    scraper = ae.AliExpressScraper()

    rows = scraper._search_via_rapidapi("water bottle")

    assert captured == {}
    assert rows[0].price == round(8.99 * 0.79, 2)
    assert rows[0].currency == "GBP"


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _cj_payload(price="10.00"):
    return {
        "code": 200,
        "data": {
            "content": [{
                "productList": [{
                    "id": "cj-1",
                    "nameEn": "Water Bottle Insulated 500ml",
                    "sellPrice": price,
                    "storeName": "A Store",
                }],
            }],
        },
    }


def _cj_get(monkeypatch, payload, captured):
    import requests

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["params"] = params
        return _FakeResponse(payload)

    monkeypatch.setenv("CJ_API_KEY", "test-key")
    monkeypatch.setenv("CJ_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr(requests, "get", fake_get)


def test_cj_au_carries_usd_without_a_gbp_conversion(monkeypatch):
    captured = {}
    _cj_get(monkeypatch, _cj_payload(), captured)
    scraper = CJDropshippingScraper(marketplace="EBAY_AU")

    rows = scraper._search_via_api("water bottle")

    assert captured["params"]["countryCode"] == "AU"
    assert rows[0].price == 10.0
    assert rows[0].currency == "USD"


def test_cj_uk_keeps_the_historical_gbp_conversion(monkeypatch):
    captured = {}
    _cj_get(monkeypatch, _cj_payload(), captured)
    scraper = CJDropshippingScraper(marketplace="EBAY_GB")

    rows = scraper._search_via_api("water bottle")

    assert captured["params"]["countryCode"] == "GB"
    assert rows[0].price == 7.9
    assert rows[0].currency == "GBP"


def test_serpapi_row_carries_the_google_scope_currency():
    row = sd._row_for(
        "aliexpress",
        {"title": "Water Bottle", "thumbnail": ""},
        {
            "link": "https://www.aliexpress.com/item/1.html",
            "title": "Water Bottle",
            "extracted_price": 12.0,
            "name": "AliExpress",
        },
        currency="AUD",
    )

    assert row is not None
    assert row.currency == "AUD"
    assert row.price == 12.0


def _browse_payload():
    return {
        "itemSummaries": [
            {
                "title": "Cheap widget",
                "price": {"value": 0.99},
                "itemWebUrl": "https://www.ebay.com.au/itm/1",
                "condition": "New",
                "seller": {"username": "seller-a"},
            },
            {
                "title": "High widget",
                "price": {"value": 50.01},
                "itemWebUrl": "https://www.ebay.com.au/itm/2",
                "condition": "New",
                "seller": {"username": "seller-b"},
            },
        ],
    }


def _ready_scraper(monkeypatch, payload):
    def fake_get(*args, **kwargs):
        return _FakeResponse(payload)

    monkeypatch.setattr("scrapers.ebay.requests.get", fake_get)
    scraper = EbayScraper("EBAY_AU")
    scraper._token = "test-token"
    scraper._token_expiry = time.time() + 3600
    return scraper


def test_ebay_au_search_gate_uses_the_explicit_aud_band(monkeypatch):
    scraper = _ready_scraper(monkeypatch, _browse_payload())

    rows = scraper._search_api("widget", price_band=(0.99, 50.00))

    assert [row.price for row in rows] == [0.99]


def test_ebay_au_sold_gate_uses_the_explicit_aud_band(monkeypatch):
    scraper = _ready_scraper(monkeypatch, _browse_payload())

    demand = scraper._get_sold_api("widget", price_band=(0.99, 50.00))

    assert demand.active_listings_in_band == 1
    assert demand.excluded_over_band == 1
    assert demand.currency == "AUD"


def test_aud_zero_shipping_is_a_known_zero():
    row = ScrapedProduct(
        source="aliexpress",
        title="Water Bottle",
        price=12.99,
        currency="AUD",
        url="https://www.aliexpress.com/item/1.html",
        shipping_cost=0.0,
        shipping_raw="A$0.00 shipping",
    )

    assert shipping_is_known(row) is True
