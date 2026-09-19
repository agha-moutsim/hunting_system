"""
CJ Dropshipping scraper — API first, falls back to Playwright scraping.
"""

import os
from typing import Optional

from bs4 import BeautifulSoup, Tag

from scrapers.base import BaseScraper, ScrapedProduct
from config import SCRAPE_CONFIG


class CJDropshippingScraper(BaseScraper):
    """Scraper for CJ Dropshipping — dropship supplier, 7–20 day delivery."""

    SUPPLIER_ID = "cj_dropshipping"
    SEARCH_URL = "https://cjdropshipping.com/search.html?keyword={query}"

    async def search(self, query: str) -> list[ScrapedProduct]:
        """Search CJ — try free API first, fallback to scraping."""
        # Try API first (free, faster, more reliable)
        api_products = self._search_via_api(query)
        if api_products:
            return api_products

        # Fallback to scraping
        url = self.SEARCH_URL.format(query=query.replace(" ", "+"))
        try:
            html = await self.fetch(url)
            return self._parse_search_results(html)
        except Exception as e:
            print(f"[WARN] CJ Dropshipping search failed for '{query}': {e}")
            return []

    def _search_via_api(self, query: str) -> list[ScrapedProduct]:
        """Try CJ Dropshipping free API v2.0."""
        api_key = os.getenv("CJ_API_KEY", "")
        if not api_key:
            return []

        try:
            import requests
            import time

            # Get token
            token = os.getenv("CJ_ACCESS_TOKEN", "")
            if not token:
                resp = requests.post(
                    "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken",
                    json={"apiKey": api_key},
                    timeout=15,
                )
                data = resp.json()
                if data.get("code") == 200:
                    token = data["data"]["accessToken"]

            if not token:
                return []

            # Search products
            resp = requests.get(
                "https://developers.cjdropshipping.com/api2.0/v1/product/listV2",
                headers={
                    "CJ-Access-Token": token,
                    "Content-Type": "application/json",
                },
                params={
                    "keyWord": query,
                    "page": 1,
                    "size": 10,
                    "countryCode": "GB",
                },
                timeout=15,
            )
            data = resp.json()
            if data.get("code") != 200:
                return []

            products = []
            for item in data.get("data", {}).get("content", []):
                for p in item.get("productList", []):
                    price_usd = float(p.get("sellPrice", 0))
                    price_gbp = round(price_usd * 0.79, 2)  # USD to GBP
                    products.append(ScrapedProduct(
                        source=self.SUPPLIER_ID,
                        title=p.get("nameEn", ""),
                        price=price_gbp,
                        url=f"https://cjdropshipping.com/product-p-{p.get('id', '')}.html",
                        image_url=p.get("bigImage", ""),
                        delivery_days_min=3,
                        delivery_days_max=7,
                        verified=True,
                    ))
            return products

        except Exception as e:
            print(f"[INFO] CJ API unavailable: {e}")
            return []

    async def get_details(self, url: str) -> ScrapedProduct:
        """Fetch a single product detail page."""
        try:
            html = await self.fetch(url)
            soup = self.parse(html)
            return self._extract_detail(soup, url)
        except Exception as e:
            print(f"[WARN] CJ Dropshipping detail fetch failed for {url}: {e}")
            return ScrapedProduct(
                source=self.SUPPLIER_ID,
                title="",
                price=0.0,
                url=url,
                delivery_days_min=7,
                delivery_days_max=20,
                verified=False,
            )

    # ------------------------------------------------------------------
    # Search parsing
    # ------------------------------------------------------------------

    def _parse_search_results(self, html: str) -> list[ScrapedProduct]:
        """Parse search results page into ScrapedProduct list."""
        soup = self.parse(html)
        products: list[ScrapedProduct] = []

        items = soup.select("div.product-item, div.product-item-box, div.item-card")
        if not items:
            items = soup.select("a.product-item__link, a[data-product-id]")

        for item in items[:20]:
            product = self._extract_search_item(item)
            if product:
                products.append(product)

        return products

    def _extract_search_item(self, item: Tag) -> Optional[ScrapedProduct]:
        """Extract a single product from a search result card."""
        title = self._extract_text(item, [
            "div.product-item__title",
            "span.product-title",
            "div.item-title",
            "a.product-item__link",
            "h3",
        ])
        if not title:
            return None

        price_text = self._extract_text(item, [
            "div.product-item__price",
            "span.price",
            "div.item-price",
            "span.text-price",
        ])
        price = self._parse_price(price_text) if price_text else 0.0

        link = self._extract_link(item)
        if not link:
            return None
        if not link.startswith("http"):
            link = f"https://cjdropshipping.com{link}"

        image_url = self._extract_image(item)

        return ScrapedProduct(
            source=self.SUPPLIER_ID,
            title=title,
            price=price,
            url=link,
            image_url=image_url,
            delivery_days_min=7,
            delivery_days_max=20,
            verified=True,
        )

    # ------------------------------------------------------------------
    # Detail page parsing
    # ------------------------------------------------------------------

    def _extract_detail(self, soup: BeautifulSoup, url: str) -> ScrapedProduct:
        """Extract product details from a CJ Dropshipping product page."""
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
        for sel in ["a.product-item__link", "a[data-product-id]", "a[href*='/product/']"]:
            el = parent.select_one(sel)
            if el and el.get("href"):
                return el["href"]
        a = parent.find("a", href=True)
        return a["href"] if a else None

    @staticmethod
    def _extract_image(parent: Tag) -> Optional[str]:
        """Get first product image URL."""
        for sel in ["img.product-img", "img.product-item__img", "img"]:
            el = parent.select_one(sel)
            if el:
                return el.get("src") or el.get("data-src")
        return None

    def _parse_delivery(self, text: str) -> tuple[int, int]:
        """Extract delivery day range from text like '7-20 business days'."""
        import re
        match = re.search(r"(\d+)\s*[-–]\s*(\d+)", text)
        if match:
            return int(match.group(1)), int(match.group(2))
        single = re.search(r"(\d+)\s*(?:business\s*)?days?", text)
        if single:
            days = int(single.group(1))
            return days, days
        return 7, 20
