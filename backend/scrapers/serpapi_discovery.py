"""
SerpApi Google Shopping — primary supplier discovery (P4).

One google_shopping call per query, filtered down to the 7 approved
suppliers in suppliers.json; the suppliers that generic UK shopping
results never rank get a targeted `site:` pass, capped at MAX_CALLS
calls in total — never one call per supplier. A result whose link domain
or displayed source does not map to an approved slug is dropped, never
padded in with whatever merchant Google happened to return.

SERPAPI_KEY is read from the environment only — no key, no rows.
"""

import json
import os
from urllib.parse import urlparse

import requests

from config import SUPPLIERS_JSON
from engine.source_type import supplier_type as classify_source
from scrapers.availability import serpapi_item_availability
from scrapers.base import ScrapedProduct
from scrapers.google_shopping import _parse_price

SERPAPI_BASE = "https://serpapi.com/search.json"

# P4 — the list never grows past the 7 approved suppliers, and a
# supplier's second row only fills space left over once every supplier
# has had its first, so one supplier cannot crowd the other six out.
MAX_SUPPLIERS = 7
MAX_PER_SUPPLIER = 2

# P4 — one generic call plus targeted `site:` passes for whatever the
# generic results missed. Capped at 4 rather than 7: one round of site:
# passes is enough to reach the dropship suppliers UK Google Shopping
# does not rank, and a second round would spend quota on the same misses.
MAX_CALLS = 4

with open(SUPPLIERS_JSON, encoding="utf-8") as f:
    _SUPPLIERS: dict = json.load(f)["suppliers"]

# Link domain -> approved slug, built from the `domains` arrays that live
# next to each supplier in suppliers.json.
_DOMAIN_TO_SLUG = {
    domain: slug
    for slug, cfg in _SUPPLIERS.items()
    for domain in cfg.get("domains", [])
}

# Displayed source (SerpApi's `source`/`seller`) -> approved slug. The
# label each supplier is listed under plus the spellings Google prints
# ("Amazon", "Amazon.co.uk"), because a shortened link (amzn.to) or a
# .co.uk alias carries no domain we can match on.
_SOURCE_TOKENS = {
    "aliexpress": ("aliexpress",),
    "amazon_uk": ("amazon",),
    "cj_dropshipping": ("cj dropshipping", "cjdropshipping"),
    "godropship": ("godropship", "go dropship"),
    "joybuy": ("joybuy",),
    "bandq": ("b&q", "b and q", "bandq"),
    "toolstation": ("toolstation",),
}

__all__ = [
    "discover",
    "discover_suppliers",
    "search_products",
    "MAX_SUPPLIERS",
    "MAX_PER_SUPPLIER",
    "MAX_CALLS",
]


def _search_shopping(query: str, api_key: str) -> list[dict] | None:
    """One SerpApi google_shopping call.

    [] = the call worked and found nothing. None = the call itself
    failed, so the caller stops instead of spending MAX_CALLS on a key
    or endpoint that is not answering.
    """
    try:
        resp = requests.get(
            SERPAPI_BASE,
            params={
                "engine": "google_shopping",
                "tbm": "shop",
                "q": query,
                "location": "United Kingdom",
                "gl": "uk",
                "hl": "en",
                "api_key": api_key,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        print(f"[WARN] SerpApi google_shopping failed for '{query}': {e}")
        return None
    except ValueError as e:
        print(f"[WARN] SerpApi google_shopping returned no JSON for '{query}': {e}")
        return None

    if not isinstance(data, dict):
        return None
    if data.get("error"):
        print(f"[WARN] SerpApi error for '{query}': {data['error']}")
        return None
    results = data.get("shopping_results") or []
    return results if isinstance(results, list) else []


def _slug_for(item: dict) -> str:
    """Approved slug for a shopping result, '' when it is not one of the 7.

    Domain match wins; the displayed source is the fallback for links
    whose host we do not index.
    """
    host = (urlparse(str(item.get("link", ""))).hostname or "").lower().replace("www.", "")
    for domain, slug in _DOMAIN_TO_SLUG.items():
        if host and (host == domain or host.endswith("." + domain)):
            return slug

    shown = str(item.get("source") or item.get("seller") or "").lower()
    if shown:
        for slug, tokens in _SOURCE_TOKENS.items():
            if slug in _SUPPLIERS and any(tok in shown for tok in tokens):
                return slug
    return ""


def _row_for(slug: str, item: dict) -> ScrapedProduct | None:
    """Build the approved-supplier row, or None when the result is unusable."""
    cfg = _SUPPLIERS[slug]
    url = str(item.get("link", "") or "")
    title = str(item.get("title", "") or "").strip()
    price = _parse_price(item.get("extracted_price", item.get("price", "")))
    if not url or not title or price <= 0:
        return None  # nothing priced/linked/titled — drop, never guess (C1)

    shown = str(item.get("source") or item.get("seller") or "").strip() or None
    # P4 — stock/shipping off the same SerpApi entry (C13); keys the
    # entry does not carry stay unknown (''/0.0/0), never defaulted (C1).
    availability = serpapi_item_availability(item)
    return ScrapedProduct(
        source=cfg["label"],
        title=title,
        price=price,
        url=url,
        image_url=item.get("thumbnail") or None,
        delivery_days_min=cfg["delivery_days_min"],
        delivery_days_max=cfg["delivery_days_max"],
        seller=shown,
        store_name=shown,
        # C10 — Google Shopping does not state condition, so this stays ''
        # ("we did not read one"), never a silent "New".
        condition="",
        verified=True,
        supplier_type=classify_source(name=cfg["label"], url=url),
        **availability,
    )


def _absorb(items: list, found: dict, order: list) -> None:
    """Filter one SerpApi response into approved-supplier rows.

    `found` is slug -> rows (never more than MAX_PER_SUPPLIER), `order`
    is the slugs in the order discovery first saw them.
    """
    for item in items:
        if not isinstance(item, dict):
            continue
        slug = _slug_for(item)
        if not slug:
            continue  # not an approved supplier — dropped, never padded in
        row = _row_for(slug, item)
        if row is None:
            continue

        bucket = found.get(slug)
        if bucket is None:
            bucket = found[slug] = []
            order.append(slug)
        if len(bucket) < MAX_PER_SUPPLIER and not any(r.url == row.url for r in bucket):
            bucket.append(row)


def _site_query(slug: str, query: str) -> str:
    """Targeted pass for one supplier, '' when it has no indexed domain."""
    domains = _SUPPLIERS[slug].get("domains") or []
    return f"site:{domains[0]} {query}" if domains else ""


def discover(query: str) -> list[ScrapedProduct]:
    """Approved-supplier rows for `query`, from SerpApi Google Shopping.

    One call in the common case, at most MAX_CALLS. Fails closed: no
    SERPAPI_KEY means no request and no rows.
    """
    api_key = os.getenv("SERPAPI_KEY", "")
    if not api_key:
        print("[WARN] SERPAPI_KEY not set — supplier discovery returns no rows")
        return []
    if not str(query or "").strip():
        return []

    query = str(query).strip()
    found: dict[str, list[ScrapedProduct]] = {}
    order: list[str] = []
    generic = _search_shopping(query, api_key)
    if generic is None:
        return []  # transport is failing — one attempt, never MAX_CALLS
    _absorb(generic, found, order)

    # Suppliers the generic pass missed, dropshippers first: UK Google
    # Shopping ranks the high-street retailers on its own, the dropship
    # marketplaces rarely if ever.
    missing = [slug for slug in _SUPPLIERS if slug not in found]
    missing.sort(key=lambda slug: _SUPPLIERS[slug].get("type", "") != "dropship")

    calls = 1
    for slug in missing:
        if calls >= MAX_CALLS:
            break
        targeted = _site_query(slug, query)
        if not targeted:
            continue
        result = _search_shopping(targeted, api_key)
        if result is None:
            break  # same failing key/endpoint — stop spending calls
        _absorb(result, found, order)
        calls += 1

    # Coverage first: every supplier's first row, then the spare rows,
    # then the P4 total cap.
    rows: list[ScrapedProduct] = []
    for slug in order:
        rows.append(found[slug][0])
    for slug in order:
        rows.extend(found[slug][1:])
    return rows[:MAX_SUPPLIERS]


# P4 callers reach this by either name — same call, same rows.
discover_suppliers = discover
search_products = discover
