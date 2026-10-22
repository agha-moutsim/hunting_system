"""
AliExpress supplier scraper — Playwright scraping, with an optional
RapidAPI search seam. The configured key may or may not expose
aliexpress-api.p.rapidapi.com/products: when it does, rows come back
tagged fetch_method="api"; when it does not (403/404 or no key), the
API call fails closed and the scraper falls back to the live page.
Prices converted USD -> GBP at 0.79.

C13 — every row carries how it was obtained: "browser" when read off a
parsed page, "api" when RapidAPI handed one over. Either way the row is
`verified` (a real read), and the reader can tell which one it was.
"""

import re
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus

import requests

from scrapers.aliexpress_api import RapidAPIAliExpress
from scrapers.availability import parse_shipping_text
from scrapers.base import BaseScraper, DELIVERY_SELECTORS, STOCK_SELECTORS, ScrapedProduct
from config import SCRAPE_CONFIG

USD_TO_GBP = 0.79


class AliExpressScraper(BaseScraper):
    """Scraper for AliExpress — live scraping, with an optional RapidAPI seam."""

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
            match = re.search(r"\b([0-5](?:\.\d+)?)\b(?![\d,])", text)
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
        low_text = (text or "").lower()
        for method in (
            "AliExpress Standard Shipping",
            "Standard Shipping",
            "ePacket",
            "Expedited Shipping",
            "Economy Shipping",
        ):
            low_method = method.lower()
            if low_method not in low_text:
                continue
            if any(
                low_method in existing.lower() or existing.lower() in low_method
                for existing in found
            ):
                continue
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

        cost, _parsed_days, raw = parse_shipping_text(text)
        range_match = re.search(
            r"(\d+)\s*(?:-|to|–|—)\s*(\d+)\s*(?:working|business)?\s*days?",
            text,
            re.I,
        )
        if range_match:
            days_min = int(range_match.group(1))
            days_max = int(range_match.group(2))
        else:
            single_match = re.search(
                r"\b(\d+)\s*(?:working|business)?\s*days?\b", text, re.I
            )
            if single_match:
                days_min = days_max = int(single_match.group(1))
            else:
                days_min = days_max = None

        if not available:
            cost = None
            days_min = None
            days_max = None
            raw = text.strip()
        elif cost <= 0 and "free" not in low:
            cost = None
        if days_min is not None and days_min <= 0:
            days_min = None
        if days_max is not None and days_max <= 0:
            days_max = None
        return available, cost, days_min, days_max, (raw or text.strip())

    async def search(self, query: str) -> list[ScrapedProduct]:
        """Search AliExpress — RapidAPI when a search-capable key answers,
        otherwise the live page."""
        # Try the API seam first. A missing/unsearchable key or a RapidAPI
        # refusal yields no rows from here, and the page scrape takes over.
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
        """AliGate (RapidAPI) search — runs only when the key really answers.

        The previous listing, `aliexpress-api.p.rapidapi.com`, was removed
        from RapidAPI (its page 404s now); the seam calls AliGate's
        /api/v2/search/text through scrapers.aliexpress_api instead. It
        stays honest both ways: with no key it fails closed before any
        HTTP call; with a key that RapidAPI or AliGate refuses (subscription
        missing, keyword parameter renamed, monthly cap reached) the
        refusal — including the gateway's own reason — is logged, no rows
        are invented, and search() scrapes the live page instead.
        """
        client = RapidAPIAliExpress()
        if not client.api_key:
            print("[WARN] AliExpress RapidAPI search disabled "
                  "(RAPIDAPI_KEY not set) — falling back to scraping")
            return []
        try:
            raw_rows = client.search_products(query)
        except requests.RequestException as exc:
            print(f"[WARN] AliExpress RapidAPI search unavailable ({exc}) "
                  "— falling back to scraping")
            return []
        products = []
        for raw_row in raw_rows:
            product = self._api_row_to_product(raw_row)
            if product:
                products.append(product)
        if products:
            return products
        print(
            f"[WARN] AliExpress RapidAPI returned no usable rows for "
            f"'{query}' — falling back to scraping"
        )
        return []

    def _api_row_to_product(self, row) -> Optional[ScrapedProduct]:
        """Convert one RapidAPI search row — skipping, never guessing.

        A row is usable only with a real title, a positive price and a real
        product URL. Stock, shipping and AliExpress Standard Shipping are
        never assumed from a payload that did not state them (C1/C13), and
        an orders figure is the source's own popularity count — carried as
        display text, never as stock availability.
        """
        if not isinstance(row, dict):
            return None
        title = str(row.get("title") or "").strip()
        if len(title) < 5:
            return None
        try:
            price = float(row.get("price"))
        except (TypeError, ValueError):
            return None
        if not (0.1 <= price <= 10000.0):
            return None
        # The payload names its own currency when it knows it: USD rows (or
        # rows that name none — this connector's long-standing assumption)
        # convert at the fixed scraper rate; GBP rows pass through
        # untouched; any other stated currency is skipped — ranking a
        # price in a currency it does not actually carry would fabricate a
        # landed cost.
        currency = str(row.get("currency") or "").strip().upper()
        if currency and currency not in ("USD", "GBP"):
            return None
        url = str(row.get("url") or "").strip()
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = self.BASE_URL + url
        if not url.startswith("http"):
            return None

        rating = row.get("rating")
        review_rating = None
        review_count = None
        review_verified = False
        if isinstance(rating, dict):
            try:
                candidate = float(
                    rating.get("rating")
                    if rating.get("rating") is not None
                    else rating.get("score")
                )
            except (TypeError, ValueError):
                candidate = None
            if candidate is not None and 0.0 <= candidate <= 5.0:
                review_rating = candidate
                review_verified = True
            try:
                count = int(str(rating.get("count", "")).replace(",", ""))
            except (TypeError, ValueError):
                count = None
            if count and count > 0:
                review_count = count
        elif rating is not None and str(rating).strip():
            review_rating, review_count, review_verified = self._parse_review_text(
                str(rating)
            )

        orders = row.get("orders")
        seller_orders = (
            str(orders).strip() if orders not in (None, 0, "") else None
        )

        return ScrapedProduct(
            source="aliexpress",
            title=title,
            price=round(price, 2) if currency == "GBP" else round(price * USD_TO_GBP, 2),
            url=url,
            image_url=(
                str(row["image_url"]).strip() if row.get("image_url") else None
            ),
            delivery_days_min=self.DELIVERY_DAYS_MIN,
            delivery_days_max=self.DELIVERY_DAYS_MAX,
            seller_orders=seller_orders,
            # C10 — the API said nothing about condition; '' (unknown),
            # never an assumed "New".
            condition="",
            verified=True,
            # C13 — a real API response, tagged as such; the page-sourced
            # rows above carry "browser" instead.
            fetch_method="api",
            # C1/C13 — the payload carried no stock, shipping or
            # Standard Shipping statement, so all of those stay unknown.
            in_stock="",
            stock_raw="",
            availability_url="",
            shipping_cost=0.0,
            shipping_raw="",
            review_rating=review_rating,
            review_count=review_count,
            review_verified=review_verified,
            review_source="rapidapi" if review_verified else "",
        )

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
