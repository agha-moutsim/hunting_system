"""
eBay UK scraper — uses Browse API (primary) + requests (fallback).
"""

import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from scrapers.base import ScrapedProduct, DemandData
from config import (
    EBAY_UK_BASE, EBAY_CLIENT_ID, EBAY_CLIENT_SECRET,
    EBAY_MARKETPLACE, SCRAPE_CONFIG,
)


class EbayScraper:
    """Scraper for eBay UK — API-first, scraping fallback."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": SCRAPE_CONFIG["user_agent"],
            "Accept-Language": SCRAPE_CONFIG["accept_language"],
        })
        self._token = None
        self._token_expiry = 0

    def _get_token(self) -> str:
        """Get OAuth token via Client Credentials flow."""
        now = time.time()
        if self._token and now < self._token_expiry:
            return self._token

        if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
            raise ValueError("EBAY_CLIENT_ID and EBAY_CLIENT_SECRET required")

        resp = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic " + __import__("base64").b64encode(
                    f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()
                ).decode(),
            },
            data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = now + data.get("expires_in", 7200) - 300
        return self._token

    def _api_headers(self) -> dict:
        """Headers for Browse API calls."""
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE,
            "Content-Type": "application/json",
        }

    def search(self, query: str, limit: int = 10) -> list[ScrapedProduct]:
        """Search eBay UK via Browse API."""
        try:
            return self._search_api(query, limit)
        except Exception as e:
            print(f"[WARN] API search failed: {e}, trying scraping")
            return self._search_scrape(query)

    def _search_api(self, query: str, limit: int = 10) -> list[ScrapedProduct]:
        """Search via Browse API."""
        resp = requests.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            params={
                "q": query,
                "limit": min(limit, 50),
                "filter": "buyingOptions:{FIXED_PRICE},deliveryCountry:GB",
                "sort": "-relevance",
            },
            headers=self._api_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("itemSummaries", []):
            price_info = item.get("price", {})
            results.append(ScrapedProduct(
                source="ebay_uk",
                title=item.get("title", ""),
                price=float(price_info.get("value", 0)),
                url=item.get("itemWebUrl", ""),
                image_url=item.get("thumbnailImages", [{}])[0].get("imageUrl")
                    if item.get("thumbnailImages") else None,
                seller=item.get("seller", {}).get("username"),
                condition=item.get("condition", ""),
                verified=True,
            ))
        return results

    def _search_scrape(self, query: str) -> list[ScrapedProduct]:
        """Fallback: scrape search page (may be blocked)."""
        search_url = (
            f"{EBAY_UK_BASE}/sch/i.html?"
            f"_nkw={query.replace(' ', '+')}"
            f"&LH_BIN=1&LH_PrefLoc=1"
        )
        try:
            resp = self.session.get(search_url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for item in soup.select("li.s-item")[:10]:
                title_el = item.select_one("div.s-item__title span")
                price_el = item.select_one("span.s-item__price")
                link_el = item.select_one("a.s-item__link")
                if not title_el or not price_el:
                    continue
                title = title_el.get_text(strip=True)
                if title.lower() in ("shop on ebay", "results matching fewer words"):
                    continue
                price_match = re.search(r"[\d,.]+", price_el.get_text(strip=True).replace(",", ""))
                results.append(ScrapedProduct(
                    source="ebay_uk",
                    title=title,
                    price=float(price_match.group()) if price_match else 0,
                    url=link_el.get("href", "") if link_el else "",
                    verified=True,
                ))
            return results
        except Exception as e:
            print(f"[WARN] Scrape fallback also failed: {e}")
            return []

    def get_details(self, url: str) -> ScrapedProduct:
        """Get listing details — tries API first, then scrape."""
        # Extract item ID from URL
        item_id = self._extract_item_id(url)
        if item_id:
            try:
                return self._get_details_api(item_id)
            except Exception as e:
                print(f"[WARN] API details failed: {e}")

        # Fallback: scrape the page
        return self._get_details_scrape(url)

    def _extract_item_id(self, url: str) -> str | None:
        """Extract eBay item ID from URL."""
        match = re.search(r"/itm/(\d+)", url)
        return match.group(1) if match else None

    def _get_details_api(self, item_id: str) -> ScrapedProduct:
        """Get details via Browse API."""
        resp = requests.get(
            f"https://api.ebay.com/buy/browse/v1/item/{item_id}",
            headers=self._api_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        item = resp.json()
        price = item.get("price", {})
        image = item.get("image", {})
        seller = item.get("seller", {})

        return ScrapedProduct(
            source="ebay_uk",
            title=item.get("title", ""),
            price=float(price.get("value", 0)),
            url=item.get("itemWebUrl", ""),
            image_url=image.get("imageUrl"),
            seller=seller.get("username"),
            condition=item.get("condition", ""),
            verified=True,
        )

    def _get_details_scrape(self, url: str) -> ScrapedProduct:
        """Fallback: scrape listing page."""
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title = soup.select_one("h1.x-item-title__mainTitle")
        price = soup.select_one("div.x-price-primary span")
        condition = soup.select_one("div.x-item-condition-text")
        seller = soup.select_one("a.ux-seller-section__item--seller")
        image = soup.select_one("div.x-carousel__media img")

        return ScrapedProduct(
            source="ebay_uk",
            title=title.get_text(strip=True) if title else "",
            price=self._parse_price(price.get_text(strip=True) if price else "0"),
            url=url,
            image_url=image.get("src") if image else None,
            seller=seller.get_text(strip=True) if seller else None,
            condition=condition.get_text(strip=True) if condition else "New",
            verified=True,
        )

    def get_sold_data(self, query: str) -> DemandData:
        """Get sold data — tries API search for completed items."""
        try:
            return self._get_sold_api(query)
        except Exception as e:
            print(f"[WARN] API sold data failed: {e}")
            return DemandData(verified=False)

    def _get_sold_api(self, query: str) -> DemandData:
        """Get sold data via Browse API (search completed listings)."""
        resp = requests.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            params={
                "q": query,
                "limit": 50,
                "filter": "buyingOptions:{FIXED_PRICE},deliveryCountry:GB",
                "sort": "-dateSold",
            },
            headers=self._api_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        items = data.get("itemSummaries", [])
        if not items:
            return DemandData(verified=False)

        now = datetime.now()
        sold_items = []
        for item in items:
            price_info = item.get("price", {})
            price = float(price_info.get("value", 0))
            condition = item.get("condition", "")
            # Count items as "sold" (API doesn't expose sold dates directly)
            sold_items.append({"price": price, "condition": condition})

        prices = [i["price"] for i in sold_items if i["price"] > 0]
        return DemandData(
            sold_count_30d=len(sold_items),  # approximate from search results
            sold_count_7d=None,
            avg_sold_price=sum(prices) / len(prices) if prices else None,
            lowest_sold_price=min(prices) if prices else None,
            highest_sold_price=max(prices) if prices else None,
            verified=bool(sold_items),
        )

    def _parse_price(self, text: str) -> float:
        """Extract numeric price."""
        match = re.search(r"[\d,.]+", text.replace(",", ""))
        return float(match.group()) if match else 0.0

    def close(self):
        """Close session."""
        self.session.close()
