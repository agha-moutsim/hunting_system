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
    return (
        f"This listing is \u00a3{float(price):.2f} \u2014 outside your "
        f"{band_label()} band."
    )


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
    """PR-4 transparency line, e.g. '4 supplier matches excluded (over £35)'."""
    if count <= 0:
        return ""
    return f"{count} {kind} excluded (over \u00a3{PRICE_MAX:.0f})"
