"""
AliExpress — via AliGate on RapidAPI (Basic tier: 100 requests/month, hard cap).

Free subscription:
    https://rapidapi.com/aligate/api/aligate-aliexpress-data-api

The previous listing (aliexpress-api.p.rapidapi.com) was removed from
RapidAPI (its page 404s), so the seam now targets the publisher-accessible
AliGate v2 surface:

    GET /api/v2/search/text  — keyword search, scoped per call.

Every call is scoped by country/currency/locale (AliGate resolves prices,
stock and shipping exactly as a shopper in that market sees them): the
defaults are GB/GBP/en_GB for the UK sourcing market, overridable with
ALIGATE_COUNTRY / ALIGATE_CURRENCY / ALIGATE_LOCALE, and the host itself is
overridable with RAPIDAPI_HOST (e.g. if subscribing to a different AliExpress
listing on RapidAPI).
"""

import os
import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# The publisher's own documented host (aligate.io and its RapidAPI listing).
# RAPIDAPI_HOST wins so a different AliExpress listing can serve the seam
# without a code change.
DEFAULT_RAPIDAPI_HOST = "aligate-aliexpress-data-api.p.rapidapi.com"

SEARCH_PATH = "/api/v2/search/text"

# Query-string key /api/v2/search/text accepts the keyword under — confirmed
# live: requesting it as `keywords` came back HTTP 200 with
# meta.error "query is required" (the gateway names its own contract).
SEARCH_KEYWORD_PARAM = "query"


class RapidAPIAliExpress:
    """AliExpress via AliGate on RapidAPI — free Basic tier, 100 req/month."""

    def __init__(self):
        self.api_key = os.getenv("RAPIDAPI_KEY", "")
        self.host = os.getenv(
            "RAPIDAPI_HOST", DEFAULT_RAPIDAPI_HOST
        ).strip()
        self.country = os.getenv("ALIGATE_COUNTRY", "GB")
        self.currency = os.getenv("ALIGATE_CURRENCY", "GBP")
        self.locale = os.getenv("ALIGATE_LOCALE", "en_GB")

    def _headers(self) -> dict:
        return {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": self.host,
        }

    def search_products(self, keyword: str, limit: int = 10) -> list[dict]:
        """Search AliExpress via AliGate — rows normalized for the converter."""
        if not self.api_key:
            raise ValueError(
                "RAPIDAPI_KEY required — subscribe (free tier) at "
                "https://rapidapi.com/aligate/api/aligate-aliexpress-data-api"
            )

        resp = requests.get(
            f"https://{self.host}{SEARCH_PATH}",
            headers=self._headers(),
            params={
                SEARCH_KEYWORD_PARAM: keyword,
                "country": self.country,
                "currency": self.currency,
                "locale": self.locale,
            },
            timeout=15,
        )
        try:
            resp.raise_for_status()
        except requests.RequestException:
            # The gateway's own words say exactly what went wrong (refused
            # key, wrong keyword parameter, cap reached) — carry them into
            # the log verbatim and truncated, never invent an explanation.
            print(
                f"[WARN] AliGate RapidAPI refused: {resp.status_code} "
                f"{str(resp.text[:300])}"
            )
            raise

        data = resp.json()

        products = []
        for item in self._rows(data)[:limit]:
            row = self._normalize_row(item)
            if row:
                products.append(row)

        if not products:
            # An HTTP 200 can still carry an app-level refusal or an
            # envelope that mouths a key different from any the parser
            # reads. Log a truncated snapshot of the REAL body so the
            # answer is diagnosed from the publisher's own words — never
            # guessed, and never any credential material.
            print(
                "[WARN] AliGate answered with no parsed rows — snapshot: "
                f"{str(data)[:400]}"
            )

        return products

    @staticmethod
    def _rows(data) -> list:
        """Search answer rows, wherever the publisher's envelope puts them.

        The exact shape of /search/text's answer body is not published; the
        parser accepts the envelope families tabular storefront APIs use — a
        bare list, or a list under products/items/results/data — and passes
        through only rows that actually are dicts.
        """
        if isinstance(data, dict):
            data = (
                data.get("products")
                or data.get("items")
                or data.get("results")
                or data.get("data")
                or []
            )
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        return []

    @staticmethod
    def _price_value(value) -> Optional[float]:
        """First real number in what the payload calls price — else None.

        Same contract the previous connector kept: a payload string like
        "US $8.99" yields 8.99; anything without a number yields nothing.
        """
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        match = re.search(r"\d+(?:[.,]\d+)?", str(value or ""))
        return float(match.group().replace(",", "")) if match else None

    def _normalize_row(self, item) -> Optional[dict]:
        """One AliGate search row — carry ONLY what the payload states.

        A dict price is the AliGate shape (min_value/max_value/currency):
        the floor price is the real, lowest stated ask. A count under
        `sales`/`orders` is carried as the popularity figure; a money
        value is never relabelled as orders. Stock, shipping and
        Standard Shipping stay untouched here — what search rows do not
        state them (C1/C13), the converter keeps unknown.
        """
        title = str(item.get("title") or item.get("product_title") or "").strip()

        raw_price = item.get("price")
        currency = None
        price = None
        if isinstance(raw_price, dict):
            currency = raw_price.get("currency")
            price = self._price_value(raw_price.get("min_value"))
        if price is None:
            price = self._price_value(
                raw_price if not isinstance(raw_price, (dict, list))
                else item.get("product_price")
            )

        orders = None
        for key in ("sales", "orders"):
            value = item.get(key)
            if isinstance(value, bool):
                continue
            try:
                candidate = int(value)
            except (TypeError, ValueError):
                continue
            if candidate > 0:
                orders = candidate
                break

        url = str(item.get("url") or item.get("product_url") or "").strip()
        if not url:
            # No URL stated: rebuild the canonical item URL from the source's
            # own product_id (AliGate documents that id as the number in the
            # AliExpress item link) — deterministic, nothing invented.
            product_id = item.get("product_id") or item.get("id")
            if product_id:
                url = (
                    "https://www.aliexpress.com/item/"
                    f"{str(product_id).strip()}.html"
                )

        image = item.get("image_url") or item.get("image") or item.get("product_image")

        return {
            "source": "AliExpress",
            "title": title,
            "price": price,
            "currency": currency,
            "url": url,
            "image_url": str(image).strip() if image else "",
            "orders": orders,
            # AliGate states ratings as a bare number ("ratings": 4.7); the
            # converter's text/dict handling covers both shapes.
            "rating": item.get("ratings") if item.get("ratings") is not None
            else item.get("rating"),
        }


def get_rapidapi_aliexpress():
    """Return a RapidAPI AliExpress instance if configured, else None."""
    if os.getenv("RAPIDAPI_KEY"):
        return RapidAPIAliExpress()
    return None
