"""
CJ Dropshipping — Free API v2.0 integration.

Register at: https://developers.cjdropshipping.com
Get API key at: https://www.cjdropshipping.com/my.html#/authorize/API

No scraping needed — real product data via official API.
"""

import os
import time
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

CJ_BASE = "https://developers.cjdropshipping.com/api2.0/v1"


class CJDropshippingAPI:
    """CJ Dropshipping API client — free, no scraping."""

    def __init__(self):
        self.api_key = os.getenv("CJ_API_KEY", "")
        self.access_token = os.getenv("CJ_ACCESS_TOKEN", "")
        self.token_expiry = 0.0

    def _get_token(self) -> str:
        """Get or refresh access token."""
        now = time.time()
        if self.access_token and now < self.token_expiry:
            return self.access_token

        if not self.api_key:
            raise ValueError("CJ_API_KEY required — get it at https://www.cjdropshipping.com/my.html#/authorize/API")

        resp = requests.post(
            f"{CJ_BASE}/authentication/getAccessToken",
            json={"apiKey": self.api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 200:
            raise ValueError(f"CJ auth failed: {data.get('message', 'Unknown error')}")

        self.access_token = data["data"]["accessToken"]
        # Token lasts 180 days, refresh at 170 days
        self.token_expiry = now + (170 * 24 * 3600)
        return self.access_token

    def _headers(self) -> dict:
        return {
            "CJ-Access-Token": self._get_token(),
            "Content-Type": "application/json",
        }

    def search_products(self, keyword: str, limit: int = 10) -> list[dict]:
        """Search CJ products by keyword. Returns list of product dicts."""
        resp = requests.get(
            f"{CJ_BASE}/product/listV2",
            headers=self._headers(),
            params={
                "keyWord": keyword,
                "page": 1,
                "size": min(limit, 20),
                "countryCode": "GB",  # UK warehouse
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 200:
            logger.warning("CJ search failed: %s", data.get("message"))
            return []

        products = []
        content = data.get("data", {}).get("content", [])
        for item in content:
            for p in item.get("productList", []):
                products.append({
                    "source": "CJ Dropshipping",
                    "title": p.get("nameEn", ""),
                    "price": float(p.get("sellPrice", 0)),
                    "original_price": float(p.get("nowPrice", p.get("sellPrice", 0))),
                    "url": f"https://cjdropshipping.com/product-p-{p.get('id', '')}.html",
                    "image_url": p.get("bigImage", ""),
                    "sku": p.get("sku", ""),
                    "category": p.get("threeCategoryName", ""),
                    "free_shipping": p.get("addMarkStatus") == 1,
                    "delivery_days": p.get("deliveryCycle", ""),
                    "inventory": p.get("warehouseInventoryNum", 0),
                })

        return products


def get_cj_scraper():
    """Return CJ API instance if configured, else None."""
    if os.getenv("CJ_API_KEY"):
        return CJDropshippingAPI()
    return None
