"""
Price band gate — CONSTRAINTS_PRICING.md PR-1..PR-4.

Single place that decides whether a price is inside the £5–£35 band.
Every layer (search, selection, aggregation, display) calls these
functions so the logic can never drift between features.
"""

from config import FILTERS

PRICE_MIN = FILTERS["price_min"]
PRICE_MAX = FILTERS["price_max"]


def in_band(price: float | None) -> bool:
    """True when the price falls inside the hard band (inclusive)."""
    if price is None:
        return False
    try:
        p = float(price)
    except (TypeError, ValueError):
        return False
    return PRICE_MIN <= p <= PRICE_MAX


def band_label() -> str:
    """Human-readable band for messages: '£5.00–£35.00'."""
    return f"\u00a3{PRICE_MIN:.2f}\u2013\u00a3{PRICE_MAX:.2f}"


def over_band_reason(price: float | None) -> str:
    """Refusal sentence for an out-of-band price (PR-3 Case A)."""
    try:
        p = float(price)
    except (TypeError, ValueError):
        # Never print a fabricated figure (C1) — no price, no number.
        return (
            f"This listing has no verified price \u2014 cannot confirm it is "
            f"inside {band_label()}."
        )
    return (
        f"This listing is \u00a3{p:.2f} \u2014 outside your "
        f"{band_label()} band."
    )


def clamp_band(filters: dict | None) -> dict:
    """Force the price band onto a filters dict from config (PR-5/PR-7).

    Client-supplied or persisted filters may carry any band; the gate
    always wins. A partial dict is merged over the full default filter
    set first, so callers never lose the non-price keys (demand/margin).
    """
    out = dict(FILTERS)
    out.update(filters or {})
    out["price_min"] = PRICE_MIN
    out["price_max"] = PRICE_MAX
    return out


def filter_products(products: list, price_attr: str = "price") -> tuple[list, int]:
    """Split products into (in_band, excluded_count) — PR-3 Case D / PR-4.

    Works on any object with a numeric price attribute (ScrapedProduct,
    dicts are not supported — pass a getter value instead).
    """
    kept = []
    excluded = 0
    for p in products:
        if in_band(getattr(p, price_attr, None)):
            kept.append(p)
        else:
            excluded += 1
    return kept, excluded


def filter_dicts(rows: list[dict], key: str = "price") -> tuple[list[dict], int]:
    """Same gate for plain dict rows (LLM output, API payloads)."""
    kept = []
    excluded = 0
    for r in rows:
        if in_band(r.get(key)):
            kept.append(r)
        else:
            excluded += 1
    return kept, excluded


def excluded_note(kind: str, count: int) -> str:
    """PR-4 transparency line, e.g. '4 supplier matches excluded (not in £5–£35 band)'.

    Wording covers every exclusion reason (over £35, under £5, missing price)
    so the note never claims a direction the data didn't have.
    """
    if count <= 0:
        return ""
    return f"{count} {kind} excluded (not in {band_label()} band)"
