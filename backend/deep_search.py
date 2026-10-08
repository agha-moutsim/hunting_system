"""Deep product research module for eBay UK reseller tool.

Combines DuckDuckGo web search (no API key required) with Ollama LLM
to research products across the web and generate actionable reselling insights.
"""

import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, List, Optional
from urllib.parse import urlparse, quote_plus

import requests
from bs4 import BeautifulSoup

from engine.match import (
    THRESHOLD_UNVERIFIED,
    filter_matches,
    image_hash_for,
    score_candidates,
)
from engine.price_gate import (
    band_label, excluded_note, filter_dicts, in_band,
)
from engine.provenance import Provenance
from engine.source_type import supplier_type as classify_source
from scrapers.availability import parse_stock_text, parse_shipping_text

# The Ollama URL and model are still read locally here (pre-existing), but the
# timeout is NOT: it lives in config.OLLAMA_TIMEOUT_S so all four call sites
# share one value, instead of the four separate `45.0` literals that had
# drifted apart. See the note on that constant before changing it.
from config import OLLAMA_TIMEOUT_S

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# A1.4 â€” budgets the run owns, below the route's FULL_TIMEOUT_S (120 s).
#
# The run happens on a worker thread that asyncio.wait_for ABANDONS when the
# route's budget expires: a thread cannot be cancelled, so an overrun does not
# merely cost time, it throws away every page already fetched and the route
# answers with an all-zero object. Two reservations make the run finish first.
#
# HANDOFF_RESERVE_S covers the gap between "this function stopped" and "the
# route has the payload" â€” one worst-case step of overshoot (a single web
# search may wait its full 30 s) plus serialising the result.
# SUPPLIER_STAGE_S is held back from the earlier stages so discovery,
# verification and image gating are never the part that runs out of road.
HANDOFF_RESERVE_S = 35.0
SUPPLIER_STAGE_S = 20.0

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _parse_llm_money(value) -> float | None:
    """Extract a numeric GBP figure from LLM output ('Â£12.99', 12.99, '12.99')."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        m = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
        if m:
            return float(m.group())
    return None


def _llm_price_range_in_band(text: str) -> bool:
    """True when EVERY figure in an LLM range string sits inside the band.

    The string looks like 'Â£5.99 - Â£12.99 (avg Â£8.50)' â€” one out-of-band
    figure makes the whole string unusable (PR-1: no figure shown out of band).
    """
    figures = [_parse_llm_money(m) for m in re.findall(r"Â£\s*\d+(?:\.\d+)?", text)]
    figures = [f for f in figures if f is not None]
    if not figures:
        # No Â£ markers â€” try every bare number, but only if there are 2+ (a range)
        bare = [_parse_llm_money(m) for m in re.findall(r"\d+(?:\.\d+)?", text)]
        bare = [f for f in bare if f is not None]
        figures = bare if len(bare) >= 2 else []
    if not figures:
        return False  # unparseable string â€” never ship an unverified figure
    return all(in_band(f) for f in figures)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TopSeller:
    name: str
    url: str
    price: str


@dataclass
class SupplierInfo:
    name: str
    price: float
    url: str
    supplier_type: str = ""  # wholesaler / retailer / dropshipper
    delivery_days: str = ""
    notes: str = ""


@dataclass
class DeepSearchResult:
    product_name: str = ""
    product_category: str = ""
    ebay_items_sold_month: str = ""
    ebay_top_sellers: List[dict] = field(default_factory=list)
    ebay_price_range: str = ""
    ebay_avg_price: float = 0.0
    ebay_price_min: float = 0.0
    ebay_price_max: float = 0.0
    ebay_price_median: float = 0.0
    ebay_total_sold_30d: int = 0
    # None = unknown (no parseable sale dates) â€” never an estimate (C1/C4).
    ebay_total_sold_7d: Optional[int] = None
    # C10 â€” set ONLY when real New-filtered eBay items backed this result.
    # '' = unknown, so the Condition row reports Unverified, never "New".
    ebay_condition: str = ""
    suppliers: List[dict] = field(default_factory=list)  # [{name, price, url, type, delivery}]
    best_supplier_price: float = 0.0
    profit: float = 0.0
    margin: float = 0.0
    verdict: str = ""  # PASS / FAIL / PENDING
    filters_passed: List[dict] = field(default_factory=list)
    competition_level: str = ""
    profit_potential: str = ""
    delivery_info: str = ""
    notes: str = ""
    sources: List[str] = field(default_factory=list)
    raw_analysis: str = ""
    # C13 â€” per-field origin: {field: {provenance, source_url, method}}.
    # Consumed by the JSON/CSV exporters so every row says where it came from.
    field_provenance: dict = field(default_factory=dict)
    # C11 â€” up to 4 REAL eBay competitor stores, built by engine.stores from
    # the same sold query this run already made. Never LLM-supplied.
    ebay_stores: List[dict] = field(default_factory=list)
    ebay_stores_provenance: dict = field(default_factory=dict)

    def attach_stores(self, sold_data: Any = None, demand: Any = None,
                      products: Any = None, query: str = "") -> None:
        """Populate the C11 store block, preferring data we already fetched."""
        from engine.stores import resolve_stores, store_provenance_block
        ladder: dict = {}
        try:
            # Network-last: sold_data/demand/products cost nothing extra.
            stores = resolve_stores(sold_data=sold_data, demand=demand,
                                    products=products, query=query,
                                    provenance=ladder)
        except Exception as e:  # noqa: BLE001 â€” stores never break an analysis
            print(f"[WARN] store discovery failed: {e}")
            stores = []
        self.ebay_stores = stores
        self.ebay_stores_provenance = store_provenance_block(stores, ladder)

    def set_fact_provenance(self, name: str, provenance: Provenance,
                            source_url: str = "", method: str = "",
                            reason: str = "", source_name: str = "") -> None:
        """Record where one factual field's value came from (C13)."""
        entry = {"provenance": provenance.value, "label": provenance.label}
        if source_url:
            entry["source_url"] = source_url
        if method:
            entry["method"] = method
        if reason:
            entry["reason"] = reason
        if source_name:
            entry["source_name"] = source_name
        self.field_provenance[name] = entry

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        lines = [
            f"Product: {self.product_name}",
            f"Category: {self.product_category}",
            f"eBay UK monthly sales: {self.ebay_items_sold_month}",
            f"eBay price range: {self.ebay_price_range}",
            f"eBay avg price: Â£{self.ebay_avg_price:.2f}",
            f"Suppliers found: {len(self.suppliers)}",
        ]
        for s in self.suppliers:
            lines.append(f"  - {s.get('name', 'N/A')} | Â£{s.get('price', 0):.2f} | {s.get('supplier_type', '')} | {s.get('url', '')}")
        lines.append(f"Best supplier cost: Â£{self.best_supplier_price:.2f}")
        lines.append(f"Profit: Â£{self.profit:.2f} | Margin: {self.margin:.1f}%")
        lines.append(f"Verdict: {self.verdict}")
        lines.append(f"Competition: {self.competition_level}")
        lines.append(f"Profit potential: {self.profit_potential}")
        if self.notes:
            lines.append(f"Notes: {self.notes}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ollama LLM
# ---------------------------------------------------------------------------

def _ollama_generate(
    prompt: str, system: str = "", timeout: float = OLLAMA_TIMEOUT_S
) -> str:
    """Send a prompt to the local Ollama API and return the generated text."""
    url = f"{OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {
            "num_predict": 800,
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. "
            "Make sure Ollama is running (ollama serve)."
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(f"Ollama request timed out after {timeout:.0f} seconds.")
    except Exception as exc:
        raise RuntimeError(f"Ollama request failed: {exc}")


# ---------------------------------------------------------------------------
# Web search via DuckDuckGo HTML
# ---------------------------------------------------------------------------

def _web_search(query: str, num_results: int = 8) -> List[dict]:
    """Search DuckDuckGo (HTML endpoint, no API key) and return result dicts."""
    url = "https://html.duckduckgo.com/html/"
    params = {"q": query, "kl": "uk-en"}
    results: List[dict] = []

    try:
        resp = requests.post(url, data=params, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return results

    soup = BeautifulSoup(resp.text, "html.parser")

    for link in soup.select("a.result__a")[:num_results]:
        title = link.get_text(strip=True)
        href = link.get("href", "")
        snippet_el = link.find_parent("div", class_="result")
        snippet = ""
        if snippet_el:
            snippet_tag = snippet_el.select_one(".result__snippet")
            if snippet_tag:
                snippet = snippet_tag.get_text(strip=True)
        results.append({
            "title": title,
            "url": href,
            "snippet": snippet,
        })

    return results


# ---------------------------------------------------------------------------
# Page text extraction
# ---------------------------------------------------------------------------

def _fetch_page_text(url: str, max_chars: int = 3000) -> str:
    """Fetch a web page, strip non-content elements, return cleaned text."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()

    for tag in soup.find_all(
        ["header", "footer", "nav", "aside", "form", "button", "input"]
    ):
        tag.decompose()

    for tag in soup.find_all(class_=re.compile(r"(sidebar|menu|cookie|popup)", re.I)):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines)

    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"

    return text


# ---------------------------------------------------------------------------
# Supplier candidate verification (C12 / C13 â€” verify or drop)
# ---------------------------------------------------------------------------

_MAX_VERIFIED_SUPPLIERS = 7  # C12: never pad past what we could confirm


def _page_availability(html: str, url: str) -> dict:
    """Stock + shipping read off a fetched supplier page.

    C13: every value here is whatever the page actually said, and the URL
    is the receipt. When the page says nothing we leave the fields empty â€”
    `shipping_cost` stays 0.0 (unknown), never a plausible-looking number.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    in_stock, stock_raw = parse_stock_text(text)
    shipping_cost, shipping_days, shipping_raw = parse_shipping_text(text)
    if not stock_raw and not shipping_raw:
        return {}
    return {
        "in_stock": in_stock,
        "stock_raw": stock_raw,
        "availability_url": url,
        "shipping_cost": shipping_cost,
        "shipping_days": shipping_days,
        "shipping_raw": shipping_raw,
    }


def _reference_image_hash(sold_data) -> int | None:
    """C14's reference side: the pHash of a real eBay sold listing.

    Deep Search works from the sold-listing window rather than a single
    product page, so those listings ARE the reference. Returns None when
    there is no sold data or no readable image â€” the image signal then
    simply does not apply and scoring stays text-only, because a substitute
    image would be a guess (C1/C13).
    """
    for item in list(getattr(sold_data, "items", None) or [])[:3]:
        hashed = image_hash_for(getattr(item, "image_url", None))
        if hashed is not None:
            return hashed
    return None


def _gate_suppliers(
    rows: list,
    reference_title: str,
    *,
    brand: str = "",
    ebay_price: float = 0.0,
    ebay_image_hash: int | None = None,
    deadline: float | None = None,
) -> list:
    """Score every supplier row against the eBay title and keep what passed.

    C14 makes matching deterministic: `score_candidates` computes
    `match_score` (never a constant, never the LLM's confidence) and
    C12 admits a row only when it cleared the threshold - so anything the
    matcher calls "no confirmed match" is dropped rather than displayed.
    Rows between the unverified and verified floors survive but carry
    `match_tier == "unverified"`, and the caller must label them as such.

    C14's image phash applies "when both images exist". Without a reference
    hash no image is downloaded at all; with one, each row's image is hashed
    once and cached on the row, and an image that cannot be read stays None
    so the score loses that component rather than gaining a made-up one.
    """
    if not rows or not reference_title:
        return rows
    if ebay_image_hash is not None:
        for row in rows:
            # A1.4 â€” each fetch may wait its full 5 s, so the tail of a long
            # row list is exactly what pushes the run past the route. Stop
            # hashing and score the rest on title and price alone; every
            # row still says which tier it reached (C14), so the score
            # loses a component rather than gaining a guessed one.
            if deadline is not None and time.monotonic() >= deadline:
                print("[INFO] supplier image matching stopped at the time budget "
                      "â€” remaining rows scored without an image")
                break
            if isinstance(row, dict) and row.get("image_hash") is None:
                row["image_hash"] = image_hash_for(row.get("image_url"))
    scored = score_candidates(
        reference_title, rows, brand=brand, ebay_price=ebay_price,
        ebay_image_hash=ebay_image_hash,
    )
    kept = filter_matches(scored, THRESHOLD_UNVERIFIED)
    dropped = len(scored) - len(kept)
    if dropped:
        print(f"[INFO] {dropped} supplier row(s) below match threshold - dropped (C14)")
    # C12 â€” the ceiling, applied AFTER the gate so the survivors are the
    # strongest matches rather than the first ones we happened to collect.
    from config import MAX_SUPPLIERS
    if len(kept) > MAX_SUPPLIERS:
        print(f"[INFO] {len(kept)} supplier row(s) past the C12 cap - keeping top {MAX_SUPPLIERS}")
        kept = kept[:MAX_SUPPLIERS]
    return kept


def _extract_title(html: str) -> str:
    """Page title, preferring og:title â€” the product name, not the site name."""
    soup = BeautifulSoup(html, "html.parser")
    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        return og["content"].strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.select_one("h1")
    return h1.get_text(strip=True) if h1 else ""


def _extract_price(html: str) -> float:
    """A price read off the page, or 0.0 when none is present.

    Looks at JSON-LD first (structured, reliable) then falls back to the
    first Â£-prefixed amount in visible text. 0.0 means NOT CONFIRMED â€”
    the caller drops the row rather than showing a guess (C1).
    """
    # JSON-LD product blocks
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select('script[type="application/ld+json"]'):
        raw = tag.string or ""
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            offers = node.get("offers")
            candidates = offers if isinstance(offers, list) else [offers]
            for offer in candidates:
                if not isinstance(offer, dict):
                    continue
                price = offer.get("price") or offer.get("lowPrice")
                if price is None:
                    continue
                try:
                    val = float(str(price).replace(",", "").replace("Â£", ""))
                except (TypeError, ValueError):
                    continue
                if val > 0:
                    return val
            if node.get("price") is not None:
                try:
                    val = float(str(node["price"]).replace(",", "").replace("Â£", ""))
                    if val > 0:
                        return val
                except (TypeError, ValueError):
                    pass

    # Visible-text fallback: first Â£ amount inside a plausible retail range.
    for match in re.finditer(r"Â£\s*([0-9]+(?:\.[0-9]{1,2})?)", soup.get_text(" ")):
        try:
            val = float(match.group(1))
        except ValueError:
            continue
        if 0.5 <= val <= 5000:
            return val
    return 0.0


def _verify_supplier_candidates(query: str, candidates: list,
                                deadline: float | None = None) -> list:
    """Fetch each candidate URL and keep ONLY what it confirms.

    C13: the LLM may name a URL, but the price, title, link and supplier
    type written into the result all come from the page itself. Anything
    that cannot be fetched or parsed is dropped â€” we never show a supplier
    row we did not read off a live page.

    `deadline` (A1.4) bounds the loop: each fetch may take its full 15 s and
    a candidate that FAILS does not count toward the cap below, so N dead
    URLs used to cost N Ã— 15 s on top of everything already spent. A URL we
    never reached is dropped for the same reason any other one is â€” it was
    not confirmed.
    """
    verified_rows: list = []
    seen_urls: set = set()

    for cand in candidates:
        if len(verified_rows) >= _MAX_VERIFIED_SUPPLIERS:
            break
        if deadline is not None and time.monotonic() >= deadline:
            print("[INFO] supplier verification stopped at the time budget "
                  "â€” remaining candidates never fetched")
            break
        if not isinstance(cand, dict):
            continue
        url = str(cand.get("url", "")).strip()
        if not url.startswith("http") or url in seen_urls:
            continue
        seen_urls.add(url)

        try:
            resp = requests.get(url, headers=_HEADERS, timeout=15)
            resp.raise_for_status()
            html = resp.text
        except requests.RequestException:
            continue  # unverifiable -> dropped, never shown

        price = _extract_price(html)
        title = _extract_title(html)
        if price <= 0 or not title:
            continue  # confirm nothing usable -> drop (C1/C12)

        host = (urlparse(url).hostname or "").replace("www.", "")
        verified_rows.append({
            "name": host,
            "full_name": host,
            "price": price,
            "url": url,
            "supplier_type": classify_source(name=host, url=url),
            "delivery_days": "",
            "product_title": title,
            "notes": "Retrieved and priced from the live product page.",
            # C13 â€” provenance travels with the row.
            "provenance": Provenance.VERIFIED.value,
            "provenance_label": Provenance.VERIFIED.label,
            "source_url": url,
            "source_name": host,
            "match_basis": cand.get("why", "") or "candidate URL confirmed by fetch",
            # P4 â€” stock/shipping as the page stated them. Absent text means
            # unknown; the keys are still present so consumers never guess.
            **_page_availability(html, url),
        })

    return verified_rows


def _discover_approved_suppliers(query: str) -> list[dict]:
    """P4 â€” SerpApi Google Shopping rows for the 7 approved suppliers.

    Primary discovery. SerpApi already hands us the title, price and stock
    read off the live listing, so these rows need no second fetch; they are
    reshaped to the same dict `_verify_supplier_candidates` builds so the
    matcher downstream scores both sources identically.

    Fails closed: no SERPAPI_KEY, a transport error or an empty result all
    produce [] and the analysis simply carries fewer suppliers (C12).
    """
    try:
        from scrapers.serpapi_discovery import discover
        rows = discover(str(query or "").strip())
    except Exception as e:
        print(f"[WARN] supplier discovery failed: {e}")
        return []

    out: list[dict] = []
    for product in rows:
        if not product or not product.url or not product.title:
            continue
        cfg_type = product.supplier_type
        delivery = ""
        lo, hi = product.delivery_days_min, product.delivery_days_max
        if lo and hi:
            delivery = f"{lo}-{hi} days"
        elif lo or hi:
            delivery = f"{int(lo or hi)} days"
        out.append({
            "name": product.source,
            "full_name": product.source,
            "price": float(product.price or 0.0),
            "url": product.url,
            "supplier_type": cfg_type,
            "delivery_days": delivery,
            "product_title": product.title,
            "notes": "Price and title read from the live Google Shopping listing.",
            # C13 â€” provenance travels with the row. Every value here came
            # off a real listing, so it is verified; nothing is a guess.
            "provenance": Provenance.VERIFIED.value,
            "provenance_label": Provenance.VERIFIED.label,
            "source_url": product.url,
            "source_name": product.source,
            "match_basis": "Google Shopping listing",
            "image_url": product.image_url or None,
            # C14 â€” pHash is computed only when both images exist; a caller
            # that has none leaves it None, never a made-up hash.
            "image_hash": None,
            # P4 â€” stock/shipping as the source stated them; absent stays
            # unknown, never defaulted.
            "in_stock": product.in_stock or "",
            "stock_raw": product.stock_raw or "",
            "shipping_cost": float(product.shipping_cost or 0.0),
            "shipping_days": int(product.shipping_days or 0),
            "shipping_raw": product.shipping_raw or "",
        })
    return out


# ---------------------------------------------------------------------------
# Main deep search
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a UK eBay reselling research assistant. You are given raw search
results and page extracts about a product. Analyse the data and return a
JSON object (all prices in GBP Â£).

You produce ANALYSIS, never facts. You will NOT be asked for seller names,
seller URLs, supplier names, supplier prices or supplier links â€” the system
retrieves those from real sources and verifies them. Do not invent any.

{
  "product_name": "string",
  "product_category": "string",
  "brand_name": "<brand/manufacturer named in the product data, else empty string>",
  "ebay_items_sold_month": "your ESTIMATE of items sold per month on eBay UK, e.g. '500-1000'",
  "ebay_price_range": "Â£low - Â£high (avg Â£avg)",
  "ebay_avg_price": 15.99,
  "supplier_candidates": [
    {
      "url": "https://exact-product-page-url-if-the-supplied-data-contains-one",
      "why": "one line: why this page is likely the same product"
    }
  ],
  "competition_level": "low | medium | high",
  "profit_potential": "low | medium | high",
  "delivery_info": "shipping/lead time notes",
  "notes": "any extra useful context for a reseller"
}

Rules:
- All prices MUST be in GBP (Â£).
- `supplier_candidates` is a list of CANDIDATE URLs you saw in the supplied
  data. Only include a URL that literally appeared in the data. If you have
  none, return an empty list. The system will fetch and verify each one;
  anything it cannot confirm is DISCARDED, so a guessed URL is wasted work.
- NEVER return a supplier name, supplier price, seller name or seller URL.
  Those come from the retrieval layer, not from you.
- brand_name must be a real brand explicitly named in the data â€” empty string
  when the product is generic/unknown (never guess).
- Label your own numbers as estimates: ebay_items_sold_month, ebay_price_range
  and ebay_avg_price are ESTIMATES unless the supplied data states them.
- If data is uncertain, say so in notes.
- Return ONLY valid JSON, no markdown fences, no commentary.
- ebay_avg_price should be a number (not a string).
"""


def _stamp_provenance(result: "DeepSearchResult") -> None:
    """Write the C13 per-field stamps onto a DeepSearchResult.

    Called by _publish() as well as at the end of a complete run. A run the
    route cut off has to hand back stamps matching what it ACTUALLY fetched:
    build_provenance_block falls back to "no data retrieved" for any field
    never stamped, which would be a lie about data we are holding.
    """
    if result.ebay_total_sold_30d or result.ebay_top_sellers:
        result.set_fact_provenance(
            "ebay_total_sold_30d", Provenance.VERIFIED,
            source_name="eBay Browse API (conditions:{NEW})"
        )
        result.set_fact_provenance(
            "ebay_top_sellers", Provenance.VERIFIED,
            source_name="eBay Browse API (conditions:{NEW})"
        )
        result.set_fact_provenance("ebay_avg_price", Provenance.VERIFIED)
        result.set_fact_provenance("ebay_condition", Provenance.VERIFIED)
    else:
        for name in ("ebay_total_sold_30d", "ebay_top_sellers", "ebay_avg_price",
                     "ebay_price_range", "ebay_items_sold_month"):
            result.set_fact_provenance(name, Provenance.UNVERIFIED,
                                       reason="no eBay sold data retrieved")
    for sup in result.suppliers:
        sup.setdefault("provenance", Provenance.VERIFIED.value)
    if result.suppliers:
        result.set_fact_provenance("suppliers", Provenance.VERIFIED,
                                   source_name="live product pages (fetched)")
    else:
        result.set_fact_provenance("suppliers", Provenance.UNVERIFIED,
                                   reason="no supplier page could be confirmed")
    for name in ("competition_level", "profit_potential", "delivery_info",
                 "notes", "product_category"):
        result.set_fact_provenance(name, Provenance.AI_INSIGHT,
                                   method="LLM analysis of retrieved pages")

    # C11/C13 â€” the store block's own stamp rides into the fields map too,
    # so an export consumer reading `provenance.fields` sees stores without
    # needing a second top-level key.
    if result.ebay_stores_provenance:
        result.field_provenance.setdefault("ebay_stores", dict(result.ebay_stores_provenance))


def deep_search_product(
    query: str,
    budget_s: float | None = None,
    sink: dict | None = None,
) -> DeepSearchResult:
    """Research a product across eBay UK and the wider web.

    Runs multiple targeted searches, fetches page content, sends
    everything to the local Ollama LLM, and returns a structured
    DeepSearchResult.

    A1.4 â€” `budget_s` is the ROUTE's budget (api/deep_search.FULL_TIMEOUT_S).
    The run reserves HANDOFF_RESERVE_S of it for handing the result back and
    stops every stage after the eBay query at that line, so it returns what
    it found instead of being abandoned mid-flight and discarded. `sink`, when
    given, is the caller's dict: each stage stamps and publishes there as it
    goes, so a run the route DOES cut off still leaves its completed work
    reachable for the partial response.
    """
    _start = time.monotonic()
    _deadline = (_start + budget_s - HANDOFF_RESERVE_S) if budget_s is not None else None
    # The search, page fetch and model must be finished SUPPLIER_STAGE_S
    # before the deadline, so the supplier stage keeps its own window.
    _prestop = (_deadline - SUPPLIER_STAGE_S) if _deadline is not None else None
    _skipped: List[str] = []

    def _out_of_time(stop: float | None = None) -> bool:
        if _deadline is None:
            return False
        return time.monotonic() >= (stop if stop is not None else _deadline)

    def _publish() -> None:
        # Stamps first: whatever the route reads out of the sink carries the
        # provenance of the stages that actually completed.
        if sink is None:
            return
        _stamp_provenance(result)
        sink["result"] = result

    result = DeepSearchResult(product_name=query)
    sources: List[str] = []
    collected_data: List[str] = []
    band_notes: List[str] = []

    # â”€â”€ Get real eBay sold data first â”€â”€
    sold_for_stores = None
    try:
        from scrapers.ebay_sold import EbaySoldScraper
        sold_scraper = EbaySoldScraper()
        sold_data = sold_scraper.get_sold_data(query)
        sold_for_stores = sold_data

        # Use real data instead of LLM estimates
        if sold_data.items:
            # C10 â€” EbaySoldScraper queries with conditions:{NEW}, so every
            # item that came back is New. No items = no condition to claim.
            result.ebay_condition = "New"
            if getattr(sold_data, "excluded_over_band", 0):
                band_notes.append(
                    excluded_note("sold listings", sold_data.excluded_over_band)
                )
            result.ebay_total_sold_30d = sold_data.total_sold_30d
            result.ebay_total_sold_7d = sold_data.total_sold_7d
            result.ebay_price_min = sold_data.price_min
            result.ebay_price_max = sold_data.price_max
            result.ebay_avg_price = sold_data.price_avg
            result.ebay_price_median = sold_data.price_median
            result.ebay_top_sellers = sold_data.top_sellers
            result.ebay_items_sold_month = f"{sold_data.total_sold_30d} items"
            result.ebay_price_range = f"Â£{sold_data.price_min:.2f} - Â£{sold_data.price_max:.2f} (avg Â£{sold_data.price_avg:.2f})"
            result.sources.extend([item.url for item in sold_data.items[:5] if item.url])
    except Exception as e:
        print(f"[WARN] eBay sold data unavailable: {e}")

    # C11 â€” competitor stores from the query we just ran (no extra request
    # in the normal case). Falls back to a search only if that yielded none.
    result.attach_stores(sold_data=sold_for_stores, query=query)
    # The eBay query and the stores off it are the floor of any answer: they
    # are published before anything discretionary can go wrong.
    _publish()

    search_queries = [
        f"{query} eBay UK sold price",
        f"{query} site:godropship.co.uk",
        f"{query} site:diy.com B&Q",
        f"{query} site:cjdropshipping.com",
        f"{query} site:toolstation.com",
        f"{query} site:joybuy.co.uk",
        f"{query} site:aliexpress.com",
        f"{query} site:amazon.co.uk",
    ]

    for sq in search_queries[:5]:
        # A1.4 â€” one search may wait its full 30 s, so the check sits BEFORE
        # it: once the line is passed we would rather run none than start a
        # step that ends after the route has already given up on us.
        if _out_of_time(_prestop):
            _skipped.append("web search")
            break
        hits = _web_search(sq, num_results=5)
        for hit in hits:
            if hit["url"]:
                sources.append(hit["url"])
            collected_data.append(
                f"[Search: {sq}] {hit['title']}\n{hit['snippet']}\nURL: {hit['url']}"
            )
        time.sleep(0.4)
    _publish()

    fetch_count = 0
    for src in sources[:4]:
        if fetch_count >= 2:
            break
        if _out_of_time(_prestop):
            _skipped.append("page fetch")
            break
        if not src.startswith("http"):
            continue
        page_text = _fetch_page_text(src)
        if page_text:
            collected_data.append(f"[Page: {src}]\n{page_text[:2000]}")
            fetch_count += 1
            time.sleep(0.3)
    _publish()

    combined = "\n\n---\n\n".join(collected_data)

    user_prompt = (
        f"Product to research: {query}\n\n"
        f"Collected search results and page data:\n\n{combined}\n\n"
        f"Analyse the above and return the JSON object as specified."
    )

    # A1.4 â€” the model is the single biggest wait on this path: its own
    # budget OLLAMA_TIMEOUT_S is the route's ENTIRE budget, so handing it
    # that value is what made an overrun certain. What it may have is what
    # is left before the supplier stage starts, and none at all once that
    # line is behind us.
    _llm_timeout = OLLAMA_TIMEOUT_S
    if _prestop is not None:
        _llm_timeout = min(OLLAMA_TIMEOUT_S, _prestop - time.monotonic())

    if _llm_timeout <= 0:
        _skipped.append("model")
        print("[INFO] Deep search reached the model with no time left â€” "
              "continuing on real eBay data, supplier estimates Unverified")
        result.raw_analysis = ""
        parsed = {}
    else:
        try:
            raw_llm = _ollama_generate(
                user_prompt, system=_SYSTEM_PROMPT, timeout=_llm_timeout
            )
            result.raw_analysis = raw_llm
            parsed = _parse_llm_json(raw_llm)
        except RuntimeError as e:
            # Rule-based fallback â€” never fabricate: leave LLM fields empty/Unverified
            print(f"[WARN] Deep search LLM failed: {e}")
            result.raw_analysis = ""
            result.notes = (
                f"LLM unavailable ({e}). Showing real eBay sold data only â€” "
                "supplier estimates marked Unverified."
            )
            parsed = {}
    _publish()

    result.sources = list(dict.fromkeys(sources))

    result.product_name = parsed.get("product_name", query)
    result.product_category = parsed.get("product_category", "")

    # Use real eBay sold data if available, otherwise fall back to LLM estimates
    if result.ebay_total_sold_30d == 0:
        # No real data, use LLM estimate
        result.ebay_items_sold_month = parsed.get("ebay_items_sold_month", "")

        # LLM price range is gated on ITS OWN numbers, not on avg (PR-2 layer 4)
        price_range = parsed.get("ebay_price_range", "")
        if price_range and not _llm_price_range_in_band(price_range):
            band_notes.append(
                f"LLM price range '{price_range}' discarded (outside {band_label()})"
            )
            price_range = ""
        result.ebay_price_range = price_range

        # Parse avg price â€” must sit inside the band or it is not usable (PR-1)
        avg = parsed.get("ebay_avg_price", 0)
        try:
            avg_f = float(avg)
        except (ValueError, TypeError):
            avg_f = 0.0
        if avg_f and not in_band(avg_f):
            band_notes.append(
                f"LLM price estimate Â£{avg_f:.2f} discarded (outside band)"
            )
            avg_f = 0.0
            result.ebay_price_range = ""
        result.ebay_avg_price = avg_f

    # C13 â€” the LLM is NOT a source of sellers. `ebay_top_sellers` used to
    # be read straight from `parsed`, so an invented name AND an invented
    # URL could be rendered as a real eBay store with a real-looking link.
    # Popped unconditionally: the field is written only by the retrieval
    # layer (real New-filtered eBay items), never by the model.
    parsed.pop("ebay_top_sellers", None)

    # C12/C13 â€” supplier rows are NEVER taken from the LLM.
    # `parsed["suppliers"]` used to be assigned verbatim and then feed
    # best_supplier_price -> profit -> verdict, so a hallucinated price could
    # produce a PASS. Candidates the LLM names are only ever URLs to FETCH;
    # a row exists here only if it was retrieved and confirmed (verify-or-drop).
    parsed.pop("suppliers", None)
    # P4 â€” SerpApi Google Shopping is the PRIMARY source of approved
    # suppliers; the LLM's candidate URLs are only the SUPPLEMENT, because
    # the model can name nothing beyond what the corpus already surfaced.
    # Both streams then pass through the same gate, so neither can reach the
    # result without a computed match (C14) and neither can push the list
    # past the C12 ceiling.
    if _out_of_time():
        # A1.4 â€” past the line. Discovery is a SerpApi round trip and
        # verification can hold its full 15 s per candidate that fails to
        # confirm, so starting a stage we already know we cannot finish is
        # how a run gets abandoned with everything else thrown away.
        _skipped.append("supplier discovery")
        verified_suppliers = []
    else:
        verified_suppliers = _discover_approved_suppliers(query)
        seen_supplier_urls = {row.get("url", "") for row in verified_suppliers}
        for row in _verify_supplier_candidates(
            query, parsed.get("supplier_candidates", []) or [],
            deadline=_deadline,
        ):
            if row.get("url", "") in seen_supplier_urls:
                continue  # same listing reached twice â€” one row, not two
            seen_supplier_urls.add(row.get("url", ""))
            verified_suppliers.append(row)
        # C14 â€” retrieved is not the same as matching. Every confirmed page is
        # now scored against the eBay title, and anything the matcher cannot
        # place above the threshold is dropped rather than shown (C12).
        verified_suppliers = _gate_suppliers(
            verified_suppliers,
            result.product_name or query,
            brand=parsed.get("brand_name", ""),
            ebay_price=result.ebay_avg_price or 0.0,
            ebay_image_hash=_reference_image_hash(sold_for_stores),
            deadline=_deadline,
        )
    if verified_suppliers:
        result.suppliers = verified_suppliers
        valid = [s for s in verified_suppliers
                 if isinstance(s.get("price"), (int, float)) and s["price"] > 0]
        if valid:
            best = min(valid, key=lambda s: s["price"])
            result.best_supplier_price = best["price"]
            # C14 â€” a merely plausible match may still set the profit input;
            # say so, because an unconfirmed identity underpins the verdict.
            if best.get("match_tier") != "verified":
                band_notes.append(
                    f"Cheapest supplier matched only at {best.get('match_score', 0.0):.2f} "
                    f"({best.get('match_label', 'not confirmed')}) â€” profit is "
                    "based on an unconfirmed product match (C14)."
                )
    elif parsed.get("supplier_candidates") and "supplier discovery" not in _skipped:
        band_notes.append(
            "Supplier candidates could not be confirmed against their live "
            "pages â€” dropped rather than shown unverified (C12)."
        )
    _publish()

    result.delivery_info = parsed.get("delivery_info", "")
    result.competition_level = parsed.get("competition_level", "")
    result.profit_potential = parsed.get("profit_potential", "")
    result.notes = parsed.get("notes", "")

    # â”€â”€ C13 provenance stamp â”€â”€
    _stamp_provenance(result)

    # â”€â”€ Calculate profit & verdict (same logic as Analyze tab) â”€â”€
    _calculate_profit_and_verdict(
        result, brand_name=str(parsed.get("brand_name", "") or "")
    )

    # PR-4 transparency: report what the band removed (never silent)
    if band_notes:
        result.notes = (result.notes + " " if result.notes else "") + "; ".join(band_notes) + "."

    # A1.4 â€” a run that stopped early says so on its own face. Without this
    # the response reads as a complete analysis whose data merely happens to
    # be thin, which is exactly the quiet shortfall C13 exists to prevent.
    if _skipped:
        _note = ("Stages skipped at the time budget: "
                 + ", ".join(dict.fromkeys(_skipped)) + ".")
        result.notes = (result.notes + " " if result.notes else "") + _note

    # No publish here: the sink holds the object itself, so every write above
    # is already visible to whoever reads it. Publishing per stage is what
    # buys the partial response; publishing at the end would change nothing.
    return result


def deep_search_fast(
    query: str,
    budget_s: float | None = None,
    sink: dict | None = None,
) -> DeepSearchResult:
    """Fast bulk analysis â€” eBay sold data + supplier scrape only, no LLM.

    Skips web searches and Ollama to run in seconds instead of minutes.
    Runs supplier scrapes in parallel for speed.

    A1.4 â€” same contract as the full path: `budget_s` is the route's, the
    scrape pool waits only for what is left of it, and `sink` receives the
    run after the eBay stage so a route timeout still returns the stores and
    sold figures this run already collected.
    """
    _start = time.monotonic()
    _deadline = (_start + budget_s - HANDOFF_RESERVE_S) if budget_s is not None else None

    def _publish() -> None:
        if sink is None:
            return
        _stamp_provenance(result)
        sink["result"] = result

    result = DeepSearchResult(product_name=query)
    sources: List[str] = []
    band_notes: List[str] = []

    # â”€â”€ Get real eBay sold data â”€â”€
    sold_for_stores = None
    try:
        from scrapers.ebay_sold import EbaySoldScraper
        sold_scraper = EbaySoldScraper()
        sold_data = sold_scraper.get_sold_data(query)
        sold_for_stores = sold_data

        if sold_data.items:
            # C10 â€” same basis as the full path: New-filtered query results.
            result.ebay_condition = "New"
            if getattr(sold_data, "excluded_over_band", 0):
                band_notes.append(
                    excluded_note("sold listings", sold_data.excluded_over_band)
                )
            result.ebay_total_sold_30d = sold_data.total_sold_30d
            result.ebay_total_sold_7d = sold_data.total_sold_7d
            result.ebay_price_min = sold_data.price_min
            result.ebay_price_max = sold_data.price_max
            result.ebay_avg_price = sold_data.price_avg
            result.ebay_price_median = sold_data.price_median
            result.ebay_top_sellers = sold_data.top_sellers
            result.ebay_items_sold_month = f"{sold_data.total_sold_30d} items"
            result.ebay_price_range = f"Â£{sold_data.price_min:.2f} - Â£{sold_data.price_max:.2f} (avg Â£{sold_data.price_avg:.2f})"
            sources.extend([item.url for item in sold_data.items[:5] if item.url])
            print(f"[OK] eBay sold: {sold_data.total_sold_30d} items, avg Â£{sold_data.price_avg:.2f}")
        else:
            print(f"[WARN] eBay sold: no items found for '{query}'")
    except Exception as e:
        print(f"[WARN] eBay sold data failed: {e}")

    # C11 â€” stores for Bulk, from the query we just ran.
    #
    # REGRESSION-006: this used to pass NO query, deliberately, so the store
    # block had no fallback rung and a product with few sold listings showed
    # no stores at all. The ladder stops at its first hit and the sold data
    # this run already fetched is rung 1 (free), so passing the query costs
    # nothing in the common case and only spends a request when that data had
    # no sellers. That is a fair trade for actually showing the stores.
    result.attach_stores(sold_data=sold_for_stores, query=query)
    # A1.4 â€” the sold query and the stores off it are published before the
    # scrape pool, so a route that gives up during scraping keeps them.
    _publish()

    # â”€â”€ Run supplier scrapes in PARALLEL â”€â”€
    import asyncio

    async def _scrape_cj():
        try:
            from scrapers.cjdropshipping import CJDropshippingScraper
            cj = CJDropshippingScraper()
            products = await cj.search(query)
            print(f"[OK] CJ Dropshipping: {len(products)} products found")
            return [("CJ Dropshipping", p) for p in products[:2]]
        except Exception as e:
            print(f"[WARN] CJ scrape failed: {e}")
            return []

    async def _scrape_ae():
        try:
            from scrapers.aliexpress import AliExpressScraper
            ae = AliExpressScraper()
            products = await ae.search(query)
            print(f"[OK] AliExpress: {len(products)} products found")
            return [("AliExpress", p) for p in products[:2]]
        except Exception as e:
            print(f"[WARN] AliExpress scrape failed: {e}")
            return []

    async def _scrape_amazon():
        try:
            from scrapers.amazon_uk import AmazonUKScraper
            amz = AmazonUKScraper()
            products = await amz.search(query)
            print(f"[OK] Amazon UK: {len(products)} products found")
            return [("Amazon UK", p) for p in products[:2]]
        except Exception as e:
            print(f"[WARN] Amazon scrape failed: {e}")
            return []

    # Run all scrapes with a hard cap so one hung site can't block the API
    import concurrent.futures

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futs = [
                pool.submit(asyncio.run, _scrape_cj()),
                pool.submit(asyncio.run, _scrape_ae()),
                pool.submit(asyncio.run, _scrape_amazon()),
            ]
            # A1.4 â€” 50 s is the ceiling, not the target: the pool waits only
            # for what is left of the route's budget, so the Bulk path can
            # hand its result back instead of being abandoned over the line.
            _scrape_wait = 50.0
            if _deadline is not None:
                _scrape_wait = max(0.0, min(_scrape_wait, _deadline - time.monotonic()))
            done, not_done = concurrent.futures.wait(futs, timeout=_scrape_wait)
            cj_results = ae_results = amz_results = []
            for i, fut in enumerate(futs):
                try:
                    val = fut.result(timeout=0) if fut in done else []
                except Exception as e:
                    print(f"[WARN] supplier scrape error: {e}")
                    val = []
                if i == 0:
                    cj_results = val
                elif i == 1:
                    ae_results = val
                else:
                    amz_results = val
            if not_done:
                print(f"[WARN] {len(not_done)} supplier scrape(s) timed out at "
                      f"{_scrape_wait:.0f}s")
    except Exception as e:
        print(f"[WARN] Parallel scrape failed: {e}")
        cj_results, ae_results, amz_results = [], [], []

    # Process results â€” supplier prices are never range-gated (PR-1);
    # only unusable rows (no positive price) are skipped.
    for source_name, product in cj_results + ae_results + amz_results:
        if not product.price or product.price <= 0:
            continue
        store_display = product.store_name or product.seller or source_name

        result.suppliers.append({
            "name": f"{source_name} - {store_display}" if store_display != source_name else source_name,
            "full_name": store_display,
            "price": product.price,
            "url": product.url,
            # C13 â€” derived from the real source, never assumed. Amazon is
            # not the only retailer and everything else is not a dropshipper.
            "supplier_type": classify_source(
                name=store_display or source_name, url=product.url
            ),
            "delivery_days": f"{product.delivery_days_min}-{product.delivery_days_max}",
            "seller_rating": product.seller_rating,
            "seller_orders": product.seller_orders,
            "product_title": product.title,
            "image_url": product.image_url,
            # C13 â€” a row only exists because a scraper read it, so it is
            # verified, and it carries its own link as the receipt.
            "provenance": Provenance.VERIFIED.value,
            "provenance_label": Provenance.VERIFIED.label,
            # C13 â€” verified AND how: an AliExpress/Amazon row can only be a
            # browser read when the credentialed API is unconfigured, and the
            # UI must not present that as indistinguishable from an API row.
            "fetch_method": getattr(product, "fetch_method", "") or "",
            "source_url": product.url,
            "source_name": source_name,
            # P4 â€” availability exactly as the scraper read it. Blank/0 means
            # the source never said, which is the only honest answer (C13).
            "in_stock": getattr(product, "in_stock", ""),
            "stock_raw": getattr(product, "stock_raw", ""),
            "availability_url": getattr(product, "availability_url", "") or product.url,
            "shipping_cost": getattr(product, "shipping_cost", 0.0),
            "shipping_days": getattr(product, "shipping_days", 0),
            "shipping_raw": getattr(product, "shipping_raw", ""),
        })

    # C14 â€” same gate as the full path: score against the eBay title and
    # drop anything the matcher cannot place above the threshold (C12).
    # Applied to the whole list at once so the cheapest-row pick below only
    # ever considers rows that cleared it.
    result.suppliers = _gate_suppliers(
        result.suppliers,
        result.product_name or query,
        ebay_price=result.ebay_avg_price or 0.0,
        ebay_image_hash=_reference_image_hash(sold_for_stores),
    )

    # Find best supplier
    if result.suppliers:
        valid = [s for s in result.suppliers if isinstance(s.get("price"), (int, float)) and s["price"] > 0]
        if valid:
            best = min(valid, key=lambda s: s["price"])
            result.best_supplier_price = best["price"]

    result.sources = sources
    result.notes = "Fast analysis (no LLM). For full analysis use Deep Search tab."

    # â”€â”€ C13 provenance stamp (fast path: no LLM, so nothing is ai_insight) â”€â”€
    if result.ebay_total_sold_30d or result.ebay_top_sellers:
        for name in ("ebay_total_sold_30d", "ebay_top_sellers", "ebay_avg_price",
                     "ebay_condition"):
            result.set_fact_provenance(name, Provenance.VERIFIED,
                                       source_name="eBay Browse API (conditions:{NEW})")
    else:
        for name in ("ebay_total_sold_30d", "ebay_top_sellers", "ebay_avg_price",
                     "ebay_price_range", "ebay_items_sold_month", "ebay_condition"):
            result.set_fact_provenance(name, Provenance.UNVERIFIED,
                                       reason="no eBay sold data retrieved")
    result.set_fact_provenance(
        "suppliers",
        Provenance.VERIFIED if result.suppliers else Provenance.UNVERIFIED,
        source_name="supplier scrapers (CJ / AliExpress / Amazon UK)",
        method="" if result.suppliers else "no supplier scrape returned a price",
    )
    # C11/C13 â€” store block stamp (same shape as the full path).
    if result.ebay_stores_provenance:
        result.field_provenance.setdefault("ebay_stores",
                                           dict(result.ebay_stores_provenance))

    # Calculate profit & verdict
    _calculate_profit_and_verdict(result)

    # PR-4 transparency: report what the band removed (never silent)
    if band_notes:
        result.notes = (result.notes + " " if result.notes else "") + "; ".join(band_notes) + "."

    return result


def _calculate_profit_and_verdict(
    result: DeepSearchResult, filters: dict | None = None, brand_name: str = ""
):
    """Adapt a DeepSearchResult to the ONE engine rule (C1).

    Money math (engine.profit) and the verdict ladder (engine.decisions)
    are not re-derived here â€” this function only builds evidence.
    """
    import re
    from dataclasses import asdict

    from engine.decisions import DecisionEngine
    from scrapers.base import DemandData, ScrapedProduct
    from utils.filters import load_filters

    ebay_price = result.ebay_avg_price
    supplier_cost = result.best_supplier_price

    # Show what data is missing
    missing = []
    if ebay_price <= 0:
        missing.append("eBay price (no sold data found)")
    if supplier_cost <= 0:
        missing.append("Supplier cost (no suppliers found)")

    if missing:
        result.verdict = "PENDING"
        result.filters_passed.append({
            "name": "Data",
            "passed": False,
            "actual": f"Missing: {', '.join(missing)}",
            "expected": "eBay avg price + supplier cost required",
            "verified": False,
        })
        result.notes = f"Cannot determine verdict â€” {', '.join(missing)}. Try Deep Search tab for full analysis with LLM."
        return

    # --- Evidence (no rules here) ---
    supplier_delivery_days = None
    for s in result.suppliers:
        match = re.search(r"(\d+)", str(s.get("delivery_days", "")))
        if match:
            supplier_delivery_days = int(match.group(1))
            break

    evidence = ScrapedProduct(
        source="ebay_uk",
        title=result.product_name or "item",
        price=ebay_price,
        url="",
        # C10 â€” '' unless real New-filtered eBay items backed this result.
        # decisions.py marks the Condition row Unverified from the blank
        # value alone (C1); the other rows' verification is unaffected.
        condition=result.ebay_condition,
        delivery_days_max=None,  # deep search has no listing delivery â€” advisory uses supplier
        verified=True,
        # C5: an LLM-named brand is checked against the VeRO catalog by the
        # engine; empty/unknown stays "No brand name detected" (never guessed).
        brand=(brand_name or "").strip(),
    )
    demand = DemandData(
        sold_count_30d=result.ebay_total_sold_30d
        or _first_int(result.ebay_items_sold_month),
        sold_count_7d=result.ebay_total_sold_7d,
        verified=False,  # eBay sold-search estimates, not verified counts
    )

    _store_prov = result.ebay_stores_provenance or {}
    verdict = DecisionEngine(filters or load_filters()).evaluate(
        evidence,
        demand,
        supplier_cost,
        supplier_delivery_days,
        # C11 - advisory only; a short or widened store search is a floor,
        # not a total, so it must not read as a market with no competitors.
        competitor_store_count=_store_prov.get("store_count"),
        competitor_stores_verified=(
            _store_prov.get("provenance") == "verified"
        ),
    )

    result.profit = verdict.profit
    result.margin = verdict.margin
    result.verdict = verdict.verdict.upper()
    result.filters_passed = [asdict(f) for f in verdict.filters]


def _first_int(text: str) -> int | None:
    """First integer in a display string like '40+ bought/month'."""
    import re

    if not text:
        return None
    match = re.search(r"(\d+)", str(text))
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------

def _parse_llm_json(text: str) -> dict:
    """Attempt to parse the LLM response as JSON.

    First tries direct parsing, then tries to extract a JSON block from
    markdown fences or surrounding text. Falls back to empty dict.
    """
    if not text:
        return {}

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    return {}
