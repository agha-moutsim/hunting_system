"""
Web-search discovery for suppliers that Google Shopping does not index.

WHY THIS EXISTS
---------------
Joybuy is a JD.com-run dropshipper with the most aggressive bot protection we
have met: its search route serves a "Joybuy Risk Control" interstitial that
redirects to /user/risk/pic and hands off to JD's risk handler at
cfe.m.jd.com. Measured 2026-10-10, that challenge is still served to headless
Chromium with playwright-stealth applied, to residential-proxy attempts via
ScrapingBee (datacenter IP -> 403, premium IP -> Risk Control), and to every
direct route. Six attempts, zero results. The site cannot be read by us.

But we do not actually need to read it.

MEASURED 2026-10-10, live, against the live API:

    google_shopping  "<product>"                      0 / 80 Joybuy hits, 3.4s
    google_shopping  "site:joybuy.com <product>"      0 hits, 67.0s   <- engine hangs
    google           "joybuy <product>"               0 hits,  1.9s
    google           "site:joybuy.com <product>"   10 / 10 Joybuy hits, 2.3s

So Joybuy is absent from Google's SHOPPING index entirely, and present in the
ordinary WEB index. The `site:` operator is not the problem I previously
recorded: on the `google` engine it is fast and exact. It is only the
`google_shopping` engine that stalls on it (67s for zero rows), which is why
`serpapi_discovery._site_query` must skip suppliers marked
`skip_site_pass` rather than being allowed to pay that.

The web pass never contacts Joybuy. We read Google's index of Joybuy, so the
Risk Control handler is never involved and there is nothing to block.

WHAT A ROW MAY CLAIM
--------------------
A web result carries a title and a URL for free. A PRICE only when Google chose
to render a rich snippet with a price extension - measured at 2 of 10 results
(20%). So:

  * a price is read ONLY from `rich_snippet.bottom.detected_extensions.price`.
    It is never parsed out of a title, guessed from the category, or carried
    over from a sibling row. An absent price is 0.0, which the rest of the app
    already reads as "not stated" (C1/C13).
  * unpriced rows are still returned. They are a real product at a real URL and
    are worth linking to; they are simply not a price, and
    `supplier_lookup._first_valid` skips anything priced at 0.0, so they can
    never become a "GBP 0.00 supplier" with infinite apparent margin.
  * stock and shipping come from the snippet's own `extensions` wording, which
    travels with the row rather than being assumed (C13).

The honest consequence, stated plainly: this makes Joybuy a LINK-OUT source
today, and a pricing source only for the minority of listings Google has
priced. A Joybuy Dropshipper account with a real product feed is the route to
complete pricing, and this module is the thing it would replace.

Fails closed: no SERPAPI_KEY, no request, no rows.
"""

import os
import re
from urllib.parse import urlparse

from engine.source_type import supplier_type as classify_source
from scrapers.availability import serpapi_item_availability
from scrapers.base import ScrapedProduct
from scrapers.serpapi_discovery import _Budget, _get_json

__all__ = ["discover_web", "joybuy_search_url", "parse_web_results"]


# One call answers the whole question, so the budget is deliberately 1. A
# second call would mean paging, and Google returns at most ten organic rows
# for a `site:` pass anyway - measured 10/10 Joybuy on the first page.
MAX_CALLS = 1

# MEASURED latency for this exact query shape, eight live calls:
#   1.0s  1.2s  1.5s  1.6s  1.9s  2.3s  21.8s  >25s
# Median is under two seconds, but there is a long tail: SerpApi's `google`
# engine on a `site:` pass is sometimes slow, and one call was still pending
# past 25s. The fast majority is worth taking; the tail is not.
#
# 12s therefore collects the typical case and abandons the tail, reporting zero
# rows. That is the correct outcome, not a failure: returning nothing is what
# this module did before it existed, and inventing a row to fill the gap is the
# one thing it must never do. 12s also fits comfortably inside
# hunter.supplier_lookup.LOOKUP_TIMEOUT, so a slow Joybuy call can never starve
# the sources that answer reliably.
#
# The number is actually passed to _get_json. An earlier version of this module
# declared a timeout constant here and never used it, so every call silently
# inherited the 20s shopping timeout instead.
TIMEOUT = 12

_JOYBUY_DOMAINS = ("joybuy.com", "joybuy.co.uk")
_JOYBUY_LABEL = "Joybuy UK"

# Google's titles are truncated with an ellipsis. Left as-is they still read
# fine, but stripping it keeps the matcher's token work honest.
_ELLIPSIS = re.compile(r"\s*[\u2026\u00a0]|\s*\.\.\.\s*$")


def joybuy_search_url(query: str) -> str:
    """The exact SerpApi query this module issues, exposed for tests and logs.

    Kept in one place so the test can assert the shape of the call instead of
    trusting a hand-written copy of it.
    """
    return f"site:{_JOYBUY_DOMAINS[0]} {query}"


def _is_joybuy(url: str) -> bool:
    """True only for a Joybuy host.

    A `site:` pass can still drift - Google occasionally returns a support page
    or a JD corporate result - so the host is re-checked on the way out rather
    than trusting the query to have been honoured.
    """
    host = (urlparse(url).hostname or "").lower().replace("www.", "")
    return any(host == d or host.endswith("." + d) for d in _JOYBUY_DOMAINS)


# A product page carries the JD numeric SKU in its path:
#   m.joybuy.com/dp/100017245073763
#   m.joybuy.com/landingPage/dp/100017205460134
# A `site:` pass also matches the site's SEO content, and for a phrase like
# "cordless drill 18v" that is what Google returns most: measured, the top hits
# were /blog/18v-cordless-combi-drill-guide/ - a buying-guide ARTICLE, not
# anything you can source. Filing that as a supplier product would put a
# non-product in front of the user with a title that reads exactly like a
# product, so the SKU shape is required rather than merely preferred.
_SKU_PATH = re.compile(r"/dp/(\d+)")


def _sku(url: str) -> str:
    """The product SKU from a Joybuy URL, '' when the path is not a product.

    Doubles as the de-duplication key: the same product is served from
    www.joybuy.co.uk and m.joybuy.co.uk, which measured as two separate SERP
    rows. Without the SKU key they would both survive - one product shown
    twice, in a table whose whole purpose is comparing prices.
    """
    m = _SKU_PATH.search(urlparse(url).path or "")
    return m.group(1) if m else ""


def _extensions(item: dict) -> list[str]:
    """The rich snippet's own wording lines, e.g. ["GBP11.99", "In stock",
    "Free delivery"]. Empty when Google rendered no snippet (C1)."""
    snippet = item.get("rich_snippet")
    if not isinstance(snippet, dict):
        return []
    bottom = snippet.get("bottom")
    if not isinstance(bottom, dict):
        return []
    found = bottom.get("extensions")
    if not isinstance(found, list):
        return []
    return [str(x) for x in found if isinstance(x, str) and str(x).strip()]


def _detected_price(item: dict) -> float:
    """The price Google explicitly detected, or 0.0.

    0.0 is the point of this function, not an oversight: on this route most
    results carry no price, and a plausible-looking guess would be worse than
    an honest blank because it would flow straight into a margin calculation.
    Only `detected_extensions.price` is trusted, and only when it is a real
    positive number.
    """
    snippet = item.get("rich_snippet")
    if not isinstance(snippet, dict):
        return 0.0
    bottom = snippet.get("bottom")
    if not isinstance(bottom, dict):
        return 0.0
    detected = bottom.get("detected_extensions")
    if not isinstance(detected, dict):
        return 0.0
    price = detected.get("price")
    if not isinstance(price, (int, float)) or isinstance(price, bool):
        return 0.0
    return float(price) if price > 0 else 0.0


def _wording(lines: list[str], *needles: str) -> str:
    """The first snippet line mentioning any needle, '' when none does."""
    for line in lines:
        low = line.lower()
        if any(n in low for n in needles):
            return line.strip()
    return ""


def parse_web_results(results: list, *, label: str = _JOYBUY_LABEL,
                      delivery_min: int = 7, delivery_max: int = 21) -> list[ScrapedProduct]:
    """Organic results -> ScrapedProduct rows. Pure, so it can be tested
    against recorded API payloads without a network call.

    A result is dropped only when it is not a Joybuy PRODUCT page or has no
    usable title. A missing price is NOT a reason to drop: see the module
    docstring.
    """
    rows: list[ScrapedProduct] = []
    seen: set[str] = set()

    for item in results or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("link", "") or "").strip()
        if not url or not _is_joybuy(url):
            continue
        sku = _sku(url)
        if not sku:
            continue  # blog / category / help page - not something to source
        if sku in seen:
            continue  # same SKU on the www and m hosts is ONE product
        title = _ELLIPSIS.sub("", str(item.get("title", "") or "")).strip()
        if len(title) < 5:
            continue
        seen.add(sku)

        price = _detected_price(item)
        lines = _extensions(item)
        stock = _wording(lines, "stock", "available", "sold out")
        shipping = _wording(lines, "delivery", "shipping", "postage")

        rows.append(ScrapedProduct(
            source=label,
            title=title,
            # 0.0 means "we did not read one". Never a guess (C1/C13).
            price=price,
            url=url,
            delivery_days_min=delivery_min,
            delivery_days_max=delivery_max,
            seller=label,
            store_name=label,
            # C10 - a web index states no condition. "" is "unread", which is
            # not "New".
            condition="",
            # C13 - a real, successfully parsed API response.
            verified=True,
            supplier_type=classify_source(name=label, url=url),
            fetch_method="api",
            **serpapi_item_availability({
                "link": url,
                "stock": stock,
                "shipping": shipping,
            }),
        ))
    return rows


def discover_web(query: str) -> list[ScrapedProduct]:
    """Joybuy rows for `query`, read from Google's web index.

    Never contacts Joybuy, so nothing here can be blocked by its risk control.
    Returns [] when there is no key, no query, no budget or no rows - never a
    fabricated fallback.
    """
    query = str(query or "").strip()
    if not query:
        return []

    api_key = os.getenv("SERPAPI_KEY", "")
    if not api_key:
        print("[WARN] SERPAPI_KEY not set - web supplier discovery returns no rows")
        return []

    budget = _Budget(MAX_CALLS)
    if not budget.spend():
        return []

    data = _get_json(
        {"engine": "google", "q": joybuy_search_url(query),
         "location": "United Kingdom", "gl": "uk", "hl": "en"},
        api_key,
        budget,
        timeout=TIMEOUT,
    )
    if data is None:
        return []

    results = data.get("organic_results")
    if not isinstance(results, list):
        return []
    return parse_web_results(results)