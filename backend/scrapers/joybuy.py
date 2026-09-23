"""
Joybuy UK supplier scraper — searches listings and extracts product details.
Extends BaseScraper (Playwright + stealth). Dropship supplier, 7-21 day delivery.
"""

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from config import SCRAPE_CONFIG
from scrapers.base import BaseScraper, ScrapedProduct

logger = logging.getLogger(__name__)

# Load supplier config from JSON
import json
from config import SUPPLIERS_JSON
with open(SUPPLIERS_JSON) as f:
    _suppliers = json.load(f)["suppliers"]

SUPPLIER = _suppliers["joybuy"]
SEARCH_URL = SUPPLIER["search_url"]  # https://www.joybuy.com/search?q={query}
BASE_URL = SUPPLIER["base_url"]     # https://www.joybuy.com
DELIVERY_MIN = SUPPLIER["delivery_days_min"]  # 7
DELIVERY_MAX = SUPPLIER["delivery_days_max"]  # 21


class JoybuyScraper(BaseScraper):
    """Scrape Joybuy UK search results and product detail pages."""

    async def search(self, query: str) -> list[ScrapedProduct]:
        """Search Joybuy and return product cards."""
        url = SEARCH_URL.replace("{query}", quote_plus(query))
        products: list[ScrapedProduct] = []

        for attempt in range(1, SCRAPE_CONFIG["max_retries"] + 1):
            try:
                html = await self.fetch(url)
                products = self._parse_search_results(html)
                if products:
                    return products
                logger.warning("Search returned 0 products, retrying (attempt %d)", attempt)
            except Exception as exc:
                logger.error("Joybuy search failed (attempt %d): %s", attempt, exc)

            if attempt < SCRAPE_CONFIG["max_retries"]:
                await asyncio.sleep(SCRAPE_CONFIG["retry_delay"])

        return products

    async def get_details(self, url: str) -> ScrapedProduct:
        """Fetch a single Joybuy listing and extract full details."""
        for attempt in range(1, SCRAPE_CONFIG["max_retries"] + 1):
            try:
                html = await self.fetch(url)
                return self._parse_detail_page(html, url)
            except Exception as exc:
                logger.error("Joybuy detail fetch failed (attempt %d): %s", attempt, exc)
                if attempt < SCRAPE_CONFIG["max_retries"]:
                    await asyncio.sleep(SCRAPE_CONFIG["retry_delay"])

        return ScrapedProduct(
            source="joybuy",
            title="",
            price=0.0,
            url=url,
            verified=False,
        )

    # ------------------------------------------------------------------
    # Private parsers
    # ------------------------------------------------------------------

    def _parse_search_results(self, html: str) -> list[ScrapedProduct]:
        """Parse search results page into ScrapedProduct list."""
        soup = self.parse(html)
        products: list[ScrapedProduct] = []
        seen_titles = set()

        cards = soup.select('[class*="product"], [class*="item"], [data-sku]')
        if not cards:
            cards = soup.select("a[href*='/product/']")

        for card in cards:
            try:
                title = self._extract_title(card)
                if not title or len(title) < 5 or title in seen_titles:
                    continue

                price = self._extract_price(card)
                if price <= 0:
                    continue

                link = self._extract_link(card)
                image_url = self._extract_image(card)

                # Try to extract delivery days from card
                delivery_min, delivery_max = DELIVERY_MIN, DELIVERY_MAX
                delivery_el = card.select_one("[class*='delivery'], [class*='shipping']")
                if delivery_el:
                    import re
                    days = re.findall(r"(\d+)", delivery_el.get_text())
                    if len(days) >= 2:
                        delivery_min = int(days[0])
                        delivery_max = int(days[1])
                    elif len(days) == 1:
                        delivery_min = delivery_max = int(days[0])

                seen_titles.add(title)
                product = ScrapedProduct(
                    source="joybuy",
                    title=title,
                    price=price,
                    url=link,
                    image_url=image_url,
                    delivery_days_min=delivery_min,
                    delivery_days_max=delivery_max,
                    condition="New",
                    verified=True,
                    raw_html=str(card),
                )
                products.append(product)
            except Exception as exc:
                logger.debug("Skipping card: %s", exc)

        return products

    def _parse_detail_page(self, html: str, url: str) -> ScrapedProduct:
        """Parse a single product detail page."""
        soup = self.parse(html)

        title = self._extract_title(soup) or ""
        price = self._extract_price(soup)
        if price <= 0:
            raise ValueError("Could not extract price from detail page")

        image_url = self._extract_image(soup)
        delivery_min, delivery_max = self._extract_delivery(soup)

        return ScrapedProduct(
            source="joybuy",
            title=title,
            price=price,
            url=url,
            image_url=image_url,
            delivery_days_min=delivery_min,
            delivery_days_max=delivery_max,
            condition="New",
            verified=True,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_title(self, element) -> str:
        """Get product title from an element tree."""
        for sel in ["h1", "[class*='title']", "[class*='name']", "h3"]:
            el = element.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return ""

    def _extract_price(self, element) -> float:
        """Extract GBP price from an element tree."""
        for sel in [
            "[class*='price'] span",
            "[class*='Price'] span",
            "[class*='price']",
            "[itemprop='price']",
        ]:
            els = element.select(sel)
            for el in els:
                text = el.get_text(strip=True)
                price = self._parse_price(text)
                if price > 0:
                    return price
                price = self._parse_price(el.get("content", ""))
                if price > 0:
                    return price
        return 0.0

    def _extract_link(self, element) -> str:
        """Extract product URL from a card element."""
        link_el = element.select_one("a[href]") if element.name != "a" else element
        if link_el:
            href = link_el.get("href", "")
            if href.startswith("/"):
                return BASE_URL + href
            if href.startswith("http"):
                return href
        return ""

    def _extract_image(self, element) -> Optional[str]:
        """Extract product image URL."""
        img = element.select_one("img")
        if img:
            src = img.get("src") or img.get("data-src") or ""
            if src:
                return src if src.startswith("http") else "https:" + src
        return None

    def _extract_delivery(self, soup) -> tuple[int, int]:
        """Try to extract delivery window from page text, fall back to supplier defaults."""
        text = soup.get_text()
        match = re.search(
            r"(\d+)\s*[-–]\s*(\d+)\s*(?:business\s+)?days?",
            text,
            re.IGNORECASE,
        )
        if match:
            return int(match.group(1)), int(match.group(2))
        return DELIVERY_MIN, DELIVERY_MAX
