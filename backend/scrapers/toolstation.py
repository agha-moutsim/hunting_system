"""
Toolstation UK scraper — Google Shopping API first, Playwright fallback.
"""

import os
import re

from bs4 import BeautifulSoup

from scrapers.availability import parse_shipping_text, serpapi_item_availability
from scrapers.base import BaseScraper, DELIVERY_SELECTORS, STOCK_SELECTORS, ScrapedProduct
from config import SCRAPE_CONFIG
from utils.redact import scrub


class ToolstationScraper(BaseScraper):
    """Scraper for Toolstation UK — retailer with fast delivery."""

    BASE_URL = "https://www.toolstation.com"
    SEARCH_URL = "https://www.toolstation.com/search?q={query}"

    async def search(self, query: str) -> list[ScrapedProduct]:
        """Search Toolstation — try Google Shopping API first, fallback to scraping."""
        # Try Google Shopping API
        api_products = self._search_via_google_shopping(query)
        if api_products:
            return api_products

        # Fallback to scraping
        url = self.SEARCH_URL.format(query=query.replace(" ", "+"))
        try:
            html = await self.fetch(url)
            return self._parse_search_results(html)
        except Exception as e:
            print(f"[WARN] Toolstation search failed for '{query}': {scrub(e)}")
            return []

    def _search_via_google_shopping(self, query: str) -> list[ScrapedProduct]:
        """Try Toolstation products via Google Shopping / SerpApi."""
        api_key = os.getenv("SERPAPI_KEY", "")
        if not api_key:
            return []

        try:
            import requests

            resp = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google_shopping",
                    "q": f"site:toolstation.com {query}",
                    "location": "United Kingdom",
                    "gl": "uk",
                    "hl": "en",
                    "api_key": api_key,
                },
                timeout=20,
            )
            data = resp.json()

            products = []
            for item in data.get("shopping_results", [])[:10]:
                source = item.get("source", "")
                if "toolstation" not in source.lower() and "toolstation.com" not in item.get("link", "").lower():
                    continue

                price = item.get("extracted_price", 0)
                if isinstance(price, str):
                    price = float(price.replace("£", "").replace(",", "") or "0")

                products.append(ScrapedProduct(
                    source="toolstation",
                    title=item.get("title", ""),
                    price=float(price),
                    url=item.get("link", ""),
                    image_url=item.get("thumbnail", ""),
                    delivery_days_min=1,
                    delivery_days_max=3,
                    verified=True,
                    # P4 — stock/shipping off the SerpApi entry (C13/C1).
                    **serpapi_item_availability(item),
                ))

            return products

        except Exception as e:
            print(f"[INFO] Toolstation Google Shopping unavailable: {scrub(e)}")
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

            # P4 — read stock/delivery only where the card prints them;
            # a missing element is unknown, never a default (C1/C13).
            stock_state, stock_raw = self._read_stock(card, STOCK_SELECTORS)
            ship_cost, ship_days, ship_raw = self._read_shipping(card, DELIVERY_SELECTORS)

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
                in_stock=stock_state,
                stock_raw=stock_raw,
                availability_url=href if stock_raw else "",
                shipping_cost=ship_cost,
                shipping_days=ship_days,
                shipping_raw=ship_raw,
            ))

        return results

    async def get_details(self, url: str) -> ScrapedProduct:
        """Get full product details from a Toolstation product page."""
        try:
            html = await self.fetch(url)
            return self._parse_product_page(html, url)
        except Exception as e:
            print(f"[WARN] Toolstation details failed for '{url}': {scrub(e)}")
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

        # P4 — availability read off this page, never assumed (C1/C13).
        # shipping_* comes from the same line the delivery days did, so
        # both describe one reading.
        stock_state, stock_raw = self._read_stock(soup, STOCK_SELECTORS)
        ship_cost, ship_days, ship_raw = parse_shipping_text(delivery_text)

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
            in_stock=stock_state,
            stock_raw=stock_raw,
            availability_url=url if stock_raw else "",
            shipping_cost=ship_cost,
            shipping_days=ship_days,
            shipping_raw=ship_raw,
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
