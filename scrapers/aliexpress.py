"""
AliExpress supplier scraper — RapidAPI first, falls back to Playwright scraping.
Prices converted USD -> GBP at 0.79.
"""

import os
import re
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus

from scrapers.base import BaseScraper, ScrapedProduct
from config import SCRAPE_CONFIG

USD_TO_GBP = 0.79


class AliExpressScraper(BaseScraper):
    """Scraper for AliExpress — API first, Playwright fallback."""

    BASE_URL = "https://www.aliexpress.com"
    SEARCH_URL = "https://www.aliexpress.com/wholesale?SearchText={query}"
    DELIVERY_DAYS_MIN = 12
    DELIVERY_DAYS_MAX = 25

    async def search(self, query: str) -> list[ScrapedProduct]:
        """Search AliExpress — try RapidAPI first, fallback to scraping."""
        # Try RapidAPI first
        api_products = self._search_via_rapidapi(query)
        if api_products:
            return api_products

        # Fallback to scraping
        search_url = self.SEARCH_URL.format(query=quote_plus(query))
        try:
            html = await self.fetch(search_url)
            return self._parse_search_results(html)
        except Exception as e:
            print(f"[WARN] AliExpress search failed for '{query}': {e}")
            return []

    def _search_via_rapidapi(self, query: str) -> list[ScrapedProduct]:
        """Try AliExpress via RapidAPI free tier."""
        api_key = os.getenv("RAPIDAPI_KEY", "")
        if not api_key:
            return []

        try:
            import requests

            resp = requests.get(
                "https://aliexpress-api.p.rapidapi.com/products",
                headers={
                    "x-rapidapi-key": api_key,
                    "x-rapidapi-host": "aliexpress-api.p.rapidapi.com",
                },
                params={"keywords": query, "limit": 10},
                timeout=15,
            )
            data = resp.json()

            products = []
            items = data.get("data", data.get("products", []))
            if isinstance(items, dict):
                items = items.get("products", [])

            for item in (items or [])[:10]:
                price_str = item.get("price", item.get("product_price", "0"))
                try:
                    price_usd = float(str(price_str).replace("£", "").replace(",", ""))
                except (ValueError, TypeError):
                    price_usd = 0.0
                price_gbp = price_usd * USD_TO_GBP

                products.append(ScrapedProduct(
                    source="aliexpress",
                    title=item.get("product_title", item.get("title", "")),
                    price=price_gbp,
                    url=item.get("product_url", item.get("url", "")),
                    image_url=item.get("product_image", item.get("image", "")),
                    delivery_days_min=self.DELIVERY_DAYS_MIN,
                    delivery_days_max=self.DELIVERY_DAYS_MAX,
                    verified=True,
                ))

            return products

        except Exception as e:
            print(f"[INFO] AliExpress RapidAPI unavailable: {e}")
            return []

    def _parse_search_results(self, html: str) -> list[ScrapedProduct]:
        """Parse AliExpress search results page."""
        soup = self.parse(html)
        results = []
        seen_titles = set()

        # AliExpress renders product cards as links with /item/ in the href
        cards = soup.select('a[href*="/item/"]')
        if not cards:
            cards = soup.select("div[data-widget='search#productList'] a[href]")

        for card in cards:
            try:
                product = self._extract_search_card(card)
                if product and product.price > 0 and product.title not in seen_titles:
                    seen_titles.add(product.title)
                    results.append(product)
            except Exception as e:
                print(f"[WARN] Failed to parse AliExpress card: {e}")
                continue

        return results

    def _extract_search_card(self, card) -> Optional[ScrapedProduct]:
        """Extract product data from a single search result card."""
        # Title — get from parent container, not just the link
        title = card.get("title", "").strip()
        if not title:
            # Try multiple selectors for title
            for sel in ["h3", "[class*='title']", "[class*='name']", "span"]:
                title_el = card.select_one(sel)
                if title_el:
                    text = title_el.get_text(strip=True)
                    if len(text) > 10:  # Real titles are longer
                        title = text
                        break
        if not title or len(title) < 5:
            return None

        # URL
        href = card.get("href", "")
        if href.startswith("//"):
            url = "https:" + href
        elif href.startswith("/"):
            url = self.BASE_URL + href
        elif href.startswith("http"):
            url = href
        else:
            url = ""

        if not url:
            return None

        # Price — look for specific price containers, avoid duplicates
        price_usd = 0.0

        # Method 1: Look for data attributes with price
        price_el = card.select_one("[data-price], [data-product-price]")
        if price_el:
            price_attr = price_el.get("data-price") or price_el.get("data-product-price", "")
            try:
                price_usd = float(str(price_attr).replace(",", ""))
            except (ValueError, TypeError):
                pass

        # Method 2: Look for specific price class patterns
        if price_usd <= 0:
            for sel in [
                "span[data-testid='product-price']",
                "[class*='Price'] [class*='value']",
                "[class*='price'] [class*='current']",
                "[class*='Price']:not([class*='original'])",
            ]:
                price_els = card.select(sel)
                for price_el in price_els:
                    text = price_el.get_text(strip=True)
                    # Match patterns like "£3.50", "$4.99", "3.50"
                    match = re.search(r"[£$]?(\d+\.?\d*)", text)
                    if match:
                        try:
                            val = float(match.group(1))
                            if 0.1 < val < 1000:  # Sanity check
                                price_usd = val
                                break
                        except ValueError:
                            continue
                if price_usd > 0:
                    break

        # Method 3: Fallback — get all text with price-like patterns
        if price_usd <= 0:
            all_text = card.get_text()
            # Find all price-like values
            prices = re.findall(r"[£$]?(\d+\.\d{2})", all_text)
            for p in prices:
                try:
                    val = float(p)
                    if 0.1 < val < 1000:
                        price_usd = val
                        break
                except ValueError:
                    continue

        if price_usd <= 0:
            return None

        price_gbp = round(price_usd * USD_TO_GBP, 2)

        # Image
        image_url = None
        img_el = card.select_one("img")
        if img_el:
            src = img_el.get("src") or img_el.get("data-src") or ""
            if src:
                image_url = src if src.startswith("http") else "https:" + src

        # Seller
        seller = None
        seller_el = card.select_one("[class*='store'], [class*='seller']")
        if seller_el:
            seller = seller_el.get_text(strip=True)

        return ScrapedProduct(
            source="aliexpress",
            title=title,
            price=price_gbp,
            url=url,
            image_url=image_url,
            delivery_days_min=self.DELIVERY_DAYS_MIN,
            delivery_days_max=self.DELIVERY_DAYS_MAX,
            seller=seller,
            condition="New",
            verified=True,
        )

    async def get_details(self, url: str) -> ScrapedProduct:
        """Get full product details from an AliExpress listing page."""
        try:
            html = await self.fetch(url)
            return self._parse_product_page(html, url)
        except Exception as e:
            print(f"[WARN] AliExpress details fetch failed for {url}: {e}")
            return ScrapedProduct(
                source="aliexpress",
                title="",
                price=0.0,
                url=url,
                verified=False,
            )

    def _parse_product_page(self, html: str, url: str) -> ScrapedProduct:
        """Parse AliExpress product detail page."""
        soup = self.parse(html)

        # Title
        title = ""
        title_el = soup.select_one("h1") or soup.select_one("[class*='title']")
        if title_el:
            title = title_el.get_text(strip=True)

        # Price (USD)
        price_usd = 0.0
        for sel in [
            "[class*='price'] span",
            "[class*='Price'] span",
            "span:has(> span)",
        ]:
            price_els = soup.select(sel)
            for price_el in price_els:
                text = price_el.get_text(strip=True)
                match = re.search(r"[\d,.]+", text)
                if match:
                    try:
                        price_usd = float(match.group().replace(",", ""))
                        if price_usd > 0:
                            break
                    except ValueError:
                        continue
            if price_usd > 0:
                break

        price_gbp = round(price_usd * USD_TO_GBP, 2) if price_usd > 0 else 0.0

        # Image
        image_url = None
        img_el = (
            soup.select_one("img[src*='ae01']")
            or soup.select_one("img[src*='alicdn']")
            or soup.select_one("[class*='gallery'] img")
        )
        if img_el:
            image_url = img_el.get("src", "")

        # Seller
        seller = None
        seller_el = (
            soup.select_one("[class*='store-name']")
            or soup.select_one("[class*='seller']")
            or soup.select_one("a[href*='/store/']")
        )
        if seller_el:
            seller = seller_el.get_text(strip=True)

        return ScrapedProduct(
            source="aliexpress",
            title=title,
            price=price_gbp,
            url=url,
            image_url=image_url,
            delivery_days_min=self.DELIVERY_DAYS_MIN,
            delivery_days_max=self.DELIVERY_DAYS_MAX,
            seller=seller,
            condition="New",
            verified=True,
            raw_html=html,
        )
