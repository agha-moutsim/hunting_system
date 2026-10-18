"""
eBay UK scraper — uses Browse API (primary) + requests (fallback).
"""

import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from scrapers.base import ScrapedProduct, DemandData, read_shipping, read_stock
from scrapers.availability import ebay_item_availability
from config import (
    EBAY_UK_BASE, EBAY_CLIENT_ID, EBAY_CLIENT_SECRET,
    EBAY_MARKETPLACE, EBAY_API_BASE, EBAY_ENVIRONMENT, SCRAPE_CONFIG,
)
from engine.price_gate import active_bounds, in_band, in_band_range
from engine.condition_gate import api_condition_filter, html_condition_param, is_new

# Query-time New-only (C10). Composed at CALL TIME so a changed active
# condition reaches the very next request — never an import-time literal.
_BASE_API_FILTER = "buyingOptions:{FIXED_PRICE},deliveryCountry:GB"


class _Unset:
    """Sentinel: 'no band argument', distinct from an explicit None.

    REGRESSION-006: omitted / (lo, hi) / None (no restriction) are three
    different requests, and a bare None default can only express two of them.
    Without the sentinel, every call that passed nothing would have looked
    like a request for the whole of eBay.
    """


_UNSET = _Unset()
# Local-gate bounds for an unrestricted request: finite, but not the user's
# buying range, which must not be re-imposed on a deliberately wide search.
_UNRESTRICTED_BOUNDS = (0.0, 1_000_000.0)


_SOLD_SOURCE_LABEL = (
    "ebay_browse_active_listings: in-band New ACTIVE listings the search "
    "returned. Supply, not sales - this app has no sold-listing search, so "
    "this call cannot produce a sold count at all."
)
# Deliberately free of the words "verified" and "exact". The label is shown
# and, worse, may be string-matched by a renderer - a source string containing
# "verified" can light a green badge on a figure that is only a count of
# returned listings.


def _api_filter(band_api: str) -> str:
    """Compose the Browse API filter: base + active condition (C10) + band.

    Condition is appended at CALL TIME so a changed active condition
    reaches the very next request — never an import-time literal.
    """
    cond = api_condition_filter()
    parts = [_BASE_API_FILTER]
    if cond:
        parts.append(cond)
    if band_api:
        parts.append(band_api)
    return ",".join(parts)


class EbayScraper:
    """Scraper for eBay UK — API-first, scraping fallback."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": SCRAPE_CONFIG["user_agent"],
            "Accept-Language": SCRAPE_CONFIG["accept_language"],
        })
        self._token = None
        self._token_expiry = 0

    def _get_token(self) -> str:
        """Get OAuth token via Client Credentials flow."""
        now = time.time()
        if self._token and now < self._token_expiry:
            return self._token

        if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
            raise ValueError("EBAY_CLIENT_ID and EBAY_CLIENT_SECRET required")

        resp = requests.post(
            f"{EBAY_API_BASE}/identity/v1/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic " + __import__("base64").b64encode(
                    f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()
                ).decode(),
            },
            data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = now + data.get("expires_in", 7200) - 300
        return self._token

    def _api_headers(self) -> dict:
        """Headers for Browse API calls."""
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE,
            "Content-Type": "application/json",
        }

    def search(self, query: str, limit: int = 10,
               price_band: tuple[float, float] | None | _Unset = _UNSET
               ) -> list[ScrapedProduct]:
        """Search eBay UK via Browse API.

        `price_band` overrides the ACTIVE range for this call only, with
        three distinct states (omitted / a band / explicit None for "no
        restriction") because None is itself meaningful. Competitor-store
        discovery needs the unrestricted form (REGRESSION-006). Omitting the
        argument preserves the original behaviour exactly.
        """
        if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
            print("[INFO] No eBay API keys — returning empty. Add EBAY_CLIENT_ID/EBAY_CLIENT_SECRET to .env")
            return []
        try:
            return self._search_api(query, limit, price_band=price_band)
        except Exception as e:
            print(f"[WARN] API search failed: {e}")
            return []

    def _search_api(self, query: str, limit: int = 10,
                    price_band: tuple[float, float] | None | _Unset = _UNSET
                    ) -> list[ScrapedProduct]:
        """Search via Browse API.

        The band used is pushed into the query (PR-2 layer 1) AND applied
        again locally below, so the two can never disagree. Dropping the price
        clause and skipping the local gate happen together, or eBay sends
        listings the local filter would then discard.
        """
        if isinstance(price_band, _Unset):
            lo, hi = active_bounds()
            unrestricted = False
        elif price_band is None:
            lo, hi = 0.0, 1_000_000.0
            unrestricted = True
        else:
            lo, hi = float(price_band[0]), float(price_band[1])
            unrestricted = False

        band_api = ("" if unrestricted
                    else f"price:[{lo:.0f}..{hi:.0f}],priceCurrency:GBP")
        resp = requests.get(
            f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search",
            params={
                "q": query,
                "limit": min(limit, 50),
                "filter": _api_filter(band_api),
                "sort": "-relevance",
            },
            headers=self._api_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("itemSummaries", []):
            price_info = item.get("price", {})
            price = float(price_info.get("value", 0))
            if not unrestricted and not in_band_range(price, lo, hi):
                continue  # defence in depth — PR-2 layer 1 (search time)
            condition = item.get("condition", "")
            if not is_new(condition):
                continue  # defence in depth — C10 condition gate
            results.append(ScrapedProduct(
                source="ebay_uk",
                title=item.get("title", ""),
                price=price,
                url=item.get("itemWebUrl", ""),
                image_url=item.get("thumbnailImages", [{}])[0].get("imageUrl")
                    if item.get("thumbnailImages") else None,
                seller=item.get("seller", {}).get("username"),
                condition=condition,
                verified=True,
                # P4 — stock/shipping only from what the Browse API
                # actually carried; absent keys stay unknown (C13/C1).
                **ebay_item_availability(item),
            ))
        return results

    def _search_scrape(self, query: str) -> list[ScrapedProduct]:
        """Fallback: scrape search page (may be blocked)."""
        lo, hi = active_bounds()
        search_url = (
            f"{EBAY_UK_BASE}/sch/i.html?"
            f"_nkw={query.replace(' ', '+')}"
            f"&LH_BIN=1&LH_PrefLoc=1"
            f"&_udlo={lo:.0f}&_udhi={hi:.0f}"
            f"{html_condition_param()}"   # C10 — query-time New-only
        )
        try:
            resp = self.session.get(search_url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for item in soup.select("li.s-item")[:10]:
                title_el = item.select_one("div.s-item__title span")
                price_el = item.select_one("span.s-item__price")
                link_el = item.select_one("a.s-item__link")
                if not title_el or not price_el:
                    continue
                title = title_el.get_text(strip=True)
                if title.lower() in ("shop on ebay", "results matching fewer words"):
                    continue
                price_match = re.search(r"[\d,.]+", price_el.get_text(strip=True).replace(",", ""))
                price = float(price_match.group()) if price_match else 0
                if not in_band(price):
                    continue  # PR-2 layer 1 (search time)
                # C10 — read the condition the page actually shows. A row we
                # cannot read is NOT New: fail closed, never default it.
                condition = self._read_condition(item)
                if not is_new(condition):
                    continue
                # P4 — stock/delivery wording off this result only; a miss
                # stays unknown, never a default (C1/C13).
                item_url = link_el.get("href", "") if link_el else ""
                stock_state, stock_raw = read_stock(item)
                ship_cost, ship_days, ship_raw = read_shipping(item)
                results.append(ScrapedProduct(
                    source="ebay_uk",
                    title=title,
                    price=price,
                    url=item_url,
                    condition=condition,
                    verified=True,
                    in_stock=stock_state,
                    stock_raw=stock_raw,
                    availability_url=item_url if stock_raw else "",
                    shipping_cost=ship_cost,
                    shipping_days=ship_days,
                    shipping_raw=ship_raw,
                ))
            return results
        except Exception as e:
            print(f"[WARN] Scrape fallback also failed: {e}")
            return []

    @staticmethod
    def _read_condition(item) -> str:
        """Pull the condition label off a search-result <li>.

        eBay renders it in one of a few places depending on layout;
        we return '' when none is found so C10 fails closed.
        """
        for selector in (
            "span.s-item__condition",
            "span.SECONDARY_INFO",
            "span[class*='condition']",
            "span.s-item__details span",
        ):
            el = item.select_one(selector)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return ""

    def get_details(self, url: str) -> ScrapedProduct:
        """Get listing details — API first, scrape only as a last resort."""
        item_id = self._extract_item_id(url)
        if item_id:
            try:
                return self._get_details_api(item_id)
            except Exception as e:
                print(f"[WARN] API details failed for item {item_id}: {e}")

                # Sandbox only knows its own test items — a real eBay item
                # will never resolve there, and scraping real eBay gets 403.
                if EBAY_ENVIRONMENT == "sandbox":
                    raise ValueError(
                        "This item was not found in the eBay Sandbox (test) database. "
                        "Sandbox only contains its own mock listings. "
                        "Use a SEARCH TERM (e.g. 'headphones') instead of a real eBay URL, "
                        "or switch to Production keys for real listings."
                    )

        # Fallback: scrape the page (always blocked by eBay — kept only as last resort)
        try:
            return self._get_details_scrape(url)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 403:
                raise ValueError(
                    "eBay blocked the direct page request (403 Forbidden). "
                    "Paste a SEARCH TERM instead of a URL, or use the eBay API keys in .env."
                )
            raise

    def _extract_item_id(self, url: str) -> str | None:
        """Extract eBay item ID from URL."""
        match = re.search(r"/itm/(\d+)", url)
        return match.group(1) if match else None

    def _get_details_api(self, item_id: str) -> ScrapedProduct:
        """Get details via Browse API.

        The API identifies items as `v1|<id>|0` (or `|1`), while URLs only
        carry the bare numeric id — try the token forms first, bare id last.
        """
        tokens = (
            [item_id] if "|" in item_id
            else [f"v1|{item_id}|0", f"v1|{item_id}|-1", item_id]
        )
        resp = None
        for token in tokens:
            resp = requests.get(
                f"{EBAY_API_BASE}/buy/browse/v1/item/{token}",
                headers=self._api_headers(),
                timeout=15,
            )
            if resp.status_code == 404:
                continue  # try next token form
            resp.raise_for_status()
            break
        if resp is None or resp.status_code == 404:
            raise requests.exceptions.HTTPError(
                "404 Client Error: item not found", response=resp
            )
        item = resp.json()
        price = item.get("price", {})
        image = item.get("image", {})
        seller = item.get("seller", {})
        condition = item.get("condition", "")

        if not is_new(condition):
            # C10 — URL hunting is the highest-risk path: a user pasting a
            # Used listing must be told so, not silently analysed as New.
            raise ValueError(
                f"This listing is '{condition or 'unknown condition'}' — "
                "only NEW listings qualify (C10)."
            )

        return ScrapedProduct(
            source="ebay_uk",
            title=item.get("title", ""),
            price=float(price.get("value", 0)),
            url=item.get("itemWebUrl", ""),
            image_url=image.get("imageUrl"),
            seller=seller.get("username"),
            condition=condition,
            verified=True,
            # P4 — availability/shippingOptions off the item payload (C13).
            **ebay_item_availability(item),
        )

    def _get_details_scrape(self, url: str) -> ScrapedProduct:
        """Fallback: scrape listing page."""
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title = soup.select_one("h1.x-item-title__mainTitle")
        price = soup.select_one("div.x-price-primary span")
        condition = soup.select_one("div.x-item-condition-text")
        seller = soup.select_one("a.ux-seller-section__item--seller")
        image = soup.select_one("div.x-carousel__media img")

        # C10 — '' when the label is absent, so this fails closed rather
        # than defaulting an unknown listing to New.
        condition_text = condition.get_text(strip=True) if condition else ""
        if not is_new(condition_text):
            raise ValueError(
                f"This listing is '{condition_text or 'unknown condition'}' — "
                "only NEW listings qualify (C10)."
            )

        # P4 — read availability/delivery off this listing page; no hook
        # means unknown, never a default (C1/C13).
        stock_state, stock_raw = read_stock(soup)
        ship_cost, ship_days, ship_raw = read_shipping(soup)

        return ScrapedProduct(
            source="ebay_uk",
            title=title.get_text(strip=True) if title else "",
            price=self._parse_price(price.get_text(strip=True) if price else "0"),
            url=url,
            image_url=image.get("src") if image else None,
            seller=seller.get_text(strip=True) if seller else None,
            condition=condition_text,
            verified=True,
            in_stock=stock_state,
            stock_raw=stock_raw,
            availability_url=url if stock_raw else "",
            shipping_cost=ship_cost,
            shipping_days=ship_days,
            shipping_raw=ship_raw,
        )

    def get_sold_data(self, query: str) -> DemandData:
        """Get sold data — tries API search for completed items."""
        if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
            return DemandData(verified=False)
        try:
            return self._get_sold_api(query)
        except Exception as e:
            print(f"[WARN] API sold data failed: {e}")
            return DemandData(verified=False)

    def _get_sold_api(self, query: str) -> DemandData:
        """Get sold data via Browse API (search completed listings)."""
        lo, hi = active_bounds()
        band_api = f"price:[{lo:.0f}..{hi:.0f}],priceCurrency:GBP"
        resp = requests.get(
            f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search",
            params={
                "q": query,
                "limit": 50,
                # C10 — condition goes into the DEMAND query too, so Used
                # sales can never inflate sold_count / avg price.
                "filter": _api_filter(band_api),
                "sort": "-dateSold",
            },
            headers=self._api_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        items = data.get("itemSummaries", [])
        if not items:
            # Even "nothing found" names the source it asked: a blank source
            # cannot distinguish "we looked and there was none" from "we never
            # asked" (C13).
            return DemandData(
                verified=False,
                data_source=_SOLD_SOURCE_LABEL,
            )

        now = datetime.now()
        sold_items = []
        excluded = 0
        # C11 — the seller rides along on this response we already paid for;
        # discarding it is what forced Analyze/URL-hunt to have no stores.
        # Condition gate applies (C10 is absolute — a Used seller is not a
        # New-condition competitor), but the price band deliberately does
        # not: a store pricing outside YOUR band is still a real competitor.
        seller_tally: dict[str, list] = {}
        for item in items:
            price_info = item.get("price", {})
            price = float(price_info.get("value", 0))
            condition = item.get("condition", "")
            username = (item.get("seller") or {}).get("username") or ""

            if username and is_new(condition):
                slot = seller_tally.setdefault(username, [0, 0.0])
                slot[0] += 1
                slot[1] += price

            if not in_band(price):
                excluded += 1  # demand stats must reflect in-band sales only — PR-1/PR-4
                continue
            if not is_new(condition):
                excluded += 1  # C10 — non-New must not reach demand stats
                continue
            # Count items as "sold" (API doesn't expose sold dates directly)
            sold_items.append({"price": price, "condition": condition})

        prices = [i["price"] for i in sold_items if i["price"] > 0]
        demand = DemandData(
            # Browse returns ACTIVE listings, so this count is SUPPLY, not
            # demand. Writing it into sold_count_30d is what made every
            # downstream "sold" figure and `verified` badge false — and eBay
            # offers this app no sold search at all: findCompletedItems was
            # decommissioned 2025-02-04 and Marketplace Insights is closed to
            # new applications.
            active_listings_in_band=len(sold_items),
            sold_count_30d=None,
            sold_count_7d=None,
            # ASKING prices of the listings above, not sale prices. These used
            # to be written into avg_sold_price / lowest_sold_price /
            # highest_sold_price / sold_prices, which is how a live listing's
            # price came to be shown as the price something SOLD for.
            avg_active_price=sum(prices) / len(prices) if prices else None,
            lowest_active_price=min(prices) if prices else None,
            highest_active_price=max(prices) if prices else None,
            # A3 - the observations behind those three figures. Carried rather
            # than re-derived so the chart plots exactly the same numbers the
            # metrics show.
            active_prices=prices,
            # No sale was read, so there is no sale price to report — not even a
            # summary one. An empty list is the honest value, and it is what
            # stops a sold-price chart being drawn out of asking prices.
            sold_prices=[],
            # No sale was read, so there is no verified demand evidence here
            # however many listings came back.
            verified=False,
            excluded_over_band=excluded,
            data_source=_SOLD_SOURCE_LABEL,
        )
        # C11 — build the shared 4-store list from what this call observed.
        if seller_tally:
            from engine.stores import stores_from_top_sellers
            demand.top_sellers = stores_from_top_sellers(
                [
                    {"name": n, "sold_count": c, "avg_price": t / c if c else 0.0}
                    for n, (c, t) in seller_tally.items()
                ]
            )
        return demand

    def _parse_price(self, text: str) -> float:
        """Extract numeric price."""
        match = re.search(r"[\d,.]+", text.replace(",", ""))
        return float(match.group()) if match else 0.0

    def close(self):
        """Close session."""
        self.session.close()
