"""
AliExpress supplier scraper — Playwright scraping.
RapidAPI search is disabled (P4): the available key has no search
endpoint, so nothing here hits that host anymore.
Prices converted USD -> GBP at 0.79.

C13 — every row this scraper returns is tagged fetch_method="browser",
because there is no API path left to produce one. It is still `verified`
(a successfully parsed page), but a reader can tell how it was obtained.
"""

import re
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus

from scrapers.availability import parse_shipping_text
from scrapers.base import BaseScraper, DELIVERY_SELECTORS, STOCK_SELECTORS, ScrapedProduct
from config import SCRAPE_CONFIG

USD_TO_GBP = 0.79


class AliExpressScraper(BaseScraper):
    """Scraper for AliExpress — Playwright scraping, API disabled (P4)."""

    BASE_URL = "https://www.aliexpress.com"
    SEARCH_URL = "https://www.aliexpress.com/wholesale?SearchText={query}"
    DELIVERY_DAYS_MIN = 12
    DELIVERY_DAYS_MAX = 25

    @staticmethod
    def _parse_review_text(text):
        """Read a 0-5 product/seller rating and count from source text only."""
        if not isinstance(text, str) or not text.strip():
            return None, None, False
        rating = None
        count = None
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:/|out of)\s*5", text, re.I)
        if match:
            rating = float(match.group(1))
        else:
            match = re.search(r"\b([0-5](?:\.\d+)?)\b", text)
            if match:
                rating = float(match.group(1))
        count_match = re.search(r"\(([\d,]+)\)", text)
        if not count_match:
            count_match = re.search(r"([\d,]+)\s*reviews?\b", text, re.I)
        if count_match:
            count = int(count_match.group(1).replace(",", ""))
        if rating is None or not (0.0 <= rating <= 5.0):
            return None, count, False
        return rating, count, True

    @staticmethod
    def _shipping_methods(text: str) -> list[str]:
        found: list[str] = []
        for method in (
            "AliExpress Standard Shipping",
            "Standard Shipping",
            "ePacket",
            "Expedited Shipping",
            "Economy Shipping",
        ):
            if method.lower() in (text or "").lower() and method not in found:
                found.append(method)
        return found

    @staticmethod
    def _read_aliexpress_standard_shipping(text: str):
        """Read AliExpress Standard Shipping from real text only."""
        low = (text or "").lower()
        if "standard shipping" not in low:
            return None, None, None, None, ""
        available = "unavailable" not in low and "not available" not in low
        from scrapers.availability import parse_shipping_text

        cost, days, raw = parse_shipping_text(text)
        if not available:
            cost = None
            days = None
            raw = text.strip()
        elif cost <= 0 and "free" not in low:
            cost = None
        if days is not None and days <= 0:
            days = None
        return available, cost, days, days, (raw or text.strip())

    async def search(self, query: str) -> list[ScrapedProduct]:
        """Search AliExpress — RapidAPI disabled, falls back to scraping."""
        # Disabled API attempt first — returns no rows (P4), keeps the seam
        # for a key that does expose a search endpoint.
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
        """RapidAPI search is disabled — fail closed (P4).

        The key available here belongs to `aliexpress-datahub`, which
        exposes /store_categories and /item_detail and no search
        endpoint, while the call this method used to make went to
        `aliexpress-api.p.rapidapi.com/products` — a host it cannot
        authenticate against. Only ever a 403/404, so we return no rows
        and let scrapers/serpapi_discovery.py carry AliExpress instead.
        """
        print("[WARN] AliExpress RapidAPI search disabled (available key has "
              "no search endpoint) — returning no rows")
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
        seller_full_name = None
        seller_rating = None
        seller_orders = None
        store_name = None

        # Try to extract store info from various selectors
        store_el = card.select_one("[class*='store'], [class*='seller'], [class*='shop']")
        if store_el:
            seller = store_el.get_text(strip=True)
            store_name = seller

        # Try to get full store name from data attributes
        store_link = card.select_one("a[href*='store']")
        if store_link:
            store_name = store_link.get_text(strip=True) or store_name

        # Try to get rating
        rating_el = card.select_one("[class*='rating'], [class*='star']")
        if rating_el:
            rating_text = rating_el.get_text(strip=True)
            if rating_text:
                seller_rating = rating_text

        # Try to get orders count
        orders_el = card.select_one("[class*='orders'], [class*='sold']")
        if orders_el:
            orders_text = orders_el.get_text(strip=True)
            if orders_text:
                seller_orders = orders_text

        # P4 — AliExpress cards print delivery/stock wording only on some
        # layouts; no element means unknown, never a default (C1/C13).
        stock_state, stock_raw = self._read_stock(card, STOCK_SELECTORS)
        ship_cost, ship_days, ship_raw = self._read_shipping(card, DELIVERY_SELECTORS)
        all_text = card.get_text(" ", strip=True)
        review_rating, review_count, review_verified = self._parse_review_text(
            seller_rating or rating_el.get_text(strip=True) if rating_el else None
        )
        shipping_methods = self._shipping_methods(all_text)
        standard_available, standard_cost, standard_min, standard_max, standard_raw = (
            self._read_aliexpress_standard_shipping(all_text)
        )
        if standard_available is True and standard_cost is None and ship_cost > 0:
            standard_cost = ship_cost
        if standard_available is True and standard_min is None:
            standard_min = ship_days or self.DELIVERY_DAYS_MIN
        if standard_available is True and standard_max is None:
            standard_max = ship_days or self.DELIVERY_DAYS_MAX
        if standard_available is True and "AliExpress Standard Shipping" not in shipping_methods and "Standard Shipping" in all_text:
            shipping_methods.insert(0, "AliExpress Standard Shipping")

        return ScrapedProduct(
            source="aliexpress",
            title=title,
            price=price_gbp,
            url=url,
            image_url=image_url,
            delivery_days_min=self.DELIVERY_DAYS_MIN,
            delivery_days_max=self.DELIVERY_DAYS_MAX,
            seller=seller,
            seller_full_name=seller_full_name,
            seller_rating=seller_rating,
            seller_orders=seller_orders,
            store_name=store_name,
            condition="New",
            verified=True,
            # C13 — no API path exists for this supplier; the page is the
            # only source, so say so rather than leaving it unstated.
            fetch_method="browser",
            in_stock=stock_state,
            stock_raw=stock_raw,
            availability_url=url if stock_raw else "",
            shipping_cost=ship_cost,
            shipping_days=ship_days,
            shipping_raw=ship_raw,
            review_rating=review_rating,
            review_count=review_count,
            review_verified=review_verified,
            review_source="seller_rating" if review_verified else "",
            shipping_methods=shipping_methods,
            standard_shipping_available=standard_available,
            standard_shipping_cost=standard_cost,
            standard_shipping_days_min=standard_min,
            standard_shipping_days_max=standard_max,
            standard_shipping_raw=standard_raw,
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

        # P4 — availability read off this page only (C1/C13); AliExpress
        # prints stock/shipping in layout-specific hooks, so a miss is
        # unknown rather than a guessed "in stock".
        stock_state, stock_raw = self._read_stock(soup, STOCK_SELECTORS)
        ship_cost, ship_days, ship_raw = self._read_shipping(soup, DELIVERY_SELECTORS)
        all_text = soup.get_text(" ", strip=True)
        shipping_methods = self._shipping_methods(all_text)
        standard_available, standard_cost, standard_min, standard_max, standard_raw = (
            self._read_aliexpress_standard_shipping(all_text)
        )
        if standard_available is True and standard_cost is None and ship_cost > 0:
            standard_cost = ship_cost
        if standard_available is True and standard_min is None:
            standard_min = ship_days or self.DELIVERY_DAYS_MIN
        if standard_available is True and standard_max is None:
            standard_max = ship_days or self.DELIVERY_DAYS_MAX
        if standard_available is True and "AliExpress Standard Shipping" not in shipping_methods and "Standard Shipping" in all_text:
            shipping_methods.insert(0, "AliExpress Standard Shipping")

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
            # C13 — detail pages too: see the search-card construction.
            fetch_method="browser",
            raw_html=html,
            in_stock=stock_state,
            stock_raw=stock_raw,
            availability_url=url if stock_raw else "",
            shipping_cost=ship_cost,
            shipping_days=ship_days,
            shipping_raw=ship_raw,
            shipping_methods=shipping_methods,
            standard_shipping_available=standard_available,
            standard_shipping_cost=standard_cost,
            standard_shipping_days_min=standard_min,
            standard_shipping_days_max=standard_max,
            standard_shipping_raw=standard_raw,
        )
