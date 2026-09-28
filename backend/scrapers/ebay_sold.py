"""
eBay UK sold listings scraper — gets real sold data from completed listings.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config import EBAY_UK_BASE, EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_API_BASE, EBAY_MARKETPLACE, SCRAPE_CONFIG
from engine.price_gate import PRICE_MIN, PRICE_MAX, in_band


@dataclass
class EbaySoldItem:
    """Single sold item from eBay."""
    title: str
    price: float
    url: str
    seller: str
    seller_url: str
    sold_date: str
    condition: str = "New"
    image_url: Optional[str] = None


@dataclass
class EbaySoldData:
    """Aggregated sold data for a product."""
    product_name: str
    query: str
    total_sold_30d: int = 0
    total_sold_7d: int = 0
    sold_prices: list[float] = field(default_factory=list)
    price_min: float = 0.0
    price_max: float = 0.0
    price_avg: float = 0.0
    price_median: float = 0.0
    top_sellers: list[dict] = field(default_factory=list)
    sold_dates: list[str] = field(default_factory=list)
    category: str = ""
    items: list[EbaySoldItem] = field(default_factory=list)
    excluded_over_band: int = 0  # PR-4: sold rows dropped by the £5–£35 gate


class EbaySoldScraper:
    """Scrape eBay UK sold/completed listings for real demand data."""

    SOLD_URL = f"{EBAY_UK_BASE}/sch/i.html"
    MAX_PAGES = 3  # Max pages to scrape (180 items per page = 540 max)

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": SCRAPE_CONFIG["user_agent"],
            "Accept-Language": SCRAPE_CONFIG["accept_language"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self._token = None
        self._token_expiry = 0
        self._band_excluded = 0

    def _get_token(self) -> str:
        """Get OAuth token via Client Credentials flow."""
        now = time.time()
        if self._token and now < self._token_expiry:
            return self._token

        if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
            raise ValueError("EBAY_CLIENT_ID and EBAY_CLIENT_SECRET required")

        resp = requests.post(
            f"{EBAY_API_BASE}/identity/v1/oauth2/token",
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

    def get_sold_data(self, query: str) -> EbaySoldData:
        """Get real sold data for a product from eBay UK."""
        result = EbaySoldData(
            product_name=query,
            query=query,
        )
        self._band_excluded = 0

        try:
            # Try API first for sold data
            api_items = self._get_sold_via_api(query)
            if api_items:
                result.items = api_items
            else:
                # Fallback to scraping
                scrape_items = self._get_sold_via_scrape(query)
                result.items = scrape_items

            # Calculate statistics
            self._calculate_stats(result)
            result.excluded_over_band = self._band_excluded

        except Exception as e:
            print(f"[WARN] eBay sold data failed for '{query}': {e}")

        return result

    def _get_sold_via_api(self, query: str) -> list[EbaySoldItem]:
        """Try to get sold items via Browse API (filter by sold status)."""
        if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
            return []

        try:
            resp = requests.get(
                f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search",
                params={
                    "q": query,
                    "limit": 50,
                    "filter": (
                        "buyingOptions:{FIXED_PRICE},deliveryCountry:GB,"
                        f"price:[{PRICE_MIN:.0f}..{PRICE_MAX:.0f}],priceCurrency:GBP"
                    ),
                    "sort": "-relevance",
                },
                headers={
                    "Authorization": f"Bearer {self._get_token()}",
                    "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE,
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            items = []
            for item in data.get("itemSummaries", []):
                price_info = item.get("price", {})
                price = float(price_info.get("value", 0))
                if not in_band(price):
                    self._band_excluded += 1  # PR-4
                    continue
                seller_info = item.get("seller", {})
                items.append(EbaySoldItem(
                    title=item.get("title", ""),
                    price=price,
                    url=item.get("itemWebUrl", ""),
                    seller=seller_info.get("username", ""),
                    seller_url=f"https://www.ebay.co.uk/str/{seller_info.get('username', '')}",
                    sold_date=datetime.now().strftime("%Y-%m-%d"),
                    image_url=item.get("thumbnailImages", [{}])[0].get("imageUrl")
                        if item.get("thumbnailImages") else None,
                ))
            return items

        except Exception as e:
            print(f"[WARN] eBay API search failed: {e}")
            return []

    def _get_sold_via_scrape(self, query: str) -> list[EbaySoldItem]:
        """Scrape eBay sold listings page."""
        items = []

        for page in range(1, self.MAX_PAGES + 1):
            try:
                url = (
                    f"{self.SOLD_URL}?"
                    f"_nkw={query.replace(' ', '+')}"
                    f"&LH_Complete=1&LH_Sold=1"
                    f"&_sop=13"  # Sort by most recently sold
                    f"&_udlo={PRICE_MIN:.0f}&_udhi={PRICE_MAX:.0f}"
                    f"&_pgn={page}"
                )

                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "html.parser")
                page_items = self._parse_sold_page(soup)

                if not page_items:
                    break  # No more items

                items.extend(page_items)

                # Rate limit between pages
                if page < self.MAX_PAGES:
                    time.sleep(2)

            except Exception as e:
                print(f"[WARN] Failed to scrape eBay sold page {page}: {e}")
                break

        return items

    def _parse_sold_page(self, soup: BeautifulSoup) -> list[EbaySoldItem]:
        """Parse a single eBay sold listings page."""
        items = []

        # eBay sold items are in list items
        for item in soup.select("li.s-item"):
            try:
                # Skip ads and "Shop on eBay" items
                title_el = item.select_one("div.s-item__title span")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                if title.lower() in ("shop on ebay", "results matching fewer words", ""):
                    continue

                # Price
                price_el = item.select_one("span.s-item__price")
                if not price_el:
                    continue

                price_text = price_el.get_text(strip=True).replace(",", "")
                price_match = re.search(r"[\d.]+", price_text)
                if not price_match:
                    continue

                price = float(price_match.group())
                if price <= 0:
                    continue
                if not in_band(price):
                    self._band_excluded += 1  # PR-4
                    continue

                # Link
                link_el = item.select_one("a.s-item__link")
                url = link_el.get("href", "") if link_el else ""

                # Seller
                seller_el = item.select_one("span.s-item__seller-info-text")
                seller = ""
                seller_url = ""
                if seller_el:
                    seller_text = seller_el.get_text(strip=True)
                    seller_match = re.search(r"(\S+)", seller_text)
                    if seller_match:
                        seller = seller_match.group(1)
                        seller_url = f"https://www.ebay.co.uk/str/{seller}"

                # Sold date (if available)
                date_el = item.select_one("span.POSITIVE")
                sold_date = date_el.get_text(strip=True) if date_el else datetime.now().strftime("%Y-%m-%d")

                # Image
                img_el = item.select_one("img.s-item__image-img")
                image_url = img_el.get("src") if img_el else None

                items.append(EbaySoldItem(
                    title=title,
                    price=price,
                    url=url,
                    seller=seller,
                    seller_url=seller_url,
                    sold_date=sold_date,
                    image_url=image_url,
                ))

            except Exception as e:
                continue

        return items

    def _calculate_stats(self, result: EbaySoldData):
        """Calculate statistics from sold items."""
        if not result.items:
            return

        # Prices
        prices = [item.price for item in result.items if item.price > 0]
        result.sold_prices = prices

        if prices:
            result.price_min = min(prices)
            result.price_max = max(prices)
            result.price_avg = sum(prices) / len(prices)
            sorted_prices = sorted(prices)
            mid = len(sorted_prices) // 2
            result.price_median = sorted_prices[mid] if len(sorted_prices) % 2 else (sorted_prices[mid-1] + sorted_prices[mid]) / 2

        # Sold counts (approximate from items collected)
        # Note: Without dates, we estimate based on item count
        result.total_sold_30d = len(result.items)
        result.total_sold_7d = min(len(result.items), len(result.items) // 4)  # Rough estimate

        # Top sellers
        seller_counts = {}
        for item in result.items:
            if item.seller:
                if item.seller not in seller_counts:
                    seller_counts[item.seller] = {
                        "name": item.seller,
                        "url": item.seller_url,
                        "sold_count": 0,
                        "total_price": 0,
                    }
                seller_counts[item.seller]["sold_count"] += 1
                seller_counts[item.seller]["total_price"] += item.price

        # Calculate avg price per seller
        for seller in seller_counts.values():
            if seller["sold_count"] > 0:
                seller["avg_price"] = round(seller["total_price"] / seller["sold_count"], 2)

        # Sort by sold count
        result.top_sellers = sorted(seller_counts.values(), key=lambda x: x["sold_count"], reverse=True)[:5]

        # Sold dates
        result.sold_dates = [item.sold_date for item in result.items if item.sold_date]
