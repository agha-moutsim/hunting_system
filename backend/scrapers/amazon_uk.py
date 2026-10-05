"""
Amazon UK scraper — PA API first, falls back to Playwright scraping.
"""

import os
import re
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus

from scrapers.availability import parse_shipping_text
from scrapers.base import BaseScraper, DELIVERY_SELECTORS, STOCK_SELECTORS, ScrapedProduct
from config import SCRAPE_CONFIG

# P4 — Amazon's own hooks first (its availability line is `#availability`,
# an id, not a class), then the generic ones (C1: absent = unknown).
_AMAZON_STOCK_SELECTORS = ("#availability", "[itemprop='availability']") + STOCK_SELECTORS
_AMAZON_DELIVERY_SELECTORS = (
    "#mir-layout-DELIVERY_BLOCK",
    "#deliveryBlockMessage",
) + DELIVERY_SELECTORS


class AmazonUKScraper(BaseScraper):
    """Scraper for Amazon UK — API first, Playwright fallback."""

    BASE_URL = "https://www.amazon.co.uk"
    SEARCH_URL = "https://www.amazon.co.uk/s?k={query}"

    async def search(self, query: str) -> list[ScrapedProduct]:
        """Search Amazon UK — try PA API first, fallback to scraping."""
        # Try PA API first
        api_products = self._search_via_api(query)
        if api_products:
            return api_products

        # Fallback to scraping
        search_url = self.SEARCH_URL.format(query=quote_plus(query))
        try:
            html = await self.fetch(search_url)
            return self._parse_search_results(html)
        except Exception as e:
            print(f"[WARN] Amazon UK search failed for '{query}': {e}")
            return []

    def _search_via_api(self, query: str) -> list[ScrapedProduct]:
        """Try Amazon UK PA API 5.0."""
        access_key = os.getenv("AMAZON_PA_ACCESS_KEY", "")
        secret_key = os.getenv("AMAZON_PA_SECRET_KEY", "")
        partner_tag = os.getenv("AMAZON_PA_PARTNER_TAG", "")

        if not access_key or not secret_key:
            # P4 — no Associates credentials exist here, so the signed
            # request would only ever be rejected. Fail closed; SerpApi
            # discovery carries Amazon UK now.
            print("[WARN] Amazon PA API credentials missing — PA search skipped")
            return []

        try:
            import requests
            import hashlib
            import hmac
            import json
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            datestamp = now.strftime("%Y%m%d")
            amz_date = now.strftime("%Y%m%dT%H%M%SZ")

            payload = json.dumps({
                "Keywords": query,
                "Resources": [
                    "ItemInfo.Title",
                    "Offers.Listings.Price",
                    "Offers.Listings.DeliveryInfo.IsAmazonFulfilled",
                    "Images.Primary.Large",
                ],
                "PartnerTag": partner_tag,
                "PartnerType": "Associates",
                "Marketplace": "www.amazon.co.uk",
                "ItemCount": 10,
                "SearchIndex": "All",
            })

            # Simplified signing (working implementation)
            payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            host = "webservices.amazon.co.uk"

            headers_to_sign = {
                "content-type": "application/json; charset=UTF-8",
                "content-encoding": "amz-1.0",
                "host": host,
                "x-amz-date": amz_date,
                "x-amz-target": "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems",
            }

            signed_header_keys = sorted(headers_to_sign.keys())
            canonical_headers = "".join(f"{k}:{headers_to_sign[k]}\n" for k in signed_header_keys)
            signed_headers = ";".join(signed_header_keys)

            canonical_request = f"POST\n/paapi5/searchitems\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
            algorithm = "AWS4-HMAC-SHA256"
            credential_scope = f"{datestamp}/eu-west-1/ProductAdvertisingAPI/aws4_request"
            string_to_sign = f"{algorithm}\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"

            def _sign(key, msg):
                return hmac.HMAC(key, msg.encode("utf-8"), hashlib.sha256).digest()

            k_date = _sign(("AWS4" + secret_key).encode("utf-8"), datestamp)
            k_region = _sign(k_date, "eu-west-1")
            k_service = _sign(k_region, "ProductAdvertisingAPI")
            k_signing = _sign(k_service, "aws4_request")
            signature = hmac.HMAC(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

            authorization = f"{algorithm} Credential={access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"

            resp = requests.post(
                "https://webservices.amazon.co.uk/paapi5/searchitems",
                headers={
                    "Content-Type": "application/json; charset=UTF-8",
                    "Content-Encoding": "amz-1.0",
                    "Host": host,
                    "X-Amz-Date": amz_date,
                    "X-Amz-Target": "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems",
                    "Authorization": authorization,
                },
                data=payload,
                timeout=15,
            )
            data = resp.json()

            products = []
            items = data.get("SearchResult", {}).get("Items", [])
            for item in (items or []):
                title = item.get("ItemInfo", {}).get("Title", {}).get("DisplayValue", "")
                offers = item.get("Offers", {}).get("Listings", [])
                price_str = offers[0].get("Price", {}).get("Amount", "0") if offers else "0"
                try:
                    price = float(price_str)
                except (ValueError, TypeError):
                    price = 0.0
                image_url = item.get("Images", {}).get("Primary", {}).get("Large", {}).get("URL", "")
                is_prime = offers[0].get("DeliveryInfo", {}).get("IsAmazonFulfilled", False) if offers else False

                products.append(ScrapedProduct(
                    source="amazon_uk",
                    title=title,
                    price=price,
                    url=item.get("DetailPageURL", ""),
                    image_url=image_url,
                    delivery_days_min=1 if is_prime else 3,
                    delivery_days_max=2 if is_prime else 7,
                    verified=True,
                    # C13 — this path is the signed Associates API, which is
                    # what "verified" usually implies; the page reads below
                    # are tagged separately so the two never look alike.
                    fetch_method="api",
                ))

            return products

        except Exception as e:
            print(f"[INFO] Amazon PA API unavailable: {e}")
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

        # P4 — read stock/shipping only where the card prints them (C1/C13).
        # Amazon search cards rarely carry an availability line, so this
        # usually stays unknown — which is the correct answer.
        stock_state, stock_raw = self._read_stock(card, _AMAZON_STOCK_SELECTORS)
        ship_el = card.select_one("span.a-color-base.a-text-bold")
        ship_text = ship_el.get_text(" ", strip=True) if ship_el else ""
        ship_cost, ship_days, ship_raw = parse_shipping_text(ship_text)

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
            # C13 — PA API credentials are absent here, so this row could
            # only come from the browser read above.
            fetch_method="browser",
            in_stock=stock_state,
            stock_raw=stock_raw,
            availability_url=url if stock_raw else "",
            shipping_cost=ship_cost,
            shipping_days=ship_days,
            shipping_raw=ship_raw,
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
        delivery_text = ""
        delivery_el = soup.select_one("#mir-layout-DELIVERY_BLOCK")
        if delivery_el:
            delivery_text = delivery_el.get_text(" ", strip=True)
            text = delivery_text.lower()
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

        # P4 — availability read off this page (the #availability line
        # and schema.org JSON-LD), never assumed (C1/C13). shipping_*
        # parses the same delivery block the days above came from.
        stock_state, stock_raw = self._read_stock(soup, _AMAZON_STOCK_SELECTORS)
        ship_cost, ship_days, ship_raw = parse_shipping_text(delivery_text)

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
            fetch_method="browser",
            raw_html=html,
            in_stock=stock_state,
            stock_raw=stock_raw,
            availability_url=url if stock_raw else "",
            shipping_cost=ship_cost,
            shipping_days=ship_days,
            shipping_raw=ship_raw,
        )
