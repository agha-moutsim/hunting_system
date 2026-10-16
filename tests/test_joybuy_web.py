"""
Joybuy web discovery (Option A) - offline, against recorded API payloads.

Every payload below is the real shape SerpApi returned on 2026-10-10 for
`site:joybuy.com` on the `google` engine. Nothing here touches the network.
"""

import pytest

from scrapers.base import ScrapedProduct


# --- recorded payloads ----------------------------------------------------

def _result(link, title, price=None, extensions=None):
    """One organic result. `price` is what Google DETECTED, if anything."""
    item = {
        "position": 1,
        "title": title,
        "link": link,
        "source": "joybuy.com",
        "snippet": "a snippet that mentions no price at all",
    }
    if price is not None or extensions is not None:
        bottom = {}
        if extensions is not None:
            bottom["extensions"] = list(extensions)
        if price is not None:
            bottom["detected_extensions"] = {"price": price, "currency": "GBP"}
        item["rich_snippet"] = {"bottom": bottom}
    return item


PRODUCT_DP = _result(
    "https://m.joybuy.com/dp/100017245073763?siteCode=UK-Site",
    "Cordless Drill Driver, Screwdriver Set 45Nm", price=11.99,
    extensions=["11.99", "In stock", "Free delivery"],
)
PRODUCT_LP = _result(
    "https://m.joybuy.com/landingPage/dp/100017205460134?siteCode=UK-Site",
    "21V Brushless Cordless Drill 45Nm", price=49.99,
    extensions=["49.99", "In stock"],
)
PRODUCT_NO_PRICE = _result(
    "https://m.joybuy.com/dp/100017431066580?siteCode=UK-Site",
    "RONTALY DZ-C-21, Cordless Drill Set, 2pcs 3000mAh",
)
BLOG = _result(
    "https://m.joybuy.co.uk/blog/18v-cordless-combi-drill-guide/uUFCb2mu",
    "Best 18V Cordless Combi Drills for UK DIY | Joybuy",
)
OFFSITE = _result("https://www.example.com/dp/123456789", "Some other shop")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Nothing may reach the network. The API is injected."""
    import requests

    def _blocked(*a, **k):
        raise AssertionError("network call attempted - inject the API instead")

    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)


# --- the query ------------------------------------------------------------

class TestQueryShape:

    def test_it_is_a_web_site_pass_not_a_shopping_one(self):
        from scrapers.joybuy_web import joybuy_search_url

        q = joybuy_search_url("cordless drill")
        assert q == "site:joybuy.com cordless drill"

    def test_inurl_is_not_used(self):
        """`inurl:dp` was measured to return ZERO products and to stall the
        engine for 65s. It must not creep back in."""
        from scrapers.joybuy_web import joybuy_search_url

        assert "inurl" not in joybuy_search_url("cordless drill")

    def test_joybuy_is_excluded_from_the_shopping_site_pass(self):
        """REGRESSION-008: the shopping engine stalls 67s on `site:joybuy.com`
        and returns nothing, so Stage 2 must skip it entirely."""
        from scrapers.serpapi_discovery import _site_query

        assert _site_query("joybuy", "cordless drill") == ""

    def test_other_suppliers_still_get_their_site_pass(self):
        from scrapers.serpapi_discovery import _site_query

        assert _site_query("toolstation", "drill").startswith("site:toolstation.com")

    def test_the_call_uses_the_web_engine_with_our_own_timeout(self, monkeypatch):
        """The dead-constant bug: a TIMEOUT that is declared but never passed
        silently inherits the 20s shopping timeout instead."""
        import scrapers.serpapi_discovery as sd
        from scrapers import joybuy_web as jw

        monkeypatch.setenv("SERPAPI_KEY", "k")
        seen = {}

        def _fake(params, api_key, budget, timeout=None):
            seen.update(params)
            seen["_timeout"] = timeout
            return {"organic_results": [PRODUCT_DP]}

        monkeypatch.setattr(jw, "_get_json", _fake)
        jw.discover_web("cordless drill")

        assert seen["engine"] == "google"
        assert seen["q"] == "site:joybuy.com cordless drill"
        assert seen["_timeout"] == jw.TIMEOUT

    def test_the_shopping_timeout_default_is_untouched(self):
        import inspect
        import scrapers.serpapi_discovery as sd

        sig = inspect.signature(sd._get_json)
        assert sig.parameters["timeout"].default is None
        assert sd._get_json.__defaults__[-1] is None


# --- what a row may claim -------------------------------------------------

class TestParsing:

    def test_a_product_page_becomes_a_row(self):
        from scrapers.joybuy_web import parse_web_results

        rows = parse_web_results([PRODUCT_DP])
        assert len(rows) == 1
        assert rows[0].price == 11.99
        assert "Cordless Drill Driver" in rows[0].title

    def test_a_price_is_read_from_the_detected_extension_only(self):
        from scrapers.joybuy_web import parse_web_results

        rows = parse_web_results([PRODUCT_LP])
        assert rows[0].price == 49.99

    def test_a_result_with_no_snippet_is_unpriced_not_zero_guessed(self):
        """0.0 means 'not stated'. Any other number here would flow straight
        into a margin calculation."""
        from scrapers.joybuy_web import parse_web_results

        rows = parse_web_results([PRODUCT_NO_PRICE])
        assert rows[0].price == 0.0
        assert rows[0].url.endswith("100017431066580?siteCode=UK-Site")

    def test_a_price_of_zero_is_not_treated_as_a_price(self):
        from scrapers.joybuy_web import parse_web_results

        rows = parse_web_results([_result(
            "https://m.joybuy.com/dp/999", "Thing", price=0, extensions=[])])
        assert rows[0].price == 0.0

    def test_a_non_numeric_price_is_ignored(self):
        from scrapers.joybuy_web import parse_web_results

        item = _result("https://m.joybuy.com/dp/999", "Thing")
        item["rich_snippet"] = {"bottom": {
            "detected_extensions": {"price": "call for price"}}}
        assert parse_web_results([item])[0].price == 0.0

    def test_no_price_is_invented_from_the_title(self):
        """A title mentioning 45Nm must not become a price."""
        from scrapers.joybuy_web import parse_web_results

        rows = parse_web_results([_result(
            "https://m.joybuy.com/dp/555", "Set 45Nm 21V 3000mAh 138 Piece")])
        assert rows[0].price == 0.0

    def test_stock_and_delivery_come_from_the_snippets_own_wording(self):
        from scrapers.joybuy_web import parse_web_results

        row = parse_web_results([PRODUCT_DP])[0]
        assert row.shipping_raw and "delivery" in row.shipping_raw.lower()
        assert row.fetch_method == "api"

    def test_condition_is_unread_never_assumed_new(self):
        from scrapers.joybuy_web import parse_web_results

        assert parse_web_results([PRODUCT_DP])[0].condition == ""

    def test_the_row_is_a_real_scraped_product(self):
        from scrapers.joybuy_web import parse_web_results

        assert isinstance(parse_web_results([PRODUCT_DP])[0], ScrapedProduct)


class TestWhatGetsDropped:

    def test_a_blog_article_is_not_a_supplier_product(self):
        """MEASURED: for 'cordless drill 18v' Google's top hits were /blog/
        articles. Filing one as a product would put a non-product in front of
        the user behind a title that reads exactly like one."""
        from scrapers.joybuy_web import parse_web_results

        assert parse_web_results([BLOG]) == []

    def test_the_same_sku_on_two_hosts_is_one_row(self):
        """Measured: www.joybuy.co.uk and m.joybuy.co.uk both appear. In a table
        whose job is comparing prices, one product shown twice is a defect."""
        from scrapers.joybuy_web import parse_web_results

        www = _result("https://www.joybuy.co.uk/dp/100017245073763",
                      "Cordless Drill Driver 45Nm", price=11.99)
        m = _result("https://m.joybuy.com/dp/100017245073763",
                    "Cordless Drill Driver 45Nm", price=11.99)
        assert len(parse_web_results([www, m])) == 1

    def test_different_skus_are_both_kept(self):
        from scrapers.joybuy_web import parse_web_results

        assert len(parse_web_results([PRODUCT_DP, PRODUCT_LP])) == 2

    def test_an_offsite_result_is_dropped(self):
        from scrapers.joybuy_web import parse_web_results

        assert parse_web_results([OFFSITE]) == []

    def test_a_stale_jd_com_host_is_dropped(self):
        from scrapers.joybuy_web import parse_web_results

        assert parse_web_results([_result(
            "https://item.jd.com/12345.html", "Thing")]) == []

    def test_junk_input_does_not_raise(self):
        from scrapers.joybuy_web import parse_web_results

        assert parse_web_results([None, 42, "x", {}, {"link": ""}]) == []

    def test_empty_input_is_empty(self):
        from scrapers.joybuy_web import parse_web_results

        assert parse_web_results([]) == []
        assert parse_web_results(None) == []


# --- failing closed -------------------------------------------------------

class TestFailsClosed:

    def test_no_key_means_no_rows(self, monkeypatch):
        from scrapers.joybuy_web import discover_web

        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        assert discover_web("cordless drill") == []

    def test_a_blank_query_costs_nothing(self, monkeypatch):
        import scrapers.serpapi_discovery as sd
        from scrapers import joybuy_web as jw

        monkeypatch.setenv("SERPAPI_KEY", "k")
        monkeypatch.setattr(sd, "_Budget", lambda n: (_ for _ in ()).throw(
            AssertionError("a budget was spent on an empty query")))
        assert jw.discover_web("   ") == []

    def test_a_transport_failure_returns_nothing_not_a_guess(self, monkeypatch):
        import requests
        from scrapers.joybuy_web import discover_web

        monkeypatch.setenv("SERPAPI_KEY", "k")
        monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(
            requests.RequestException("down")))
        assert discover_web("cordless drill") == []

    def test_a_non_json_body_returns_nothing(self, monkeypatch):
        import scrapers.serpapi_discovery as sd
        from scrapers.joybuy_web import discover_web

        monkeypatch.setenv("SERPAPI_KEY", "k")

        class _R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                raise ValueError("not json")

        monkeypatch.setattr(sd.requests, "get", lambda *a, **k: _R())
        assert discover_web("cordless drill") == []

    def test_an_error_payload_returns_nothing(self, monkeypatch):
        import scrapers.serpapi_discovery as sd
        from scrapers.joybuy_web import discover_web

        monkeypatch.setenv("SERPAPI_KEY", "k")

        class _R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"error": "Invalid API key"}

        monkeypatch.setattr(sd.requests, "get", lambda *a, **k: _R())
        assert discover_web("cordless drill") == []

    def test_a_missing_organic_key_returns_nothing(self, monkeypatch):
        import scrapers.serpapi_discovery as sd
        from scrapers.joybuy_web import discover_web

        monkeypatch.setenv("SERPAPI_KEY", "k")

        class _R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"search_metadata": {"id": "x"}}

        monkeypatch.setattr(sd.requests, "get", lambda *a, **k: _R())
        assert discover_web("cordless drill") == []

    def test_it_spends_at_most_one_call(self, monkeypatch):
        from scrapers.joybuy_web import discover_web
        import scrapers.joybuy_web as jw

        monkeypatch.setenv("SERPAPI_KEY", "k")
        assert jw.MAX_CALLS == 1

        calls = []

        def _fake(params, api_key, budget, timeout=None):
            calls.append(params)
            return {"organic_results": [PRODUCT_DP]}

        monkeypatch.setattr(jw, "_get_json", _fake)
        discover_web("cordless drill")
        assert len(calls) == 1


# --- how it reaches the product -------------------------------------------

class TestUnpricedRowsCannotLookFree:

    def test_the_priced_matcher_skips_an_unpriced_row(self):
        """The whole point: an unpriced Joybuy row must never become a
        'GBP 0.00 supplier' with infinite apparent margin."""
        from hunter.supplier_lookup import _first_valid

        row = ScrapedProduct(
            source="Joybuy UK", title="Cordless Drill Driver 45Nm",
            price=0.0, url="https://m.joybuy.com/dp/1",
        )
        assert _first_valid([row]) is None

    def test_a_priced_row_still_competes(self):
        from hunter.supplier_lookup import _first_valid

        row = ScrapedProduct(
            source="Joybuy UK", title="Cordless Drill Driver 45Nm",
            price=11.99, url="https://m.joybuy.com/dp/1",
        )
        assert _first_valid([row]) is row


class TestCatalog:

    def test_joybuy_is_enabled_and_marked_web_discovery(self):
        import json
        from config import SUPPLIERS_JSON

        with open(SUPPLIERS_JSON, encoding="utf-8") as f:
            cfg = json.load(f)["suppliers"]["joybuy"]

        assert cfg["enabled"] is True
        assert cfg["discovery"] == "web"
        assert cfg["skip_site_pass"] is True
        assert cfg["scrapable"] is False

    def test_the_honest_limit_is_recorded_next_to_the_flag(self):
        """An enabled supplier whose price coverage is 20% must say so where
        the next person will read it, not only in a commit message."""
        import json
        from config import SUPPLIERS_JSON

        with open(SUPPLIERS_JSON, encoding="utf-8") as f:
            cfg = json.load(f)["suppliers"]["joybuy"]

        assert "20%" in cfg["price_coverage"]
        assert "revisit_if" in cfg
        assert "disabled_reason" not in cfg