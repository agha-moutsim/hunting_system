"""
C11 — up to 4 real eBay competitor stores per analysis.

Every feature (Analyze, URL-hunt, Deep Search, Bulk, Category Hunter)
surfaces the SAME list, produced by THIS module, from real
``seller.username`` values read off eBay responses.

Two rules from the spec that shape every function here:

  * ``sold_count`` is **listings observed in the search window (cap 50)** —
    it is NOT eBay's sold count. It travels with a human label
    (``sold_count_label``) so no consumer can silently promote it.
  * a ``/str/`` storefront URL is emitted **only when that exact href was
    read off an eBay page** (REGRESSION-007). It used to be derived from the
    username, which conflated two different eBay identifiers and produced
    dead "Store not found" links wearing a ``verified`` stamp. A seller we
    have a username for but never saw a storefront link for gets the
    canonical ``/usr/`` profile instead, marked ``url_kind="seller_profile"``
    and stamped unverified with the reason attached.

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
from urllib.parse import urlparse

from config import EBAY_UK_BASE, STORE_COUNT

# C11 — how many stores any feature may surface.
MAX_STORES = STORE_COUNT

# The window the counts are taken from. Browse API / HTML sold search both
# page at 50; the label says so because the number means nothing without it.
OBSERVED_WINDOW = 50
# eBay bills per call. A rare product would otherwise walk every query rung
# (measured: 15 calls / 67s for one title), so the ladder is bounded. Rungs
# are ordered most-precise-first, so the cap drops the broadest ones - the
# least trustworthy for identity - and never the ones we would prefer.
MAX_LADDER_RUNGS = 8

# C11 — the required human label. Kept in one place so every renderer and
# every export uses identical wording.
SOLD_COUNT_LABEL = f"observed listings (search window, cap {OBSERVED_WINDOW})"

STORE_URL_TEMPLATE = f"{EBAY_UK_BASE}/str/{{slug}}"
SELLER_PROFILE_URL_TEMPLATE = f"{EBAY_UK_BASE}/usr/{{username}}"

SOURCE_NAME = "eBay sold-listing search (conditions:{NEW})"

# Why a row can be unverified even though eBay gave us the username.
PROFILE_NOT_STOREFRONT = (
    "storefront URL not confirmed - showing the seller's eBay profile, which "
    "is not the same thing as their shop"
)

# ---------------------------------------------------------------------------
# Identity: two distinct eBay identifiers, never conflated again
# ---------------------------------------------------------------------------
#
# REGRESSION-007: this module used to build ``ebay.co.uk/str/{username}`` and
# stamp the result ``verified``. Those are two different identifiers:
#
#     seller user ID  -> /usr/{username}   exists for every real account
#     store URL slug  -> /str/{slug}       exists only if the seller set one
#
# eBay derives the slug independently of the username, so ``/str/{username}``
# is usually a dead "Store not found". The old code never looked at the link
# eBay had already rendered on the listing, so it had no way to know whether a
# storefront actually existed and claimed Verified anyway.
#
# The rule now: a ``/str/`` URL is emitted ONLY when we observed that exact
# href on a page eBay served us. Otherwise the row links to ``/usr/``, which
# is canonical for a real username, and says plainly that it is not a
# storefront.

def seller_profile_url(username: str) -> str:
    """Canonical seller-profile URL. Valid for any real eBay username.

    This is the honest fallback: eBay's own canonical form for an account, so
    it resolves whenever the username is real, and it makes no claim about the
    seller owning a storefront.
    """
    name = normalise_username(username)
    return SELLER_PROFILE_URL_TEMPLATE.format(username=name) if name else ""


def store_url_from_observed_slug(slug: str) -> str:
    """Storefront URL for a slug we READ OFF an eBay page.

    Call this only with a slug taken from a link eBay itself rendered. A
    username is not a slug and must never be passed here.
    """
    clean = normalise_username(slug)
    return STORE_URL_TEMPLATE.format(slug=clean) if clean else ""


def is_observed_store_url(url: Any) -> bool:
    """True only for an https ``/str/`` href on eBay's own host.

    The host check is load-bearing: a hostile or scraped-elsewhere value such
    as ``https://evil.example/str/x`` has the right shape but is not something
    eBay served us, so it must never be presented as an observed storefront.
    """
    text = str(url or "").strip()
    if not text.lower().startswith("https://"):
        return False
    if "/str/" not in text:
        return False
    try:
        host = urlparse(text).hostname or ""
    except ValueError:
        return False
    return host == "ebay.co.uk" or host.endswith(".ebay.co.uk")


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
    """Deprecated alias for :func:`seller_profile_url`.

    Kept so older callers and tests keep importing successfully, but it no
    longer builds a storefront: a username is not a store slug.
    """
    return seller_profile_url(username)


def _row(name: str, sold_count: int, avg_price: float,
         source_name: str = SOURCE_NAME,
         observed_store_url: str = "") -> dict:
    """One store row, stamped per C13.

    ``verified`` now means something stricter than it used to: the link on
    this row is a storefront URL we OBSERVED on an eBay page. A row with only
    a seller profile is stamped UNVERIFIED with the reason attached, because
    eBay told us the account exists but not that it has a shop.
    """
    from engine.provenance import Provenance

    observed = observed_store_url if is_observed_store_url(observed_store_url) else ""
    if observed:
        url = observed
        url_kind = "observed"
        derived = False
        prov = Provenance.VERIFIED
        reason = ""
    else:
        url = seller_profile_url(name)
        url_kind = "seller_profile"
        derived = True
        prov = Provenance.UNVERIFIED
        reason = PROFILE_NOT_STOREFRONT

    row = {
        "name": name,
        "url": url,
        # Which of the two eBay identifiers this link is.
        "url_kind": url_kind,
        # C11 - True only when we built the link ourselves from a username.
        "url_derived": derived,
        "sold_count": int(sold_count),
        # C11 - the label travels WITH the number.
        "sold_count_label": SOLD_COUNT_LABEL,
        "avg_price": round(float(avg_price or 0.0), 2),
        "provenance": prov.value,
        "provenance_label": prov.label,
        "source_name": source_name,
    }
    if reason:
        row["provenance_reason"] = reason
    return row


def build_stores(counts: Iterable[tuple], source_name: str = SOURCE_NAME,
                 limit: int = MAX_STORES,
                 observed_store_urls: Optional[dict] = None) -> list[dict]:
    """Turn ``(username, sold_count, avg_price)`` triples into store rows.

    Sorts by observed count desc, de-duplicates usernames case-insensitively
    (eBay usernames are case-insensitive, so ``Store`` and ``store`` are one
    seller), drops unusable names, and never exceeds ``limit`` (C11).

    ``observed_store_urls`` maps a username to a ``/str/`` href that was read
    off an eBay page. Only a seller listed there is shown a storefront link;
    everyone else gets the canonical ``/usr/`` profile.
    """
    if not counts:
        return []
    observed_store_urls = observed_store_urls or {}
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
        row = _row(name, count_i, avg_f, source_name=source_name,
                   observed_store_url=observed_store_urls.get(name, ""))
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
    """Aggregate directly from ``EbaySoldItem`` objects.

    ``item.store_url`` is the storefront href eBay rendered on the listing we
    parsed, or '' when the page showed no store link. Passing it through is
    what lets a row be an observed storefront instead of a guess.
    """
    tally: dict[str, list] = {}
    observed: dict[str, str] = {}
    for item in items or []:
        name = normalise_username(getattr(item, "seller", None))
        if not name:
            continue
        price = float(getattr(item, "price", 0.0) or 0.0)
        slot = tally.setdefault(name, [0, 0.0])
        slot[0] += 1
        slot[1] += price
        seen_url = getattr(item, "store_url", "") or ""
        if name not in observed and is_observed_store_url(seen_url):
            observed[name] = seen_url
    return build_stores(
        ((n, c, t / c if c else 0.0) for n, (c, t) in tally.items()),
        source_name=source_name, limit=limit,
        observed_store_urls=observed,
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
    observed: dict[str, str] = {}
    for s in top_sellers or []:
        if not isinstance(s, dict):
            continue
        name = s.get("name") or s.get("seller") or ""
        # A malformed row must be skipped, never raised (C11) — a scraper
        # dict with sold_count="x" is dropped rather than crashing discovery.
        try:
            count = int(s.get("sold_count") or 0)
        except (TypeError, ValueError):
            continue
        avg = s.get("avg_price")
        try:
            if avg is None:
                total = float(s.get("total_price") or 0.0)
                avg = total / count if count else 0.0
            else:
                avg = float(avg)
        except (TypeError, ValueError):
            continue
        clean = normalise_username(name)
        seen_url = s.get("store_url") or ""
        if clean and clean not in observed and is_observed_store_url(seen_url):
            observed[clean] = seen_url
        counts.append((name, count, avg))
    return build_stores(counts, source_name=source_name, limit=limit,
                        observed_store_urls=observed)


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

def search_stores(query: str, limit: int = MAX_STORES) -> tuple[list[dict], dict]:
    """Find competitor stores, widening BOTH the price band and the query.

    REGRESSION-006: the user saw one competitor store, or none, on every
    analysis. Two compounding causes, both measured against the live Browse
    API rather than reasoned about:

      1. PRICE BAND. `discover_stores` searched inside the user's ACTIVE band
         (default GBP5-35). That band is a SOURCING decision - what you are
         willing to buy - not a statement about who competes with you. A shop
         selling a GBP120 greenhouse competes with the GBP29.99 greenhouse the
         user intends to buy, so filtering competitors by the buyer's own
         budget removed exactly the sellers worth knowing about. Measured:

             "Greenhouse 6ft Polycarbonate"  band 5-35 -> 0 sellers
                                            band 1-100 -> 6 sellers
                                            no band    -> 24 sellers

      2. THE FULL TITLE. eBay matches on all terms, so a 12-word title
         matched nothing:

             "Pasabahce 2 Colorful Cups Saucers Dissolving Skyline Bone
              China 5oz Coffee Tea"            -> 0 items, 0 sellers
             "pasabahce colorful cups saucers" -> 50 items, 24 sellers

    `sort` was ruled out: -relevance and -dateSold return identical counts.

    The ladder therefore widens in a fixed order, always trying the most
    precise rung first:

        exact title + active band      (what we did before, and it often
                                       returned literally nothing)
        exact title + wide band        (competitors outside the buy budget)
        shorter query + wide band      (competitors for a broader product)

    Rungs are MERGED until `limit` distinct sellers are collected, not
    abandoned at the first hit: C11 asks for up to 4 stores, and one seller
    has not answered that. Measured - the Bosch drill returns 1 seller in the
    buying band and 4 once the band is widened, so stopping early would have
    preserved the very bug this fixes.

    Procurement is NOT affected: the ladder is used only to find WHO the
    competitors are. What the user may buy is still governed by the active
    band everywhere else (PR-1/PR-4).

    Returns ``(rows, provenance)``. Whenever a rung other than the first was
    needed, the block is stamped UNVERIFIED with the reason, because we have
    not confirmed those stores sell *this* item. C11 says show real stores;
    C13 says never claim more than we know.

    Never raises - an analysis must not fail because store discovery did.
    """
    from engine.provenance import Provenance

    original = str(query or "").strip()
    if not original:
        return [], {
            "provenance": Provenance.UNVERIFIED.value,
            "label": Provenance.UNVERIFIED.label,
            "reason": "no search text supplied",
            "broadened": False,
        }

    rungs = _store_ladder(original)

    # Merge across rungs rather than stopping at the first hit. C11 asks for
    # UP TO 4 stores; a rung that yields one seller has not answered the
    # question. Measured on real titles:
    #
    #   "Bosch Professional GSB 13 RE 18V Cordless Combi Drill Body Only"
    #       active band 5-35 ->  1 seller,  1 item
    #       wide band 1-500   ->  4 sellers, 42 items
    #
    # Stopping at the first hit would have kept showing 1 store - the exact
    # symptom this ladder exists to fix. So rungs are tried until `limit` is
    # reached or the ladder runs out, and the most precise rungs win any ties.
    merged: list[dict] = []
    seen_names: set[str] = set()
    used_bands: list[tuple[float, float] | None] = []
    used_queries: list[str] = []

    for index, (candidate, band) in enumerate(rungs):
        if len(merged) >= limit:
            break
        # The plain-search fallback is a different SOURCE, not a widening
        # step, so it is tried once (on the most precise rung) rather than on
        # every rung - otherwise a 12-rung ladder would spend 24 eBay calls
        # chasing a source that returns the same sellers anyway.
        rows = _stores_for_single_query(candidate, limit, band=band,
                                        allow_search_fallback=(index == 0))
        if not rows:
            continue
        used_queries.append(candidate)
        used_bands.append(band)
        for row in rows:
            key = str(row.get("name", "")).lower()
            if not key or key in seen_names:
                continue
            seen_names.add(key)
            merged.append(row)

    rows = merged[:limit]

    if not rows:
        return [], {
            "provenance": Provenance.UNVERIFIED.value,
            "label": Provenance.UNVERIFIED.label,
            "reason": (
                f"eBay returned no listings for '{original}' in any price "
                f"range tried, so no competitor stores could be identified"
            ),
            "broadened": True,
            "query_original": original,
        }

    # The stores we show come from the most precise rung that produced any.
    used_query = used_queries[0] if used_queries else original
    used_band = used_bands[0] if used_bands else None

    is_exact = used_query == original
    in_active_band = _is_active_band(used_band)
    broadened = not (is_exact and in_active_band)

    entry: dict[str, Any] = {
        "query_used": used_query,
        "query_original": original,
        "price_band_used": (
            None if used_band is None
            else [round(used_band[0], 2), round(used_band[1], 2)]
        ),
        "broadened": broadened,
    }

    if broadened:
        reasons = []
        if not in_active_band:
            reasons.append(
                f"found outside the active GBP5-35 buying band "
                f"(searched GBP{used_band[0]:g}-GBP{used_band[1]:g})"
                if used_band else "found with no price restriction"
            )
        if not is_exact:
            reasons.append(
                f"eBay matched nothing for the full title, so competitors come "
                f"from the broader search '{used_query}'"
            )
        entry.update({
            "provenance": Provenance.UNVERIFIED.value,
            "label": Provenance.UNVERIFIED.label,
            "reason": (
                "these stores sell the same product outside your buying band, "
                "or a similar product - they are real sellers but not a "
                "confirmed head-to-head match: " + "; ".join(reasons)
            ),
        })
        return rows, entry

    entry.update({
        "provenance": Provenance.VERIFIED.value,
        "label": Provenance.VERIFIED.label,
        "source_name": SOURCE_NAME,
        "method": (
            f"aggregated seller.username from eBay sold-listing search; "
            f"top {len(rows)} by observed count, cap {OBSERVED_WINDOW}"
        ),
    })
    return rows, entry


def _is_active_band(band: tuple[float, float] | None) -> bool:
    """True when `band` is the user's active buying range (or unrestricted)."""
    if band is None:
        return False
    try:
        from engine.price_gate import active_bounds
        lo, hi = active_bounds()
    except Exception:  # noqa: BLE001
        return True
    return abs(band[0] - lo) < 0.01 and abs(band[1] - hi) < 0.01


def _store_ladder(title: str) -> list[tuple[str, tuple[float, float] | None]]:
    """(query, price_band) rungs, most precise first.

    Widen the BAND before the QUERY. That order is deliberate and measured:
    "Greenhouse 6ft Polycarbonate" gains 24 sellers by widening the band alone
    and keeps its exact title, whereas shortening the query on its own gives
    0. A competitor is identified by the product, not by the words we happen
    to search, so keeping the title and losing the price filter is the smaller
    claim to make.

    Capped by `MAX_LADDER_RUNGS` because eBay bills per call and a rare
    product would otherwise walk every rung (measured: 67s and 15 calls for
    one Pasabahce title before the cap). When the cap bites it keeps the exact
    title and the brand-drop rungs, and trims the tail-shortening ladder -
    because a rare BRAND is the other way a title matches nothing
    ("pasabahce 2 colorful cups & saucers" -> 0 items; "colorful cups" -> 49).
    """
    try:
        from engine.price_gate import active_bounds
        lo, hi = active_bounds()
    except Exception:  # noqa: BLE001
        lo, hi = 5.0, 35.0

    try:
        from engine.query_extract import (
            fallback_queries,
            _leading_brand_candidates,
        )
    except Exception:  # noqa: BLE001
        fallback_queries = None
        _leading_brand_candidates = None

    wide = (1.0, 500.0)
    rungs: list[tuple[str, tuple[float, float] | None]] = [(title, (lo, hi))]
    if (lo, hi) != wide:
        rungs.append((title, wide))
        rungs.append((title, None))

    shorten_rungs: list[tuple[str, tuple[float, float] | None]] = []
    if fallback_queries is not None:
        try:
            for shorter in fallback_queries(title):
                shorten_rungs.append((shorter, wide))
                shorten_rungs.append((shorter, None))
        except Exception as e:  # noqa: BLE001 - never break on extraction bugs
            print(f"[WARN] query extraction failed for '{title}': {e}")

    brand_rungs: list[tuple[str, tuple[float, float] | None]] = []
    if _leading_brand_candidates is not None:
        try:
            for shorter in _leading_brand_candidates(title):
                brand_rungs.append((shorter, wide))
                brand_rungs.append((shorter, None))
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] brand-drop extraction failed for '{title}': {e}")

    # Drop a shortening rung that repeats a brand-drop rung, so the budget is
    # not spent twice on the same query.
    brand_queries = {q.lower() for q, _b in brand_rungs}
    shorten_rungs = [
        (q, b) for q, b in shorten_rungs if q.lower() not in brand_queries
    ]

    ladder = rungs + brand_rungs + shorten_rungs
    return ladder[:MAX_LADDER_RUNGS]


def _stores_for_single_query(
    query: str,
    limit: int = MAX_STORES,
    band: tuple[float, float] | None = None,
    allow_search_fallback: bool = True,
) -> list[dict]:
    """Stores for exactly one query inside one price band.

    `band=None` means "no price restriction", which is a different request
    from any band, so the two search paths each honour it explicitly rather
    than inheriting the active bounds.

    `allow_search_fallback=False` skips the plain-search second try. The
    ladder widens the band and the query, and doing a second source on every
    rung would double the call count for no new information.
    """
    if not query:
        return []
    try:
        from scrapers.ebay_sold import EbaySoldScraper
        sold = EbaySoldScraper().get_sold_data(query, price_band=band)
        rows = stores_from_items(getattr(sold, "items", []) or [], limit=limit)
        if rows:
            return rows
        rows = stores_from_top_sellers(getattr(sold, "top_sellers", []) or [],
                                       limit=limit)
        if rows:
            return rows
    except Exception as e:  # noqa: BLE001 - discovery must never break analysis
        print(f"[WARN] store discovery (sold search) failed for '{query}': {e}")

    if not allow_search_fallback:
        return []

    try:
        from scrapers.ebay import EbayScraper
        products = EbayScraper().search(query, limit=OBSERVED_WINDOW,
                                        price_band=band)
        return stores_from_products(products, limit=limit)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] store discovery (search fallback) failed for '{query}': {e}")
        return []


def discover_stores(query: str, limit: int = MAX_STORES) -> list[dict]:
    """Stores for a query, with the ladder applied. Rows only.

    Kept as the row-only interface for callers that predate
    `search_stores`; new code should call `search_stores` so it can also
    report whether the search had to be broadened.
    """
    rows, _provenance = search_stores(query, limit=limit)
    return rows


def annotate_store_checks(rows: list[dict], *, verify: bool = True) -> list[dict]:
    """REGRESSION-007: check each OBSERVED storefront and record the verdict.

    Identity (Phase 2) stopped fabricating ``/str/`` links. This asks the
    question that actually matters: does the shop exist? Measured 2026-10-10
    over eight stores the system had been showing as ``Verified`` — four came
    back HTTP 410, i.e. eBay has no shop at that slug.

    A row that turns out to be dead is demoted to UNVERIFIED and keeps its
    reason. It is NOT dropped: "this seller competes with you but has no
    storefront" is a fact worth showing, and dropping it would quietly shrink
    a list the user can see the reason for.

    A row we could not check (``unavailable``) keeps whatever provenance it
    had — a blocked request is not evidence of absence (C13).

    Costs at most ``verify.MAX_CHECKS`` calls per process; past that every
    row reports ``unavailable`` and nothing is guessed.
    """
    if not rows or not verify:
        return rows

    from engine.verify import StoreCheck, verify_store_url

    for row in rows:
        # Only an observed storefront can be wrong in this way. A seller
        # profile link was never claiming to be a shop.
        if row.get("url_kind") != "observed":
            continue
        try:
            result = verify_store_url(row.get("url", ""))
        except Exception as e:  # noqa: BLE001 - never break discovery
            row["store_check"] = "unavailable"
            row["store_check_reason"] = f"check could not run: {type(e).__name__}"
            continue

        row["store_check"] = result.status.value
        row["store_check_reason"] = result.reason
        if result.status is StoreCheck.NOT_FOUND:
            from engine.provenance import Provenance

            row["provenance"] = Provenance.UNVERIFIED.value
            row["provenance_label"] = Provenance.UNVERIFIED.label
            row["provenance_reason"] = (
                "eBay reports no storefront at this URL - the seller account "
                "is real but the shop is not there"
            )
    return rows


def resolve_stores(query: str = "", demand: Any = None, products: Iterable[Any] = None,
                   sold_data: Any = None, limit: int = MAX_STORES,
                   provenance: Optional[dict] = None) -> list[dict]:
    """Best-available stores for a caller, preferring data it ALREADY holds.

    Order matters — free data first, network last:
      1. ``sold_data``  (an EbaySoldScraper result the caller ran anyway)
      2. ``demand``     (DemandData.top_sellers — same query, no new call)
      3. ``products``   (a search result the caller already has)
      4. ``query``      (last resort: spend a request)

    When rung 4 is used, `provenance` is filled with the ladder's own
    provenance (including whether the search had to widen), so the caller can
    stamp the block honestly instead of claiming "verified" for a broadened
    search. Free-data rungs (1-3) never widen, so they are verified as-is.

    Whatever the rung, every returned row has been through
    :func:`annotate_store_checks`, so an observed storefront that eBay denies
    is demoted rather than presented as a store.
    """
    if provenance is not None:
        provenance.clear()

    if sold_data is not None:
        rows = stores_from_items(getattr(sold_data, "items", []) or [], limit=limit)
        if not rows:
            rows = stores_from_top_sellers(
                getattr(sold_data, "top_sellers", []) or [], limit=limit)
        if rows:
            return annotate_store_checks(rows)

    if demand is not None:
        rows = stores_from_demand(demand, limit=limit)
        if rows:
            return annotate_store_checks(rows)

    if products:
        rows = stores_from_products(products, limit=limit)
        if rows:
            return annotate_store_checks(rows)

    if query:
        rows, ladder = search_stores(query, limit=limit)
        if provenance is not None:
            provenance.update(ladder)
        return annotate_store_checks(rows)
    return []


# ---------------------------------------------------------------------------
# Provenance helpers for the store block
# ---------------------------------------------------------------------------

def store_provenance_block(stores: Optional[list], ladder: Optional[dict] = None) -> dict:
    """The C13 stamp for the store block.

    An empty list is UNVERIFIED — "we found no stores" and "we could not
    look" are both unconfirmed, and neither may be shown as verified.

    REGRESSION-006: a SHORT list is also reported, because C11 asks for up to
    MAX_STORES and returning one is a different fact from returning four.
    The count that came back, the reason, and whether the search had to widen
    all travel together - a single store stamped "Verified, top 1 by
    observed count" reads exactly like a healthy result, and it is the
    failure the user reported.
    """
    from engine.provenance import Provenance

    found = bool(stores)
    short = bool(found) and len(stores) < MAX_STORES

    # REGRESSION-007: the block may never be stamped stronger than the rows it
    # describes. A live Phase 7 run showed the block reading `verified` while
    # every row beneath it read `unverified` — four real SELLERS, but not one
    # confirmed STOREFRONT. Counting sellers is not confirming shops, so a
    # block with no confirmed storefront is unverified whatever the count.
    unconfirmed = found and any(
        r.get("provenance") != Provenance.VERIFIED.value for r in stores
    )

    prov = (Provenance.VERIFIED
            if (found and not short and not unconfirmed)
            else Provenance.UNVERIFIED)
    entry: dict[str, Any] = {"provenance": prov.value, "label": prov.label}

    if found:
        confirmed = sum(
            1 for r in stores if r.get("provenance") == Provenance.VERIFIED.value
        )
        entry["confirmed_storefronts"] = confirmed
        entry["store_count"] = len(stores)
        entry["max_stores"] = MAX_STORES
        if confirmed:
            entry["source_name"] = SOURCE_NAME
            entry["method"] = (
                f"aggregated seller.username from eBay sold-listing search; "
                f"top {len(stores)} by observed count, cap {OBSERVED_WINDOW}"
            )
        else:
            entry["reason"] = (
                f"{len(stores)} eBay seller account(s) were identified, but no "
                f"storefront link was confirmed on the listing pages — these "
                f"link to seller profiles, which are not shops"
            )
    else:
        entry["store_count"] = 0
        entry["max_stores"] = MAX_STORES
        entry["confirmed_storefronts"] = 0
        entry["reason"] = (ladder or {}).get(
            "reason", "no seller usernames returned by the eBay search"
        )

    if short:
        # Both facts matter and neither replaces the other: a thin block AND
        # an unconfirmed storefront are different problems, so the reasons
        # are joined rather than one overwriting the other.
        thin_reason = (
            f"only {len(stores)} of {MAX_STORES} competitor stores were "
            f"identified - eBay returned very few listings for this product, "
            f"so this is a thin competitor picture rather than a full one"
        )
        prior = entry.get("reason", "").strip()
        entry["reason"] = f"{prior} {thin_reason}".strip() if prior else thin_reason

    # A widened search is never a confirmed head-to-head set (C13).
    if ladder:
        if ladder.get("broadened"):
            entry["provenance"] = Provenance.UNVERIFIED.value
            entry["label"] = Provenance.UNVERIFIED.label
            entry["broadened"] = True
            entry.setdefault("reason", ladder.get("reason", ""))
        if ladder.get("query_used"):
            entry["query_used"] = ladder["query_used"]
        if ladder.get("price_band_used") is not None:
            entry["price_band_used"] = ladder["price_band_used"]

    return entry
