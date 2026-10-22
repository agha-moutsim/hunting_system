"""The AliExpress RapidAPI seam — three honest behaviours.

The known key historically had no search endpoint, so this path failed
closed before any HTTP call. It must stay that way per key state:

  1. a search-capable key answers — rows convert to ScrapedProduct and
     carry fetch_method="api", with stock/shipping/Standard Shipping
     left unknown because the payload never stated them;
  2. RapidAPI refuses the key (403/404) — no rows, nothing invented,
     and the live-page scrape takes over;
  3. no key at all — fail closed exactly as before.

The connector is tested against a stubbed HTTP response (its title,
price, orders and rating mapping); the converter is tested with
connector-normalized rows. None of these tests reach the network.
"""

import pytest
import requests

from scrapers import aliexpress_api
from scrapers.aliexpress import AliExpressScraper
from scrapers.aliexpress_api import RapidAPIAliExpress

SCRAPER = AliExpressScraper()

# Connector-normalized row: what RapidAPIAliExpress.search_products
# actually returns (price parsed to a float, real orders only).
USABLE_ROW = {
    "title": "Water Bottle Insulated 500ml",
    "price": 8.99,
    "url": "https://www.aliexpress.com/item/1.html",
    "image_url": "https://ae01.alicdn.com/a.jpg",
    "orders": 1521,
    "rating": "4.8 (1,234 reviews)",
}


@pytest.fixture
def _search_key(monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", "rapidapi-search-key")


@pytest.fixture
def _answer_with(monkeypatch):
    """Make RapidAPIAliExpress.search_products return stubbed rows only."""

    def _apply(rows):
        monkeypatch.setattr(
            RapidAPIAliExpress,
            "search_products",
            lambda self, keyword, limit=30: list(rows),
        )

    return _apply


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestTheConnectorMapping:
    """RapidAPIAliExpress UI — what a payload row is allowed to mean."""

    def test_a_price_string_with_currency_still_parses(self, monkeypatch, _search_key):
        payload = {
            "data": [
                {
                    "product_title": "Water Bottle Insulated 500ml",
                    "price": "US $8.99",
                    "product_url": "https://www.aliexpress.com/item/1.html",
                    "rating": "4.8 (1,234 reviews)",
                }
            ]
        }
        monkeypatch.setattr(
            aliexpress_api.requests, "get", lambda *a, **k: _FakeResponse(payload)
        )
        rows = RapidAPIAliExpress().search_products("water bottle")

        assert rows[0]["price"] == 8.99
        assert rows[0]["title"] == "Water Bottle Insulated 500ml"
        assert rows[0]["url"] == "https://www.aliexpress.com/item/1.html"
        assert rows[0]["rating"] == "4.8 (1,234 reviews)"

    def test_a_sale_price_is_never_labelled_as_orders(self, monkeypatch, _search_key):
        payload = {
            "data": [
                {
                    "title": "Water Bottle Insulated 500ml",
                    "price": "US $8.99",
                    "url": "https://www.aliexpress.com/item/1.html",
                    "orders": 1521,
                    "product_sale_price": "US $7.24",
                }
            ]
        }
        monkeypatch.setattr(
            aliexpress_api.requests, "get", lambda *a, **k: _FakeResponse(payload)
        )
        row = RapidAPIAliExpress().search_products("water bottle")[0]

        assert row["orders"] == 1521

    def test_without_a_key_the_connector_raises(self, monkeypatch):
        monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
        with pytest.raises(ValueError):
            RapidAPIAliExpress().search_products("water bottle")


class TestRowsFromASearchKey:
    def test_usable_rows_convert_to_api_products(self, monkeypatch, _search_key, _answer_with):
        _answer_with([USABLE_ROW])
        rows = SCRAPER._search_via_rapidapi("water bottle")

        assert [p.fetch_method for p in rows] == ["api"]
        row = rows[0]
        assert row.source == "aliexpress"
        assert row.title == "Water Bottle Insulated 500ml"
        assert row.price == round(8.99 * 0.79, 2)
        assert row.url == "https://www.aliexpress.com/item/1.html"
        assert row.image_url == "https://ae01.alicdn.com/a.jpg"
        assert row.seller_orders == "1521"
        assert row.review_rating == 4.8
        assert row.review_count == 1234
        assert row.review_verified is True
        assert row.review_source == "rapidapi"
        assert row.verified is True

    def test_unstated_stock_and_shipping_stay_unknown(self, monkeypatch, _search_key, _answer_with):
        _answer_with([USABLE_ROW])
        row = SCRAPER._search_via_rapidapi("water bottle")[0]

        # C1/C13 — the payload never said, so nothing is assumed.
        assert (row.in_stock, row.stock_raw, row.availability_url) == ("", "", "")
        assert (row.shipping_cost, row.shipping_days, row.shipping_raw) == (0.0, 0, "")
        assert row.standard_shipping_available is None
        assert row.shipping_methods == []

    def test_a_rating_dict_gives_rating_and_count(self, monkeypatch, _search_key, _answer_with):
        _answer_with([
            {
                "title": "Stereo Headphones Wireless New",
                "price": 5.0,
                "url": "https://www.aliexpress.com/item/4.html",
                "rating": {"rating": 4.2, "count": "56"},
            }
        ])
        row = SCRAPER._search_via_rapidapi("headphones")[0]

        assert row.review_rating == 4.2
        assert row.review_count == 56
        assert row.review_verified is True

    def test_a_rating_string_without_a_count_has_no_count(self, monkeypatch, _search_key, _answer_with):
        _answer_with([
            {
                "title": "Stereo Headphones Wireless New",
                "price": 5.0,
                "url": "https://www.aliexpress.com/item/5.html",
                "rating": "4.0",
            }
        ])
        row = SCRAPER._search_via_rapidapi("headphones")[0]

        assert row.review_rating == 4.0
        assert row.review_count is None
        assert row.review_verified is True


class TestUnusableRowsAreSkipped:
    def test_rows_missing_title_price_or_url_never_make_a_product(
        self, monkeypatch, _search_key, _answer_with
    ):
        _answer_with([
            {"title": "Usb", "price": 5.0, "url": "https://www.aliexpress.com/item/1.html"},
            {"title": "No Price Headphones", "price": None, "url": "https://www.aliexpress.com/item/2.html"},
            {"title": "No URL Headphones 10x", "price": 5.0, "url": ""},
            {"title": "Zero Price Headphones", "price": 0.0, "url": "https://www.aliexpress.com/item/3.html"},
            "not-a-dict",
        ])
        assert SCRAPER._search_via_rapidapi("headphones") == []


class TestRefusalAndAbsence:
    def test_a_rapidapi_refusal_returns_no_rows(self, monkeypatch, _search_key):
        def _refuse(self, keyword, limit=30):
            raise requests.HTTPError("403 Client Error")

        monkeypatch.setattr(RapidAPIAliExpress, "search_products", _refuse)
        assert SCRAPER._search_via_rapidapi("water bottle") == []

    def test_an_empty_answer_returns_no_rows(self, monkeypatch, _search_key, _answer_with):
        _answer_with([])
        assert SCRAPER._search_via_rapidapi("water bottle") == []

    def test_without_a_key_it_fails_closed(self, monkeypatch):
        monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
        assert SCRAPER._search_via_rapidapi("water bottle") == []
