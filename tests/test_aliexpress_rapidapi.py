"""The AliExpress RapidAPI (AliGate) seam — three honest behaviours.

The prior listing was removed from RapidAPI (404); the seam now targets
AliGate's /api/v2/search/text. It must stay that way per key state:

  1. a search-capable key answers — rows convert to ScrapedProduct and
     carry fetch_method="api", with stock/shipping/Standard Shipping
     left unknown because the payload never stated them;
  2. RapidAPI refuses the key (refusal, renamed parameter, monthly cap) —
     the gateway's own reason is logged, no rows are invented, and the
     live-page scrape takes over;
  3. no key at all — fail closed exactly as before.

Currency is treated as the payload's own admission: GBP rows pass through
unconverted, USD rows (or rows that name none) convert at the scraper's
fixed rate, and any other stated currency is skipped — never ranked as
GBP. The connector is tested against a stubbed HTTP response; the
converter is tested with connector-normalized rows. No test reaches the
network.
"""

import pytest
import requests

from scrapers import aliexpress_api
from scrapers.aliexpress import AliExpressScraper
from scrapers.aliexpress_api import RapidAPIAliExpress

SCRAPER = AliExpressScraper()

# Connector-normalized row: what RapidAPIAliExpress.search_products
# returns (price parsed to a float, real orders only, currency as stated).
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
    def __init__(self, payload, status_code=200, text="OK"):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")

    def json(self):
        return self._payload


def _stub_get(monkeypatch, response):
    monkeypatch.setattr(
        aliexpress_api.requests, "get", lambda *a, **k: response
    )


class TestTheConnectorMapping:
    """RapidAPIAliExpress UI — what an AliGate payload row is allowed to mean."""

    def test_an_aligate_row_carries_only_stated_fields(
        self, monkeypatch, _search_key
    ):
        payload = {
            "meta": {"code": 200, "execution_time": "1.2s"},
            "products": [
                {
                    "title": "Water Bottle Insulated 500ml",
                    "price": {
                        "min_value": 12.77,
                        "max_value": 18.50,
                        "currency": "GBP",
                    },
                    "ratings": 4.7,
                    "sales": 1200,
                    "product_id": "1005006474515657",
                }
            ],
        }
        _stub_get(monkeypatch, _FakeResponse(payload))
        rows = RapidAPIAliExpress().search_products("water bottle")

        assert rows[0]["price"] == 12.77
        assert rows[0]["currency"] == "GBP"
        assert rows[0]["title"] == "Water Bottle Insulated 500ml"
        # A real popularity count, under the key that states it.
        assert rows[0]["orders"] == 1200
        assert rows[0]["rating"] == 4.7
        # The canonical item URL rebuilt from the payload's own product_id.
        assert (
            rows[0]["url"]
            == "https://www.aliexpress.com/item/1005006474515657.html"
        )
        assert rows[0]["image_url"] == ""

    def test_a_price_string_with_currency_still_parses(self, monkeypatch, _search_key):
        payload = {
            "products": [
                {
                    "product_title": "Water Bottle Insulated 500ml",
                    "price": "US $8.99",
                    "product_url": "https://www.aliexpress.com/item/1.html",
                    "rating": "4.8 (1,234 reviews)",
                }
            ]
        }
        _stub_get(monkeypatch, _FakeResponse(payload))
        rows = RapidAPIAliExpress().search_products("water bottle")

        assert rows[0]["price"] == 8.99
        assert rows[0]["currency"] is None
        assert rows[0]["title"] == "Water Bottle Insulated 500ml"
        assert rows[0]["url"] == "https://www.aliexpress.com/item/1.html"
        assert rows[0]["rating"] == "4.8 (1,234 reviews)"

    def test_a_sale_price_is_never_labelled_as_orders(self, monkeypatch, _search_key):
        payload = {
            "products": [
                {
                    "title": "Water Bottle Insulated 500ml",
                    "price": {"min_value": 8.99, "currency": "USD"},
                    "orders": 1521,
                    "product_sale_price": "US $7.24",
                }
            ]
        }
        _stub_get(monkeypatch, _FakeResponse(payload))
        rows = RapidAPIAliExpress().search_products("water bottle")

        assert rows[0]["orders"] == 1521

    @pytest.mark.parametrize("envelope", [
        [  # a bare list
            {"title": "Water Bottle Insulated 500ml"},
        ],
        {"data": [{"title": "Water Bottle Insulated 500ml"}]},
        {"items": [{"title": "Water Bottle Insulated 500ml"}]},
        {"results": [{"title": "Water Bottle Insulated 500ml"}]},
    ])
    def test_rows_are_found_wherever_the_envelope_puts_them(
        self, monkeypatch, _search_key, envelope
    ):
        _stub_get(monkeypatch, _FakeResponse(envelope))
        rows = RapidAPIAliExpress().search_products("water bottle")
        assert rows[0]["title"] == "Water Bottle Insulated 500ml"

    def test_the_host_follows_the_environment(self, monkeypatch, _search_key):
        monkeypatch.setenv(
            "RAPIDAPI_HOST", "other-aliexpress.p.rapidapi.com"
        )
        assert RapidAPIAliExpress().host == "other-aliexpress.p.rapidapi.com"

    def test_the_default_host_is_aligate(self, monkeypatch):
        monkeypatch.delenv("RAPIDAPI_HOST", raising=False)
        assert (
            RapidAPIAliExpress().host
            == "aligate-aliexpress-data-api.p.rapidapi.com"
        )

    def test_a_refusal_carries_the_gateway_s_own_reason(
        self, monkeypatch, _search_key, capsys
    ):
        _stub_get(
            monkeypatch,
            _FakeResponse({}, status_code=403, text="You are not subscribed"),
        )
        with pytest.raises(requests.RequestException):
            RapidAPIAliExpress().search_products("water bottle")
        out = capsys.readouterr().out
        assert "[WARN] AliGate RapidAPI refused: 403" in out
        assert "You are not subscribed" in out

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
        # No currency stated by the payload: the long-standing USD
        # assumption applies.
        assert row.price == round(8.99 * 0.79, 2)
        assert row.url == "https://www.aliexpress.com/item/1.html"
        assert row.image_url == "https://ae01.alicdn.com/a.jpg"
        assert row.seller_orders == "1521"
        assert row.review_rating == 4.8
        assert row.review_count == 1234
        assert row.review_verified is True
        assert row.review_source == "rapidapi"
        assert row.verified is True

    def test_a_gbp_row_passes_through_unconverted(
        self, monkeypatch, _search_key, _answer_with
    ):
        _answer_with([
            {
                "title": "Water Bottle Insulated 500ml",
                "price": 12.77,
                "currency": "GBP",
                "url": "https://www.aliexpress.com/item/7.html",
            }
        ])
        row = SCRAPER._search_via_rapidapi("water bottle")[0]

        # The payload said GBP; an FX pass-through here would be wrong.
        assert row.price == 12.77
        assert row.price != round(12.77 * 0.79, 2)

    def test_rows_in_currencies_without_a_gbp_conversion_are_skipped(
        self, monkeypatch, _search_key, _answer_with
    ):
        _answer_with([
            {
                "title": "Water Bottle Insulated 500ml",
                "price": 14.99,
                "currency": "EUR",
                "url": "https://www.aliexpress.com/item/8.html",
            }
        ])
        assert SCRAPER._search_via_rapidapi("water bottle") == []

    def test_an_aligate_row_converts_with_its_rating_kept(
        self, monkeypatch, _search_key, _answer_with
    ):
        _answer_with([
            {
                "title": "Wireless Earbuds Pro Model X",
                "price": 12.77,
                "currency": "GBP",
                "url": "https://www.aliexpress.com/item/6.html",
                "rating": 4.7,
                "orders": 990,
            }
        ])
        row = SCRAPER._search_via_rapidapi("earbuds")[0]

        assert row.price == 12.77
        assert row.review_rating == 4.7
        assert row.review_verified is True
        assert row.seller_orders == "990"

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
