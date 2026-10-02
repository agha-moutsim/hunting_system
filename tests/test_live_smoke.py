"""Opt-in smoke tests against the REAL APIs.

Everything else in this suite is hermetic: fixtures, fakes, no network. That
is correct for a gate you run on every commit, but it means a whole class of
production failure is invisible to CI - an expired token, a renamed API host,
a response that now returns zero rows, a supplier endpoint quietly returning
404 HTML. Those only announce themselves live.

So these exist, and they stay out of the default run because they spend real
API quota against a 5,000/day budget:

    $ set EBAY_LIVE=1
    $ python -m pytest tests/test_live_smoke.py -m live -q -s

What they assert is deliberately narrow. They do not assert a specific sold
count or a specific price - those change hourly and would make the test
useless. They assert STRUCTURE and HONESTY: that a live call returns a shape
the parsers understand, and that missing data is reported as missing rather
than as a zero.
"""

import os

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("EBAY_LIVE") != "1",
        reason="live API tests are opt-in: set EBAY_LIVE=1 (they spend real quota)",
    ),
]


@pytest.fixture(scope="module")
def ebay():
    from scrapers.ebay import EbayScraper

    scraper = EbayScraper()
    yield scraper
    scraper.close()


class TestLiveSoldSearch:
    def test_a_real_sold_search_returns_a_readable_30d_figure(self, ebay):
        """'cordless drill' sells in volume every day, so a zero here means
        the integration is broken, not that the market is empty."""
        demand = ebay.get_sold_data("cordless drill")

        assert demand is not None
        assert demand.sold_count_30d is not None, (
            "live sold search returned no 30d count - check the token and host"
        )
        assert demand.sold_count_30d > 0
        assert demand.data_source, "a real count must name where it came from"

    def test_a_live_search_returns_products_with_the_fields_the_ui_needs(self, ebay):
        products = ebay.search("cordless drill", limit=5)

        assert products, "a live search returned nothing"
        for p in products:
            assert p.title and p.price > 0 and p.url
            assert p.condition, "an unread condition must be '' , never assumed New"


class TestLiveStoreSearch:
    def test_a_live_store_search_returns_at_most_four_real_stores(self):
        """C11's cap, checked against the live API rather than a fake."""
        from engine.stores import search_stores

        stores, _ladder = search_stores("cordless drill")

        assert len(stores) <= 4
        for s in stores:
            assert s.get("name")
            assert s.get("url", "").startswith("http")

    def test_the_store_provenance_never_claims_verified_on_an_empty_result(self, ebay):
        """'we found none' and 'we could not look' are both unconfirmed."""
        from engine.stores import store_provenance_block

        block = store_provenance_block([])
        assert block["provenance"] == "unverified"
        assert block.get("store_count") == 0


class TestLiveSupplierDiscovery:
    def test_live_discovery_only_ever_returns_approved_suppliers(self):
        """C12, live: whatever Google returns, no row may name a supplier that
        is not on the approved list.

        Checked on `source`, which _row_for fills from the approved supplier's
        own configured label. NOT on `supplier_type`: that field is
        classify_source()'s answer to "what kind of seller is this" -
        dropshipper / wholesaler / retailer / unknown - so asserting an
        approved SLUG against it fails on correct code. (It did, the first
        time this ran.)
        """
        from scrapers.serpapi_discovery import _SUPPLIERS, discover

        if not os.environ.get("SERPAPI_KEY"):
            pytest.skip("SERPAPI_KEY not set")

        approved_labels = {cfg["label"] for cfg in _SUPPLIERS.values()}
        known_types = {"dropshipper", "wholesaler", "retailer", "unknown"}

        rows = discover("cordless drill")
        assert rows, "live discovery returned nothing to check"
        for row in rows:
            assert row.source in approved_labels, (
                f"live discovery returned unapproved supplier {row.source!r}"
            )
            assert row.supplier_type in known_types, (
                f"supplier_type {row.supplier_type!r} is not a classification"
            )

    def test_live_rows_never_fabricate_a_price(self):
        """A row whose price could not be read must carry no price, not £0."""
        from scrapers.serpapi_discovery import discover

        if not os.environ.get("SERPAPI_KEY"):
            pytest.skip("SERPAPI_KEY not set")

        for row in discover("cordless drill"):
            if getattr(row, "price", None) is not None:
                assert row.price > 0, f"fabricated price {row.price!r}"


class TestLiveDemandMonitor:
    def test_a_live_monitor_run_records_a_real_snapshot(self):
        """One real fetch, recorded. A second run inside the same second will
        not produce a trend - that is the point, and it is asserted in the
        hermetic tests."""
        from hunter.demand_monitor import fetch_and_record, series_for_query

        row = fetch_and_record("live smoke cordless drill", source="live_smoke")
        assert row.query == "live smoke cordless drill"
        assert row.captured_at is not None

        series = series_for_query("live smoke cordless drill")
        assert len(series) >= 1