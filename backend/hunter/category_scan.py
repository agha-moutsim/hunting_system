"""eBay category scanning — browse a category, or search what the user typed.

REGRESSION-001: the category lookup used to fall back to Electronics (293) for
anything it did not recognise, and never sent the typed words to eBay at all.
Resolution now lives in `hunter.category_resolver`; this module only decides
how to ask (category_ids vs q) and how to parse the answer.
"""

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from config import EBAY_UK_BASE, EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_API_BASE, EBAY_MARKETPLACE, SCRAPE_CONFIG, FILTERS
from engine.condition_gate import html_condition_param, is_new
from hunter.category_resolver import (  # noqa: F401  (re-exported for hunter/__init__)
    EBAY_CATEGORIES,
    MODE_CATEGORY,
    ResolvedSearch,
    category_choices,
    resolve_category,
)


@dataclass
class CategoryProduct:
    """A product found in a category scan."""
    title: str
    price: float
    url: str
    image_url: Optional[str] = None
    seller: Optional[str] = None
    condition: str = ""   # C10 — '' = unread; never assume New
    buying_format: str = "Buy It Now"
    category: str = ""
    # 1.6 — what was actually asked for: "category" or "keyword", plus the
    # text sent to eBay. A row never claims a category it did not come from.
    search_mode: str = ""
    search_query: str = ""
    # Filled later. `sold_*` are OBSERVED SALES (None = not measured, which is
    # the normal case — see scrapers/base.py DemandData). `active_listings_in_band`
    # is the in-band New listing count: SUPPLY, kept apart so no badge, gate or
    # verdict can read one as the other.
    sold_30d: Optional[int] = None
    sold_7d: Optional[int] = None
    active_listings_in_band: Optional[int] = None
    supplier_price: float = 0.0
    supplier_name: str = ""
    supplier_url: str = ""
    # REGRESSION-004 — WHY there is (or is not) a supplier price. "" is
    # deliberately invalid: a row never looked up must not look like one that
    # was checked and found clean.
    #   "found" | "no_supplier" | "out_of_band" | "timeout"
    supplier_status: str = ""
    # C13 - the reason behind supplier_status, in words the UI can show.
    supplier_status_reason: str = ""
    # REGRESSION-005 - provenance for the MONEY figures. profit/margin stay
    # 0.0 when we have no data, but these say so, so the UI can show "no
    # supplier data" instead of a confident red GBP0.00.
    #   "estimated" (computed from real inputs) | "unverified" (not computable)
    profit_provenance: str = ""
    profit_provenance_label: str = ""
    profit_provenance_reason: str = ""
    profit_provenance_method: str = ""
    # "found" | "no_supplier" | "out_of_band" | "timeout" | "" - why the
    # profit figure is or is not there.
    profit_status: str = ""
    # C13 - supplier postage when the source stated it. 0.0 = unknown.
    shipping_cost: float = 0.0
    shipping_raw: str = ""
    # Sourcing standard - real review, stock, shipping and ranking evidence.
    # None/False/empty means "not read"; never a default or a guess.
    supplier_review_rating: Optional[float] = None
    supplier_review_count: Optional[int] = None
    supplier_review_verified: bool = False
    supplier_stock_status: str = ""
    supplier_stock_verified: bool = False
    supplier_shipping_known: bool = False
    supplier_shipping_methods: list[str] = field(default_factory=list)
    supplier_standard_shipping_available: Optional[bool] = None
    supplier_standard_shipping_cost: Optional[float] = None
    supplier_standard_shipping_days_min: Optional[int] = None
    supplier_standard_shipping_days_max: Optional[int] = None
    supplier_standard_shipping_raw: str = ""
    supplier_total_landed_cost: Optional[float] = None
    supplier_sourcing_preferred: bool = False
    supplier_sourcing_eligible: bool = False
    supplier_sourcing_reasons: list[str] = field(default_factory=list)
    supplier_sourcing_score: float = 0.0
    supplier_sourcing_policy_version: str = ""
    # Hot/trending, computed by hunter/demand_hotness.py from the two demand
    # counts above. `hot` is derived, never assigned by hand;
    # hot_provenance == "unverified" means we had no demand data to judge.
    hot: bool = False
    hot_basis: str = ""
    hot_provenance: str = ""
    hot_reason: str = ""
    demand_pace_7d_per_week: Optional[float] = None
    demand_pace_30d_per_week: Optional[float] = None
    # Windowed variants so the UI can toggle 7d / 30d without a re-fetch.
    # The 7d numbers exist only when a real capture did.
    hot_7d: bool = False
    hot_7d_basis: str = ""
    hot_7d_provenance: str = ""
    hot_7d_reason: str = ""
    hot_30d: bool = False
    hot_30d_basis: str = ""
    hot_30d_provenance: str = ""
    hot_30d_reason: str = ""
    profit: float = 0.0
    margin: float = 0.0
    verdict: str = ""
    # C11 — stores from the sellers this scan observed ([] when none).
    ebay_stores: list = field(default_factory=list)
    # C14 — computed by engine/match.py, never a constant. "" = unscored,
    # which consumers must treat as failed (C12: unscored is not a pass).
    supplier_match_score: float = 0.0
    supplier_match_tier: str = ""
    supplier_match_label: str = ""


def scan_category(
    category_name: str,
    price_min: float = FILTERS["price_min"],
    price_max: float = FILTERS["price_max"],
    max_results: int = 50,
) -> list[CategoryProduct]:
    """Browse a known category, or search eBay for what the user actually typed.

    C14/REGRESSION-001: the old one-liner was
    `EBAY_CATEGORIES.get(category_name, "293")`, so "garden tools" silently
    became Electronics and the typed words never reached eBay. An empty
    search returns nothing rather than a default category.
    """
    resolved = resolve_category(category_name)
    if not resolved.text:
        print("[WARN] Category scan called with no search text - nothing to do")
        return []

    # Try API first
    products = _scan_via_api(resolved, price_min, price_max, max_results)
    if products:
        return products

    # Fallback to scraping
    return _scan_via_scrape(resolved, price_min, price_max, max_results)


def _search_params(resolved: ResolvedSearch, price_min: float, price_max: float,
                   max_results: int) -> dict:
    """The Browse API query for a resolved search.

    Exactly one of `category_ids` (browse) or `q` (search) is ever sent —
    sending both would let eBay ignore the keywords.
    """
    params: dict = {
        "limit": min(max_results, 50),
        "filter": (
            f"buyingOptions:{{FIXED_PRICE}},"
            f"conditions:{{NEW}},"
            f"deliveryCountry:GB,"
            f"price:[{price_min}..{price_max}],"
            f"priceCurrency:GBP"
        ),
        "sort": "-relevance",
    }
    if resolved.is_category:
        params["category_ids"] = resolved.category_id
    else:
        params["q"] = resolved.text
    return params


def _scan_via_api(
    resolved: ResolvedSearch,
    price_min: float,
    price_max: float,
    max_results: int,
) -> list[CategoryProduct]:
    """Browse or search via the Browse API."""
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

        # Search eBay — a category browse, or a real keyword search
        resp = requests.get(
            f"{EBAY_API_BASE}/buy/browse/v1/item_summary/search",
            params=_search_params(resolved, price_min, price_max, max_results),
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
            condition = item.get("condition", "")
            if not is_new(condition):
                continue  # C10 — defence in depth behind conditions:{NEW}
            products.append(CategoryProduct(
                title=item.get("title", ""),
                price=price,
                url=item.get("itemWebUrl", ""),
                image_url=item.get("thumbnailImages", [{}])[0].get("imageUrl")
                    if item.get("thumbnailImages") else None,
                seller=seller_info.get("username"),
                condition=condition,
                # 1.6 — the row records what was ACTUALLY asked for. The old
                # code stamped the user's raw text onto rows that had come
                # from category 293, so the page read "garden tools" above a
                # shelf of electronics.
                category=resolved.label or resolved.text,
                search_mode=resolved.mode,
                search_query=resolved.text,
            ))

            if len(products) >= max_results:
                break

        # C11 — the sellers arrived on the response we already paid for;
        # only listings that cleared the New gate reached `products`, so
        # aggregating them keeps the condition gate intact.
        try:
            from engine.stores import stores_from_products
            stores = stores_from_products(products)
        except Exception as e:
            print(f"[WARN] Store build failed for category scan: {e}")
            stores = []
        for p in products:
            p.ebay_stores = list(stores)

        return products

    except Exception as e:
        print(f"[WARN] Category API scan failed: {e}")
        return []


def _scan_via_scrape(
    resolved: ResolvedSearch,
    price_min: float,
    price_max: float,
    max_results: int,
) -> list[CategoryProduct]:
    """Fallback: scrape the eBay category page, or run the search on the site.

    A keyword search has no category page, so it uses eBay's own search URL
    (`/sch/i.html?_nkw=`) rather than a category shelf.
    """
    products = []

    try:
        if resolved.is_category:
            path = f"{EBAY_UK_BASE}/b/{resolved.category_id}/n.html"
            extra = ""
        else:
            quoted = quote_plus(resolved.text)
            path = f"{EBAY_UK_BASE}/sch/i.html"
            extra = f"&_nkw={quoted}"
        url = (
            f"{path}?"
            f"_pgn=1"
            f"{extra}"
            f"&LH_Price=1"
            f"&_udlo={price_min:.0f}"
            f"&_udhi={price_max:.0f}"
            f"&LH_BIN=1"
            f"{html_condition_param()}"   # C10 — active condition, not a literal
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

                # C10 — the URL carries LH_ItemCondition=1000, but we still
                # read the label the page shows; unread = dropped, never
                # defaulted to New.
                condition = ""
                for sel in ("span.s-item__condition", "span.SECONDARY_INFO",
                            "span[class*='condition']"):
                    cond_el = item.select_one(sel)
                    if cond_el and cond_el.get_text(strip=True):
                        condition = cond_el.get_text(strip=True)
                        break
                if not is_new(condition):
                    continue

                products.append(CategoryProduct(
                    title=title,
                    price=price,
                    url=link_el.get("href", ""),
                    condition=condition,
                    category=resolved.label or resolved.text,
                    search_mode=resolved.mode,
                    search_query=resolved.text,
                ))

                if len(products) >= max_results:
                    break

            except Exception:
                continue

    except Exception as e:
        print(f"[WARN] Category scrape failed: {e}")

    return products
