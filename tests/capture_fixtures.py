"""Capture REAL API responses as offline test fixtures.

Run once, deliberately, when an API shape needs locking into the suite:

    python -m tests.capture_fixtures

Why this exists: unit tests built from hand-written JSON only prove the code
parses what the author imagined. These fixtures are actual responses, trimmed
and scrubbed, so the suite fails the moment eBay or SerpApi changes a field
name - which is the failure mode that actually bites in production.

Scrubbing: any key containing key/token/secret/auth is dropped, and item
listings are truncated to the first few. Listing ids and prices are public
marketplace data and are kept, because a fixture with the prices removed
would not exercise the band or profit rules at all.
"""

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Dropped: genuine credentials.
_CREDENTIAL_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "client_secret",
    "secret",
    "password",
    "authorization",
    "auth",
}

# Dropped: a vendor endpoint URL we never read, which carries a long opaque
# continuation cursor. Nothing in the codebase parses it.
_VENDOR_JUNK_KEYS = {"serpapi_immersive_product_api"}

# KEPT ON PURPOSE: `immersive_product_page_token`.
# It is token-shaped, and an earlier blanket "drop anything called *token*"
# rule deleted it - which quietly gutted the fixture, because
# serpapi_discovery._resolve_store reads exactly this field. A pagination
# cursor for one result set is not a credential and grants no access to
# anything. tests/test_real_payload_fixtures.py asserts it survives, so the
# scrubber cannot silently destroy the coverage again.
_TOKEN_SHAPED_BUT_KEPT = {"immersive_product_page_token"}


def _scrub(value):
    """Recursively drop credential keys and vendor junk, keep real shapes."""
    if isinstance(value, dict):
        return {
            k: _scrub(v)
            for k, v in value.items()
            if k not in _CREDENTIAL_KEYS and k not in _VENDOR_JUNK_KEYS
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def capture_ebay(query: str = "greenhouse 6ft", keep: int = 4) -> dict:
    import requests

    from config import EBAY_API_BASE
    from scrapers.ebay import EbayScraper

    scraper = EbayScraper()
    try:
        resp = requests.get(
            f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search",
            params={"q": query, "limit": 10},
            headers=scraper._api_headers(),
            timeout=25,
        )
        resp.raise_for_status()
        data = resp.json()
    finally:
        scraper.close()

    data = _scrub(data)
    summaries = data.get("itemSummaries") or []
    data["itemSummaries"] = summaries[:keep]
    data.pop("next", None)
    data.pop("currentPage", None)
    data["_fixture_note"] = (
        f"Real eBay Browse item_summary/search response for q={query!r}, "
        "trimmed to the first item summaries. Captured by tests/capture_fixtures.py."
    )
    return data


def capture_serpapi(query: str = "greenhouse 6ft", keep: int = 4) -> dict:
    import requests

    api_key = os.getenv("SERPAPI_KEY", "")
    if not api_key:
        raise SystemExit("SERPAPI_KEY not set - cannot capture a SerpApi fixture")

    resp = requests.get(
        "https://serpapi.com/search.json",
        params={
            "engine": "google_shopping",
            "q": query,
            "hl": "en",
            "gl": "gb",
            "api_key": api_key,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = _scrub(resp.json())

    for block in ("shopping_results", "inline_shopping_results"):
        if isinstance(data.get(block), list):
            data[block] = data[block][:keep]
    data["_fixture_note"] = (
        f"Real SerpApi google_shopping response for q={query!r}, trimmed. "
        "Captured by tests/capture_fixtures.py. search_parameters dropped."
    )
    data.pop("search_parameters", None)
    data.pop("search_metadata", None)
    return data


def capture_ebay_deals() -> str:
    """Real card objects from eBay's own deals page.

    Stored as a TEXT fragment, not re-serialised JSON. The cards are fragments
    of a much larger HTML payload and sit among thousands of other tags, so the
    thing worth pinning is that the parser finds them inside that payload at
    all. Tidying them into clean JSON first would test the parser against a
    shape eBay never serves, which is the exact failure this directory exists
    to prevent.
    """
    from scrapers.ebay_deals import EbayDealsScraper, _CARD_RE

    html = EbayDealsScraper().fetch_page()
    cards = [match.group(0) for match in _CARD_RE.finditer(html)]
    if not cards:
        raise SystemExit(
            "no deal cards found on the deals page - the payload shape has "
            "changed, and scrapers/ebay_deals.py needs looking at"
        )

    header = (
        "<!-- Real card objects captured verbatim from "
        "https://www.ebay.co.uk/deals.\n"
        "     Key order in this payload is NOT stable between renders, which is\n"
        "     why the parser matches the object first and each field inside it\n"
        "     separately. Captured by tests/capture_fixtures.py. -->\n"
    )
    return header + "<script>\n" + ",\n".join(cards) + "\n</script>\n"


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)

    deals = capture_ebay_deals()
    (FIXTURES / "ebay_deals_cards.html").write_text(deals, encoding="utf-8", newline="\n")
    print(f"ebay_deals_cards.html: {deals.count('listingId')} cards")

    ebay = capture_ebay()
    (FIXTURES / "ebay_browse_search.json").write_text(
        json.dumps(ebay, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"ebay_browse_search.json: {len(ebay.get('itemSummaries') or [])} items")

    serp = capture_serpapi()
    (FIXTURES / "serpapi_google_shopping.json").write_text(
        json.dumps(serp, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        "serpapi_google_shopping.json: "
        f"{len(serp.get('shopping_results') or [])} shopping_results"
    )


if __name__ == "__main__":
    main()