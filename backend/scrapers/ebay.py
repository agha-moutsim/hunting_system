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
    EBAY_CLIENT_ID, EBAY_CLIENT_SECRET,
    EBAY_API_BASE, EBAY_ENVIRONMENT, SCRAPE_CONFIG,
)
from marketplaces import get_marketplace
from engine.price_gate import active_bounds, in_band, in_band_range
from engine.condition_gate import api_condition_filter, html_condition_param, is_new
from scrapers.browse_fields import (
    SOURCE_ITEM,
    SOURCE_SUMMARY,
    listing_id_of,
    query_listing,
)

# Query-time New-only (C10). Composed at CALL TIME so a changed active
# condition reaches the very next request — never an import-time literal.
# Phase J: deliveryCountry is the selected market's, not a GB constant.
def _base_api_filter(market: dict) -> str:
    return (
        "buyingOptions:{FIXED_PRICE},"
        f"deliveryCountry:{market['delivery_country']}"
    )


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
#: Non-GBP markets do not get the GBP band, so the UK label's "in-band" would
#: be a claim about a restriction this response never had.
_SOLD_SOURCE_LABEL_UNRESTRICTED = (
    "ebay_browse_active_listings: New ACTIVE listings the search returned. "
    "Supply, not sales - this app has no sold-listing search, so this call "
    "cannot produce a sold count at all."
)
# Deliberately free of the words "verified" and "exact". The label is shown
# and, worse, may be string-matched by a renderer - a source string containing
# "verified" can light a green badge on a figure that is only a count of
# returned listings.


def _api_filter(band_api: str, market: dict | None = None) -> str:
    """Compose the Browse API filter: base + active condition (C10) + band.

    Condition is appended at CALL TIME so a changed active condition
    reaches the very next request — never an import-time literal.
    """
    cond = api_condition_filter()
    parts = [_base_api_filter(market or get_marketplace())]
    if cond:
        parts.append(cond)
    if band_api:
        parts.append(band_api)
    return ",".join(parts)


class EbayScraper:
    """Scraper for one eBay marketplace — API-first, scraping fallback.

    `marketplace=None` keeps the historical EBAY_GB behaviour. A route that
    accepted a market passes its id here; the Browse header, delivery country,
    price currency, site host and item source all follow that one record.
    """

    def __init__(self, marketplace: str | None = None):
        self.marketplace = get_marketplace(marketplace)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": SCRAPE_CONFIG["user_agent"],
            "Accept-Language": SCRAPE_CONFIG["accept_language"],
        })
        self._token = None
        self._token_expiry = 0
        #: (listing_id, payload, source) for every Browse payload this scraper
        #: reads. Drained by whichever caller holds a database session - see
        #: analysis_pipeline.save_analysis_to_db. Kept as a plain list rather
        #: than a callback so the scraper stays free of database knowledge and
        #: a failed write cannot fail a scrape.
        self.observations: list[tuple[str, dict, str]] = []
        #: One completed search result set per `_search_api` call, including
        #: a zero-listing answer. A separate list from `observations` because
        #: this records PRESENCE (the set), while observations record CHANGE
        #: (a reading that differed). The analysis pipeline drains both.
        self.query_observations: list[dict] = []

    @property
    def source(self) -> str:
        """The stored source token for this market.

        EBAY_GB keeps the historical `ebay_uk` token: millions of stored rows
        and the verdict's marketplace gate already use it, and renaming the
        same marketplace's evidence would split its history in two. Other
        markets use their registry country code.
        """
        code = self.marketplace["country_code"].lower()
        return "ebay_uk" if code == "gb" else f"ebay_{code}"

    def _observe(self, payload: dict, source: str) -> None:
        """Keep one Browse payload as a reading rather than dropping it.

        Every field kept here was already in hand - the response was read
        before this was called - so this spends no API call. A payload that
        cannot name its listing is skipped: there would be nothing to file the
        reading under (see browse_fields.listing_id_of).

        Deliberately not inside the per-item loops. The price-band and condition
        gates decide what counts as a competitor for THIS analysis, but they do
        not make the other listings un-read. What eBay returned is what was
        measured; which part of it was eligible is a property of the analysis,
        and it is already recorded there.
        """
        listing_id = listing_id_of(payload)
        if listing_id:
            self.observations.append((listing_id, payload, source))

    def _observe_summaries(self, data: dict, source: str) -> None:
        """Offer every summary in a Browse response to the readings list."""
        if not isinstance(data, dict):
            return
        summaries = data.get("itemSummaries")
        if isinstance(summaries, list):
            for summary in summaries:
                self._observe(summary, source)

    def _record_query_observation(
        self,
        query: str,
        data: dict,
        *,
        limit: int,
        price_filter: str,
    ) -> None:
        """Keep the SET this search returned, including an empty set.

        `_observe_summaries` keeps each listing's fields, but it deliberately
        does not write an unchanged reading twice. Churn needs the other
        fact: which listings the search returned at this moment. So this
        records the whole set once per search, before the local price and
        condition gates - the question is what eBay returned for the request
        as sent, not which part passed this analysis's gates.

        A response is only recorded when it looks like a search answer. An
        error body that happens to parse as JSON must not become a measured
        zero; without `itemSummaries` or `total`, there is no evidence the
        search ran.
        """
        if not isinstance(data, dict):
            return
        if "itemSummaries" not in data and "total" not in data:
            return

        listings: list[dict] = []
        seen: set[str] = set()
        for summary in data.get("itemSummaries") or []:
            row = query_listing(summary)
            if row is None:
                continue
            listing_id = row["listing_id"]
            if listing_id in seen:
                continue
            seen.add(listing_id)
            listings.append(row)

        self.query_observations.append(
            {
                "query": query,
                "observed_at": datetime.utcnow(),
                "source": "browse_search",
                "filter": price_filter,
                "limit": limit,
                "listings": listings,
            }
        )

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
            "X-EBAY-C-MARKETPLACE-ID": self.marketplace["id"],
            "Content-Type": "application/json",
        }

    def search(self, query: str, limit: int = 10,
               price_band: tuple[float, float] | None | _Unset = _UNSET
               ) -> list[ScrapedProduct]:
        """Search the selected eBay marketplace via Browse API.

        `price_band` overrides the ACTIVE range for this call only, with
        three distinct states (omitted / a band / explicit None for "no
        restriction") because None is itself meaningful. Competitor-store
        discovery needs the unrestricted form (REGRESSION-006). Omitting the
        argument preserves the original behaviour exactly.
        """
        if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
            print("[INFO] No eBay API keys - returning empty. Add EBAY_CLIENT_ID/EBAY_CLIENT_SECRET to .env")
            return []
        try:
            return self.search_checked(query, limit, price_band=price_band)
        except Exception as e:
            print(f"[WARN] API search failed: {e}")
            return []

    def search_checked(self, query: str, limit: int = 10,
                       price_band: tuple[float, float] | None | _Unset = _UNSET
                       ) -> list[ScrapedProduct]:
        """Search and let a failure reach the caller.

        `search()` deliberately returns [] when eBay does not answer, which is
        right for a pipeline that can carry on with fewer competitors. It is
        wrong for a route that must distinguish "eBay returned no listing"
        from "eBay never answered"; those routes call this instead.
        """
        if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
            raise ValueError(
                "eBay API credentials are not configured, so no search was made."
            )
        return self._search_api(query, limit, price_band=price_band)

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
            if self.marketplace["currency"] == "GBP":
                lo, hi = active_bounds()
                unrestricted = False
            else:
                # The active band is a GBP decision. On a USD/EUR/AUD/CAD
                # marketplace there is no conversion here, so the only honest
                # default is an unrestricted search rather than filtering a
                # dollar price against pound bounds.
                lo, hi = 0.0, 1_000_000.0
                unrestricted = True
        elif price_band is None:
            lo, hi = 0.0, 1_000_000.0
            unrestricted = True
        else:
            lo, hi = float(price_band[0]), float(price_band[1])
            unrestricted = False

        band_api = ("" if unrestricted
                    else f"price:[{lo:.0f}..{hi:.0f}],"
                         f"priceCurrency:{self.marketplace['currency']}")
        sample_limit = min(limit, 50)
        api_filter = _api_filter(band_api, self.marketplace)
        resp = requests.get(
            f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search",
            params={
                "q": query,
                "limit": sample_limit,
                "filter": api_filter,
                "sort": "-relevance",
            },
            headers=self._api_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        # Phase G - the set this search returned, before the local gates.
        # Recorded separately from the change history so a stable listing
        # still leaves evidence that it was present in this observation.
        self._record_query_observation(
            query,
            data,
            limit=sample_limit,
            price_filter=api_filter,
        )

        # Phase B - the search response carries a creation date, seller
        # feedback, region, postage and category for every listing below. Kept
        # before the gates, so an out-of-band or Used listing is still a real
        # reading of a real listing.
        self._observe_summaries(data, SOURCE_SUMMARY)

        results = []
        for item in data.get("itemSummaries", []):
            price_info = item.get("price", {})
            price = float(price_info.get("value", 0))
            if (
                self.marketplace["currency"] == "GBP"
                and not unrestricted
                and not in_band_range(price, lo, hi)
            ):
                continue  # defence in depth — PR-2 layer 1 (search time)
            condition = item.get("condition", "")
            if not is_new(condition):
                continue  # defence in depth — C10 condition gate
            results.append(ScrapedProduct(
                source=self.source,
                title=item.get("title", ""),
                price=price,
                url=item.get("itemWebUrl", ""),
                image_url=item.get("thumbnailImages", [{}])[0].get("imageUrl")
                    if item.get("thumbnailImages") else None,
                seller=item.get("seller", {}).get("username"),
                condition=condition,
                verified=True,
                currency=self.marketplace["currency"],
                # P4 — stock/shipping only from what the Browse API
                # actually carried; absent keys stay unknown (C13/C1).
                **ebay_item_availability(item),
            ))
        return results

    def search_titles(self, query: str, limit: int = 50) -> list[ScrapedProduct]:
        """One Browse search for the title helper, with no price band.

        `search()` deliberately swallows a failed request and returns an empty
        list, which is right for an analysis that can carry on with fewer
        competitors. The title helper reports a sample size, so it must be
        able to tell "eBay returned nothing" from "eBay did not answer"; this
        method lets the failure reach the caller.

        The condition gate still applies (C10): only New listings reach the
        count. The price band is dropped because the helper describes the
        titles for a query, not the slice of them inside the user's buying
        range.
        """
        return self._search_api(query, limit=limit, price_band=None)

    def _search_scrape(self, query: str) -> list[ScrapedProduct]:
        """Fallback: scrape search page (may be blocked)."""
        lo, hi = active_bounds()
        currency = self.marketplace["currency"]
        # The active buying band is expressed in GBP. Re-imposing those
        # numbers on a USD/EUR/AUD/CAD page would filter against a currency
        # we are not reading, so the fallback only applies the band in GBP.
        band_clause = (
            f"&_udlo={lo:.0f}&_udhi={hi:.0f}" if currency == "GBP" else ""
        )
        search_url = (
            f"{self.marketplace['site_base']}/sch/i.html?"
            f"_nkw={query.replace(' ', '+')}"
            f"&LH_BIN=1&LH_PrefLoc=1"
            f"{band_clause}"
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
                if currency == "GBP" and not in_band(price):
                    continue  # PR-2 layer 1 (search time), GBP only
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
                    source=self.source,
                    title=title,
                    price=price,
                    url=item_url,
                    condition=condition,
                    verified=True,
                    currency=currency,
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
        # Phase B - kept before the C10 condition gate below: a Used listing is
        # still a listing that was read, and this reading claims nothing about
        # whether it qualifies.
        self._observe(item, SOURCE_ITEM)
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
            source=self.source,
            title=item.get("title", ""),
            price=float(price.get("value", 0)),
            url=item.get("itemWebUrl", ""),
            image_url=image.get("imageUrl"),
            seller=seller.get("username"),
            condition=condition,
            verified=True,
            currency=price.get("currency") or self.marketplace["currency"],
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
            source=self.source,
            title=title.get_text(strip=True) if title else "",
            price=self._parse_price(price.get_text(strip=True) if price else "0"),
            url=url,
            image_url=image.get("src") if image else None,
            seller=seller.get_text(strip=True) if seller else None,
            condition=condition_text,
            verified=True,
            currency=self.marketplace["currency"],
            in_stock=stock_state,
            stock_raw=stock_raw,
            availability_url=url if stock_raw else "",
            shipping_cost=ship_cost,
            shipping_days=ship_days,
            shipping_raw=ship_raw,
        )

    def get_sold_data(
        self, query: str,
        price_band: tuple[float, float] | None | _Unset = _UNSET,
    ) -> DemandData:
        """Get sold data — tries API search for completed items.

        `price_band` has the same three-state contract as `search`: omitted
        means the active GBP band on the UK market (and no band elsewhere),
        a tuple is used verbatim, and None asks for no price restriction.
        """
        if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
            return DemandData(verified=False, currency=self.marketplace["currency"])
        try:
            return self._get_sold_api(query, price_band)
        except Exception as e:
            print(f"[WARN] API sold data failed: {e}")
            return DemandData(verified=False, currency=self.marketplace["currency"])

    def _get_sold_api(
        self, query: str,
        price_band: tuple[float, float] | None | _Unset = _UNSET,
    ) -> DemandData:
        """Get sold data via Browse API (search completed listings)."""
        currency = self.marketplace["currency"]
        if isinstance(price_band, _Unset):
            if currency == "GBP":
                lo, hi = active_bounds()
                band_api = (
                    f"price:[{lo:.0f}..{hi:.0f}],priceCurrency:{currency}"
                )
                apply_band = True
            else:
                lo, hi = _UNRESTRICTED_BOUNDS
                band_api = ""
                apply_band = False
        elif price_band is None:
            lo, hi = _UNRESTRICTED_BOUNDS
            band_api = ""
            apply_band = False
        else:
            lo, hi = float(price_band[0]), float(price_band[1])
            band_api = (
                f"price:[{lo:.0f}..{hi:.0f}],priceCurrency:{currency}"
            )
            apply_band = True
        source_label = (
            _SOLD_SOURCE_LABEL if apply_band
            else _SOLD_SOURCE_LABEL_UNRESTRICTED
        )
        resp = requests.get(
            f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search",
            params={
                "q": query,
                "limit": 50,
                # C10 — condition goes into the DEMAND query too, so Used
                # sales can never inflate sold_count / avg price.
                "filter": _api_filter(band_api, self.marketplace),
                "sort": "-dateSold",
            },
            headers=self._api_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        # Phase B - the fifty summaries this query returned, kept in full.
        self._observe_summaries(data, SOURCE_SUMMARY)

        items = data.get("itemSummaries", [])
        if not items:
            # Even "nothing found" names the source it asked: a blank source
            # cannot distinguish "we looked and there was none" from "we never
            # asked" (C13).
            return DemandData(
                verified=False,
                data_source=source_label,
                currency=currency,
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

            if apply_band and not in_band(price):
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
            data_source=source_label,
            currency=currency,
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
