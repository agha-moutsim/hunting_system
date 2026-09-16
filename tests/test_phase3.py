"""
Test Phase 3: eBay scraper (API-first design).
Works with or without API keys — falls back to scraping.
"""

import os
from scrapers.ebay import EbayScraper
from config import EBAY_CLIENT_ID


def test_ebay_search():
    """Test eBay search."""
    scraper = EbayScraper()
    try:
        mode = "API" if EBAY_CLIENT_ID else "scraping"
        print(f"  Mode: {mode}")
        results = scraper.search("stainless steel water bottle")
        print(f"  Results: {len(results)} items")
        for i, r in enumerate(results[:3]):
            print(f"    {i+1}. {r.title[:50]}... GBP{r.price}")
        if results:
            assert results[0].price > 0, "Price is 0"
        print("[PASS] eBay search")
        return True
    except Exception as e:
        print(f"[FAIL] eBay search: {e}")
        return False
    finally:
        scraper.close()


def test_ebay_details():
    """Test eBay listing details."""
    scraper = EbayScraper()
    try:
        # Try API first
        if EBAY_CLIENT_ID:
            results = scraper.search("stainless steel water bottle", limit=1)
            if results:
                url = results[0].url
            else:
                url = "https://www.ebay.co.uk/itm/385329859103"
        else:
            url = "https://www.ebay.co.uk/itm/385329859103"
        details = scraper.get_details(url)
        print(f"  Title: {details.title[:50]}...")
        print(f"  Price: GBP{details.price}")
        assert details.title, "No title found"
        print("[PASS] eBay details")
        return True
    except Exception as e:
        print(f"[FAIL] eBay details: {e}")
        return False
    finally:
        scraper.close()


def main():
    print("=" * 50)
    print("PHASE 3 TEST: eBay Scraper")
    print("=" * 50)

    if not EBAY_CLIENT_ID:
        print("[INFO] No EBAY_CLIENT_ID — using scraping fallback")
        print("  Get free API keys at: https://developer.ebay.com")
        print()

    r1 = test_ebay_search()
    r2 = test_ebay_details()

    print("=" * 50)
    if r1 and r2:
        print("PHASE 3: ALL TESTS PASSED")
    else:
        print("PHASE 3: SOME TESTS FAILED")
    print("=" * 50)


if __name__ == "__main__":
    main()
