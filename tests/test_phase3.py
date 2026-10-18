"""
Test Phase 3: eBay scraper (API-first design).
Works with or without API keys — falls back to scraping.

Assertions are NOT swallowed: a failure fails the test.

Both tests below call the real eBay API or scrape the live site, so the module
carries the `live` marker and is excluded from the default run by pytest.ini.
Run it on demand with:  python -m pytest -m live tests/test_phase3.py
"""

import os

import pytest

from scrapers.ebay import EbayScraper
from config import EBAY_CLIENT_ID

pytestmark = pytest.mark.live


def test_ebay_search():
    """eBay search returns priced results."""
    scraper = EbayScraper()
    try:
        results = scraper.search("stainless steel water bottle")
        assert len(results) > 0, "Search returned no results"
        assert results[0].price > 0, f"First result has price {results[0].price}"
        assert results[0].url, "First result has no URL"
    finally:
        scraper.close()


def test_ebay_details():
    """eBay listing details return a title and price."""
    scraper = EbayScraper()
    try:
        if EBAY_CLIENT_ID:
            results = scraper.search("stainless steel water bottle", limit=1)
            url = results[0].url if results else "https://www.ebay.co.uk/itm/385329859103"
        else:
            url = "https://www.ebay.co.uk/itm/385329859103"
        details = scraper.get_details(url)
        assert details.title, "No title found"
        assert details.price > 0, f"Price is {details.price}"
    finally:
        scraper.close()
