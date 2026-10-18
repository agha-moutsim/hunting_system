"""eBay's own Deals page — the only merchandising surface this app can read.

WHY THIS EXISTS
---------------
The board this feeds was going to rank products by "hotness". That plan was
measured against the live account and abandoned, because eBay offers this app
no best-seller or sold-volume data at all:

  * getMostWatchedItems (Merchandising API) — deprecated 2024-07-29,
    decommissioned 2025-01-06.
  * findCompletedItems (Finding API)        — decommissioned 2025-02-04.
  * Marketplace Insights                    — HTTP 403, scope not granted, and
                                              closed to new applications.
  * Deals API                               — HTTP 400, scope not granted.
  * Browse API                              — returns no watchCount, no
                                              quantitySold and no bidCount, and
                                              silently ignores every `sort`
                                              that could proxy for popularity.
                                              (Nineteen such values were tried
                                              and returned byte-identical
                                              ordering to no sort at all.)

Ranking by anything else would have been ranking by supply while claiming
demand. So the board reads a surface that genuinely is real: eBay's own
curated discount page, `https://www.ebay.co.uk/deals`, which answers HTTP 200
to a plain request with no ScrapingBee credit.

Every card on it is a real live listing. Every claim this app makes about a
card comes either from eBay's own page or from the Browse API keyed by that
card's listing id.

HONESTY (C13)
-------------
The board built on this module must say "curated by eBay". eBay selects these
items; this app does not know, and must never imply, which items sell best.
No sold count is ever attached to a deal, because no sold count was measured.

PRICES ARE NOT ON THE DEALS PAGE
--------------------------------
The page's embedded payload carries the merchandised cards with `listingId`,
`imageUrl` and `title` and nothing else — no price. Prices are filled in one
listing at a time from the Browse API via `get_item_by_legacy_id`. A card
whose price could not be read keeps `price = None` and is still shown, because
the card itself is real; what it must never do is display a 0 or a guess.

That is 108 Browse calls for a full page — one per card, plus a second for the
cards whose bare legacy id does not resolve (see `_by_title`; on one live page
that was 35 of 73 cards). At the hourly refresh that is ~2,600/day against the
5,000/day allowance, which is why this is a scheduled job and not a
request-time fetch.

WHAT ELSE A BROWSE CALL RETURNS
-------------------------------
Far more than a price. Each payload also carries the listing's creation date,
the seller's feedback percentage and score, whether that seller is a business or
an individual, the item's location, the postage charged, the category and the
buying options — all of which this module used to drop on the floor. Since the
rich-fields pass, every payload it fetches is handed to `on_observation` and
stored; see scrapers/browse_fields.py for what each field is and why `None`
there means "eBay did not return it". This costs no extra API call: the fields
were in the response the price came from.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

from config import (
    EBAY_API_BASE,
    EBAY_CLIENT_ID,
    EBAY_CLIENT_SECRET,
    EBAY_MARKETPLACE,
    EBAY_UK_BASE,
    SCRAPE_CONFIG,
)
from engine.stores import is_observed_store_url, seller_profile_url
from scrapers.browse_fields import SOURCE_ITEM, SOURCE_SUMMARY

logger = logging.getLogger(__name__)

DEALS_URL = f"{EBAY_UK_BASE}/deals"

#: The one label this board is allowed to wear. eBay curates the page; the
#: word "popular" or "best selling" would be a claim nobody measured.
SOURCE = "ebay_deals"
SOURCE_LABEL = "eBay Deals — curated by eBay"

#: A merchandised card in the page's embedded payload.
#:
#: Key ORDER is not stable between renders, so the object body is matched first
#: and each field is then pulled out of that body on its own. The body cannot
#: cross a brace: these objects are flat, and `[^{}]` is what keeps a match
#: inside one object instead of running into the next.
_CARD_RE = re.compile(r'\{[^{}]{0,1200}?"listingId"\s*:\s*"(\d{9,15})"[^{}]{0,1200}?\}')
_TITLE_RE = re.compile(r'"(?:title|itemTitle)"\s*:\s*"((?:[^"\\]|\\.)*)"')
_IMAGE_RE = re.compile(r'"(?:imageUrl|imageURL)"\s*:\s*"([^"]+)"')
_ITEM_URL_RE = re.compile(r'"(?:itemWebUrl|itemUrl)"\s*:\s*"([^"]+)"')

#: eBay serves image URLs at whatever size the page asked for. The card wants a
#: fixed box, and eBay's own convention is that the `s-lNNN` segment sets the
#: longest edge, so it is rewritten rather than cropped in CSS — a 225px source
#: stretched into a 400px box is the blurry look this avoids.
_IMAGE_SIZE_RE = re.compile(r"/s-l\d+\.(jpg|jpeg|png|webp)$", re.I)


def _upgrade_image(url: str, size: int = 500) -> str:
    """Ask eBay for a larger render of the same image, or leave the URL alone."""
    if not url:
        return ""
    return _IMAGE_SIZE_RE.sub(rf"/s-l{size}.\1", url)


def _decode(raw: str) -> str:
    """Decode a JSON string body, falling back to the raw text.

    Titles carry ™, ®, curly quotes and escaped slashes. Decoding through json
    is what renders them as eBay wrote them. When eBay serves a fragment that
    is not valid JSON the raw text is still a real title, so it is kept rather
    than dropping a genuine listing over a cosmetic problem.
    """
    try:
        return json.loads(f'"{raw}"')
    except Exception:
        return raw


@dataclass
class DealItem:
    """One real listing eBay has chosen to merchandise on its deals page."""

    listing_id: str
    title: str
    #: Position on eBay's page, 0-based. Recorded because it is a real
    #: observation about the page, not because it means "ranked by sales".
    position: int = 0
    image_url: str = ""
    #: Canonical item URL. Built from the listing id when the API did not hand
    #: one back, which is the same form the API returns.
    item_url: str = ""
    #: Real price read from the Browse API, or None when it could not be read.
    #: None is rendered as "see price on eBay" — never as 0, never as a guess.
    price: Optional[float] = None
    currency: str = ""
    seller: str = ""
    store_name: str = ""
    #: The seller's storefront, and whether eBay itself rendered that link.
    #: Kept apart for the same reason `engine.stores` does it: a username is
    #: not a store slug, and only an observed `/str/` URL may claim to be one.
    store_url: str = ""
    store_verified: bool = False
    condition: str = ""
    #: Which refresh produced this row, so a stale row is visibly stale.
    fetched_at: Optional[str] = None
    source: str = SOURCE
    source_label: str = SOURCE_LABEL
    #: False while the card carries only what the deals page itself gave us.
    price_read: bool = False


def parse_deals_page(html: str) -> list[DealItem]:
    """Pull the merchandised cards out of an eBay deals page.

    Pure: no network, no globals, so the parser can be pinned against a saved
    page. Returns the cards in page order, de-duplicated by listing id — the
    page repeats entries across its sections and a duplicated card would
    otherwise occupy two slots in the rotation.
    """
    if not html:
        return []

    seen: dict[str, DealItem] = {}
    for position, match in enumerate(_CARD_RE.finditer(html)):
        listing_id = match.group(1)
        body = match.group(0)

        title_match = _TITLE_RE.search(body)
        if not title_match:
            # A card with no title cannot be shown honestly, so it is not
            # shown at all rather than rendered as a blank placeholder.
            continue
        title = _decode(title_match.group(1)).strip()
        if not title:
            continue

        image_match = _IMAGE_RE.search(body)
        url_match = _ITEM_URL_RE.search(body)
        item = DealItem(
            listing_id=listing_id,
            title=title,
            position=position,
            image_url=_upgrade_image(image_match.group(1)) if image_match else "",
            item_url=(url_match.group(1) if url_match else "") or "",
        )
        if not item.item_url:
            item.item_url = f"{EBAY_UK_BASE}/itm/{listing_id}"

        # First occurrence wins: the earliest slot is where eBay put it.
        seen.setdefault(listing_id, item)

    return list(seen.values())


def _price_of(payload: dict) -> tuple[Optional[float], str]:
    """Read `price` whether it arrives as an object or a bare string.

    eBay is not consistent about this between the two item endpoints, and the
    difference has to be absorbed here or a real price silently becomes None.
    """
    raw = payload.get("price")
    if isinstance(raw, dict):
        value = raw.get("value")
        currency = str(raw.get("currency") or "")
    elif isinstance(raw, str) and raw.strip():
        text = raw.strip()
        match = re.search(r"([\d.,]+)", text)
        value = match.group(1).replace(",", "") if match else None
        currency = "GBP" if "£" in text else ""
    else:
        return None, ""
    if value is None:
        return None, currency
    try:
        return float(value), currency
    except (TypeError, ValueError):
        return None, currency


class EbayDealsScraper:
    """Read eBay's own deals page, then price its cards from the Browse API."""

    def __init__(
        self,
        on_observation: Optional[Callable[[str, dict, str], None]] = None,
    ) -> None:
        #: Called with (listing_id, payload, source) for every real reading this
        #: scraper takes. None by default - the scraper neither knows nor cares
        #: what a caller does with a reading, which is what keeps it free of
        #: database knowledge and testable without one.
        self.on_observation = on_observation
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": SCRAPE_CONFIG["user_agent"],
            "Accept-Language": SCRAPE_CONFIG["accept_language"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self._token: Optional[str] = None
        self._token_expiry = 0.0
        self._api_calls = 0
        self._price_failures = 0

    # -- Browse API ---------------------------------------------------------

    def _get_token(self) -> str:
        """Application token via the client-credentials flow."""
        now = time.time()
        if self._token and now < self._token_expiry:
            return self._token
        if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
            raise ValueError("EBAY_CLIENT_ID and EBAY_CLIENT_SECRET required")
        credentials = f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()
        resp = requests.post(
            f"{EBAY_API_BASE}/identity/v1/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic " + base64.b64encode(credentials).decode(),
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = now + payload.get("expires_in", 7200) - 300
        return self._token

    def _api_get(self, path: str, params: dict) -> Optional[dict]:
        """One authenticated Browse GET.

        Returns None for anything that is not a usable payload. The only thing
        it raises is QuotaExhausted, which the caller turns into "stop asking".
        """
        try:
            resp = requests.get(
                f"{EBAY_API_BASE}{path}",
                params=params,
                headers={
                    "Authorization": f"Bearer {self._get_token()}",
                    "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE,
                    "Accept": "application/json",
                },
                timeout=20,
            )
        except Exception:
            return None

        self._api_calls += 1
        if resp.status_code == 429:
            raise QuotaExhausted()
        if resp.status_code != 200:
            return None
        try:
            payload = resp.json()
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _by_id(self, item: DealItem) -> Optional[dict]:
        return self._api_get(
            "/buy/browse/v1/item/get_item_by_legacy_id",
            {"legacy_item_id": item.listing_id},
        )

    def _by_title(self, item: DealItem) -> Optional[dict]:
        """Second chance for a listing the by-id endpoint cannot resolve.

        Some deals are multi-variation listings: their RESTful id carries a
        non-zero variation (v1|306325186003|606018449347), and for those
        `get_item_by_legacy_id` answers HTTP 400 / errorId 11006 for the bare
        legacy id. The listing is perfectly live and in this marketplace — a
        title search returns it with its price — so without this the card loses
        a price it can genuinely have. Measured: 35 of 73 cards on one page
        failed this way, which is half the board.

        The result is matched on `legacyItemId` EXACTLY. The title is only a way
        to REACH the listing; a summary belonging to any other seller is
        discarded, so this can never attach someone else's price to this card.
        """
        payload = self._api_get(
            "/buy/browse/v1/item_summary/search",
            {"q": item.title[:100], "limit": 50},
        )
        if not payload:
            return None
        for summary in payload.get("itemSummaries") or []:
            if str(summary.get("legacyItemId") or "") == item.listing_id:
                return summary
        return None

    def _apply(self, item: DealItem, payload: dict) -> bool:
        """Copy what a card needs out of an eBay item payload.

        One place, so the by-id path and the search fallback cannot disagree
        about what a card ends up holding.
        """
        price, currency = _price_of(payload)
        if price is None:
            return False

        item.price = price
        item.currency = currency
        item.price_read = True

        seller = payload.get("seller") or {}
        item.seller = str(seller.get("username") or "")
        item.store_name = str(seller.get("storeName") or "")

        # The store ladder, reused rather than reinvented: an eBay-rendered
        # `/str/` URL is an observed storefront, anything else falls back to the
        # seller's profile, which claims nothing about owning a store.
        observed = str(seller.get("storeUrl") or "")
        if is_observed_store_url(observed):
            item.store_url = observed
            item.store_verified = True
        else:
            item.store_url = seller_profile_url(item.seller)
            item.store_verified = False

        if payload.get("condition"):
            item.condition = str(payload["condition"])
        if payload.get("itemWebUrl"):
            item.item_url = str(payload["itemWebUrl"])
        image = (payload.get("image") or {}).get("imageUrl")
        if image:
            item.image_url = _upgrade_image(str(image))
        return True

    def _observe(self, listing_id: str, payload: dict, source: str) -> None:
        """Hand one real reading to the sink, if a sink is attached.

        A side effect must never cost the board its prices, so a failing sink is
        logged and swallowed here. It cannot go unnoticed: the refresh reports
        how many readings it recorded, and a sink that starts failing shows up
        there.
        """
        if self.on_observation is None:
            return
        try:
            self.on_observation(listing_id, payload, source)
        except Exception:  # noqa: BLE001 - reported to the log, never raised
            logger.warning(
                "Observation sink failed for listing %s", listing_id, exc_info=True
            )

    def enrich(self, item: DealItem) -> bool:
        """Fill one card's price and seller from the Browse API.

        Returns True when a price was read. Failures are counted, never
        guessed: a card that cannot be priced keeps `price = None` and stays on
        the board, because the listing is real either way.
        """
        payload = self._by_id(item)
        source = SOURCE_ITEM
        if payload is None:
            payload = self._by_title(item)
            source = SOURCE_SUMMARY
        if payload is None:
            self._price_failures += 1
            return False

        # Recorded before the price is judged: the listing's fields are real
        # whether or not this card ends up with a readable price, and a card
        # with no price is exactly the one whose other fields are worth having.
        self._observe(item.listing_id, payload, source)

        if not self._apply(item, payload):
            self._price_failures += 1
            return False
        return True

    # -- Page ---------------------------------------------------------------

    def fetch_page(self, url: str = DEALS_URL) -> str:
        """Fetch the deals page. Raises on a non-200 rather than parsing HTML
        that is really an error page — a 403 body would otherwise parse to
        zero cards and read as "eBay has no deals today"."""
        resp = self.session.get(url, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"eBay deals page returned HTTP {resp.status_code}")
        return resp.text

    def fetch_deals(
        self,
        limit: Optional[int] = None,
        enrich: bool = True,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> list[DealItem]:
        """Fetch the page, then price up to `limit` of its cards.

        `limit` exists for a cheap partial refresh and for tests; the scheduled
        job passes None and prices the whole page.
        """
        items = parse_deals_page(self.fetch_page())
        if not enrich:
            return items[:limit] if limit else items

        targets = items[:limit] if limit else items
        for index, item in enumerate(targets):
            try:
                self.enrich(item)
            except QuotaExhausted:
                # Recorded honestly: the rest keep no price this refresh.
                break
            if on_progress:
                on_progress(index + 1, len(targets))
        return items

    # -- Reporting ----------------------------------------------------------

    @property
    def api_calls(self) -> int:
        """Browse calls spent, so a run can be checked against the allowance."""
        return self._api_calls

    @property
    def price_failures(self) -> int:
        return self._price_failures


class QuotaExhausted(RuntimeError):
    """The Browse allowance is spent; stop asking for prices this run."""
