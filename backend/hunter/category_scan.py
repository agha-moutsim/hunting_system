"""eBay category scanning — fetch listings from a category."""

import re
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config import EBAY_UK_BASE, EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_API_BASE, EBAY_MARKETPLACE, SCRAPE_CONFIG, FILTERS


# Predefined eBay UK categories
EBAY_CATEGORIES = {
    "Electronics": "293",
    "Home & Garden": "1173",
    "Clothing, Shoes & Accessories": "11450",
    "Sports & Outdoors": "888",
    "Toys & Hobbies": "220",
    "Health & Beauty": "2610",
    "Automotive": "9800",
    "Pet Supplies": "1281",
    "Baby Essentials": "263955",
    "Jewellery & Watches": "281",
    "Business & Industrial": "12576",
    "Cameras & Photo": "625",
    "Computers/Tablets": "580581",
    "Musical Instruments": "619",
    "Collectibles": "1",
}


@dataclass
class CategoryProduct:
    """A product found in a category scan."""
    title: str
    price: float
    url: str
    image_url: Optional[str] = None
    seller: Optional[str] = None
    condition: str = "New"
    buying_format: str = "Buy It Now"
    category: str = ""
    # Filled later
    sold_30d: int = 0
    sold_7d: int = 0
    supplier_price: float = 0.0
    supplier_name: str = ""
    supplier_url: str = ""
    profit: float = 0.0
    margin: float = 0.0
    verdict: str = ""


def scan_category(
    category_name: str,
    price_min: float = FILTERS["price_min"],
    price_max: float = FILTERS["price_max"],
    max_results: int = 50,
) -> list[CategoryProduct]:
    """Scan an eBay category and return filtered products."""
    category_id = EBAY_CATEGORIES.get(category_name, "293")

    # Try API first
    products = _scan_via_api(category_id, price_min, price_max, max_results, category_name)
    if products:
        return products

    # Fallback to scraping
    return _scan_via_scrape(category_id, price_min, price_max, max_results, category_name)


def _scan_via_api(
    category_id: str,
    price_min: float,
    price_max: float,
    max_results: int,
    category_name: str,
) -> list[CategoryProduct]:
    """Scan category via Browse API."""
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        return []

    try:
        # Get OAuth token
        import base64
        resp = requests.post(
            f"{EBAY_API_BASE}/identity/v1/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": "Basic " + base64.b64encode(
                    f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()
                ).decode(),
            },
            data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
            timeout=10,
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]

        # Search category
        resp = requests.get(
            f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search",
            params={
                "category_ids": category_id,
                "limit": min(max_results, 50),
                "filter": (
                    f"buyingOptions:{{FIXED_PRICE}},"
                    f"conditions:{{NEW}},"
                    f"deliveryCountry:GB,"
                    f"price:[{price_min}..{price_max}],"
                    f"priceCurrency:GBP"
                ),
                "sort": "-relevance",
            },
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE,
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        products = []
        for item in data.get("itemSummaries", []):
            price_info = item.get("price", {})
            price = float(price_info.get("value", 0))
            if price < price_min or price > price_max:
                continue

            seller_info = item.get("seller", {})
            products.append(CategoryProduct(
                title=item.get("title", ""),
                price=price,
                url=item.get("itemWebUrl", ""),
                image_url=item.get("thumbnailImages", [{}])[0].get("imageUrl")
                    if item.get("thumbnailImages") else None,
                seller=seller_info.get("username"),
                condition=item.get("condition", "New"),
                category=category_name,
            ))

            if len(products) >= max_results:
                break

        return products

    except Exception as e:
        print(f"[WARN] Category API scan failed: {e}")
        return []


def _scan_via_scrape(
    category_id: str,
    price_min: float,
    price_max: float,
    max_results: int,
    category_name: str,
) -> list[CategoryProduct]:
    """Fallback: scrape eBay category page."""
    products = []

    try:
        url = (
            f"{EBAY_UK_BASE}/b/{category_id}/n.html?"
            f"_pgn=1"
            f"&LH_Price=1"
            f"&_udlo={price_min:.0f}"
            f"&_udhi={price_max:.0f}"
            f"&LH_BIN=1"
            f"&LH_ItemCondition=1000"
        )

        session = requests.Session()
        session.headers.update({
            "User-Agent": SCRAPE_CONFIG["user_agent"],
            "Accept-Language": SCRAPE_CONFIG["accept_language"],
        })

        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for item in soup.select("li.s-item")[:max_results]:
            try:
                title_el = item.select_one("div.s-item__title span")
                price_el = item.select_one("span.s-item__price")
                link_el = item.select_one("a.s-item__link")

                if not title_el or not price_el or not link_el:
                    continue

                title = title_el.get_text(strip=True)
                if title.lower() in ("shop on ebay", "results matching fewer words", ""):
                    continue

                price_text = price_el.get_text(strip=True).replace(",", "")
                price_match = re.search(r"[\d.]+", price_text)
                if not price_match:
                    continue

                price = float(price_match.group())
                if price < price_min or price > price_max:
                    continue

                products.append(CategoryProduct(
                    title=title,
                    price=price,
                    url=link_el.get("href", ""),
                    category=category_name,
                ))

                if len(products) >= max_results:
                    break

            except Exception:
                continue

    except Exception as e:
        print(f"[WARN] Category scrape failed: {e}")

    return products
