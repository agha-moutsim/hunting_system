"""Phase F - the scraper seam the title route uses.

`search()` swallows a failed Browse call and returns an empty list, which is
right for an analysis that can carry on with fewer competitors. The title
helper reports a sample size, so it needs a call that can distinguish "eBay
returned nothing" from "eBay did not answer". These tests pin that seam
without a network call.
"""

from __future__ import annotations

import pytest

from scrapers.ebay import EbayScraper


class TestSearchTitles:
    def test_asks_for_an_unrestricted_price_band(self, monkeypatch):
        scraper = EbayScraper()
        seen = {}

        def fake(query, limit=10, price_band="omitted"):
            seen["query"] = query
            seen["limit"] = limit
            seen["price_band"] = price_band
            return []

        monkeypatch.setattr(scraper, "_search_api", fake)
        try:
            assert scraper.search_titles("garden hose", limit=7) == []
        finally:
            scraper.close()

        assert seen == {
            "query": "garden hose",
            "limit": 7,
            "price_band": None,
        }

    def test_a_failed_call_reaches_the_caller(self, monkeypatch):
        scraper = EbayScraper()

        def boom(*args, **kwargs):
            raise RuntimeError("eBay is down")

        monkeypatch.setattr(scraper, "_search_api", boom)
        try:
            with pytest.raises(RuntimeError, match="eBay is down"):
                scraper.search_titles("garden hose")
        finally:
            scraper.close()
