"""
Price range gate — CONSTRAINTS_PRICING.md PR-1..PR-4.

Single place that decides whether a price is inside the ACTIVE range
(default £5–£35, user-adjustable per PR-5/PR-7). Every layer (search,
selection, aggregation, display) calls these functions so the logic
can never drift between features. Supplier prices are exempt (PR-1) —
never route a supplier price through these functions.
"""

from config import FILTERS
from utils.filters import load_filters

# Config DEFAULTS (the fallback range) — callers that need the ACTIVE
# range must go through in_band()/band_label()/load_filters().
PRICE_MIN = FILTERS["price_min"]
PRICE_MAX = FILTERS["price_max"]


def _range() -> tuple[float, float]:
    f = load_filters()
    return f["price_min"], f["price_max"]


def active_bounds() -> tuple[float, float]:
    """Active (user-adjustable) range read AT CALL TIME — search-time layers
    (PR-2 layer 1) must push these into the eBay query, never import-time
    PRICE_MIN/PRICE_MAX defaults."""
    return _range()


def in_band(price: float | None) -> bool:
    """True when the price falls inside the active range (inclusive)."""
    return in_band_range(price, *_range())


def in_band_range(price: float | None, lo: float, hi: float) -> bool:
    """True when the price falls inside an EXPLICIT range (inclusive).

    Separate from `in_band` because a caller that searched eBay with a wider
    band must gate its results against THAT band. Re-checking the active range
    instead would throw away exactly the listings the wider search was for -
    which is what made competitor-store discovery return nothing
    (REGRESSION-006).
    """
    if price is None:
        return False
    try:
        p = float(price)
    except (TypeError, ValueError):
        return False
    return lo <= p <= hi


def band_label(
    price_range: tuple[float, float] | None = None,
    currency_symbol: str = "\u00a3",
) -> str:
    """Human-readable active range for messages: '£5.00–£35.00'.

    Pass an explicit range/symbol for a market whose band is not the active
    GBP one (e.g. the AU A$0.99–A$50.00 band). With no arguments this keeps
    the historical UK behaviour.
    """
    lo, hi = price_range if price_range is not None else _range()
    return f"{currency_symbol}{lo:.2f}\u2013{currency_symbol}{hi:.2f}"


def over_band_reason(
    price: float | None,
    price_range: tuple[float, float] | None = None,
    currency_symbol: str = "\u00a3",
) -> str:
    """Refusal sentence for an out-of-range price (PR-3 Case A)."""
    label = band_label(price_range, currency_symbol)
    try:
        p = float(price)
    except (TypeError, ValueError):
        return (
            f"This listing has no verified price \u2014 cannot confirm it is "
            f"inside {label}."
        )
    return (
        f"This listing is {currency_symbol}{p:.2f} \u2014 outside your "
        f"{label} range."
    )


def clamp_band(
    filters: dict | None,
    defaults: dict | None = None,
) -> dict:
    """Merge a filters dict over the full default set, keeping a VALID user
    range (PR-5/PR-7: config holds the defaults; the user may adjust).

    An invalid range (non-numeric, min >= max, out of sane bounds) falls
    back to the supplied defaults — the GBP config by default, or a market's
    own band when one is passed. That matters for AU: a bad A$ range must not
    silently become the GBP 5..35 band. A partial dict is merged over the full
    default filter set first, so callers never lose the non-price keys
    (demand/margin).
    """
    base = dict(FILTERS)
    if defaults:
        base.update(defaults)
    out = dict(base)
    out.update(filters or {})
    try:
        lo = float(out["price_min"])
        hi = float(out["price_max"])
        if not (0 < lo < hi <= 10000):
            raise ValueError
        out["price_min"] = lo
        out["price_max"] = hi
    except (TypeError, ValueError):
        out["price_min"] = base["price_min"]
        out["price_max"] = base["price_max"]
    return out


def filter_products(
    products: list,
    price_attr: str = "price",
    price_range: tuple[float, float] | None = None,
) -> tuple[list, int]:
    """Split products into (in_range, excluded_count) — PR-3 / PR-4.

    Works on any object with a numeric price attribute (ScrapedProduct,
    dicts are not supported — pass a getter value instead). `price_range`
    is the band the caller searched with; it is in that market's currency.
    """
    kept = []
    excluded = 0
    for p in products:
        price = getattr(p, price_attr, None)
        if price_range is not None:
            passed = in_band_range(price, *price_range)
        else:
            passed = in_band(price)
        if passed:
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


def excluded_note(
    kind: str,
    count: int,
    price_range: tuple[float, float] | None = None,
    currency_symbol: str = "\u00a3",
) -> str:
    """PR-4 transparency line, e.g. '4 sold listings excluded (not in £5–£35 range)'.

    Covers eBay-side exclusions only — supplier prices are never excluded
    by range (PR-1), so supplier kinds must never be passed here. The range
    and symbol belong to the market that produced the rows.
    """
    if count <= 0:
        return ""
    return (
        f"{count} {kind} excluded "
        f"(not in {band_label(price_range, currency_symbol)} range)"
    )
