"""
SerpApi Google Shopping — primary supplier discovery (P4).

THREE stages, because a SerpApi `google_shopping` result does NOT carry the
merchant's URL — every `link` on it is Google's own redirect, and
`product_link` is `https://www.google.com/...`. Verified against the live API
before this was written; guessing a product URL would violate C1.

  1. SEARCH  one `google_shopping` call (plus a `site:` pass for whatever it
            missed) tells us the SUPPLIER — the `source` field — and the
            title and price Google indexed.
  2. RESOLVE one `google_immersive_product` call per row we actually keep
            turns that into a real merchant product URL, and hands us the
            offer's own price, shipping line and stock wording.
  3. BUILD   a row per approved supplier, coverage first (every supplier's
            first row, then the spares), capped at MAX_SUPPLIERS.

A result whose source does not map to one of the 7 suppliers in
suppliers.json is dropped, never padded in with whatever merchant Google
happened to return (C12).

All three stages draw on ONE budget of MAX_CALLS SerpApi requests per query —
the API bills per request, so discovery can never quietly spend whatever it
likes. No SERPAPI_KEY means no request and no rows (fails closed).
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
from utils.redact import scrub

SERPAPI_BASE = "https://serpapi.com/search.json"

# P4 — the list never grows past the 7 approved suppliers, and a
# supplier's second row only fills space left over once every supplier
# has had its first, so one supplier cannot crowd the other six out.
MAX_SUPPLIERS = 7
MAX_PER_SUPPLIER = 2

# One budget for search AND resolve calls. One generic search, a couple of
# targeted `site:` passes and enough resolves to give every supplier a real
# URL all fit inside this; the 7 approved suppliers need at most one resolve
# each for their first row.
MAX_CALLS = 10

_TIMEOUT = 20

with open(SUPPLIERS_JSON, encoding="utf-8") as f:
    _SUPPLIERS: dict = json.load(f)["suppliers"]

# A supplier marked "enabled": false stays in the file with its reason, so the
# decision is auditable, but must never contribute a whitelist entry — or
# SerpApi results would still be labelled as an approved supplier we do not
# actually use. (amazon_uk is currently disabled: PA-API 5 is deprecated,
# access needs 10 sales in 30 days, and the licence bars this use case.)
_ACTIVE_SUPPLIERS = {
    slug: cfg for slug, cfg in _SUPPLIERS.items()
    if cfg.get("enabled", True)
}

# Link domain -> approved slug, built from the `domains` arrays that live
# next to each supplier in suppliers.json.
_DOMAIN_TO_SLUG = {
    domain: slug
    for slug, cfg in _ACTIVE_SUPPLIERS.items()
    for domain in cfg.get("domains", [])
}

# Displayed source (SerpApi's `source`/`seller`/store `name`) -> approved
# slug. The label each supplier is listed under plus the spellings Google
# prints ("Amazon", "Amazon.co.uk"), because an `amzn.to` short link or a
# .co.uk alias may carry no host we index.
_SOURCE_TOKENS = {
    "aliexpress": ("aliexpress",),
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


class _Budget:
    """Shared call budget. Every SerpApi request spends one, and once the
    budget is gone discovery stops instead of spending more.

    `exhausted` is the other stop condition: the account itself is out of
    searches for the month, so spending is pointless however many calls are
    left. Once set, every later `spend()` fails — the remaining offers for a
    supplier are skipped instead of each one paying for a 429."""

    def __init__(self, limit: int) -> None:
        self.left = limit
        self.exhausted = False

    def spend(self) -> bool:
        if self.exhausted or self.left <= 0:
            return False
        self.left -= 1
        return True


def _get_json(params: dict, api_key: str, budget: "_Budget",
              timeout: float | None = None) -> dict | None:
    """One SerpApi request. None = the call failed (transport, non-JSON or a
    reported error), so the caller stops rather than burning the budget on a
    key or endpoint that is not answering.

    `timeout` defaults to the module's own. It exists because the two callers
    hit genuinely different endpoints: `google_shopping` answers in ~3s, while
    `google` on a `site:` pass measured 1.2s, 1.6s and 2.3s on good days and
    over 20s on others. Forcing the shopping timeout onto the web engine was
    measured to abandon the call mid-flight, so a caller that knows its own
    endpoint passes its own number.
    """
    params = {**params, "api_key": api_key}
    try:
        resp = requests.get(
            SERPAPI_BASE, params=params,
            timeout=_TIMEOUT if timeout is None else timeout)
    except requests.RequestException as e:
        # scrub(): `requests` puts the whole URL — api_key included — into
        # its exception text, and this line lands in be.log (A4).
        print(f"[WARN] SerpApi request failed ({params.get('engine')}): {scrub(e)}")
        return None

    # 429 is deliberately ambiguous: SerpApi documents it for BOTH "you are
    # sending too fast" and "your account has run out of searches". Only the
    # response body separates them, and `raise_for_status()` would discard it
    # — so the exhausted case would be reported as a rate limit, and every
    # remaining offer would retry into the same wall.
    if resp.status_code == 429:
        try:
            message = str(resp.json().get("error") or "")
        except ValueError:
            message = ""
        if "run out of searches" in message.lower():
            budget.exhausted = True
            print(
                "[WARN] SerpApi: account has run out of searches - supplier "
                "discovery is unavailable until the monthly quota resets"
            )
        else:
            print(f"[WARN] SerpApi rate limited (429): {scrub(message) or 'too many requests'}")
        return None

    try:
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        print(f"[WARN] SerpApi request failed ({params.get('engine')}): {scrub(e)}")
        return None
    except ValueError as e:
        print(f"[WARN] SerpApi returned no JSON ({params.get('engine')}): {scrub(e)}")
        return None

    if not isinstance(data, dict):
        return None
    if data.get("error"):
        print(f"[WARN] SerpApi error ({params.get('engine')}): {data['error']}")
        return None
    return data


def _search_shopping(query: str, api_key: str, budget: _Budget) -> list[dict] | None:
    """One `google_shopping` call.

    [] = the call worked and found nothing. None = the call itself failed.
    """
    if not budget.spend():
        return None
    data = _get_json(
        {"engine": "google_shopping", "q": query, "location": "United Kingdom",
         "gl": "uk", "hl": "en"},
        api_key,
        budget,
    )
    if data is None:
        return None
    results = data.get("shopping_results") or []
    return results if isinstance(results, list) else []


def _slug_for(item: dict) -> str:
    """Approved slug for a shopping result, '' when it is not one of the 7.

    Domain match wins; the displayed source is the fallback, and it is the
    one that actually fires here — Google's own links carry no merchant host.
    """
    host = (urlparse(str(item.get("link", ""))).hostname or "").lower().replace("www.", "")
    for domain, slug in _DOMAIN_TO_SLUG.items():
        if host and (host == domain or host.endswith("." + domain)):
            return slug

    shown = str(item.get("source") or item.get("seller") or item.get("name") or "").lower()
    if shown:
        for slug, tokens in _SOURCE_TOKENS.items():
            if slug in _SUPPLIERS and any(tok in shown for tok in tokens):
                return slug
    return ""


def _resolve_store(item: dict, api_key: str, budget: _Budget) -> tuple[str, dict] | None:
    """Turn one shopping result into a real merchant offer.

    Costs one `google_immersive_product` call and returns the `stores[]`
    entry that actually links out to an approved supplier — the only place
    SerpApi publishes the merchant URL, price, shipping line and stock
    wording.

    Returns None when the budget is spent, the token is missing, or no
    approved store is offering it. The slug returned is the one the OFFER'S
    OWN DOMAIN maps to, not the one Google filed the search result under —
    an offer must never be labelled with a supplier it does not belong to.
    """
    token = str(item.get("immersive_product_page_token") or "")
    if not token or not budget.spend():
        return None

    data = _get_json(
        {"engine": "google_immersive_product", "page_token": token},
        api_key,
        budget,
    )
    if data is None:
        return None

    product = data.get("product_results") or {}
    stores = product.get("stores") if isinstance(product, dict) else None
    if not isinstance(stores, list):
        return None

    for store in stores:
        if not isinstance(store, dict):
            continue
        if not str(store.get("link") or "").strip():
            continue  # no merchant URL -> no row (C1: never invent one)
        # The offer must belong to an APPROVED supplier, and it says so by
        # its own domain or its own name — not by where Google filed it.
        slug = _slug_for({"link": store["link"], "name": store.get("name", "")})
        if slug:
            return slug, store
    return None


def _stock_text(store: dict) -> str:
    """Stock wording off the offer, '' when the offer states none.

    SerpApi puts it in `details_and_offers` as prose ("In stock online",
    "Out of stock"). Only a line about stock is kept; nothing is inferred
    from an offer that simply does not mention it (C1).
    """
    details = store.get("details_and_offers")
    if not isinstance(details, list):
        return ""
    for line in details:
        if not isinstance(line, str):
            continue
        low = line.lower()
        if "stock" in low or "available" in low:
            return line.strip()
    return ""


def _offer_availability(store: dict) -> dict:
    """The six P4 fields off one resolved offer.

    The offer's `shipping` line carries the postage wording and
    `details_and_offers` carries the stock wording; anything absent stays
    unknown (C1) — 0.0 shipping means "not stated", never "free" (C13).
    """
    stock = _stock_text(store)
    source = {
        "link": str(store.get("link") or ""),
        "stock": stock,
        "shipping": store.get("shipping") if isinstance(store.get("shipping"), str) else "",
    }
    return serpapi_item_availability(source)


def _row_for(slug: str, item: dict, store: dict) -> ScrapedProduct | None:
    """Build the approved-supplier row, or None when the offer is unusable."""
    cfg = _SUPPLIERS[slug]
    url = str(store.get("link", "") or "").strip()
    title = str(store.get("title", "") or "").strip() or str(item.get("title", "") or "").strip()
    price = store.get("extracted_price")
    if not isinstance(price, (int, float)) or price <= 0:
        price = _parse_price(store.get("price", store.get("total", "")))
    if not url or not title or not price or price <= 0:
        return None  # nothing priced/linked/titled — drop, never guess (C1)

    shown = str(store.get("name") or item.get("source") or "").strip() or None
    availability = _offer_availability(store)
    shipping_line = str(store.get("shipping") or "").strip()
    shipping_methods = []
    if shipping_line:
        for method in (
            "AliExpress Standard Shipping",
            "Standard Shipping",
            "ePacket",
            "Expedited Shipping",
            "Economy Shipping",
        ):
            if method.lower() in shipping_line.lower() and method not in shipping_methods:
                shipping_methods.append(method)
    if slug == "aliexpress" and "standard shipping" in shipping_line.lower():
        from scrapers.availability import parse_shipping_text

        standard_available = "unavailable" not in shipping_line.lower()
        standard_cost, standard_days, standard_raw = parse_shipping_text(
            shipping_line
        )
        if standard_cost <= 0 and "free" not in shipping_line.lower():
            standard_cost = None
        if standard_days <= 0:
            standard_days = None
        if "AliExpress Standard Shipping" not in shipping_methods and "Standard Shipping" in shipping_line:
            shipping_methods.insert(0, "AliExpress Standard Shipping")
        availability.update(
            {
                "standard_shipping_available": standard_available,
                "standard_shipping_cost": standard_cost,
                "standard_shipping_days_min": standard_days,
                "standard_shipping_days_max": standard_days,
                "standard_shipping_raw": standard_raw or shipping_line,
            }
        )
    else:
        availability.update(
            {
                "standard_shipping_available": None,
                "standard_shipping_cost": None,
                "standard_shipping_days_min": None,
                "standard_shipping_days_max": None,
                "standard_shipping_raw": "",
            }
        )
    availability["shipping_methods"] = shipping_methods
    availability.setdefault("review_rating", None)
    availability.setdefault("review_count", None)
    availability.setdefault("review_verified", False)
    availability.setdefault("review_source", "")
    return ScrapedProduct(
        source=cfg["label"],
        title=title,
        price=float(price),
        url=url,
        image_url=item.get("thumbnail") or item.get("serpapi_thumbnail") or None,
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


def _site_query(slug: str, query: str) -> str:
    """Targeted pass for one supplier, '' when it has no indexed domain.

    REGRESSION-008: a supplier the SHOPPING index does not carry must not be
    sent down this road. Measured 2026-10-10 against the live API:

        google_shopping  "site:joybuy.com <product>"   0 rows,  67.0s
        google           "site:joybuy.com <product>"   10/10,   2.3s

    So the stall is the SHOPPING engine refusing the `site:` operator, not the
    operator itself, and paying 67s per query for zero rows is a real cost on
    every lookup. A supplier flagged `skip_site_pass` is served instead by
    scrapers.joybuy_web, which reads Google's WEB index and never contacts
    the supplier at all; it returns '' here so Stage 2 skips it.
    """
    cfg = _SUPPLIERS[slug]
    if cfg.get("skip_site_pass"):
        return ""
    domains = cfg.get("domains") or []
    return f"site:{domains[0]} {query}" if domains else ""


def discover(query: str) -> list[ScrapedProduct]:
    """Approved-supplier rows for `query`, from SerpApi Google Shopping.

    Coverage first: every supplier's first real row, then the spare rows,
    then the P4 cap of MAX_SUPPLIERS. Fails closed: no SERPAPI_KEY means no
    request and no rows.
    """
    api_key = os.getenv("SERPAPI_KEY", "")
    if not api_key:
        print("[WARN] SERPAPI_KEY not set - supplier discovery returns no rows")
        return []
    if not str(query or "").strip():
        return []
    query = str(query).strip()

    budget = _Budget(MAX_CALLS)
    generic = _search_shopping(query, api_key, budget)
    if generic is None:
        return []  # transport is failing - one attempt, never the whole budget

    # slug -> offers still waiting to be resolved, in first-seen order.
    waiting: dict[str, list[dict]] = {}
    order: list[str] = []
    for item in generic:
        if not isinstance(item, dict):
            continue
        slug = _slug_for(item)
        if not slug:
            continue  # not an approved supplier - dropped, never padded in
        if slug not in waiting:
            waiting[slug] = []
            order.append(slug)
        if len(waiting[slug]) < MAX_PER_SUPPLIER:
            waiting[slug].append(item)

    rows: dict[str, list[ScrapedProduct]] = {}

    def _resolve_one(slug: str) -> None:
        """Resolve the next waiting offer for `slug`, if any survives."""
        bucket = waiting.get(slug) or []
        while bucket:
            if budget.exhausted:
                break  # out of searches: the rest of this bucket is unwinnable
            item = bucket.pop(0)
            resolved = _resolve_store(item, api_key, budget)
            if resolved is None:
                continue  # unresolvable -> try the next offer, never fabricate
            real_slug, store = resolved
            if real_slug != slug:
                # The offer is real but belongs to another approved supplier;
                # filing it under this one would mislabel whose listing it is.
                continue
            row = _row_for(slug, item, store)
            if row is None:
                continue
            rows.setdefault(slug, []).append(row)
            return

    # Stage 1 — give every supplier the generic pass already found a row.
    for slug in list(order):
        if budget.exhausted or budget.left <= 0:
            break
        _resolve_one(slug)

    # Stage 2 — suppliers the generic pass missed, dropshippers first: UK
    # Google Shopping ranks the high-street retailers on its own, the
    # dropship marketplaces rarely if ever.
    missing = [s for s in _SUPPLIERS if s not in rows]
    missing.sort(key=lambda s: _SUPPLIERS[s].get("type", "") != "dropship")
    for slug in missing:
        if budget.exhausted or budget.left <= 0:
            break
        targeted = _site_query(slug, query)
        if not targeted:
            continue
        found = _search_shopping(targeted, api_key, budget)
        if found is None:
            break  # same failing key/endpoint - stop spending the budget
        for item in found:
            if not isinstance(item, dict) or _slug_for(item) != slug:
                continue  # a site: pass that drifted off-target
            if len(waiting.get(slug, [])) < MAX_PER_SUPPLIER:
                waiting.setdefault(slug, []).append(item)
                if slug not in order:
                    order.append(slug)
        if slug in waiting and waiting[slug]:
            _resolve_one(slug)

    # Stage 3 — a second row per supplier, budget permitting.
    for slug in [s for s in order if s in rows]:
        if budget.exhausted or budget.left <= 0:
            break
        if len(rows[slug]) >= MAX_PER_SUPPLIER:
            continue
        _resolve_one(slug)

    # Coverage first: every supplier's first row, then the spare rows,
    # then the P4 total cap.
    out: list[ScrapedProduct] = []
    for slug in order:
        if slug in rows and rows[slug]:
            out.append(rows[slug][0])
    for slug in order:
        out.extend(rows.get(slug, [])[1:])
    return out[:MAX_SUPPLIERS]


# P4 callers reach this by either name - same call, same rows.
discover_suppliers = discover
search_products = discover
