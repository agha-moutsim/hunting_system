"""
C11 — up to 4 real eBay competitor stores per analysis.

Every feature (Analyze, URL-hunt, Deep Search, Bulk, Category Hunter)
surfaces the SAME list, produced by THIS module, from real
``seller.username`` values read off eBay responses.

Two rules from the spec that shape every function here:

  * ``sold_count`` is **listings observed in the search window (cap 50)** —
    it is NOT eBay's sold count. It travels with a human label
    (``sold_count_label``) so no consumer can silently promote it.
  * the store URL is **derived** as ``ebay.co.uk/str/{username}``, never
    observed on the page. Every row therefore carries ``url_derived: True``.

Discovery is designed to cost **no extra network calls**: the sold-listing
and demand queries already return seller usernames, and callers were simply
discarding them. This module normalises whatever those paths hand it, and
only falls back to its own search when a caller has no sellers at all.

Fail-closed everywhere: no sellers ⇒ empty list + unverified stamps, never
an empty-looking "verified" row and never an exception that kills the parent
analysis.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from config import EBAY_UK_BASE, STORE_COUNT

# C11 — how many stores any feature may surface.
MAX_STORES = STORE_COUNT

# The window the counts are taken from. Browse API / HTML sold search both
# page at 50; the label says so because the number means nothing without it.
OBSERVED_WINDOW = 50

# C11 — the required human label. Kept in one place so every renderer and
# every export uses identical wording.
SOLD_COUNT_LABEL = f"observed listings (search window, cap {OBSERVED_WINDOW})"

STORE_URL_TEMPLATE = f"{EBAY_UK_BASE}/str/{{username}}"

SOURCE_NAME = "eBay sold-listing search (conditions:{NEW})"


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def normalise_username(raw: Any) -> str:
    """Reduce whatever eBay handed us to a bare seller username.

    The HTML path returns strings like ``"good_store (12345)"`` — a
    feedback count glued to the name. Passing that through would produce a
    storefront URL that 404s, so strip the parenthesised tail and any
    surrounding whitespace. Returns '' when nothing usable is left, and
    callers treat '' as "no store".
    """
    if not raw:
        return ""
    name = str(raw).strip()
    if not name:
        return ""
    if "(" in name and name.rstrip().endswith(")"):
        name = name.split("(", 1)[0].strip()
    # eBay usernames cannot contain a slash or a space; anything that does
    # is a scraped fragment rather than a username.
    if "/" in name or " " in name:
        return ""
    return name


def derive_store_url(username: str) -> str:
    """Build the storefront URL from a username.

    C11 marks this DERIVED — we never observed the link, we constructed it,
    so every row built from it carries ``url_derived=True``.
    """
    name = normalise_username(username)
    return STORE_URL_TEMPLATE.format(username=name) if name else ""


# ---------------------------------------------------------------------------
# Row construction
# ---------------------------------------------------------------------------

def _row(name: str, sold_count: int, avg_price: float,
         source_name: str = SOURCE_NAME,
         provenance: str = "verified") -> dict:
    """One store row, stamped per C13.

    ``verified`` here means exactly: these values were read off a real eBay
    response. It does NOT mean we confirmed the storefront exists.
    """
    from engine.provenance import Provenance

    prov = Provenance.VERIFIED if provenance == "verified" else Provenance.UNVERIFIED
    return {
        "name": name,
        "url": derive_store_url(name),
        # C11 — declared derived so a consumer can never claim it was observed.
        "url_derived": True,
        "sold_count": int(sold_count),
        # C11 — the label travels WITH the number.
        "sold_count_label": SOLD_COUNT_LABEL,
        "avg_price": round(float(avg_price or 0.0), 2),
        "provenance": prov.value,
        "provenance_label": prov.label,
        "source_name": source_name,
    }


def build_stores(counts: Iterable[tuple], source_name: str = SOURCE_NAME,
                 limit: int = MAX_STORES) -> list[dict]:
    """Turn ``(username, sold_count, avg_price)`` triples into store rows.

    Sorts by observed count desc, de-duplicates usernames case-insensitively
    (eBay usernames are case-insensitive, so ``Store`` and ``store`` are one
    seller), drops unusable names, and never exceeds ``limit`` (C11).
    """
    if not counts:
        return []
    seen: dict[str, dict] = {}
    for entry in counts:
        # Every coercion lives INSIDE the guard. The obvious failure is a
        # 3-char string, which unpacks as a 3-tuple and therefore survives
        # a bare `name, count, avg = entry` — only int()/float() then blows
        # up. A malformed row must be skipped, never raised (C11).
        if isinstance(entry, (str, bytes)):
            continue
        try:
            name, count, avg = entry
            name = normalise_username(name)
            if not name:
                continue
            count_i = int(count or 0)
            avg_f = float(avg or 0.0)
        except (TypeError, ValueError):
            continue
        key = name.lower()
        if key in seen:
            # Merge duplicates — same seller, two spellings.
            existing = seen[key]
            prior = existing["_n"]
            merged_n = prior + count_i
            existing["sold_count"] += count_i
            if avg_f and merged_n:
                # Re-weighted mean, so merging cannot silently skew the price.
                existing["avg_price"] = (
                    (existing["avg_price"] * prior + avg_f * count_i) / merged_n
                )
            existing["_n"] = merged_n
            continue
        row = _row(name, count_i, avg_f, source_name=source_name)
        row["_n"] = count_i or 1
        seen[key] = row

    rows = sorted(seen.values(), key=lambda r: r["sold_count"], reverse=True)
    for r in rows:
        r.pop("_n", None)
        r["avg_price"] = round(r["avg_price"], 2)
    return rows[:limit]


# ---------------------------------------------------------------------------
# Sources — each is "here are the sellers I already have"
# ---------------------------------------------------------------------------

def stores_from_items(items: Iterable[Any], source_name: str = SOURCE_NAME,
                      limit: int = MAX_STORES) -> list[dict]:
    """Aggregate directly from ``EbaySoldItem`` objects."""
    tally: dict[str, list] = {}
    for item in items or []:
        name = normalise_username(getattr(item, "seller", None))
        if not name:
            continue
        price = float(getattr(item, "price", 0.0) or 0.0)
        slot = tally.setdefault(name, [0, 0.0])
        slot[0] += 1
        slot[1] += price
    return build_stores(
        ((n, c, t / c if c else 0.0) for n, (c, t) in tally.items()),
        source_name=source_name, limit=limit,
    )


def stores_from_top_sellers(top_sellers: Iterable[dict],
                            source_name: str = SOURCE_NAME,
                            limit: int = MAX_STORES) -> list[dict]:
    """Normalise the ``EbaySoldData.top_sellers`` dicts into store rows.

    That scraper caps at 5 and emits an internal ``total_price`` accumulator;
    we re-derive the average, drop the accumulator, apply the C11 cap of 4
    and attach the label + provenance it never had.
    """
    counts = []
    for s in top_sellers or []:
        if not isinstance(s, dict):
            continue
        name = s.get("name") or s.get("seller") or ""
        count = int(s.get("sold_count") or 0)
        avg = s.get("avg_price")
        if avg is None:
            total = float(s.get("total_price") or 0.0)
            avg = total / count if count else 0.0
        counts.append((name, count, avg))
    return build_stores(counts, source_name=source_name, limit=limit)


def stores_from_products(products: Iterable[Any],
                         source_name: str = SOURCE_NAME,
                         limit: int = MAX_STORES) -> list[dict]:
    """Aggregate from ``ScrapedProduct`` objects (search-path fallback).

    A plain search response gives us sellers but no sold counts, so every
    row starts at 1 observed listing. Those rows are still ``verified`` —
    we DID read the username — but the small counts are honest about the
    smaller window they came from.
    """
    tally: dict[str, list] = {}
    for p in products or []:
        name = normalise_username(getattr(p, "seller", None))
        if not name:
            continue
        price = float(getattr(p, "price", 0.0) or 0.0)
        slot = tally.setdefault(name, [0, 0.0])
        slot[0] += 1
        slot[1] += price
    return build_stores(
        ((n, c, t / c if c else 0.0) for n, (c, t) in tally.items()),
        source_name=source_name, limit=limit,
    )


def stores_from_demand(demand: Any, limit: int = MAX_STORES) -> list[dict]:
    """Stores carried on a ``DemandData`` — the zero-cost path for Analyze.

    ``DemandData.top_sellers`` is populated by the sold query Analyze and
    URL-hunt already run, so this adds no request of its own.
    """
    top = getattr(demand, "top_sellers", None)
    if top:
        return stores_from_top_sellers(top, limit=limit)
    return []


def stores_from_scan(product: Any, limit: int = MAX_STORES) -> list[dict]:
    """Stores carried on a ``CategoryProduct`` — the zero-cost Hunter path."""
    top = getattr(product, "ebay_stores", None)
    if top:
        # Already built by stores.py upstream — just re-cap it.
        return list(top)[:limit]
    return []


# ---------------------------------------------------------------------------
# Shared discovery entry point
# ---------------------------------------------------------------------------

def discover_stores(query: str, limit: int = MAX_STORES) -> list[dict]:
    """Find the top ``limit`` eBay stores for a query.

    The ONE entry point a feature should reach for when it has no sellers
    already in hand. Tries the sold-listing search (gives real observed
    counts), then a plain search (sellers but no counts).

    Never raises: an analysis must not fail because store discovery did.
    """
    if not query:
        return []
    try:
        from scrapers.ebay_sold import EbaySoldScraper
        sold = EbaySoldScraper().get_sold_data(query)
        rows = stores_from_items(getattr(sold, "items", []) or [], limit=limit)
        if rows:
            return rows
        rows = stores_from_top_sellers(getattr(sold, "top_sellers", []) or [],
                                       limit=limit)
        if rows:
            return rows
    except Exception as e:  # noqa: BLE001 — discovery must never break analysis
        print(f"[WARN] store discovery (sold search) failed for '{query}': {e}")

    try:
        from scrapers.ebay import EbayScraper
        products = EbayScraper().search(query, limit=OBSERVED_WINDOW)
        return stores_from_products(products, limit=limit)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] store discovery (search fallback) failed for '{query}': {e}")
        return []


def resolve_stores(query: str = "", demand: Any = None, products: Iterable[Any] = None,
                   sold_data: Any = None, limit: int = MAX_STORES) -> list[dict]:
    """Best-available stores for a caller, preferring data it ALREADY holds.

    Order matters — free data first, network last:
      1. ``sold_data``  (an EbaySoldScraper result the caller ran anyway)
      2. ``demand``     (DemandData.top_sellers — same query, no new call)
      3. ``products``   (a search result the caller already has)
      4. ``query``      (last resort: spend a request)
    """
    if sold_data is not None:
        rows = stores_from_items(getattr(sold_data, "items", []) or [], limit=limit)
        if not rows:
            rows = stores_from_top_sellers(
                getattr(sold_data, "top_sellers", []) or [], limit=limit)
        if rows:
            return rows

    if demand is not None:
        rows = stores_from_demand(demand, limit=limit)
        if rows:
            return rows

    if products:
        rows = stores_from_products(products, limit=limit)
        if rows:
            return rows

    if query:
        return discover_stores(query, limit=limit)
    return []


# ---------------------------------------------------------------------------
# Provenance helpers for the store block
# ---------------------------------------------------------------------------

def store_provenance_block(stores: Optional[list]) -> dict:
    """The C13 stamp for the store block.

    An empty list is UNVERIFIED — "we found no stores" and "we could not
    look" are both unconfirmed, and neither may be shown as verified.
    """
    from engine.provenance import Provenance

    found = bool(stores)
    prov = Provenance.VERIFIED if found else Provenance.UNVERIFIED
    entry: dict[str, Any] = {"provenance": prov.value, "label": prov.label}
    if found:
        entry["source_name"] = SOURCE_NAME
        entry["method"] = (
            f"aggregated seller.username from eBay sold-listing search; "
            f"top {len(stores)} by observed count, cap {OBSERVED_WINDOW}"
        )
    else:
        entry["reason"] = "no seller usernames returned by the eBay search"
    return entry
