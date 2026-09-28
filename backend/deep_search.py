"""Deep product research module for eBay UK reseller tool.

Combines DuckDuckGo web search (no API key required) with Ollama LLM
to research products across the web and generate actionable reselling insights.
"""

import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from urllib.parse import urlparse, quote_plus

import requests
from bs4 import BeautifulSoup

from engine.price_gate import (
    PRICE_MAX, band_label, excluded_note, filter_dicts, in_band,
)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

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
    """Extract a numeric GBP figure from LLM output ('£12.99', 12.99, '12.99')."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        m = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
        if m:
            return float(m.group())
    return None


def _llm_price_in_band(value) -> bool:
    """True when an LLM-provided price figure sits inside the band."""
    p = _parse_llm_money(value)
    return p is not None and in_band(p)


def _llm_price_range_in_band(text: str) -> bool:
    """True when EVERY figure in an LLM range string sits inside the band.

    The string looks like '£5.99 - £12.99 (avg £8.50)' — one out-of-band
    figure makes the whole string unusable (PR-1: no figure shown out of band).
    """
    figures = [_parse_llm_money(m) for m in re.findall(r"£\s*\d+(?:\.\d+)?", text)]
    figures = [f for f in figures if f is not None]
    if not figures:
        # No £ markers — try every bare number, but only if there are 2+ (a range)
        bare = [_parse_llm_money(m) for m in re.findall(r"\d+(?:\.\d+)?", text)]
        bare = [f for f in bare if f is not None]
        figures = bare if len(bare) >= 2 else []
    if not figures:
        return False  # unparseable string — never ship an unverified figure
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
    ebay_total_sold_7d: int = 0
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

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        lines = [
            f"Product: {self.product_name}",
            f"Category: {self.product_category}",
            f"eBay UK monthly sales: {self.ebay_items_sold_month}",
            f"eBay price range: {self.ebay_price_range}",
            f"eBay avg price: £{self.ebay_avg_price:.2f}",
            f"Suppliers found: {len(self.suppliers)}",
        ]
        for s in self.suppliers:
            lines.append(f"  - {s.get('name', 'N/A')} | £{s.get('price', 0):.2f} | {s.get('supplier_type', '')} | {s.get('url', '')}")
        lines.append(f"Best supplier cost: £{self.best_supplier_price:.2f}")
        lines.append(f"Profit: £{self.profit:.2f} | Margin: {self.margin:.1f}%")
        lines.append(f"Verdict: {self.verdict}")
        lines.append(f"Competition: {self.competition_level}")
        lines.append(f"Profit potential: {self.profit_potential}")
        if self.notes:
            lines.append(f"Notes: {self.notes}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ollama LLM
# ---------------------------------------------------------------------------

def _ollama_generate(prompt: str, system: str = "", timeout: float = 45.0) -> str:
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
# Main deep search
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a UK eBay reselling research assistant. You are given raw search
results and page extracts about a product. Analyse the data and return a
JSON object with the following fields (all prices in GBP £):

{
  "product_name": "string",
  "product_category": "string",
  "ebay_items_sold_month": "estimated items sold per month on eBay UK, e.g. '500-1000'",
  "ebay_top_sellers": [
    {"name": "seller name", "url": "eBay listing URL", "price": "£XX.XX"}
  ],
  "ebay_price_range": "£low - £high (avg £avg)",
  "ebay_avg_price": 15.99,
  "suppliers": [
    {
      "name": "supplier name",
      "price": 5.99,
      "url": "https://supplier-url.com",
      "supplier_type": "wholesaler | retailer | dropshipper | manufacturer",
      "delivery_days": "3-5",
      "notes": "any notes"
    }
  ],
  "competition_level": "low | medium | high",
  "profit_potential": "low | medium | high",
  "delivery_info": "shipping/lead time notes",
  "notes": "any extra useful context for a reseller"
}

Rules:
- All prices MUST be in GBP (£).
- Find MULTIPLE suppliers (at least 2-3 if possible) with real prices and links.
- Focus on UK market data only.
- If data is uncertain, say so in notes.
- Return ONLY valid JSON, no markdown fences, no commentary.
- Use up to 3 top eBay sellers. If fewer found, return fewer.
- ebay_avg_price should be a number (not a string).
- Each supplier price should be a number (not a string).
"""


def deep_search_product(query: str) -> DeepSearchResult:
    """Research a product across eBay UK and the wider web.

    Runs multiple targeted searches, fetches page content, sends
    everything to the local Ollama LLM, and returns a structured
    DeepSearchResult.
    """
    result = DeepSearchResult(product_name=query)
    sources: List[str] = []
    collected_data: List[str] = []
    band_notes: List[str] = []

    # ── Get real eBay sold data first ──
    try:
        from scrapers.ebay_sold import EbaySoldScraper
        sold_scraper = EbaySoldScraper()
        sold_data = sold_scraper.get_sold_data(query)

        # Use real data instead of LLM estimates
        if sold_data.items:
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
            result.ebay_price_range = f"£{sold_data.price_min:.2f} - £{sold_data.price_max:.2f} (avg £{sold_data.price_avg:.2f})"
            result.sources.extend([item.url for item in sold_data.items[:5] if item.url])
    except Exception as e:
        print(f"[WARN] eBay sold data unavailable: {e}")

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
        hits = _web_search(sq, num_results=5)
        for hit in hits:
            if hit["url"]:
                sources.append(hit["url"])
            collected_data.append(
                f"[Search: {sq}] {hit['title']}\n{hit['snippet']}\nURL: {hit['url']}"
            )
        time.sleep(0.4)

    fetch_count = 0
    for src in sources[:4]:
        if fetch_count >= 2:
            break
        if not src.startswith("http"):
            continue
        page_text = _fetch_page_text(src)
        if page_text:
            collected_data.append(f"[Page: {src}]\n{page_text[:2000]}")
            fetch_count += 1
            time.sleep(0.3)

    combined = "\n\n---\n\n".join(collected_data)

    user_prompt = (
        f"Product to research: {query}\n\n"
        f"Collected search results and page data:\n\n{combined}\n\n"
        f"Analyse the above and return the JSON object as specified."
    )

    try:
        raw_llm = _ollama_generate(user_prompt, system=_SYSTEM_PROMPT, timeout=45.0)
        result.raw_analysis = raw_llm
        parsed = _parse_llm_json(raw_llm)
    except RuntimeError as e:
        # Rule-based fallback — never fabricate: leave LLM fields empty/Unverified
        print(f"[WARN] Deep search LLM failed: {e}")
        result.raw_analysis = ""
        result.notes = (
            f"LLM unavailable ({e}). Showing real eBay sold data only — "
            "supplier estimates marked Unverified."
        )
        parsed = {}

    result.sources = list(dict.fromkeys(sources))

    result.product_name = parsed.get("product_name", query)
    result.product_category = parsed.get("product_category", "")

    # Use real eBay sold data if available, otherwise fall back to LLM estimates
    if result.ebay_total_sold_30d == 0:
        # No real data, use LLM estimate
        result.ebay_items_sold_month = parsed.get("ebay_items_sold_month", "")

        # LLM top sellers carry price strings — every figure must sit in band (PR-1)
        top_sellers = parsed.get("ebay_top_sellers", []) or []
        kept_sellers, excluded_sellers = [], 0
        for s in top_sellers:
            if _llm_price_in_band(s.get("price")):
                kept_sellers.append(s)
            else:
                excluded_sellers += 1
        result.ebay_top_sellers = kept_sellers
        if excluded_sellers:
            band_notes.append(excluded_note("LLM top-seller figures", excluded_sellers))

        # LLM price range is gated on ITS OWN numbers, not on avg (PR-2 layer 4)
        price_range = parsed.get("ebay_price_range", "")
        if price_range and not _llm_price_range_in_band(price_range):
            band_notes.append(
                f"LLM price range '{price_range}' discarded (outside {band_label()})"
            )
            price_range = ""
        result.ebay_price_range = price_range

        # Parse avg price — must sit inside the band or it is not usable (PR-1)
        avg = parsed.get("ebay_avg_price", 0)
        try:
            avg_f = float(avg)
        except (ValueError, TypeError):
            avg_f = 0.0
        if avg_f and not in_band(avg_f):
            band_notes.append(
                f"LLM price estimate £{avg_f:.2f} discarded (outside band)"
            )
            avg_f = 0.0
            result.ebay_price_range = ""
        result.ebay_avg_price = avg_f

    # Parse multiple suppliers — price band gate (CONSTRAINTS_PRICING.md PR-2 layer 3)
    suppliers = parsed.get("suppliers", [])
    if suppliers:
        suppliers, excluded_suppliers = filter_dicts(suppliers, "price")
        if excluded_suppliers:
            band_notes.append(excluded_note("supplier matches", excluded_suppliers))
    if suppliers:
        result.suppliers = suppliers
        # Find best (cheapest) supplier
        valid = [s for s in suppliers if isinstance(s.get("price"), (int, float)) and s["price"] > 0]
        if valid:
            best = min(valid, key=lambda s: s["price"])
            result.best_supplier_price = best["price"]

    result.delivery_info = parsed.get("delivery_info", "")
    result.competition_level = parsed.get("competition_level", "")
    result.profit_potential = parsed.get("profit_potential", "")
    result.notes = parsed.get("notes", "")

    # ── Calculate profit & verdict (same logic as Analyze tab) ──
    _calculate_profit_and_verdict(result)

    # PR-4 transparency: report what the band removed (never silent)
    if band_notes:
        result.notes = (result.notes + " " if result.notes else "") + "; ".join(band_notes) + "."

    return result


def deep_search_fast(query: str) -> DeepSearchResult:
    """Fast bulk analysis — eBay sold data + supplier scrape only, no LLM.
    
    Skips web searches and Ollama to run in seconds instead of minutes.
    Runs supplier scrapes in parallel for speed.
    """
    result = DeepSearchResult(product_name=query)
    sources: List[str] = []
    band_notes: List[str] = []

    # ── Get real eBay sold data ──
    try:
        from scrapers.ebay_sold import EbaySoldScraper
        sold_scraper = EbaySoldScraper()
        sold_data = sold_scraper.get_sold_data(query)

        if sold_data.items:
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
            result.ebay_price_range = f"£{sold_data.price_min:.2f} - £{sold_data.price_max:.2f} (avg £{sold_data.price_avg:.2f})"
            sources.extend([item.url for item in sold_data.items[:5] if item.url])
            print(f"[OK] eBay sold: {sold_data.total_sold_30d} items, avg £{sold_data.price_avg:.2f}")
        else:
            print(f"[WARN] eBay sold: no items found for '{query}'")
    except Exception as e:
        print(f"[WARN] eBay sold data failed: {e}")

    # ── Run supplier scrapes in PARALLEL ──
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
            done, not_done = concurrent.futures.wait(futs, timeout=50.0)
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
                print(f"[WARN] {len(not_done)} supplier scrape(s) timed out at 50s")
    except Exception as e:
        print(f"[WARN] Parallel scrape failed: {e}")
        cj_results, ae_results, amz_results = [], [], []

    # Process results — price band gate (CONSTRAINTS_PRICING.md PR-2 layer 3)
    excluded_suppliers = 0
    for source_name, product in cj_results + ae_results + amz_results:
        if not in_band(product.price):
            excluded_suppliers += 1
            continue
        supplier_type = "retailer" if source_name == "Amazon UK" else "dropshipper"
        store_display = product.store_name or product.seller or source_name

        result.suppliers.append({
            "name": f"{source_name} - {store_display}" if store_display != source_name else source_name,
            "full_name": store_display,
            "price": product.price,
            "url": product.url,
            "supplier_type": supplier_type,
            "delivery_days": f"{product.delivery_days_min}-{product.delivery_days_max}",
            "seller_rating": product.seller_rating,
            "seller_orders": product.seller_orders,
            "product_title": product.title,
            "image_url": product.image_url,
        })

    # Find best supplier
    if result.suppliers:
        valid = [s for s in result.suppliers if isinstance(s.get("price"), (int, float)) and s["price"] > 0]
        if valid:
            best = min(valid, key=lambda s: s["price"])
            result.best_supplier_price = best["price"]

    result.sources = sources
    result.notes = "Fast analysis (no LLM). For full analysis use Deep Search tab."
    if excluded_suppliers:
        band_notes.append(excluded_note("supplier matches", excluded_suppliers))

    # Calculate profit & verdict
    _calculate_profit_and_verdict(result)

    # PR-4 transparency: report what the band removed (never silent)
    if band_notes:
        result.notes = (result.notes + " " if result.notes else "") + "; ".join(band_notes) + "."

    return result


def _calculate_profit_and_verdict(result: DeepSearchResult):
    """Calculate profit, margin, and verdict using the same rules as the Analyze tab."""
    from config import FILTERS

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
        result.notes = f"Cannot determine verdict — {', '.join(missing)}. Try Deep Search tab for full analysis with LLM."
        return

    # eBay fees: 12.8% final value + 3% returns buffer
    ebay_fee_pct = 0.128
    returns_buffer_pct = 0.03
    total_fee_pct = ebay_fee_pct + returns_buffer_pct

    ebay_fees = ebay_price * total_fee_pct
    profit = ebay_price - supplier_cost - ebay_fees
    margin = (profit / ebay_price * 100) if ebay_price > 0 else 0

    result.profit = round(profit, 2)
    result.margin = round(margin, 1)

    # Apply filters (same as config.py FILTERS)
    filters_passed = []

    # Price filter
    price_ok = FILTERS["price_min"] <= supplier_cost <= FILTERS["price_max"]
    filters_passed.append({
        "name": "Supplier Price",
        "passed": price_ok,
        "actual": f"£{supplier_cost:.2f}",
        "expected": f"£{FILTERS['price_min']:.2f} - £{FILTERS['price_max']:.2f}",
        "verified": True,
    })

    # Profit filter
    profit_ok = profit > 0
    filters_passed.append({
        "name": "Profitable",
        "passed": profit_ok,
        "actual": f"£{profit:.2f}",
        "expected": "> £0.00",
        "verified": True,
    })

    # Margin filter (>= 25%)
    margin_min = FILTERS.get("margin_min", 25.0)
    margin_ok = margin >= margin_min
    filters_passed.append({
        "name": "Margin",
        "passed": margin_ok,
        "actual": f"{margin:.1f}%",
        "expected": f">= {margin_min}%",
        "verified": True,
    })

    # Demand filter (estimated from eBay data)
    filters_passed.append({
        "name": "Demand",
        "passed": True,  # Can't strictly verify from deep search
        "actual": result.ebay_items_sold_month or "Estimated (unverified)",
        "expected": f">= {FILTERS['demand_min_30d']} sold/month",
        "verified": False,
    })

    # Delivery filter
    delivery_max = FILTERS.get("delivery_target_max", 8)
    delivery_exception = FILTERS.get("delivery_exception_max", 25)
    demand_strong = FILTERS.get("demand_strong_30d", 30)

    # Parse delivery from suppliers
    for s in result.suppliers:
        days_str = s.get("delivery_days", "")
        if days_str:
            import re
            match = re.search(r"(\d+)", str(days_str))
            if match:
                days = int(match.group(1))
                # Exception for high-demand products
                demand_monthly = 0
                if result.ebay_items_sold_month:
                    m = re.search(r"(\d+)", result.ebay_items_sold_month)
                    if m:
                        demand_monthly = int(m.group(1))

                if demand_monthly >= demand_strong and days <= delivery_exception:
                    delivery_ok = True
                else:
                    delivery_ok = days <= delivery_max

                filters_passed.append({
                    "name": f"Delivery ({s.get('name', '')})",
                    "passed": delivery_ok,
                    "actual": f"{days} days",
                    "expected": f"{delivery_max} days max",
                    "verified": False,
                })
                break

    # Brand filter (LLM-estimated)
    filters_passed.append({
        "name": "Brand",
        "passed": True,  # LLM should have filtered, but unverified
        "actual": "Generic (LLM-estimated)",
        "expected": "Generic only",
        "verified": False,
    })

    result.filters_passed = filters_passed

    # Verdict (same logic as DecisionEngine)
    all_critical = [f for f in filters_passed if f["name"] in ("Supplier Price", "Profitable", "Margin")]
    all_critical_passed = all(f["passed"] for f in all_critical)
    any_unverified = any(not f["verified"] for f in filters_passed)

    if all_critical_passed and profit > 0:
        result.verdict = "PASS"
    elif any_unverified and profit > 0:
        result.verdict = "PENDING"
    else:
        result.verdict = "FAIL"


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
