r"""A variant price range must not cost us the whole CJ response.

A2. CJ's `product/listV2` returns `sellPrice` as one number for a simple
SKU and as a range where the product has options: "119.61 -- 137.84". The
code did a bare `float()` on it, raised ValueError, and the handler that
caught it reported "CJ API unavailable" — so a single unparseable row
threw away every row in the response, and a supplier with valid
credentials contributed nothing at all.

Two things are under test:

  * the parser. A range takes its UPPER bound, matching availability's
    delivery-day rule, so a cost figure can never be quoted lower than the
    source said and a margin can never look better than it is (C1).
  * the batch. One unreadable row is dropped with a warning; the rest
    survive. Previously it was all or nothing.
"""

import pytest

from scrapers.cjdropshipping import CJDropshippingScraper, _sell_price_usd

pytestmark = pytest.mark.usefixtures("_no_network")


@pytest.fixture()
def _no_network(monkeypatch):
    """CJ would otherwise reach out with whatever credentials are in .env."""
    def _blocked(*args, **kwargs):
        raise AssertionError("network call attempted — this file runs offline")

    import requests
    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)


# ---------------------------------------------------------------------------
# 1. The parser
# ---------------------------------------------------------------------------

class TestThePriceParser:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            # A variant range -> its UPPER bound, never the cheap end.
            ("119.61 -- 137.84", 137.84),
            ("119.61 - 137.84", 137.84),
            ("119.61 to 137.84", 137.84),
            ("119.61~137.84", 137.84),
            # A plain figure is passed through untouched.
            ("12.99", 12.99),
            (119.61, 119.61),
            (42, 42.0),
            # Currency symbols and separators are not a reason to give up.
            ("$119.61", 119.61),
            ("GBP 12.99", 12.99),
            ("1,199.61", 1199.61),
        ],
    )
    def test_it_reads_the_figure_the_source_gave(self, raw, expected):
        assert _sell_price_usd(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", ["", None, "n/a", "--", [1], {}])
    def test_something_it_cannot_read_returns_zero_rather_than_raising(
        self, raw
    ):
        """0.0 is 'we did not read a price' — the same answer
        google_shopping._parse_price gives. Raising here is what deleted
        the response."""
        assert _sell_price_usd(raw) == 0.0


# ---------------------------------------------------------------------------
# 2. The batch survives one bad row
# ---------------------------------------------------------------------------

def _payload(*prices):
    return {
        "code": 200,
        "data": {
            "content": [
                {
                    "productList": [
                        {
                            "sellPrice": price,
                            "nameEn": f"Product {i}",
                            "id": str(i),
                            "storeName": "A Store",
                        }
                        for i, price in enumerate(prices)
                    ]
                }
            ]
        },
    }


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _search(monkeypatch, *prices):
    """Drive the real `_search_via_api` against a canned CJ payload."""
    import requests

    monkeypatch.setenv("CJ_API_KEY", "test-key")
    monkeypatch.setenv("CJ_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _Resp(_payload(*prices))
    )
    return CJDropshippingScraper()._search_via_api("cordless drill")


class TestOneBadRowDoesNotCostTheBatch:
    def test_a_range_priced_product_returns_a_row(self, monkeypatch):
        """THE regression. Every SKU in this payload is range-priced, which
        used to raise on the first one and report the API as unavailable."""
        rows = _search(monkeypatch, "119.61 -- 137.84", "10.00 - 12.00")

        assert len(rows) == 2
        # Upper bound of each range, converted USD -> GBP.
        assert rows[0].price == pytest.approx(round(137.84 * 0.79, 2))
        assert rows[1].price == pytest.approx(round(12.00 * 0.79, 2))
        assert rows[0].source == "cj_dropshipping"

    def test_an_unreadable_price_is_dropped_not_priced_at_zero(
        self, monkeypatch, capsys
    ):
        """A £0.00 supplier row would poison every margin computed from it.
        Dropping it and saying so is the honest answer (C1)."""
        rows = _search(monkeypatch, "n/a", "9.99")

        assert len(rows) == 1
        assert rows[0].price == pytest.approx(round(9.99 * 0.79, 2))
        assert "no readable price" in capsys.readouterr().out

    def test_a_payload_of_unreadable_prices_returns_no_rows_without_raising(
        self, monkeypatch
    ):
        assert _search(monkeypatch, "n/a", "", "sold out") == []
