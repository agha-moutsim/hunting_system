"""
Google Shopping — Free product search via SerpApi.

Covers UK suppliers: B&Q, Toolstation, Amazon, and hundreds more.
Free tier: 5,000 searches/month at https://serpapi.com
"""

import os
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search.json"


class GoogleShoppingAPI:
    """Google Shopping search via SerpApi — covers B&Q, Toolstation, etc."""

    def __init__(self):
        self.api_key = os.getenv("SERPAPI_KEY", "")

    def search_products(self, keyword: str, limit: int = 10) -> list[dict]:
        """Search Google Shopping for UK products."""
        if not self.api_key:
            raise ValueError("SERPAPI_KEY required — get free key at https://serpapi.com")

        resp = requests.get(
            SERPAPI_BASE,
            params={
                "engine": "google_shopping",
                "q": keyword,
                "location": "United Kingdom",
                "gl": "uk",
                "hl": "en",
                "api_key": self.api_key,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        products = []
        for item in data.get("shopping_results", [])[:limit]:
            # Extract retailer name
            retailer = item.get("source", item.get("seller", "Unknown"))

            # Filter to our target suppliers if needed
            products.append({
                "source": retailer,
                "title": item.get("title", ""),
                "price": _parse_price(item.get("extracted_price", item.get("price", "0"))),
                "original_price": _parse_price(item.get("extracted_price", item.get("price", "0"))),
                "url": item.get("link", ""),
                "image_url": item.get("thumbnail", ""),
                "rating": item.get("rating"),
                "reviews": item.get("reviews"),
                "delivery": item.get("delivery", ""),
            })

        return products


class BQScraper:
    """B&Q products via Google Shopping."""

    def search_products(self, keyword: str, limit: int = 10) -> list[dict]:
        api = GoogleShoppingAPI()
        all_results = api.search_products(f"site:diy.com {keyword}", limit=limit)
        # Filter to B&Q only
        bq_results = [r for r in all_results if "b&q" in r["source"].lower() or "diy.com" in r.get("url", "").lower()]

        if not bq_results:
            # Try without site filter
            bq_results = [r for r in api.search_products(keyword, limit=limit * 2)
                         if "b&q" in r["source"].lower() or "diy.com" in r.get("url", "").lower()]

        return bq_results[:limit]


class ToolstationScraperAPI:
    """Toolstation products via Google Shopping."""

    def search_products(self, keyword: str, limit: int = 10) -> list[dict]:
        api = GoogleShoppingAPI()
        all_results = api.search_products(f"site:toolstation.com {keyword}", limit=limit)
        ts_results = [r for r in all_results if "toolstation" in r["source"].lower() or "toolstation.com" in r.get("url", "").lower()]

        if not ts_results:
            ts_results = [r for r in api.search_products(keyword, limit=limit * 2)
                         if "toolstation" in r["source"].lower()]

        return ts_results[:limit]


def _parse_price(val) -> float:
    """Parse price from various formats."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.replace("£", "").replace(",", "").strip()
        try:
            return float(val)
        except ValueError:
            return 0.0
    return 0.0
