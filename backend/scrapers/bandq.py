"""
B&Q (diy.com) scraper — Google Shopping API first, Playwright fallback.
"""

import os
import re
from urllib.parse import quote_plus

from scrapers.availability import parse_shipping_text, serpapi_item_availability
from scrapers.base import BaseScraper, DELIVERY_SELECTORS, STOCK_SELECTORS, ScrapedProduct
from utils.redact import scrub


class BandQScraper(BaseScraper):
    """Scraper for B&Q (diy.com) — UK retailer with fast delivery."""

    BASE_URL = "https://www.diy.com"
    SEARCH_URL = "https://www.diy.com/search?query={query}"
    SOURCE = "bandq"
    DELIVERY_MIN = 1
    DELIVERY_MAX = 5

    async def search(self, query: str) -> list[ScrapedProduct]:
        """Search B&Q — try Google Shopping API first, fallback to scraping."""
        # Try Google Shopping API
        api_products = self._search_via_google_shopping(query)
        if api_products:
            return api_products

        # Fallback to scraping
        search_url = self.SEARCH_URL.format(query=quote_plus(query))
        try:
            html = await self.fetch(search_url)
            return self._parse_search_results(html)
        except Exception as e:
            print(f"[WARN] B&Q search failed for '{query}': {scrub(e)}")
            return []

    def _search_via_google_shopping(self, query: str) -> list[ScrapedProduct]:
        """Try B&Q products via Google Shopping / SerpApi."""
        api_key = os.getenv("SERPAPI_KEY", "")
        if not api_key:
            return []

        try:
            import requests

            resp = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google_shopping",
                    "q": f"site:diy.com {query}",
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
                if "b&q" not in source.lower() and "diy.com" not in item.get("link", "").lower():
                    continue

                price = item.get("extracted_price", 0)
                if isinstance(price, str):
                    price = float(price.replace("£", "").replace(",", "") or "0")

                products.append(ScrapedProduct(
                    source="bandq",
                    title=item.get("title", ""),
                    price=float(price),
                    url=item.get("link", ""),
                    image_url=item.get("thumbnail", ""),
                    delivery_days_min=self.DELIVERY_MIN,
                    delivery_days_max=self.DELIVERY_MAX,
                    verified=True,
                    # P4 — stock/shipping off the SerpApi entry (C13/C1).
                    **serpapi_item_availability(item),
                ))

            return products

        except Exception as e:
            print(f"[INFO] B&Q Google Shopping unavailable: {scrub(e)}")
            return []

    def _parse_search_results(self, html: str) -> list[ScrapedProduct]:
        """Parse B&Q search results page."""
        soup = self.parse(html)
        results = []

        cards = soup.select(
            "li.search-results__item, "
            "div[data-test='product-card'], "
            "div.product-card, "
            "article.product"
        )
        if not cards:
            cards = soup.select("a[href*='/p/']")

        for card in cards:
            try:
                product = self._extract_search_card(card)
                if product and product.price > 0:
                    results.append(product)
            except Exception as e:
                print(f"[WARN] B&Q failed to parse search card: {scrub(e)}")
                continue

        return results

    def _extract_search_card(self, card) -> ScrapedProduct | None:
        """Extract product data from a single B&Q search result card."""
        title_el = card.select_one(
            "h3, h2, span[data-test='product-title'], "
            "span.product-title, div[class*='title']"
        )
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None

        link_el = card.select_one("a[href]")
        href = ""
        if link_el:
            href = link_el.get("href", "")
            if href and not href.startswith("http"):
                href = f"{self.BASE_URL}{href}"

        price = self._extract_price(card)
        if price <= 0:
            return None

        image_url = self._extract_image(card)

        # P4 — read stock/delivery only where the card prints them; a
        # missing element is unknown, never a default (C1/C13).
        stock_state, stock_raw = self._read_stock(card, STOCK_SELECTORS)
        ship_cost, ship_days, ship_raw = self._read_shipping(card, DELIVERY_SELECTORS)

        return ScrapedProduct(
            source=self.SOURCE,
            title=title,
            price=price,
            url=href,
            image_url=image_url,
            delivery_days_min=self.DELIVERY_MIN,
            delivery_days_max=self.DELIVERY_MAX,
            seller="B&Q",
            condition="New",
            verified=True,
            in_stock=stock_state,
            stock_raw=stock_raw,
            availability_url=href if stock_raw else "",
            shipping_cost=ship_cost,
            shipping_days=ship_days,
            shipping_raw=ship_raw,
        )

    def _extract_price(self, card) -> float:
        """Extract price from a card element."""
        price_el = card.select_one(
            "span[data-test='product-price'], "
            "span.product-price, "
            "div[class*='price'] span, "
            "meta[itemprop='price']"
        )
        if price_el:
            content = price_el.get("content")
            if content:
                return self._parse_price(content)
            return self._parse_price(price_el.get_text(strip=True))

        all_text = card.get_text(" ", strip=True)
        match = re.search(r"£\s*([\d,.]+)", all_text)
        if match:
            return self._parse_price(match.group(0))

        return 0.0

    def _extract_image(self, card) -> str | None:
        """Extract image URL from a card element."""
        img_el = card.select_one("img[src], img[data-src], meta[property='og:image']")
        if not img_el:
            return None
        return (
            img_el.get("src")
            or img_el.get("data-src")
            or img_el.get("content")
        )

    async def get_details(self, url: str) -> ScrapedProduct:
        """Get full product details from a B&Q product page."""
        try:
            html = await self.fetch(url)
            return self._parse_product_page(html, url)
        except Exception as e:
            print(f"[WARN] B&Q details fetch failed for {url}: {scrub(e)}")
            return ScrapedProduct(
                source=self.SOURCE,
                title="",
                price=0.0,
                url=url,
                verified=False,
            )

    def _parse_product_page(self, html: str, url: str) -> ScrapedProduct:
        """Parse B&Q product detail page."""
        soup = self.parse(html)

        title = ""
        title_el = soup.select_one(
            "h1, span[data-test='product-title'], "
            "div[class*='product-name']"
        )
        if title_el:
            title = title_el.get_text(strip=True)

        price = 0.0
        price_el = soup.select_one(
            "span[data-test='product-price'], "
            "div[class*='price'] span, "
            "meta[itemprop='price']"
        )
        if price_el:
            content = price_el.get("content")
            if content:
                price = self._parse_price(content)
            else:
                price = self._parse_price(price_el.get_text(strip=True))

        if price <= 0:
            all_text = soup.get_text(" ", strip=True)
            match = re.search(r"£\s*([\d,.]+)", all_text)
            if match:
                price = self._parse_price(match.group(0))

        image_url = None
        img_el = soup.select_one(
            "img[class*='product'], "
            "div[class*='gallery'] img, "
            "meta[property='og:image']"
        )
        if img_el:
            image_url = (
                img_el.get("src")
                or img_el.get("content")
                or img_el.get("data-src")
            )

        delivery_min, delivery_max = self.DELIVERY_MIN, self.DELIVERY_MAX
        delivery_el = soup.select_one(
            "span[class*='delivery'], "
            "div[class*='delivery'], "
            "div[class*='shipping']"
        )
        if delivery_el:
            delivery_min, delivery_max = self._parse_delivery(
                delivery_el.get_text(strip=True)
            )

        seller = "B&Q"
        seller_el = soup.select_one(
            "span[class*='brand'], a[class*='brand']"
        )
        if seller_el:
            seller = seller_el.get_text(strip=True)

        # P4 — availability read off this page, never assumed (C1/C13).
        # shipping_* is parsed from the SAME element the delivery days
        # above came from, so both describe one reading of one line.
        stock_state, stock_raw = self._read_stock(soup, STOCK_SELECTORS)
        ship_cost, ship_days, ship_raw = parse_shipping_text(
            delivery_el.get_text(" ", strip=True) if delivery_el else ""
        )

        return ScrapedProduct(
            source=self.SOURCE,
            title=title,
            price=price,
            url=url,
            image_url=image_url,
            delivery_days_min=delivery_min,
            delivery_days_max=delivery_max,
            seller=seller,
            condition="New",
            verified=True,
            raw_html=html,
            in_stock=stock_state,
            stock_raw=stock_raw,
            availability_url=url if stock_raw else "",
            shipping_cost=ship_cost,
            shipping_days=ship_days,
            shipping_raw=ship_raw,
        )

    def _parse_delivery(self, text: str) -> tuple[int | None, int | None]:
        """Extract delivery days from text like '1-5 working days'."""
        if not text:
            return self.DELIVERY_MIN, self.DELIVERY_MAX

        text_lower = text.lower()

        if "next day" in text_lower or "next-day" in text_lower:
            return 1, 1

        if "same day" in text_lower:
            return 0, 0

        match = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*(?:working\s*)?days?", text_lower)
        if match:
            return int(match.group(1)), int(match.group(2))

        match = re.search(r"(\d+)\s*(?:working\s*)?days?", text_lower)
        if match:
            days = int(match.group(1))
            return days, days

        return self.DELIVERY_MIN, self.DELIVERY_MAX
