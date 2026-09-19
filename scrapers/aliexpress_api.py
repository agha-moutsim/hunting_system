"""
AliExpress — via RapidAPI (free tier: 30 req/min).

Get free key at: https://rapidapi.com/aliexpressapi/api/aliexpress-api/
"""

import os
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

RAPIDAPI_HOST = "aliexpress-api.p.rapidapi.com"


class RapidAPIAliExpress:
    """AliExpress via RapidAPI — free tier available."""

    def __init__(self):
        self.api_key = os.getenv("RAPIDAPI_KEY", "")
        self.host = RAPIDAPI_HOST

    def _headers(self) -> dict:
        return {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": self.host,
        }

    def search_products(self, keyword: str, limit: int = 10) -> list[dict]:
        """Search AliExpress products via RapidAPI."""
        if not self.api_key:
            raise ValueError("RAPIDAPI_KEY required — get free key at https://rapidapi.com/aliexpressapi/api/aliexpress-api/")

        resp = requests.get(
            f"https://{self.host}/products",
            headers=self._headers(),
            params={
                "keywords": keyword,
                "limit": min(limit, 30),
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        products = []
        items = data.get("data", data.get("products", []))
        if isinstance(items, dict):
            items = items.get("products", [])

        for item in (items or [])[:limit]:
            price_str = item.get("price", item.get("product_price", "0"))
            try:
                price = float(str(price_str).replace("£", "").replace(",", ""))
            except (ValueError, TypeError):
                price = 0.0

            products.append({
                "source": "AliExpress",
                "title": item.get("product_title", item.get("title", "")),
                "price": price,
                "original_price": price,
                "url": item.get("product_url", item.get("url", "")),
                "image_url": item.get("product_image", item.get("image", "")),
                "orders": item.get("product_sale_price", item.get("orders", 0)),
                "rating": item.get("product_rating"),
            })

        return products


def get_rapidapi_aliexpress():
    """Return RapidAPI AliExpress instance if configured, else None."""
    if os.getenv("RAPIDAPI_KEY"):
        return RapidAPIAliExpress()
    return None
