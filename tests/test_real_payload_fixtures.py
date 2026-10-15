"""The parsers, against REAL API responses instead of imagined ones.

Every other test in this suite feeds the code JSON somebody typed. These
feed it bytes eBay and SerpApi actually returned, captured by
tests/capture_fixtures.py and committed under tests/fixtures/.

That distinction matters more than it sounds. The hand-written fixtures
cannot tell you that eBay renamed `itemWebUrl`, that SerpApi stopped sending
`extracted_price`, or that `seller` stopped being a nested object - those
changes pass every invented test and then break a live product. A real
payload fails loudly the day the shape moves.

The payload is captured and scrubbed: credentials and vendor URLs are
removed, listing ids and prices are kept, because a fixture with the prices
stripped out would not exercise the band or profit rules at all.
"""

import json
from pathlib import Path

import pytest
import requests

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def ebay_payload():
    return json.loads((FIXTURES / "ebay_browse_search.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def serpapi_payload():
    return json.loads(
        (FIXTURES / "serpapi_google_shopping.json").read_text(encoding="utf-8")
    )


class _Resp:
    """Just enough of requests.Response for the scrapers."""

    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestRealBrowsePayloadShape:
    def test_the_fixture_still_has_the_keys_the_parser_reads(self, ebay_payload):
        """Guards the capture script. If someone tightens the scrubber and it
        eats a field the parser depends on, the fixture becomes decorative
        and every test below quietly stops testing anything."""
        item = ebay_payload["itemSummaries"][0]
        for key in (
            "itemId",
            "title",
            "price",
            "condition",
            "itemWebUrl",
            "seller",
            "thumbnailImages",
            "itemLocation",
            "shippingOptions",
        ):
            assert key in item, f"real Browse payload lost {key!r}"

    def test_the_fixture_is_real_not_invented(self, ebay_payload):
        """Guards against someone replacing the capture with a hand-written
        payload that happens to pass: a real response carries pagination and
        per-item noise that invented fixtures are too tidy to have."""
        assert "itemSummaries" in ebay_payload
        assert len(ebay_payload["itemSummaries"]) >= 2
        # real listings carry an id and a numeric price, not our test doubles
        for item in ebay_payload["itemSummaries"]:
            assert item["itemId"]
            assert float(item["price"]["value"]) > 0

    def test_price_is_a_nested_object_not_a_bare_number(self, ebay_payload):
        """A real trap: `price` is {"currency", "value"}. Code written
        against a float crashes on the first live call."""
        price = ebay_payload["itemSummaries"][0]["price"]
        assert isinstance(price, dict)
        assert "value" in price and "currency" in price

    def test_the_search_returns_products_from_the_real_payload(
        self, monkeypatch, ebay_payload
    ):
        """The four captured listings cost GBP156-465, so they sit above the
        app's default GBP5-35 band. An explicit wide band is passed here on
        purpose: this test is about parsing real bytes, and the band gate has
        its own test below."""
        from scrapers.ebay import EbayScraper

        seen = {}

        def fake_get(url, params=None, headers=None, timeout=None):
            seen["params"] = params or {}
            return _Resp(ebay_payload)

        monkeypatch.setattr(requests, "get", fake_get)
        monkeypatch.setattr("scrapers.ebay.requests.get", fake_get, raising=False)

        products = EbayScraper()._search_api(
            "greenhouse 6ft", limit=10, price_band=(0.0, 100000.0)
        )

        assert products, "a real payload must produce at least one product"
        for p in products:
            assert p.source == "ebay_uk"
            assert p.price > 0
            assert p.title
            assert p.url
            assert p.seller, "seller.username is nested in the real payload"
        assert seen["params"]["q"] == "greenhouse 6ft"

    def test_the_band_clause_is_sent_and_reapplied_on_real_data(
        self, monkeypatch, ebay_payload
    ):
        """PR-2 layer 1, on real listings: the band goes into the query AND
        is applied locally, so the two cannot disagree. The captured prices
        are GBP156-465, so a GBP5-35 band must drop every one of them - and
        must have told eBay so in the filter."""
        from scrapers.ebay import EbayScraper

        seen = {}

        def fake_get(url, params=None, headers=None, timeout=None):
            seen["params"] = params or {}
            return _Resp(ebay_payload)

        monkeypatch.setattr(requests, "get", fake_get)
        monkeypatch.setattr("scrapers.ebay.requests.get", fake_get, raising=False)

        scraper = EbayScraper()
        in_band = scraper._search_api("greenhouse 6ft", limit=10, price_band=(0.0, 100000.0))
        assert in_band, "precondition: the wide band keeps the real listings"

        kept = scraper._search_api("greenhouse 6ft", limit=10, price_band=(5.0, 35.0))
        assert kept == [], "every captured listing is above GBP35 and must be dropped"

        # and the same band was pushed into the query eBay was asked
        assert "price:[5..35]" in seen["params"]["filter"]
        assert "priceCurrency:GBP" in seen["params"]["filter"]

    def test_the_real_condition_gate_survives_the_real_payload(
        self, monkeypatch, ebay_payload
    ):
        """C10 on live-shaped data: whatever eBay calls the condition, only
        New survives - and an unreadable one is not silently accepted."""
        from scrapers.ebay import EbayScraper

        def fake_get(url, params=None, headers=None, timeout=None):
            return _Resp(ebay_payload)

        monkeypatch.setattr(requests, "get", fake_get)
        monkeypatch.setattr("scrapers.ebay.requests.get", fake_get, raising=False)

        products = EbayScraper()._search_api("greenhouse 6ft", limit=10)
        for p in products:
            assert p.condition in ("New", "new"), p.condition

    def test_a_real_payload_with_no_price_key_yields_no_fake_zero(
        self, monkeypatch, ebay_payload
    ):
        """If the shape ever loses `price`, the parser must drop the listing,
        not admit it at £0.00 - a £0 greenhouse passes every price band."""
        from scrapers.ebay import EbayScraper

        broken = {
            "itemSummaries": [
                {k: v for k, v in ebay_payload["itemSummaries"][0].items()
                 if k != "price"}
            ]
        }

        def fake_get(url, params=None, headers=None, timeout=None):
            return _Resp(broken)

        monkeypatch.setattr(requests, "get", fake_get)
        monkeypatch.setattr("scrapers.ebay.requests.get", fake_get, raising=False)

        assert EbayScraper()._search_api("greenhouse 6ft", limit=10) == []


class TestRealSoldPayloadSaysWhereItCameFrom:
    """Found by the live smoke test, not by reading the code.

    `get_sold_data` returned a real 30d count with `data_source = None`, so a
    figure genuinely derived from an eBay sold-listing search could not name
    its own origin. That is the C13 gap this project exists to close: an
    unlabelled number is indistinguishable from a guess.

    It also matters that the label is honest about WHAT the number is. The
    count is how many in-band New listings the sold search returned - not a
    true 30-day sales total - so the label has to say that too.
    """

    def test_the_sold_path_stamps_its_source(self, monkeypatch, ebay_payload):
        from scrapers.ebay import EbayScraper

        def fake_get(url, params=None, headers=None, timeout=None):
            return _Resp(ebay_payload)

        monkeypatch.setattr(requests, "get", fake_get)
        monkeypatch.setattr("scrapers.ebay.requests.get", fake_get, raising=False)

        demand = EbayScraper()._get_sold_api("greenhouse 6ft")

        assert demand.data_source, "a real sold count must name its source"
        assert "sold" in demand.data_source.lower()

    def test_the_label_does_not_overstate_what_the_number_is(
        self, monkeypatch, ebay_payload
    ):
        """It is a count of returned in-band New listings, so the label may not
        imply a verified sales total."""
        from scrapers.ebay import EbayScraper

        def fake_get(url, params=None, headers=None, timeout=None):
            return _Resp(ebay_payload)

        monkeypatch.setattr(requests, "get", fake_get)
        monkeypatch.setattr("scrapers.ebay.requests.get", fake_get, raising=False)

        demand = EbayScraper()._get_sold_api("greenhouse 6ft")
        label = demand.data_source.lower()

        assert "verified" not in label
        assert "exact" not in label

    def test_an_empty_result_is_unverified_and_still_labelled(
        self, monkeypatch, ebay_payload
    ):
        """No listings means no count - and a None source on that path would
        hide the difference between 'none found' and 'never asked'."""
        from scrapers.ebay import EbayScraper

        def fake_get(url, params=None, headers=None, timeout=None):
            return _Resp({"itemSummaries": []})

        monkeypatch.setattr(requests, "get", fake_get)
        monkeypatch.setattr("scrapers.ebay.requests.get", fake_get, raising=False)

        demand = EbayScraper()._get_sold_api("greenhouse 6ft")

        assert demand.verified is False
        assert demand.sold_count_30d is None
        assert demand.data_source, "even an empty result must name the source it asked"


class TestRealSerpApiPayloadShape:
    def test_the_fixture_still_has_the_keys_the_resolver_reads(self, serpapi_payload):
        """serpapi_discovery._resolve_store reads immersive_product_page_token
        and _row_for reads extracted_price. An earlier scrubber deleted the
        token as if it were a credential; this test is what stops that from
        happening again."""
        row = serpapi_payload["shopping_results"][0]
        for key in (
            "title",
            "extracted_price",
            "product_link",
            "source",
            "immersive_product_page_token",
        ):
            assert key in row, f"real SerpApi payload lost {key!r}"

    def test_no_credential_survived_the_capture(self, serpapi_payload):
        """The other half of the guard: the fixture is committed, so it must
        not carry anything that authenticates."""

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    assert k.lower() not in {"api_key", "access_token", "secret"}
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(serpapi_payload)

    def test_extracted_price_is_a_real_number_not_a_string_with_a_symbol(
        self, serpapi_payload
    ):
        """`extracted_price` arrives as a float while `price` arrives as
        '£49.99'. A parser that assumes either shape breaks on the other."""
        row = serpapi_payload["shopping_results"][0]
        assert isinstance(row["extracted_price"], (int, float))
        assert isinstance(row["price"], str)

    def test_the_source_slug_is_read_from_the_real_row(self, serpapi_payload):
        """The captured rows are real Google Shopping results, and they are
        mostly NOT one of the 7 approved suppliers - so the honest assertion
        is that every real row maps to a real approved slug or to nothing at
        all. A parser that invented a slug here would breach C12."""
        from scrapers.serpapi_discovery import _SUPPLIERS, _slug_for

        for row in serpapi_payload["shopping_results"]:
            slug = _slug_for(row)
            assert slug == "" or slug in _SUPPLIERS, (
                f"real row produced a non-approved supplier {slug!r}"
            )

    def test_a_real_non_approved_source_fails_closed(self, serpapi_payload):
        """'GardenSite' is what the captured rows actually say, and it is not
        an approved supplier, so no row may be built from it."""
        from scrapers.serpapi_discovery import _slug_for

        sources = [
            r.get("source") or r.get("seller") or r.get("name")
            for r in serpapi_payload["shopping_results"]
        ]
        assert "GardenSite" in sources, "fixture changed; keep this test honest"
        assert _slug_for({"source": "GardenSite", "link": ""}) == ""

    def test_an_approved_source_maps_to_its_slug(self):
        """The positive case, on the same code path: the spelling Google
        actually prints has to reach the approved supplier."""
        from scrapers.serpapi_discovery import _slug_for

        assert _slug_for({"source": "aliexpress", "link": ""}) == "aliexpress"
        assert _slug_for({"source": "cj dropshipping", "link": ""}) == "cj_dropshipping"

    def test_a_disabled_supplier_is_never_whitelisted(self):
        """2026-10: amazon_uk was disabled in suppliers.json.

        PA-API 5 is deprecated, access needs 10 sales in 30 days, and the
        Associates licence bars aggregating product data for analysis — so a
        SerpApi row naming Amazon must NOT become an approved supplier. Before
        this test existed that mapping was live, which would have let Amazon
        rows back in through the discovery path while it was being removed
        everywhere else.
        """
        from scrapers.serpapi_discovery import _slug_for

        assert _slug_for({"source": "Amazon.co.uk", "link": ""}) == ""
        assert _slug_for({"source": "Amazon", "link": ""}) == ""
        assert _slug_for({"source": "amazon.co.uk", "link": ""}) == ""

    def test_a_real_row_with_no_source_key_still_returns_nothing(self, serpapi_payload):
        """At least one captured row carries no `source` at all. The fallback
        chain must not turn a missing field into a supplier."""
        from scrapers.serpapi_discovery import _slug_for

        missing = [r for r in serpapi_payload["shopping_results"] if "source" not in r]
        assert missing, "fixture changed; keep this test honest"
        for row in missing:
            assert _slug_for(row) == ""