r"""C13 — a supplier row must say HOW it was obtained.

For AliExpress the credentialed API path is permanently disabled (the only
key available belongs to a host with no search endpoint), and for Amazon UK
the Associates credentials are absent. So the only thing that can produce
either of those rows is a Playwright read of the live page.

That row IS `verified`: C13 defines verified as "a real API response OR a
successfully parsed page", and the page really was parsed. What has to be
disclosed is which of the two it was, because a green "Verified" alone reads
as though an API returned it — the "looks like a working supplier source"
failure this guards against.

`fetch_method`:
  "api"     a credentialed/signed API response
  "browser" read off a live page in a Playwright browser
  ""        not stated — absence is unknown, never a default (C1)

Absent must never be silently read as "an API", which is why the default
assertion below is part of the contract.
"""

from dataclasses import asdict, fields

import pytest

from scrapers.base import ScrapedProduct

# Long enough to clear every scraper's title-length guard (>= 5, >= 10).
TITLE = "Bosch PSB 1800 LI-2 Cordless Combi Drill 18V"


def _row(**kw) -> ScrapedProduct:
    return ScrapedProduct(
        source="supplier", title=TITLE, price=9.99,
        url="https://supplier.example/p/1", **kw,
    )


class TestTheFieldItself:
    def test_absent_by_default_so_it_never_claims_an_api(self):
        """The whole point of the field: unknown must read as unknown."""
        assert _row().fetch_method == ""

    def test_it_is_appended_after_the_original_fields_not_inserted_into_them(
        self,
    ):
        """ScrapedProduct is constructed positionally across the codebase;
        inserting a field before the existing ones silently shifts every
        argument after it. The fields added later sit at the tail, in the
        order they were added, and `image_hash` — the last original field —
        still comes before them."""
        names = [f.name for f in fields(ScrapedProduct)]
        assert names[-4:] == [
            "standard_shipping_cost",
            "standard_shipping_days_min",
            "standard_shipping_days_max",
            "standard_shipping_raw",
        ]
        assert names.index("image_hash") == len(names) - 15
        assert asdict(_row())["fetch_method"] == ""

    def test_only_the_two_documented_values_are_meaningful(self):
        assert _row(fetch_method="api").fetch_method == "api"
        assert _row(fetch_method="browser").fetch_method == "browser"


class TestAliExpress:
    """No API path exists at all, so every row it returns is a browser read."""

    def test_search_card_is_tagged_browser(self):
        from scrapers.aliexpress import AliExpressScraper

        html = (
            f'<div><a href="/item/1005001234567890.html" title="{TITLE}">'
            f'<h3>{TITLE}</h3><span data-price="89.99"></span></a></div>'
        )
        soup = AliExpressScraper().parse(html)
        card = soup.select_one("a[href*='/item/']")
        assert card is not None, "the fixture must actually exercise the parser"

        product = AliExpressScraper()._extract_search_card(card)

        assert product is not None
        assert product.fetch_method == "browser"

    def test_it_does_not_report_an_api_it_does_not_have(self):
        from scrapers.aliexpress import AliExpressScraper

        scraper = AliExpressScraper()
        # The disabled API seam must stay silent rather than emit rows.
        assert scraper._search_via_rapidapi("drill") == []


class TestAmazonUK:
    """Two real paths: the signed Associates API, and the page read."""

    @pytest.fixture()
    def pa_credentials(self, monkeypatch):
        monkeypatch.setenv("AMAZON_PA_ACCESS_KEY", "AKIA-TEST")
        monkeypatch.setenv("AMAZON_PA_SECRET_KEY", "SECRET-TEST")
        monkeypatch.setenv("AMAZON_PA_PARTNER_TAG", "TAG-TEST")

    def test_search_card_is_tagged_browser(self):
        from scrapers.amazon_uk import AmazonUKScraper

        html = (
            '<div data-component-type="s-search-result">'
            f"<h2><a href='/dp/B0123456789'><span>{TITLE}</span></a></h2>"
            '<span class="a-price"><span class="a-price-whole">89</span>'
            '<span class="a-price-fraction">99</span></span></div>'
        )
        soup = AmazonUKScraper().parse(html)
        card = soup.select_one('div[data-component-type="s-search-result"]')
        assert card is not None, "the fixture must actually exercise the parser"

        product = AmazonUKScraper()._extract_search_card(card)

        assert product is not None
        assert product.fetch_method == "browser"

    def test_pa_api_rows_are_tagged_api(self, pa_credentials, monkeypatch):
        """The two paths must be distinguishable, not both 'verified'."""
        import requests

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "SearchResult": {
                        "Items": [{
                            "ItemInfo": {"Title": {"DisplayValue": TITLE}},
                            "Offers": {"Listings": [{
                                "Price": {"Amount": "89.99"},
                                "DeliveryInfo": {"IsAmazonFulfilled": True},
                            }]},
                            "Images": {"Primary": {"Large": {"URL": ""}}},
                            "DetailPageURL": "https://amazon.co.uk/dp/B0123456789",
                        }]
                    }
                }

        monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())

        from scrapers.amazon_uk import AmazonUKScraper

        products = AmazonUKScraper()._search_via_api("drill")

        assert len(products) == 1
        assert products[0].fetch_method == "api"

    def test_without_credentials_it_returns_nothing_at_all(self, monkeypatch):
        """Fail closed: no rows means no rows, never a browser row labelled
        'api'."""
        import requests

        def _boom(*a, **k):
            raise AssertionError("no request may be attempted without keys")

        monkeypatch.setattr(requests, "post", _boom)
        monkeypatch.delenv("AMAZON_PA_ACCESS_KEY", raising=False)

        from scrapers.amazon_uk import AmazonUKScraper

        assert AmazonUKScraper()._search_via_api("drill") == []


class _ExportResult:
    """A deep-search-shaped object carrying suppliers — only the attributes
    export/format.py actually reads."""

    def __init__(self, suppliers):
        self.product_name = TITLE
        self.product_category = "Power Tools"
        self.ebay_items_sold_month = "100 items"
        self.ebay_top_sellers = []
        self.ebay_price_min = 15.0
        self.ebay_price_max = 12.0
        self.ebay_avg_price = 12.0
        self.ebay_price_median = 12.0
        self.ebay_total_sold_30d = 100
        self.ebay_total_sold_7d = 25
        self.suppliers = suppliers
        self.best_supplier_price = 9.99
        self.verdict = "PENDING"
        self.field_provenance = {}
        self.ebay_stores = []


def _dict_row(**kw) -> dict:
    row = {
        "name": "AliExpress", "full_name": "AliExpress", "price": 9.99,
        "url": "https://www.aliexpress.com/item/1.html",
        "supplier_type": "dropshipper", "delivery_days": "12-25",
        "seller_rating": "", "seller_orders": "", "product_title": TITLE,
        "image_url": "", "provenance": "verified",
        "provenance_label": "Verified",
        "source_url": "https://www.aliexpress.com/item/1.html",
        "source_name": "AliExpress", "match_basis": "",
    }
    row.update(kw)
    return row


class TestTheTagTravelsToTheUI:
    """A field nobody forwards is a field nobody reads."""

    def test_the_analyze_serializer_includes_it(self):
        from api.analyze import _serialize

        out = _serialize(_row(fetch_method="browser"))

        assert out["fetch_method"] == "browser"

    def test_the_json_export_forwards_a_browser_row(self):
        from export.format import format_to_schema

        out = format_to_schema(
            _ExportResult([_dict_row(fetch_method="browser")])
        )

        assert out["suppliers"][0]["fetch_method"] == "browser"

    def test_the_json_export_reports_blank_not_an_api_when_absent(self):
        """'fetch_method' was never stated by this row. Forwarding '' keeps
        that true; omitting it would be equally honest but the key must
        never come back carrying a value nobody wrote."""
        from export.format import format_to_schema

        out = format_to_schema(_ExportResult([_dict_row()]))

        assert out["suppliers"][0]["fetch_method"] == ""


class TestTheDeepSearchRowCarriesIt:
    """deep_search_fast builds supplier dicts by hand — this is the Bulk path,
    so a tag that does not survive here is invisible on most of the rows."""

    def test_a_browser_tagged_hit_is_forwarded(self, monkeypatch):
        from tests.test_match_wiring import (
            REF_TITLE,
            TITLE_MATCH,
            _product,
            _stub_fast_path,
        )
        import deep_search as ds

        _stub_fast_path(monkeypatch, {
            "AliExpress": [
                _product(TITLE_MATCH, source="aliexpress",
                         fetch_method="browser"),
            ],
        })

        result = ds.deep_search_fast(REF_TITLE)

        assert len(result.suppliers) == 1, (
            "the matcher should have kept this row"
        )
        assert result.suppliers[0]["fetch_method"] == "browser"

    def test_a_row_that_never_stated_one_exports_blank(self, monkeypatch):
        from tests.test_match_wiring import (
            REF_TITLE,
            TITLE_MATCH,
            _product,
            _stub_fast_path,
        )
        import deep_search as ds

        _stub_fast_path(monkeypatch, {
            "AliExpress": [_product(TITLE_MATCH, source="aliexpress")],
        })

        result = ds.deep_search_fast(REF_TITLE)

        assert len(result.suppliers) == 1
        assert result.suppliers[0]["fetch_method"] == ""


class TestTheCategoryHunterRowCarriesIt:
    """hunter/supplier_lookup builds dicts by hand, so it must forward it."""

    def test_an_aliexpress_hit_is_forwarded_as_browser(self, monkeypatch):
        from hunter.supplier_lookup import _lookup_single_supplier
        from hunter.category_scan import CategoryProduct
        from scrapers.aliexpress import AliExpressScraper

        hit = ScrapedProduct(
            source="aliexpress", title=TITLE, price=9.99,
            url="https://www.aliexpress.com/item/1.html",
            fetch_method="browser",
        )

        async def _search(self, query):
            return [hit]

        monkeypatch.setattr(AliExpressScraper, "search", _search)
        # Discovery must yield nothing so the AE fallback is what runs.
        import scrapers.serpapi_discovery as disc
        monkeypatch.setattr(disc, "discover", lambda q: [])
        from scrapers.cjdropshipping import CJDropshippingScraper

        async def _cj(self, q):
            return []

        monkeypatch.setattr(CJDropshippingScraper, "search", _cj)

        product = CategoryProduct(
            title=TITLE, price=12.0, url="https://www.ebay.co.uk/itm/1"
        )
        import analysis_pipeline as ap

        row = ap.run_async(_lookup_single_supplier(product))

        assert row is not None, "the AE fallback should have produced the row"
        assert row["fetch_method"] == "browser"

    def test_a_row_that_never_stated_one_is_blank(self, monkeypatch):
        from hunter.supplier_lookup import _lookup_single_supplier
        from hunter.category_scan import CategoryProduct
        from scrapers.aliexpress import AliExpressScraper

        hit = ScrapedProduct(
            source="aliexpress", title=TITLE, price=9.99,
            url="https://www.aliexpress.com/item/1.html",
        )  # fetch_method deliberately unset

        async def _search(self, query):
            return [hit]

        monkeypatch.setattr(AliExpressScraper, "search", _search)
        import scrapers.serpapi_discovery as disc
        monkeypatch.setattr(disc, "discover", lambda q: [])
        from scrapers.cjdropshipping import CJDropshippingScraper

        async def _cj(self, q):
            return []

        monkeypatch.setattr(CJDropshippingScraper, "search", _cj)

        product = CategoryProduct(
            title=TITLE, price=12.0, url="https://www.ebay.co.uk/itm/1"
        )
        import analysis_pipeline as ap

        row = ap.run_async(_lookup_single_supplier(product))

        assert row is not None
        assert row["fetch_method"] == ""
