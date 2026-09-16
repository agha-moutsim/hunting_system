"""
B&Q (diy.com) scraper — Playwright stealth for bot bypass.
"""

import re
from urllib.parse import quote_plus

from scrapers.base import BaseScraper, ScrapedProduct


class BandQScraper(BaseScraper):
    """Scraper for B&Q (diy.com) — UK retailer with fast delivery."""

    BASE_URL = "https://www.diy.com"
    SEARCH_URL = "https://www.diy.com/search?query={query}"
    SOURCE = "bandq"
    DELIVERY_MIN = 1
    DELIVERY_MAX = 5

    async def search(self, query: str) -> list[ScrapedProduct]:
        """Search B&Q for products matching query."""
        search_url = self.SEARCH_URL.format(query=quote_plus(query))
        try:
            html = await self.fetch(search_url)
            return self._parse_search_results(html)
        except Exception as e:
            print(f"[WARN] B&Q search failed for '{query}': {e}")
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
                print(f"[WARN] B&Q failed to parse search card: {e}")
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
            print(f"[WARN] B&Q details fetch failed for {url}: {e}")
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
