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


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TopSeller:
    name: str
    url: str
    price: str


@dataclass
class DeepSearchResult:
    product_name: str = ""
    product_category: str = ""
    ebay_items_sold_month: str = ""
    ebay_top_sellers: List[dict] = field(default_factory=list)
    ebay_price_range: str = ""
    supplier_name: str = ""
    supplier_type: str = ""
    supplier_cost: str = ""
    supplier_link: str = ""
    delivery_info: str = ""
    competition_level: str = ""
    profit_potential: str = ""
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
            f"Supplier: {self.supplier_name} ({self.supplier_type})",
            f"Supplier cost: {self.supplier_cost}",
            f"Supplier link: {self.supplier_link}",
            f"Delivery: {self.delivery_info}",
            f"Competition: {self.competition_level}",
            f"Profit potential: {self.profit_potential}",
            f"Top eBay sellers: {len(self.ebay_top_sellers)}",
        ]
        for s in self.ebay_top_sellers:
            lines.append(f"  - {s.get('name', 'N/A')} | {s.get('price', 'N/A')} | {s.get('url', '')}")
        if self.notes:
            lines.append(f"Notes: {self.notes}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ollama LLM
# ---------------------------------------------------------------------------

def _ollama_generate(prompt: str, system: str = "") -> str:
    """Send a prompt to the local Ollama API and return the generated text."""
    url = f"{OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {
            "num_predict": 2000,
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=180)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. "
            "Make sure Ollama is running (ollama serve)."
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama request timed out after 180 seconds.")
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
  "supplier_name": "company or website name",
  "supplier_type": "wholesaler | retailer | dropshipper | manufacturer",
  "supplier_cost": "£XX.XX estimated cost",
  "supplier_link": "URL to the supplier page",
  "delivery_info": "shipping/lead time notes",
  "competition_level": "low | medium | high",
  "profit_potential": "low | medium | high",
  "notes": "any extra useful context for a reseller"
}

Rules:
- All prices MUST be in GBP (£).
- Focus on UK market data only.
- If data is uncertain, say so in notes.
- Return ONLY valid JSON, no markdown fences, no commentary.
- Use up to 3 top eBay sellers. If fewer found, return fewer.
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

    search_queries = [
        f"{query} eBay UK sold price",
        f"{query} supplier wholesale UK",
        f"{query} dropshipping supplier UK",
        f"{query} product retail price UK",
    ]

    for sq in search_queries:
        hits = _web_search(sq, num_results=6)
        for hit in hits:
            if hit["url"]:
                sources.append(hit["url"])
            collected_data.append(
                f"[Search: {sq}] {hit['title']}\n{hit['snippet']}\nURL: {hit['url']}"
            )
        time.sleep(1.5)

    fetch_count = 0
    for src in sources[:6]:
        if fetch_count >= 4:
            break
        if not src.startswith("http"):
            continue
        page_text = _fetch_page_text(src)
        if page_text:
            collected_data.append(f"[Page: {src}]\n{page_text[:2000]}")
            fetch_count += 1
            time.sleep(1)

    combined = "\n\n---\n\n".join(collected_data)

    user_prompt = (
        f"Product to research: {query}\n\n"
        f"Collected search results and page data:\n\n{combined}\n\n"
        f"Analyse the above and return the JSON object as specified."
    )

    raw_llm = _ollama_generate(user_prompt, system=_SYSTEM_PROMPT)
    result.raw_analysis = raw_llm
    result.sources = list(dict.fromkeys(sources))

    parsed = _parse_llm_json(raw_llm)

    result.product_name = parsed.get("product_name", query)
    result.product_category = parsed.get("product_category", "")
    result.ebay_items_sold_month = parsed.get("ebay_items_sold_month", "")
    result.ebay_top_sellers = parsed.get("ebay_top_sellers", [])
    result.ebay_price_range = parsed.get("ebay_price_range", "")
    result.supplier_name = parsed.get("supplier_name", "")
    result.supplier_type = parsed.get("supplier_type", "")
    result.supplier_cost = parsed.get("supplier_cost", "")
    result.supplier_link = parsed.get("supplier_link", "")
    result.delivery_info = parsed.get("delivery_info", "")
    result.competition_level = parsed.get("competition_level", "")
    result.profit_potential = parsed.get("profit_potential", "")
    result.notes = parsed.get("notes", "")

    return result


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
