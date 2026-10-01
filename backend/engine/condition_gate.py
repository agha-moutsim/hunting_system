"""
Condition gate — CONSTRAINTS.md C10.

New-only is enforced at TWO points, and both read the SAME function so no
feature can drift:

  1. QUERY TIME  — every eBay call carries conditions:{NEW} (Browse API) or
     LH_ItemCondition=1000 (HTML), so a Used listing is never fetched.
  2. POST-FILTER — a row whose condition is not New is dropped BEFORE
     supplier search and LLM spend, not at verdict time.

A missing / blank / unrecognised condition is NOT New: it fails closed.
FILTERS["condition"] is the single source of truth, validated against
ALLOWED_CONDITIONS — the verdict engine reads it instead of a literal.
"""

from config import FILTERS, ALLOWED_CONDITIONS
from utils.filters import load_filters

# v1 accepts exactly one condition (C10). The allow-list itself lives in
# config.py so utils.filters can validate without importing this module.
API_CONDITION_FILTER = "conditions:{NEW}"

# eBay HTML search parameter (scrape fallback / sold search).
HTML_CONDITION_PARAM = "&LH_ItemCondition=1000"

# Normalised tokens that count as New. eBay labels vary by API and by
# seller entry ("New with tags", "Brand New", "New (Other)"), so we match
# on a token basis rather than exact string — but ONLY these.
_NEW_TOKENS = frozenset({"new", "brandnew", "newwithtags", "newwithbox", "newother"})

# Everything else is explicitly not-New. Listed so an unknown label can
# never be silently treated as New by omission.
_NOT_NEW_TOKENS = frozenset({
    "used", "preowned", "pre-owned", "preownedowned", "secondhand", "second-hand",
    "refurbished", "sellerrefurbished", "certifiedrefurbished", "excellentrefurbished",
    "verygoodrefurbished", "goodrefurbished", "openbox", "open-box",
    "forparts", "forpartsornotworking", "damaged", "unspecified", "unknown",
})


def active_condition(filters: dict | None = None) -> str:
    """The condition this run must satisfy, read AT CALL TIME.

    Mirrors price_gate.active_bounds(): never an import-time constant.
    An invalid/unknown value falls back to the config default ("New")
    rather than opening the gate.
    """
    try:
        raw = (filters or load_filters()).get("condition", FILTERS["condition"])
    except Exception:
        raw = FILTERS["condition"]
    value = str(raw or "").strip()
    if value in ALLOWED_CONDITIONS:
        return value
    return FILTERS["condition"]


def normalize_condition(condition: str | None) -> str:
    """Collapse eBay's many condition labels to a comparable token.

    'New with tags' -> 'new'. 'Seller Refurbished' -> 'refurbished'.
    Empty / None -> '' (never 'new' — C10 fails closed).
    """
    if not condition:
        return ""
    cleaned = "".join(ch for ch in str(condition).lower() if ch.isalnum())
    if not cleaned:
        return ""
    if cleaned in _NEW_TOKENS:
        return "new"
    for token in _NOT_NEW_TOKENS:
        if cleaned == token or cleaned.startswith(token):
            return "refurbished" if "refurb" in token else (
                "used" if token in {"used", "preowned", "preownedowned",
                                    "secondhand", "second-hand"} else token
            )
    return cleaned


def is_new(condition: str | None) -> bool:
    """True only when the listing is affirmatively New.

    A blank or unparseable condition returns False — C10: we never assume.
    """
    return normalize_condition(condition) == "new"


def condition_passes(condition: str | None, required: str | None = None) -> bool:
    """Does this listing satisfy the ACTIVE required condition?

    v1 supports only New, but the required value comes from the active
    filter set so the verdict engine stops hardcoding 'new'.
    """
    want = normalize_condition(required if required is not None
                               else active_condition())
    if not want:
        return False
    return normalize_condition(condition) == want


def api_condition_filter(required: str | None = None) -> str:
    """Browse API filter fragment for the active condition (query time)."""
    if (normalize_condition(required if required is not None else active_condition())
            == "new"):
        return API_CONDITION_FILTER
    return ""


def html_condition_param(required: str | None = None) -> str:
    """HTML search parameter for the active condition (scrape fallback)."""
    if (normalize_condition(required if required is not None else active_condition())
            == "new"):
        return HTML_CONDITION_PARAM
    return ""


def filter_products_by_condition(products: list) -> tuple[list, int]:
    """Split products into (new_only, excluded_count) — C10 post-filter.

    Runs BEFORE supplier search and LLM spend so a Used listing never
    consumes budget. Works on any object with a `.condition` attribute.
    """
    required = active_condition()
    kept, excluded = [], 0
    for p in products:
        if condition_passes(getattr(p, "condition", None), required):
            kept.append(p)
        else:
            excluded += 1
    return kept, excluded


def filter_dicts_by_condition(rows: list[dict], key: str = "condition") -> tuple[list, int]:
    """Same gate for plain dict rows (API payloads, LLM output)."""
    required = active_condition()
    kept, excluded = [], 0
    for r in rows:
        if condition_passes(r.get(key), required):
            kept.append(r)
        else:
            excluded += 1
    return kept, excluded


def validate_condition(value) -> bool:
    """Allow-list check for the filters API (422 on anything but New)."""
    return isinstance(value, str) and value.strip() in ALLOWED_CONDITIONS
