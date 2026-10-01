"""
Amazon UK — Product Advertising API 5.0 (PA API).

Free with Amazon Associates account.
Sign up at: https://affiliate-program.amazon.co.uk
Requires 3 qualifying sales in 30 days to maintain access.
"""

import os
import time
import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

# Amazon PA API 5.0 endpoints
PA_API_ENDPOINT = "https://webservices.amazon.co.uk/paapi5"
PA_API_HOST = "webservices.amazon.co.uk"
PA_API_REGION = "eu-west-1"
PA_API_SERVICE = "ProductAdvertisingAPI"


class AmazonUKAPI:
    """Amazon UK Product Advertising API — free with Associates account."""

    def __init__(self):
        self.access_key = os.getenv("AMAZON_PA_ACCESS_KEY", "")
        self.secret_key = os.getenv("AMAZON_PA_SECRET_KEY", "")
        self.partner_tag = os.getenv("AMAZON_PA_PARTNER_TAG", "")
        self.host = PA_API_HOST
        self.region = PA_API_REGION

    def _sign_request(self, payload: str) -> dict:
        """Generate AWS Signature V4 headers for PA API."""
        now = datetime.now(timezone.utc)
        datestamp = now.strftime("%Y%m%d")
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")

        # Create canonical request
        canonical_uri = "/paapi5/searchitems"
        canonical_querystring = ""
        content_type = "application/json; charset=UTF-8"
        content_encoding = "amz-1.0"

        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        headers_to_sign = {
            "content-type": content_type,
            "content-encoding": content_encoding,
            "host": self.host,
            "x-amz-date": amz_date,
            "x-amz-target": "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems",
        }

        signed_header_keys = sorted(headers_to_sign.keys())
        canonical_headers = ""
        for key in signed_header_keys:
            canonical_headers += f"{key}:{headers_to_sign[key]}\n"

        signed_headers = ";".join(signed_header_keys)

        canonical_request = f"POST\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"

        # Create string to sign
        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{datestamp}/{self.region}/{PA_API_SERVICE}/aws4_request"
        string_to_sign = f"{algorithm}\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"

        # Calculate signature
        def _sign(key, msg):
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        k_date = _sign(("AWS4" + self.secret_key).encode("utf-8"), datestamp)
        k_region = _sign(k_date, self.region)
        k_service = _sign(k_region, PA_API_SERVICE)
        k_signing = _sign(k_service, "aws4_request")

        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        authorization = f"{algorithm} Credential={self.access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"

        return {
            "Content-Type": content_type,
            "Content-Encoding": content_encoding,
            "Host": self.host,
            "X-Amz-Date": amz_date,
            "X-Amz-Target": "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems",
            "Authorization": authorization,
        }

    def search_products(self, keyword: str, limit: int = 10) -> list[dict]:
        """Search Amazon UK products via PA API."""
        if not self.access_key or not self.secret_key:
            # P4 — fail closed instead of raising: no credentials exist
            # in this environment, and an exception here took the caller
            # down with it. SerpApi discovery carries Amazon UK now.
            print("[WARN] Amazon PA API credentials missing — returning no rows")
            return []

        import json

        payload = json.dumps({
            "Keywords": keyword,
            "Resources": [
                "ItemInfo.Title",
                "Offers.Listings.Price",
                "Offers.Listings.DeliveryInfo.IsAmazonFulfilled",
                "Images.Primary.Large",
            ],
            "PartnerTag": self.partner_tag,
            "PartnerType": "Associates",
            "Marketplace": "www.amazon.co.uk",
            "ItemCount": min(limit, 10),
            "SearchIndex": "All",
        })

        headers = self._sign_request(payload)

        resp = requests.post(
            f"{PA_API_ENDPOINT}/searchitems",
            headers=headers,
            data=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        products = []
        items = data.get("SearchResult", {}).get("Items", [])
        for item in (items or []):
            title_data = item.get("ItemInfo", {}).get("Title", {})
            offers = item.get("Offers", {}).get("Listings", [])
            price_data = offers[0].get("Price", {}) if offers else {}
            image_data = item.get("Images", {}).get("Primary", {}).get("Large", {})

            price_str = price_data.get("Amount", "0")
            try:
                price = float(price_str)
            except (ValueError, TypeError):
                price = 0.0

            products.append({
                "source": "Amazon UK",
                "title": title_data.get("DisplayValue", ""),
                "price": price,
                "original_price": price,
                "url": item.get("DetailPageURL", ""),
                "image_url": image_data.get("URL", ""),
                "is_prime": offers[0].get("DeliveryInfo", {}).get("IsAmazonFulfilled", False) if offers else False,
                "asin": item.get("ASIN", ""),
            })

        return products


def get_amazon_scraper():
    """Return Amazon API instance if configured, else None."""
    if os.getenv("AMAZON_PA_ACCESS_KEY"):
        return AmazonUKAPI()
    return None
