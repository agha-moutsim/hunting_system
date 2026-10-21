"""
Base scraper class — uses Playwright with stealth to bypass bot detection.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page
from playwright_stealth import Stealth

from config import SCRAPE_CONFIG
from scrapers.availability import (
    parse_shipping_text,
    parse_stock_text,
    parse_structured_availability,
)

logger = logging.getLogger(__name__)

# P4 — stock/delivery hooks the HTML scrapers read. Narrow on purpose:
# they name the element a retailer prints availability or delivery in,
# never a whole card (a card also contains the product price, and a £
# read from the wrong element would be a fabricated shipping cost, C1).
STOCK_SELECTORS = (
    "[itemprop='availability']",
    "span[class*='availability']",
    "div[class*='availability']",
    "span[class*='stock']",
    "div[class*='stock']",
)
DELIVERY_SELECTORS = (
    "span[class*='delivery']",
    "div[class*='delivery']",
    "span[class*='shipping']",
    "div[class*='shipping']",
    "span[class*='postage']",
    "div[class*='postage']",
)


def first_text(root, selectors) -> str:
    """Text of the first element matching any selector, '' when none.

    C1 — absence is unknown: no element means '' so the caller sees
    "we read nothing", never an assumed figure. schema.org availability
    markup carries the state in `href`/`content`, so those attribute
    values win over visible text.
    """
    for selector in selectors:
        el = root.select_one(selector)
        if el is None:
            continue
        for attr in ("content", "href"):
            val = el.get(attr)
            if isinstance(val, str) and "schema.org/" in val:
                return val
        text = el.get_text(" ", strip=True)
        if text:
            return text
    return ""


def read_stock(root, selectors=STOCK_SELECTORS) -> tuple[str, str]:
    """(state, raw) for a page/card — visible stock text first, then
    schema.org markup inside JSON-LD. ("", "") when the page states
    nothing: unknown is the answer, never a default (C1/C13).
    """
    text = first_text(root, selectors)
    if text:
        return parse_stock_text(text)
    for script in root.select("script[type='application/ld+json']"):
        state, raw = parse_structured_availability(script.get_text() or "")
        if state or raw:
            return state, raw
    return "", ""


def read_shipping(root, selectors=DELIVERY_SELECTORS) -> tuple[float, int, str]:
    """(cost, days, raw) for a delivery line, all unknown when no
    matching element exists (C1). See parse_shipping_text: trust `raw`
    when cost is 0.0 — it carries the exact text the figure came from.
    """
    return parse_shipping_text(first_text(root, selectors))


@dataclass
class ScrapedProduct:
    """Standardized product data from any source."""
    source: str
    title: str
    price: float
    url: str
    image_url: Optional[str] = None
    delivery_days_min: Optional[int] = None
    delivery_days_max: Optional[int] = None
    seller: Optional[str] = None
    seller_full_name: Optional[str] = None
    seller_rating: Optional[str] = None
    seller_orders: Optional[str] = None
    store_name: Optional[str] = None
    # C10 — '' means "we did not read a condition", NOT "New". Every prior
    # silent default of "New" let Used listings pass by omission.
    condition: str = ""
    brand: Optional[str] = None
    verified: bool = True
    raw_html: Optional[str] = None
    scraped_at: datetime = field(default_factory=datetime.now)
    # P4 — engine.source_type's verdict for this row, classified from the
    # row's own URL/name. '' = not classified; never assumed "dropship".
    # Appended last so existing positional constructions cannot shift.
    supplier_type: str = ""
    # P4 — stock & shipping, read off a real page/API only (C13: raw text
    # travels with the parsed value). '' / 0.0 / 0 mean "we did not read
    # this" (C1) — in_stock is never assumed "in_stock" and shipping_cost
    # is never a plausible figure. shipping_cost 0.0 cannot separate
    # "free" from "unknown" by number alone, so callers trust
    # shipping_raw when cost is 0 (it is '' only when unread).
    # C14 — engine/match.py consumes these names; append-only, exact.
    in_stock: str = ""            # "in_stock" | "low_stock" | "out_of_stock" | "" (unknown)
    stock_raw: str = ""           # the exact source text, e.g. "Only 3 left", "23 available"
    availability_url: str = ""    # where the stock figure was read from (usually the product URL)
    shipping_cost: float = 0.0    # 0.0 = unknown, NEVER a guessed figure
    shipping_days: int = 0        # 0 = unknown
    shipping_raw: str = ""        # exact source text, e.g. "Free delivery Thursday"
    # C14 — written ONLY by engine.match (computed, never a constant).
    # `match_tier == ""` means "not scored yet", which consumers must treat
    # as failed — C12 admits a supplier row only after it cleared threshold.
    match_score: float = 0.0
    match_tier: str = ""          # "verified" | "unverified" | "no_match" | "" (unscored)
    match_label: str = ""         # "verified match" | "not confirmed" | "no confirmed match"
    match_basis: str = ""         # human-readable reason the score is what it is
    match_method: str = ""        # names the algorithm, for the audit trail
    # C14 — pHash of `image_url`, None while it is unread. Written by
    # engine.match.image_hash_for; never a made-up value, and absent means
    # the image could not be obtained so the score falls back to text only.
    image_hash: Optional[int] = None
    # C13 — HOW this row was obtained, which matters for the suppliers whose
    # credentialed API path fails closed: for them only a Playwright page
    # read can produce a row at all, and a reader should be able to tell that
    # apart from a row an API handed us.
    #   "api"     a credentialed/signed API response
    #   "browser" read off a live page in a Playwright browser
    #   ""        not stated — absence is unknown, never assumed (C1).
    # The row is still `verified` either way: C13 defines verified as "a real
    # API response OR a successfully parsed page", and this says which of the
    # two it was. Appended last so existing positional constructions hold.
    fetch_method: str = ""
    # C13 — every factual value carries one of the four labels, and the label
    # is DATA, not a UI decision. These were absent until 2026-10-06, which
    # is why Analyze supplier rows rendered no provenance badge at all: the
    # frontend only draws one when `provenance` is present (or verified is
    # false), so a row that read a real page still showed nothing.
    #   "" = not stamped yet. engine.provenance.stamp_scraped_product fills
    #   it from `verified`; it is never defaulted to "verified" here, because
    #   a constructor that has not read anything must not claim it did.
    provenance: str = ""
    provenance_label: str = ""
    # Phase J — the ISO currency of `price`, when the source stated it. ''
    # means the source did not say, never an assumed GBP. Appended last so
    # existing positional constructions cannot shift.
    currency: str = ""
    # Sourcing standard — real review evidence, when the source stated it.
    # None means "not read", never a guessed rating or count.
    review_rating: Optional[float] = None
    review_count: Optional[int] = None
    review_verified: bool = False
    review_source: str = ""
    # Sourcing standard — shipping methods the source actually named. Empty
    # means none were read; a method is never invented.
    shipping_methods: list[str] = field(default_factory=list)
    # Sourcing standard — AliExpress Standard Shipping, verified from the
    # listing. None means "not stated", False means "unavailable".
    standard_shipping_available: Optional[bool] = None
    standard_shipping_cost: Optional[float] = None
    standard_shipping_days_min: Optional[int] = None
    standard_shipping_days_max: Optional[int] = None
    standard_shipping_raw: str = ""
    # Sourcing standard — deterministic policy output. These are computed by
    # engine.sourcing, never by an LLM or a hidden threshold. Appended last so
    # existing positional constructions cannot shift.
    sourcing_preferred: bool = False
    sourcing_eligible: bool = False
    sourcing_reasons: list[str] = field(default_factory=list)
    total_landed_cost: Optional[float] = None
    review_good: bool = False
    stock_verified: bool = False
    shipping_known: bool = False
    standard_shipping_applicable: bool = False
    sourcing_score: float = 0.0
    sourcing_policy_version: str = ""
@dataclass
class DemandData:
    """Sales demand evidence from eBay.

    DISCIPLINE (2026-10-18) — `sold_count_30d` / `sold_count_7d` are OBSERVED
    SALES and nothing else. Only a browser purchase-history capture can supply
    them today, so None is the normal case and means "sales were not measured"
    — never "no sales" (C1/C4).

    eBay offers this app no sold-listing search: the Finding API's
    findCompletedItems was decommissioned on 2025-02-04, Marketplace Insights
    is closed to new applications, and the Browse API returns ACTIVE listings
    only. A query therefore yields a count of live listings — real and useful
    (it says how crowded a niche is) but SUPPLY, not demand. That count used to
    be written into `sold_count_30d`, which made every downstream "sold" figure
    and every `verified` badge false. It now lives in
    `active_listings_in_band`.
    """
    sold_count_30d: Optional[int] = None
    sold_count_7d: Optional[int] = None
    #: In-band New ACTIVE listings the query returned. The request asks for 50,
    #: so a popular niche saturates and ties: it orders badly at the top and
    #: must never be presented or ranked as sales volume.
    active_listings_in_band: Optional[int] = None
    #: The ASKING PRICES of exactly those live listings — the same rows
    #: `active_listings_in_band` counts. Each one is a real price read from
    #: eBay, but a LISTING price: nothing was sold to produce it. It is a
    #: SUPPLY-side price picture — what it would cost to compete in the niche
    #: today — and it is not, and cannot be made into, evidence of a sale.
    #:
    #: Until 2026-10-19 these numbers lived in `avg_sold_price` /
    #: `lowest_sold_price` / `highest_sold_price` / `sold_prices`, which put a
    #: "sold" label on a live asking price. That was the same defect as
    #: `sold_count_30d` holding a listing count, one field over: the numbers
    #: were real and the word describing them was not.
    avg_active_price: Optional[float] = None
    lowest_active_price: Optional[float] = None
    highest_active_price: Optional[float] = None
    last_sale_date: Optional[str] = None
    #: OBSERVED SALE PRICES and nothing else — what a buyer actually paid. Only
    #: a purchase-history capture can supply these (see `utils.purchase_history`
    #: and the P5 extension path), so None is the normal case and means "no sale
    #: was read", never "the price was zero" (C1/C4).
    avg_sold_price: Optional[float] = None
    lowest_sold_price: Optional[float] = None
    highest_sold_price: Optional[float] = None
    verified: bool = True
    # P5: verification of the 7-day figure specifically. None = no browser
    # purchase-history capture (fall back to `verified`); True = capture-backed.
    verified_7d: Optional[bool] = None
    # PHASE C - the sold figure's provenance, carried as a value/time pair:
    # WHICH source produced it and WHEN that source observed it. Set only by the
    # purchase-history override, and None on every other path, because nothing
    # else this app can reach produces a sold number at all.
    sold_source: Optional[str] = None
    sold_captured_at: Optional[datetime] = None
    # P5: where these counts came from, e.g. "ebay_sold_listings" or
    # "ebay_sold_listings+purchase_history" when a capture was applied.
    data_source: Optional[str] = None
    excluded_over_band: int = 0  # PR-4: sold rows dropped by the band gate
    # C11 — competitor stores aggregated from the SAME sold query this
    # object already ran, so Analyze/URL-hunt get stores for free instead
    # of paying for a second request. Normalised by engine.stores.
    top_sellers: list = field(default_factory=list)
    # A3 - every individual SALE price held for this query, in order. The
    # min/avg/max above are derived from this list and used to be all that
    # survived: the list itself was computed and thrown away, which is why no
    # chart could ever be drawn from real data. Empty means "we hold no sale
    # observations", never "no sales" - sold_count_30d is the count, and the
    # two are reported together, never substituted.
    #
    # The LISTING-price observations live in `active_prices`. The two lists are
    # never merged and never substituted for one another: a live asking price
    # is not evidence of a sale, however many of them there are.
    sold_prices: list = field(default_factory=list)
    #: The prices behind the three `*_active_price` figures above, in the order
    #: eBay returned them. Carried rather than re-derived, so a chart plots
    #: exactly the numbers the metrics show.
    active_prices: list = field(default_factory=list)
    #: Phase J — the ISO currency of every price above. '' means the source
    #: did not state one; an empty string is never rendered as GBP.
    currency: str = ""


class BaseScraper(ABC):
    """Base class — Playwright with stealth for bot bypass."""

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None

    async def close(self):
        """Close browser and cleanup resources."""
        try:
            if self._page:
                await self._page.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        finally:
            self._page = None
            self._browser = None
            self._playwright = None

    async def _ensure_browser(self):
        """Lazy-init stealth browser on first use."""
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            context = await self._browser.new_context(
                user_agent=SCRAPE_CONFIG["user_agent"],
                locale="en-GB",
                viewport={"width": 1920, "height": 1080},
                java_script_enabled=True,
            )
            self._page = await context.new_page()
            stealth = Stealth()
            await stealth.apply_stealth_async(self._page)

    async def fetch(self, url: str, retries: int = 2) -> str:
        """Fetch a URL using stealth Playwright with retry logic."""
        await self._ensure_browser()

        last_error = None
        for attempt in range(retries + 1):
            try:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await self._page.wait_for_timeout(3000)
                return await self._page.content()
            except Exception as e:
                last_error = e
                if attempt < retries:
                    delay = (attempt + 1) * 2  # 2s, 4s, 6s
                    logger.warning(
                        "Fetch attempt %d/%d failed for %s, retrying in %ds: %s",
                        attempt + 1, retries + 1, url, delay, e
                    )
                    await asyncio.sleep(delay)

        raise last_error

    def parse(self, html: str):
        """Parse HTML into BeautifulSoup."""
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser")

    def _parse_price(self, text: str) -> float:
        """Extract numeric price from text."""
        import re
        match = re.search(r"[\d,.]+", text.replace(",", ""))
        return float(match.group()) if match else 0.0

    def _first_text(self, root, selectors) -> str:
        """``root.select_one`` text, '' when nothing matches (C1)."""
        return first_text(root, selectors)

    def _read_stock(self, root, selectors=STOCK_SELECTORS) -> tuple[str, str]:
        """(state, raw) for a page/card — see ``read_stock``."""
        return read_stock(root, selectors)

    def _read_shipping(self, root, selectors=DELIVERY_SELECTORS) -> tuple[float, int, str]:
        """(cost, days, raw) for a delivery line — see ``read_shipping``."""
        return read_shipping(root, selectors)

    @abstractmethod
    async def search(self, query: str) -> list[ScrapedProduct]:
        pass

    @abstractmethod
    async def get_details(self, url: str) -> ScrapedProduct:
        pass

    async def close(self):
        """Close browser."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
