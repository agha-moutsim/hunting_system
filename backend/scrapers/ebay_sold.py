"""
eBay sold listings scraper — gets real sold data from completed listings.

One scraper follows one marketplace record: the Browse API header, delivery
country, price currency and site host all come from `marketplaces`. The
default remains EBAY_GB, so existing callers keep the same request.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import EBAY_UK_BASE, EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_API_BASE, SCRAPE_CONFIG
from engine.price_gate import active_bounds, in_band_range
from engine.condition_gate import api_condition_filter, html_condition_param, is_new
from marketplaces import get_marketplace
from scrapers.availability import ebay_item_availability


class _Unset:
    """Sentinel: 'caller did not pass a band', distinct from an explicit None.

    REGRESSION-006: the three cases - omitted, a (lo, hi) tuple, and an
    explicit "no price restriction" - cannot share a single ``None`` default,
    because ``None`` is itself one of the meaningful values. Without this,
    every procurement call that passed nothing was indistinguishable from one
    that asked for the whole of eBay.
    """


_UNSET = _Unset()


def _absolute_ebay_url(href: str, site_base: str = EBAY_UK_BASE) -> str:
    """Normalise a scraped href into a URL on the selected eBay host.

    Returns '' unless the href really points at an eBay storefront on THAT
    host, so a relative link or a link to another marketplace can never be
    mistaken for an observed storefront for this card.
    """
    raw = str(href or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = f"https:{raw}"
    elif raw.startswith("/"):
        raw = f"{site_base.rstrip('/')}{raw}"
    if not raw.startswith(("http://", "https://")):
        return ""
    host = (urlparse(site_base).hostname or "ebay.co.uk").lower()
    actual_host = (urlparse(raw).hostname or "").lower()
    if actual_host != host or "/str/" not in raw.lower():
        return ""
    return raw.split("?")[0].split("#")[0]


def _seller_profile_link(username: str, site_base: str = EBAY_UK_BASE) -> str:
    """Canonical /usr/ profile for a seller username. Never a /str/ link."""
    from engine.stores import seller_profile_url

    return seller_profile_url(username, site_base=site_base)

# The local gate for an unrestricted request needs finite bounds, but must
# not re-impose the user's buying range. Any real eBay price is inside this.
_UNRESTRICTED_BOUNDS = (0.0, 1_000_000.0)


@dataclass
class EbaySoldItem:
    """Single sold item from eBay."""
    title: str
    price: float
    url: str
    seller: str
    seller_url: str
    sold_date: str
    # C10 — '' by default: an unread condition is NOT New. Never assume.
    condition: str = ""
    image_url: Optional[str] = None
    # P4 — stock/shipping read off the same Browse-API response (C13);
    # ''/0.0/0 = the response did not state it, never a default (C1).
    # Appended last so existing positional constructions cannot shift.
    in_stock: str = ""
    stock_raw: str = ""
    availability_url: str = ""
    shipping_cost: float = 0.0
    shipping_days: int = 0
    shipping_raw: str = ""
    # REGRESSION-007: the storefront href eBay actually rendered for this
    # seller, or '' when the source showed no store link. The Browse API
    # carries no slug, so the API path leaves this empty rather than guessing
    # one from the username.
    store_url: str = ""


@dataclass
class EbaySoldData:
    """Aggregated sold data for a product."""
    product_name: str
    query: str
    # OBSERVED SALES. Set only when the sold/completed-listing page was really
    # read (that page lists ended sales). None = not measured — the Browse API
    # path cannot see sold items at all, so it leaves these None and fills
    # `active_listings_in_band` instead (C1/C4: never an assumed count).
    total_sold_30d: Optional[int] = None
    # None = no parseable sale dates → unknown (C1: never estimated).
    total_sold_7d: Optional[int] = None
    #: In-band New ACTIVE listings: SUPPLY, not demand.
    active_listings_in_band: Optional[int] = None
    #: Which path produced `items` — "ebay_sold_scrape" (ended sales, so a
    #: count of them IS a sold count) or "ebay_browse_active" (live listings,
    #: so it is not). The meaning of the two counts above is derived from THIS
    #: and never assumed, because the same `len(items)` means two different
    #: things depending on where the items came from.
    items_source: str = ""
    #: SALE prices only — what a buyer actually paid. Only the sold/completed
    #: page can produce a genuine one, so this stays EMPTY on the Browse path
    #: and the prices go to `active_prices` instead. A live listing's asking
    #: price is not a sale price, and the same `prices` list means two
    #: different things depending on where the items came from.
    sold_prices: list[float] = field(default_factory=list)
    #: The prices of the live listings, when that is what `items` holds. Real
    #: prices read from eBay, but SUPPLY-side in meaning.
    active_prices: list[float] = field(default_factory=list)
    price_min: float = 0.0
    price_max: float = 0.0
    price_avg: float = 0.0
    price_median: float = 0.0
    top_sellers: list[dict] = field(default_factory=list)
    sold_dates: list[str] = field(default_factory=list)
    category: str = ""
    items: list[EbaySoldItem] = field(default_factory=list)
    excluded_over_band: int = 0  # PR-4: sold rows dropped by the market band
    excluded_non_new: int = 0     # C10: sold rows dropped by the New-only gate
    #: Phase E2 — the ISO currency of every price in this result. '' means the
    #: caller did not state one; a market-aware scraper always fills it.
    currency: str = ""


class EbaySoldScraper:
    """Scrape one eBay marketplace's sold/completed listings for demand data."""

    SOLD_URL = f"{EBAY_UK_BASE}/sch/i.html"
    MAX_PAGES = 3  # Max pages to scrape (180 items per page = 540 max)

    def __init__(self, marketplace: str | None = None):
        self.marketplace = get_marketplace(marketplace)
        self.site_base = self.marketplace["site_base"].rstrip("/")
        self.currency = self.marketplace["currency"]
        self.delivery_country = self.marketplace["country_code"]
        self.sold_url = f"{self.site_base}/sch/i.html"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": SCRAPE_CONFIG["user_agent"],
            "Accept-Language": SCRAPE_CONFIG["accept_language"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self._token = None
        self._token_expiry = 0
        self._band_excluded = 0
        self._condition_excluded = 0  # C10: non-New rows dropped
        # REGRESSION-006: which band this call searches, resolved per call.
        # The market states its own band when it has one (AU: A$0.99-A$50);
        # otherwise the active GBP range is the historical default.
        band = self.marketplace.get("price_band") or {}
        self._default_band = (
            (float(band["min"]), float(band["max"]))
            if band.get("min") is not None and band.get("max") is not None
            else active_bounds()
        )
        self._band_used = self._default_band
        self._unrestricted = False

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

    def get_sold_data(self, query: str,
                      price_band: tuple[float, float] | None | _Unset = _UNSET
                      ) -> EbaySoldData:
        """Get real sold data for a product from the selected marketplace.

        `price_band` overrides the market's default band for this call only:

          omitted (the default) -> the market band (AU: A$0.99-A$50; UK: the
                                   active user range), unchanged
          a (lo, hi) tuple       -> that band, used in the query AND locally
          explicit ``None``     -> NO price restriction at all

        The three cases need three states, and a bare ``None`` default could
        not express them: ``None`` is a meaningful request in its own right
        ("no restriction"), so it is distinguished by a sentinel
        (REGRESSION-006). Getting this wrong silently widened every
        procurement search to the whole of eBay.

        Competitor-store discovery passes the wide band, because a shop
        selling a GBP120 greenhouse competes with the GBP29.99 one you intend
        to buy. Procurement callers pass nothing and keep the active band
        (PR-1/PR-4 unchanged).
        """
        # Resolve the three states into one internal representation.
        self._band_used = None if price_band is None else (
            None if isinstance(price_band, _Unset) else tuple(price_band)
        )
        if isinstance(price_band, _Unset):
            self._band_used = self._default_band
            self._unrestricted = False
        elif price_band is None:
            self._band_used = None
            self._unrestricted = True
        else:
            self._band_used = (float(price_band[0]), float(price_band[1]))
            self._unrestricted = False
        result = EbaySoldData(
            product_name=query,
            query=query,
            currency=self.currency,
        )
        self._band_override = price_band
        self._band_excluded = 0
        self._condition_excluded = 0

        try:
            # Try API first for sold data
            api_items = self._get_sold_via_api(query)
            if api_items:
                result.items = api_items
                # The Browse API cannot see sold items — these are LIVE
                # listings, so counting them measures supply, not sales.
                # Recorded so _calculate_stats knows which number it holds
                # instead of assuming (C1/C4).
                result.items_source = "ebay_browse_active"
            else:
                # Fallback to scraping the sold/completed page, which lists
                # real ended sales.
                scrape_items = self._get_sold_via_scrape(query)
                result.items = scrape_items
                result.items_source = "ebay_sold_scrape" if scrape_items else ""

            # Calculate statistics
            self._calculate_stats(result)
            result.excluded_over_band = self._band_excluded
            result.excluded_non_new = self._condition_excluded

        except Exception as e:
            print(f"[WARN] eBay sold data failed for '{query}': {e}")

        return result

    def _resolve_band(self) -> tuple[float, float]:
        """The price bounds for THIS call, for the local gate.

        Even when the request carried no price clause, a finite local bound is
        needed so the gate below has something to compare against. The
        unrestricted case uses a deliberately wide range - the API already
        declined to filter, so locally re-imposing the GBP5-35 band would
        discard exactly the listings the wide search was for
        (REGRESSION-006).
        """
        if self._band_used is not None:
            return self._band_used
        return _UNRESTRICTED_BOUNDS

    def _get_sold_via_api(self, query: str) -> list[EbaySoldItem]:
        """Try to get sold items via Browse API (filter by sold status)."""
        if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
            return []

        try:
            lo, hi = self._resolve_band()
            band_api = (
                f"price:[{lo:.0f}..{hi:.0f}],priceCurrency:{self.currency}"
            )
            # C10 — condition joins the filter so Used listings never enter
            # the demand set or the top-seller aggregation.
            cond = api_condition_filter()
            filter_parts = [
                "buyingOptions:{FIXED_PRICE}",
                f"deliveryCountry:{self.delivery_country}",
            ]
            if cond:
                filter_parts.append(cond)
            if self._band_used is not None:
                filter_parts.append(band_api)
            resp = requests.get(
                f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search",
                params={
                    "q": query,
                    "limit": 50,
                    "filter": ",".join(filter_parts),
                    "sort": "-relevance",
                },
                headers={
                    "Authorization": f"Bearer {self._get_token()}",
                    "X-EBAY-C-MARKETPLACE-ID": self.marketplace["id"],
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            items = []
            for item in data.get("itemSummaries", []):
                price_info = item.get("price", {})
                price = float(price_info.get("value", 0))
                # Gate against the band this call actually searched, not the
                # active one. Re-checking the active range here silently
                # discarded every listing a widened store search had found
                # (REGRESSION-006).
                if not in_band_range(price, lo, hi):
                    self._band_excluded += 1  # PR-4
                    continue
                condition = item.get("condition", "")
                if not is_new(condition):
                    self._condition_excluded += 1  # C10
                    continue
                seller_info = item.get("seller", {})
                items.append(EbaySoldItem(
                    title=item.get("title", ""),
                    price=price,
                    url=item.get("itemWebUrl", ""),
                    seller=seller_info.get("username", ""),
                    # REGRESSION-007: the Browse API gives a seller user ID and
                    # no store slug. This used to build /str/{username}, which
                    # 404s whenever the seller's slug differs. The canonical
                    # /usr/ profile is the only link this response supports;
                    # store_url stays '' because no storefront was observed.
                    seller_url=_seller_profile_link(
                        seller_info.get("username", ""), self.site_base),
                    store_url="",
                    sold_date="",  # Browse summaries carry no sale date — never fake one
                    condition=condition,
                    image_url=item.get("thumbnailImages", [{}])[0].get("imageUrl")
                        if item.get("thumbnailImages") else None,
                    # P4 — availability/shippingOptions only when the
                    # response carried them (C13/C1); the HTML fallback
                    # below states none, so it leaves them unknown.
                    **ebay_item_availability(item),
                ))
            return items

        except Exception as e:
            print(f"[WARN] eBay API search failed: {e}")
            return []

    def _get_sold_via_scrape(self, query: str) -> list[EbaySoldItem]:
        """Scrape eBay sold listings page (HTML fallback)."""
        items = []

        for page in range(1, self.MAX_PAGES + 1):
            try:
                lo, hi = self._resolve_band()
                # The price clause is omitted entirely when the caller asked
                # for no restriction, so the two never disagree with the
                # local in_band() gate below.
                price_clause = (
                    "" if self._band_used is None
                    else f"&_udlo={lo:.0f}&_udhi={hi:.0f}"
                )
                url = (
                    f"{self.sold_url}?"
                    f"_nkw={query.replace(' ', '+')}"
                    f"&LH_Complete=1&LH_Sold=1"
                    f"&_sop=13"  # Sort by most recently sold
                    f"{price_clause}"
                    f"{html_condition_param()}"  # C10 — New-only at query time
                    f"&_pgn={page}"
                )

                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "html.parser")
                page_items = self._parse_sold_page(soup)

                if not page_items:
                    break  # No more items

                items.extend(page_items)

                # Rate limit between pages
                if page < self.MAX_PAGES:
                    time.sleep(2)

            except Exception as e:
                print(f"[WARN] Failed to scrape eBay sold page {page}: {e}")
                break

        return items

    def _parse_sold_page(self, soup: BeautifulSoup) -> list[EbaySoldItem]:
        """Parse a single eBay sold listings page."""
        items = []

        # REGRESSION-007b: this method used `lo, hi` at the band gate without
        # ever binding them — they were locals of `_get_sold_via_scrape`, a
        # different scope. Every item therefore raised NameError, and the
        # blanket `except: continue` below swallowed it, so the HTML sold
        # path silently returned zero items and store discovery always fell
        # through to the API. Bind them here, or drop the gate entirely when
        # the caller asked for no restriction.
        lo, hi = self._resolve_band()

        # eBay sold items are in list items
        for item in soup.select("li.s-item"):
            try:
                # Skip ads and "Shop on eBay" items
                title_el = item.select_one("div.s-item__title span")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                if title.lower() in ("shop on ebay", "results matching fewer words", ""):
                    continue

                # Price
                price_el = item.select_one("span.s-item__price")
                if not price_el:
                    continue

                price_text = price_el.get_text(strip=True).replace(",", "")
                price_match = re.search(r"[\d.]+", price_text)
                if not price_match:
                    continue

                price = float(price_match.group())
                if price <= 0:
                    continue
                # Gate against the band this call searched (REGRESSION-006).
                if not in_band_range(price, lo, hi):
                    self._band_excluded += 1  # PR-4
                    continue

                # Link
                link_el = item.select_one("a.s-item__link")
                url = link_el.get("href", "") if link_el else ""

# Seller
                # REGRESSION-007: this block used to take the first whitespace
                # token and BUILD `/str/{seller}` from it. A seller user ID is
                # not a store slug, so that link is usually a dead "Store not
                # found". eBay already renders the real storefront href next to
                # the seller name when the seller has one, so read that first
                # and only fall back to the canonical /usr/ profile.
                seller_el = item.select_one("span.s-item__seller-info-text")
                seller = ""
                store_url = ""
                seller_url = ""
                if seller_el:
                    anchor = seller_el.select_one("a[href*='/str/']")
                    if anchor is None:
                        scope = item.select_one(".s-item__seller-info")
                        if scope is not None:
                            anchor = scope.select_one("a[href*='/str/']")
                    if anchor is not None:
                        store_url = _absolute_ebay_url(
                            anchor.get("href", ""), self.site_base
                        )
                        # The anchor's text is the store's display name.
                        seller_text = anchor.get_text(strip=True)
                    else:
                        seller_text = seller_el.get_text(strip=True)
                    seller_match = re.search(r"(\S+)", seller_text)
                    if seller_match:
                        seller = seller_match.group(1)
                    seller_url = store_url or _seller_profile_link(
                        seller, self.site_base
                    )

                # Sold date (if available) — "" when the page omits it, never faked
                date_el = item.select_one("span.POSITIVE")
                sold_date = date_el.get_text(strip=True) if date_el else ""

                # Image
                img_el = item.select_one("img.s-item__image-img")
                image_url = img_el.get("src") if img_el else None

                # C10 — read the condition the page shows; '' when absent
                # so a row we cannot confirm is dropped, never assumed New.
                condition = ""
                for sel in ("span.s-item__condition", "span.SECONDARY_INFO",
                            "span[class*='condition']"):
                    cond_el = item.select_one(sel)
                    if cond_el and cond_el.get_text(strip=True):
                        condition = cond_el.get_text(strip=True)
                        break
                if not is_new(condition):
                    self._condition_excluded += 1  # C10
                    continue

                items.append(EbaySoldItem(
                    title=title,
                    price=price,
                    url=url,
                    seller=seller,
                    seller_url=seller_url,
                    store_url=store_url,
                    sold_date=sold_date,
                    condition=condition,
                    image_url=image_url,
                ))

            except Exception as e:
                continue

        return items

    def _calculate_stats(self, result: EbaySoldData):
        """Calculate statistics from sold items."""
        if not result.items:
            return

        # Prices. WHICH list these belong in depends on where `items` came
        # from, so it is decided by `items_source` and never assumed — the same
        # way the count below is. Every price here is real and was read from
        # eBay; the difference is whether anybody bought at it, and that is
        # exactly the difference the two field names have to carry.
        prices = [item.price for item in result.items if item.price > 0]
        if result.items_source == "ebay_sold_scrape":
            result.sold_prices = prices
            result.active_prices = []
        else:
            result.sold_prices = []
            result.active_prices = prices

        if prices:
            result.price_min = min(prices)
            result.price_max = max(prices)
            result.price_avg = sum(prices) / len(prices)
            sorted_prices = sorted(prices)
            mid = len(sorted_prices) // 2
            result.price_median = sorted_prices[mid] if len(sorted_prices) % 2 else (sorted_prices[mid-1] + sorted_prices[mid]) / 2

        # Counts. WHICH count this is depends on where `items` came from, so it
        # is decided by `items_source` rather than assumed — the same
        # `len(items)` means two different things depending on the path
        # (C1/C4: never an assumed count).
        #   "ebay_sold_scrape"  → the sold/completed page, so a count of its
        #                         rows IS a count of observed sold listings.
        #   "ebay_browse_active" → live listings: SUPPLY. Recording that as
        #                         sales is exactly the bug this replaces.
        if result.items_source == "ebay_sold_scrape":
            result.total_sold_30d = len(result.items)
            result.active_listings_in_band = None
        else:
            result.total_sold_30d = None
            result.active_listings_in_band = len(result.items)
        # 7d = ONLY from parseable sale dates — None when the pages carry no
        # usable dates. Never an estimate (C1/C4: no assumed counts).
        from datetime import date as _date
        from utils.purchase_history import parse_date
        today = _date.today()
        parsed = [d for d in (parse_date(i.sold_date) for i in result.items) if d]
        if parsed:
            result.total_sold_7d = sum(
                1 for d in parsed if d <= today and (today - d).days <= 7
            )
        else:
            result.total_sold_7d = None

        # Top sellers
        seller_counts = {}
        for item in result.items:
            if item.seller:
                if item.seller not in seller_counts:
                    seller_counts[item.seller] = {
                        "name": item.seller,
                        "url": item.seller_url,
                        # REGRESSION-007: carry the observed storefront href so
                        # engine.stores can show a real store link when we
                        # actually saw one.
                        "store_url": getattr(item, "store_url", "") or "",
                        "sold_count": 0,
                        "total_price": 0,
                    }
                seller_counts[item.seller]["sold_count"] += 1
                seller_counts[item.seller]["total_price"] += item.price

        # Calculate avg price per seller
        for seller in seller_counts.values():
            if seller["sold_count"] > 0:
                seller["avg_price"] = round(seller["total_price"] / seller["sold_count"], 2)

        # Sort by sold count
        result.top_sellers = sorted(seller_counts.values(), key=lambda x: x["sold_count"], reverse=True)[:5]

        # Sold dates
        result.sold_dates = [item.sold_date for item in result.items if item.sold_date]
