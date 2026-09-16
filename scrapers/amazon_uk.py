"""
Amazon UK scraper — uses Playwright stealth to search and extract product data.
"""

import re
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus

from scrapers.base import BaseScraper, ScrapedProduct
from config import SCRAPE_CONFIG


class AmazonUKScraper(BaseScraper):
    """Scraper for Amazon UK — Playwright stealth with BeautifulSoup parsing."""

    BASE_URL = "https://www.amazon.co.uk"
    SEARCH_URL = "https://www.amazon.co.uk/s?k={query}"

    async def search(self, query: str) -> list[ScrapedProduct]:
        """Search Amazon UK for products matching query."""
        search_url = self.SEARCH_URL.format(query=quote_plus(query))
        try:
            html = await self.fetch(search_url)
            return self._parse_search_results(html)
        except Exception as e:
            print(f"[WARN] Amazon UK search failed for '{query}': {e}")
            return []

    def _parse_search_results(self, html: str) -> list[ScrapedProduct]:
        """Parse Amazon UK search results page."""
        soup = self.parse(html)
        results = []

        for card in soup.select('div[data-component-type="s-search-result"]'):
            try:
                product = self._extract_search_card(card)
                if product and product.price > 0:
                    results.append(product)
            except Exception as e:
                print(f"[WARN] Failed to parse search card: {e}")
                continue

        return results

    def _extract_search_card(self, card) -> Optional[ScrapedProduct]:
        """Extract product data from a single search result card."""
        title_el = card.select_one("h2 a span")
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        if not title:
            return None

        link_el = card.select_one("h2 a")
        url = ""
        if link_el and link_el.get("href"):
            href = link_el["href"]
            if href.startswith("/"):
                url = f"{self.BASE_URL}{href}"
            else:
                url = href

        price_whole = card.select_one("span.a-price-whole")
        price_frac = card.select_one("span.a-price-fraction")
        price = 0.0
        if price_whole:
            whole = price_whole.get_text(strip=True).replace(",", "").rstrip(".")
            frac = price_frac.get_text(strip=True) if price_frac else "00"
            try:
                price = float(f"{whole}.{frac}")
            except ValueError:
                price = self._parse_price(price_whole.get_text(strip=True))

        if price <= 0:
            price_el = card.select_one("span.a-price span.a-offscreen")
            if price_el:
                price = self._parse_price(price_el.get_text(strip=True))

        image_el = card.select_one("img.s-image")
        image_url = image_el.get("src") if image_el else None

        delivery_min, delivery_max = self._extract_delivery_info(card)

        seller = None
        seller_el = card.select_one("span.a-size-base-plus")
        if seller_el:
            seller = seller_el.get_text(strip=True)

        condition = "New"
        if card.select_one("span.a-text-price"):
            condition = "Renewed"

        return ScrapedProduct(
            source="amazon_uk",
            title=title,
            price=price,
            url=url,
            image_url=image_url,
            delivery_days_min=delivery_min,
            delivery_days_max=delivery_max,
            seller=seller,
            condition=condition,
            verified=True,
        )

    def _extract_delivery_info(self, card) -> tuple[Optional[int], Optional[int]]:
        """Extract delivery estimate from search card."""
        delivery_min = 1
        delivery_max = 5

        delivery_el = card.select_one("span.a-color-base.a-text-bold")
        if delivery_el:
            text = delivery_el.get_text(strip=True).lower()
            if "prime" in text:
                delivery_min, delivery_max = 1, 2
            elif "free delivery" in text:
                delivery_min, delivery_max = 1, 3
            else:
                day_match = re.search(r"(\d+)", text)
                if day_match:
                    days = int(day_match.group(1))
                    delivery_min = days
                    delivery_max = days

        return delivery_min, delivery_max

    async def get_details(self, url: str) -> ScrapedProduct:
        """Get full product details from an Amazon UK product page."""
        try:
            html = await self.fetch(url)
            return self._parse_product_page(html, url)
        except Exception as e:
            print(f"[WARN] Amazon UK details fetch failed for {url}: {e}")
            return ScrapedProduct(
                source="amazon_uk",
                title="",
                price=0.0,
                url=url,
                verified=False,
            )

    def _parse_product_page(self, html: str, url: str) -> ScrapedProduct:
        """Parse Amazon UK product detail page."""
        soup = self.parse(html)

        title = ""
        title_el = soup.select_one("#productTitle")
        if title_el:
            title = title_el.get_text(strip=True)

        price = 0.0
        price_el = soup.select_one("span.a-price-whole")
        if price_el:
            whole = price_el.get_text(strip=True).replace(",", "").rstrip(".")
            frac_el = soup.select_one("span.a-price-fraction")
            frac = frac_el.get_text(strip=True) if frac_el else "00"
            try:
                price = float(f"{whole}.{frac}")
            except ValueError:
                price = self._parse_price(price_el.get_text(strip=True))

        if price <= 0:
            core_price_el = soup.select_one("#corePrice_feature_div span.a-offscreen")
            if core_price_el:
                price = self._parse_price(core_price_el.get_text(strip=True))

        image_url = None
        img_el = soup.select_one("#landingImage") or soup.select_one("#imgBlkFront")
        if img_el:
            image_url = img_el.get("data-old-hires") or img_el.get("src")

        delivery_min, delivery_max = 1, 5
        delivery_el = soup.select_one("#mir-layout-DELIVERY_BLOCK")
        if delivery_el:
            text = delivery_el.get_text(strip=True).lower()
            if "prime" in text:
                delivery_min, delivery_max = 1, 2
            else:
                day_matches = re.findall(r"(\d+)\s*(?:day|business)", text)
                if len(day_matches) >= 2:
                    delivery_min = int(day_matches[0])
                    delivery_max = int(day_matches[1])
                elif len(day_matches) == 1:
                    delivery_min = int(day_matches[0])
                    delivery_max = delivery_min + 2

        seller = None
        seller_el = soup.select_one("#sellerProfileTriggerId") or soup.select_one("#bylineInfo")
        if seller_el:
            seller = seller_el.get_text(strip=True)

        condition = "New"
        condition_el = soup.select_one("#productCondition")
        if condition_el:
            condition = condition_el.get_text(strip=True)

        return ScrapedProduct(
            source="amazon_uk",
            title=title,
            price=price,
            url=url,
            image_url=image_url,
            delivery_days_min=delivery_min,
            delivery_days_max=delivery_max,
            seller=seller,
            condition=condition,
            verified=True,
            raw_html=html,
        )
