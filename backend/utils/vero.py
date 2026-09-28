"""VeRO brand check — CONSTRAINTS.md C5.

C5: a brand name registered in eBay's Verified Rights Owner (VeRO) programme
is a FAIL (counterfeit-listing risk); a brand that is not on VeRO, or an
ambiguous/missing brand name, is acceptable (generic products, PENDING).

This module only reads the local catalog in data/vero_brands.json (built from
the participant-profile list cited in that file's `source` field). It makes no
network calls and never guesses: empty or unreadable catalog -> "unknown".

Usage:
    from utils.vero import check_vero, vero_catalog_info

    check_vero("Nike")          # "registered" | "not_registered" | "unknown"
    vero_catalog_info()         # {"count": N, "generated_at": ..., "loaded": bool}
"""

import json
import re
from pathlib import Path

VERO_FILE = Path(__file__).parent.parent / "data" / "vero_brands.json"

REGISTERED = "registered"
NOT_REGISTERED = "not_registered"
UNKNOWN = "unknown"

_SUFFIXES = frozenset({"ltd", "limited", "gmbh", "llc", "inc", "co", "uk"})
_MARKS = "\u00ae\u2122\u2120\u00a9"

_cache: dict | None = None


def normalize_brand(name: str | None) -> str:
    """Lowercase, drop (R)(tm) marks and punctuation, strip trailing company
    suffixes, collapse whitespace. Empty string means nothing usable."""
    if not name or not str(name).strip():
        return ""
    text = str(name).lower()
    for mark in _MARKS:
        text = text.replace(mark, " ")
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    words = re.sub(r"\s+", " ", text).split()
    while words and words[-1] in _SUFFIXES:
        words.pop()
    return " ".join(words)


def _span(needle: str, haystack: str) -> bool:
    """True when needle appears in haystack on whole-token boundaries."""
    if not needle:
        return False
    idx = haystack.find(needle)
    end_of_hay = len(haystack)
    while idx != -1:
        end = idx + len(needle)
        left_ok = idx == 0 or not haystack[idx - 1].isalnum()
        right_ok = end == end_of_hay or not haystack[end].isalnum()
        if left_ok and right_ok:
            return True
        idx = haystack.find(needle, idx + 1)
    return False


def _load() -> dict:
    try:
        raw = json.loads(VERO_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"brands": [], "generated_at": None, "loaded": False}
    entries = list(raw.get("brands") or []) + list(raw.get("manual_additions") or [])
    brands: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        normalized = normalize_brand(entry)
        if normalized and normalized not in seen:
            seen.add(normalized)
            brands.append(normalized)
    return {
        "brands": sorted(brands),
        "generated_at": raw.get("generated_at"),
        "loaded": True,
    }


def _catalog() -> dict:
    global _cache
    if _cache is None:
        _cache = _load()
    return _cache


def check_vero(brand_name: str | None) -> str:
    """Verdict for one brand name under CONSTRAINTS.md C5.

    Returns "registered" (FAIL), "not_registered" (pass) or "unknown"
    (unverified — blank name, or no catalog to check against).
    """
    query = normalize_brand(brand_name)
    if not query:
        return UNKNOWN
    brands = _catalog()["brands"]
    if not brands:
        return UNKNOWN
    for brand in brands:
        if brand == query or _span(brand, query) or _span(query, brand):
            return REGISTERED
    return NOT_REGISTERED


def vero_catalog_info() -> dict:
    """Catalog status for the API status surface."""
    catalog = _catalog()
    return {
        "count": len(catalog["brands"]),
        "generated_at": catalog.get("generated_at"),
        "loaded": bool(catalog.get("loaded")),
    }
