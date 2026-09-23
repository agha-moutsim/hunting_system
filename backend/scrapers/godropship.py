"""
GoDropship scraper — uses Playwright stealth via BaseScraper.
Dropship supplier, 7–18 day delivery.
"""

from typing import Optional

from bs4 import BeautifulSoup, Tag

from scrapers.base import BaseScraper, ScrapedProduct
from config import SCRAPE_CONFIG


class GoDropshipScraper(BaseScraper):
    """Scraper for GoDropship — dropship supplier, 7–18 day delivery."""

    SUPPLIER_ID = "godropship"
    SEARCH_URL = "https://www.godropship.com/search?q={query}"
    DELIVERY_MIN = 7
    DELIVERY_MAX = 18

    async def search(self, query: str) -> list[ScrapedProduct]:
        """Search GoDropship and return product list."""
        url = self.SEARCH_URL.format(query=query.replace(" ", "+"))
        try:
            html = await self.fetch(url)
            return self._parse_search_results(html)
        except Exception as e:
            print(f"[WARN] GoDropship search failed for '{query}': {e}")
            return []

    async def get_details(self, url: str) -> ScrapedProduct:
        """Fetch a single product detail page."""
        try:
            html = await self.fetch(url)
            soup = self.parse(html)
            return self._extract_detail(soup, url)
        except Exception as e:
            print(f"[WARN] GoDropship detail fetch failed for {url}: {e}")
            return ScrapedProduct(
                source=self.SUPPLIER_ID,
                title="",
                price=0.0,
                url=url,
                delivery_days_min=self.DELIVERY_MIN,
                delivery_days_max=self.DELIVERY_MAX,
                verified=False,
            )

    # ------------------------------------------------------------------
    # Search parsing
    # ------------------------------------------------------------------

    def _parse_search_results(self, html: str) -> list[ScrapedProduct]:
        """Parse search results page into ScrapedProduct list."""
        soup = self.parse(html)
        products: list[ScrapedProduct] = []

        items = soup.select("div.product-item, div.product-card, div.item-card, div.product-box")
        if not items:
            items = soup.select("a[href*='/product/'], a[data-product-id]")

        for item in items[:20]:
            product = self._extract_search_item(item)
            if product:
                products.append(product)

        return products

    def _extract_search_item(self, item: Tag) -> Optional[ScrapedProduct]:
        """Extract a single product from a search result card."""
        title = self._extract_text(item, [
            "div.product-title",
            "span.product-name",
            "div.item-title",
            "h3",
            "a[href*='/product/']",
        ])
        if not title or len(title) < 5:
            return None

        price_text = self._extract_text(item, [
            "div.product-price",
            "span.price",
            "div.item-price",
            "span.text-price",
            "[class*='price']",
        ])
        price = self._parse_price(price_text) if price_text else 0.0
        if price <= 0:
            return None

        link = self._extract_link(item)
        if not link:
            return None
        if not link.startswith("http"):
            link = f"https://www.godropship.com{link}"

        image_url = self._extract_image(item)

        # Try to extract delivery days from text
        delivery_text = self._extract_text(item, [
            "div.delivery-time",
            "span.shipping",
            "[class*='delivery']",
        ])
        delivery_min, delivery_max = self.DELIVERY_MIN, self.DELIVERY_MAX
        if delivery_text:
            import re
            days = re.findall(r"(\d+)", delivery_text)
            if len(days) >= 2:
                delivery_min = int(days[0])
                delivery_max = int(days[1])
            elif len(days) == 1:
                delivery_min = delivery_max = int(days[0])

        return ScrapedProduct(
            source=self.SUPPLIER_ID,
            title=title,
            price=price,
            url=link,
            image_url=image_url,
            delivery_days_min=delivery_min,
            delivery_days_max=delivery_max,
            verified=True,
        )

    # ------------------------------------------------------------------
    # Detail page parsing
    # ------------------------------------------------------------------

    def _extract_detail(self, soup: BeautifulSoup, url: str) -> ScrapedProduct:
        """Extract product details from a GoDropship product page."""
        title = self._extract_text(soup, [
            "h1.product-title",
            "div.detail-title",
            "h1.item-title",
            "h1",
        ]) or ""

        price_text = self._extract_text(soup, [
            "span.product-price",
            "div.price",
            "span.text-price",
            "div.detail-price",
            "[class*='price']",
        ])
        price = self._parse_price(price_text) if price_text else 0.0

        image_url = None
        img = soup.select_one("img.product-img, img.detail-img, img.main-img")
        if img:
            image_url = img.get("src") or img.get("data-src")

        delivery_text = self._extract_text(soup, [
            "span.delivery-time",
            "div.shipping-info",
            "span.shipping",
            "div.delivery",
        ])
        days_min, days_max = self._parse_delivery(delivery_text)

        return ScrapedProduct(
            source=self.SUPPLIER_ID,
            title=title,
            price=price,
            url=url,
            image_url=image_url,
            delivery_days_min=days_min,
            delivery_days_max=days_max,
            verified=True,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(parent: Tag, selectors: list[str]) -> str:
        """Try each selector in order, return first non-empty text."""
        for sel in selectors:
            el = parent.select_one(sel)
            if el:
                text = el.get_text(strip=True)
                if text:
                    return text
        return ""

    @staticmethod
    def _extract_link(parent: Tag) -> Optional[str]:
        """Get href from the first product link."""
        for sel in ["a[href*='/product/']", "a[data-product-id]", "a.product-link"]:
            el = parent.select_one(sel)
            if el and el.get("href"):
                return el["href"]
        a = parent.find("a", href=True)
        return a["href"] if a else None

    @staticmethod
    def _extract_image(parent: Tag) -> Optional[str]:
        """Get first product image URL."""
        for sel in ["img.product-img", "img.product-image", "img"]:
            el = parent.select_one(sel)
            if el:
                return el.get("src") or el.get("data-src")
        return None

    def _parse_delivery(self, text: str) -> tuple[int, int]:
        """Extract delivery day range from text like '7-18 business days'."""
        import re
        match = re.search(r"(\d+)\s*[-–]\s*(\d+)", text)
        if match:
            return int(match.group(1)), int(match.group(2))
        single = re.search(r"(\d+)\s*(?:business\s*)?days?", text)
        if single:
            days = int(single.group(1))
            return days, days
        return self.DELIVERY_MIN, self.DELIVERY_MAX
