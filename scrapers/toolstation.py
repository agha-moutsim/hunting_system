"""
Toolstation UK scraper — Playwright stealth for bot bypass.
"""

import re

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, ScrapedProduct
from config import SCRAPE_CONFIG


class ToolstationScraper(BaseScraper):
    """Scraper for Toolstation UK — retailer with fast delivery."""

    BASE_URL = "https://www.toolstation.com"
    SEARCH_URL = "https://www.toolstation.com/search?q={query}"

    async def search(self, query: str) -> list[ScrapedProduct]:
        """Search Toolstation for products."""
        url = self.SEARCH_URL.format(query=query.replace(" ", "+"))
        try:
            html = await self.fetch(url)
            return self._parse_search_results(html)
        except Exception as e:
            print(f"[WARN] Toolstation search failed for '{query}': {e}")
            return []

    def _parse_search_results(self, html: str) -> list[ScrapedProduct]:
        """Parse search results page into ScrapedProduct list."""
        soup = self.parse(html)
        results = []

        for card in soup.select("div.product-card, li.product-card, div[class*='product']"):
            title_el = card.select_one("a[class*='title'], h2, h3, span[class*='name']")
            price_el = card.select_one("span[class*='price'], div[class*='price']")
            link_el = card.select_one("a[href]")
            image_el = card.select_one("img[src], img[data-src]")

            if not title_el or not price_el:
                continue

            title = title_el.get_text(strip=True)
            if not title:
                continue

            price = self._parse_price(price_el.get_text(strip=True))
            if price <= 0:
                continue

            href = link_el.get("href", "") if link_el else ""
            if href and not href.startswith("http"):
                href = f"{self.BASE_URL}{href}"

            image_url = None
            if image_el:
                image_url = image_el.get("src") or image_el.get("data-src")

            results.append(ScrapedProduct(
                source="toolstation",
                title=title,
                price=price,
                url=href,
                image_url=image_url,
                delivery_days_min=1,
                delivery_days_max=5,
                seller="Toolstation",
                condition="New",
                verified=True,
            ))

        return results

    async def get_details(self, url: str) -> ScrapedProduct:
        """Get full product details from a Toolstation product page."""
        try:
            html = await self.fetch(url)
            return self._parse_product_page(html, url)
        except Exception as e:
            print(f"[WARN] Toolstation details failed for '{url}': {e}")
            return ScrapedProduct(
                source="toolstation",
                title="",
                price=0.0,
                url=url,
                verified=False,
            )

    def _parse_product_page(self, html: str, url: str) -> ScrapedProduct:
        """Parse a single product page."""
        soup = self.parse(html)

        title_el = soup.select_one("h1, span[class*='title'], div[class*='product-name']")
        price_el = soup.select_one("span[class*='price'], div[class*='price'], meta[itemprop='price']")
        image_el = soup.select_one("img[class*='product'], div[class*='gallery'] img, meta[property='og:image']")
        delivery_el = soup.select_one("span[class*='delivery'], div[class*='delivery'], div[class*='shipping']")
        seller_el = soup.select_one("span[class*='brand'], a[class*='brand'], div[class*='seller']")

        title = title_el.get_text(strip=True) if title_el else ""

        price = 0.0
        if price_el:
            price_content = price_el.get("content") or price_el.get_text(strip=True)
            price = self._parse_price(price_content)

        image_url = None
        if image_el:
            image_url = image_el.get("src") or image_el.get("content") or image_el.get("data-src")

        delivery_text = delivery_el.get_text(strip=True) if delivery_el else ""
        delivery_min, delivery_max = self._parse_delivery(delivery_text)

        seller = seller_el.get_text(strip=True) if seller_el else "Toolstation"

        return ScrapedProduct(
            source="toolstation",
            title=title,
            price=price,
            url=url,
            image_url=image_url,
            delivery_days_min=delivery_min or 1,
            delivery_days_max=delivery_max or 5,
            seller=seller,
            condition="New",
            verified=True,
        )

    def _parse_delivery(self, text: str) -> tuple[int | None, int | None]:
        """Extract delivery days from text like '1-5 working days' or 'Next day'."""
        if not text:
            return None, None

        text_lower = text.lower()

        if "next day" in text_lower or "next-day" in text_lower:
            return 1, 1

        match = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*(?:working\s*)?days?", text_lower)
        if match:
            return int(match.group(1)), int(match.group(2))

        match = re.search(r"(\d+)\s*(?:working\s*)?days?", text_lower)
        if match:
            days = int(match.group(1))
            return days, days

        return None, None

    def _parse_price(self, text: str) -> float:
        """Extract numeric GBP price from text."""
        text = text.replace("£", "").replace(",", "").strip()
        match = re.search(r"[\d.]+", text)
        return float(match.group()) if match else 0.0
