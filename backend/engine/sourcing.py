"""Sourcing policy — one deterministic rule for "best supplier" everywhere.

Every product-discovery feature (Analyze, Deep Search, Bulk, Category Hunter)
scores and ranks supplier rows through this module, so two features can never
disagree about which supplier is preferred for the same evidence.

The policy is code, not a model: no LLM, no guessed thresholds hidden in
prompts, no fabricated availability. Missing evidence stays missing and is
reported as a reason rather than being treated as a pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

SOURCING_POLICY_VERSION = "sourcing-policy-v1"

# A rating at or above this counts as "good customer reviews". A lower verified
# rating is still real evidence and is ranked, but it is not a preferred option.
DEFAULT_MIN_REVIEW_RATING = 4.0

# Stock states the source actually printed. Anything else is unknown.
_IN_STOCK_STATES = frozenset({"in_stock", "low_stock"})
_OUT_OF_STOCK_STATES = frozenset({"out_of_stock"})

# A zero shipping figure is only a measurement when the source printed the
# zero in a currency it names. `A$0.00` and `AUD 0.00` are as real as
# `£0.00`; an unqualified "0" is still unknown (C1).
_ZERO_SHIPPING = re.compile(
    r"(?:£|gbp|pounds?|a\$|aud)\s*0(?:\.0+)?\b"
    r"|0(?:\.0+)?\s*(?:£|gbp|pounds?|a\$|aud)"
)


@dataclass(frozen=True)
class SourcingAssessment:
    """One supplier's sourcing verdict and the evidence behind it."""

    preferred: bool
    eligible: bool
    reasons: tuple[str, ...]
    total_landed_cost: Optional[float]
    review_verified: bool
    review_rating: Optional[float]
    review_count: Optional[int]
    review_good: bool
    stock_status: str
    stock_verified: bool
    shipping_known: bool
    shipping_cost: Optional[float]
    standard_shipping_applicable: bool
    standard_shipping_available: Optional[bool]
    standard_shipping_cost: Optional[float]
    standard_shipping_days_min: Optional[int]
    standard_shipping_days_max: Optional[int]
    delivery_days: Optional[int]
    product_match_verified: bool
    sourcing_score: float
    policy_version: str = SOURCING_POLICY_VERSION


def _get(product: Any, name: str, default: Any = None) -> Any:
    """Read a field from a ScrapedProduct or a supplier dict."""
    if isinstance(product, Mapping):
        return product.get(name, default)
    return getattr(product, name, default)


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def _parse_review(product: Any) -> tuple[Optional[float], Optional[int], bool]:
    """Return (rating, count, verified) from real review fields only."""
    rating = _as_float(_get(product, "review_rating"))
    count = _as_int(_get(product, "review_count"))

    if rating is None:
        raw = _get(product, "seller_rating")
        if isinstance(raw, str) and raw.strip():
            match = re.search(r"(\d+(?:\.\d+)?)\s*(?:/|out of)\s*5", raw, re.I)
            if match:
                rating = _as_float(match.group(1))
            else:
                match = re.search(
                    r"\b([0-5](?:\.\d+)?)\b(?:\s*\(([\d,]+)\))?",
                    raw,
                    re.I,
                )
                if match:
                    rating = _as_float(match.group(1))
                    if count is None and match.group(2):
                        count = _as_int(match.group(2))
            if count is None:
                count_match = re.search(r"\(([\d,]+)\)", raw)
                if not count_match:
                    count_match = re.search(r"([\d,]+)\s*reviews?\b", raw, re.I)
                if count_match:
                    count = _as_int(count_match.group(1))

    if rating is None or not (0.0 <= rating <= 5.0):
        return None, count, False
    return rating, count, True


def _shipping_known(product: Any) -> bool:
    """Whether the source actually stated a shipping cost.

    0.0 is ambiguous by design: it can mean "free" or "unread". The raw text
    is the only way to tell them apart.
    """
    cost = _as_float(_get(product, "shipping_cost", 0.0)) or 0.0
    raw = str(_get(product, "shipping_raw", "") or "").strip()
    if cost > 0:
        return True
    if cost == 0.0 and raw:
        low = raw.lower()
        if "free" in low:
            return True
        if _ZERO_SHIPPING.search(low):
            return True
    return False


def _shipping_cost(product: Any) -> Optional[float]:
    if not _shipping_known(product):
        return None
    cost = _as_float(_get(product, "shipping_cost", 0.0))
    return 0.0 if cost is None else cost


def _delivery_days(product: Any) -> Optional[int]:
    days = _as_int(_get(product, "shipping_days"))
    if days is not None and days > 0:
        return days
    lo = _as_int(_get(product, "delivery_days_min"))
    hi = _as_int(_get(product, "delivery_days_max"))
    if hi is not None and hi > 0:
        return hi
    if lo is not None and lo > 0:
        return lo
    return None


def _stock_state(product: Any) -> str:
    state = str(_get(product, "in_stock", "") or "").strip().lower()
    if state:
        return state
    raw = str(_get(product, "stock_raw", "") or "").strip()
    if raw:
        low = raw.lower()
        if "out of stock" in low or "sold out" in low or "unavailable" in low:
            return "out_of_stock"
        if "low stock" in low or "limited" in low or "only" in low:
            return "low_stock"
        if "in stock" in low or "available" in low:
            return "in_stock"
    return ""


def _aliexpress_standard_shipping(
    product: Any,
) -> tuple[Optional[bool], Optional[float], Optional[int], Optional[int], str]:
    """Read AliExpress standard shipping from real fields only."""
    available = _get(product, "standard_shipping_available")
    if isinstance(available, str):
        low = available.strip().lower()
        if low in {"true", "yes", "available"}:
            available = True
        elif low in {"false", "no", "unavailable"}:
            available = False
        else:
            available = None
    if not isinstance(available, bool):
        available = None

    cost = _as_float(_get(product, "standard_shipping_cost"))
    if cost is None and available is True:
        cost = _shipping_cost(product)
    days_min = _as_int(_get(product, "standard_shipping_days_min"))
    days_max = _as_int(_get(product, "standard_shipping_days_max"))
    raw = str(_get(product, "standard_shipping_raw", "") or "").strip()
    if not raw:
        raw = str(_get(product, "shipping_raw", "") or "").strip()

    if available is True:
        if cost is None:
            cost = _shipping_cost(product)
        if days_min is None:
            days_min = _as_int(_get(product, "shipping_days"))
        if days_max is None:
            days_max = days_min

    return available, cost, days_min, days_max, raw


def _reasons(product: Any, assessment_partial: dict) -> list[str]:
    reasons: list[str] = []
    if not assessment_partial["product_match_verified"]:
        reasons.append("product match not verified")
    price = _as_float(_get(product, "price"))
    if price is None or price <= 0:
        reasons.append("product price not read")
    stock_status = assessment_partial["stock_status"]
    if stock_status == "out_of_stock":
        reasons.append("out of stock")
    elif stock_status != "in_stock" and stock_status != "low_stock":
        reasons.append("stock status not verified")
    elif stock_status == "low_stock":
        reasons.append("low stock")
    if not assessment_partial["shipping_known"]:
        reasons.append("shipping cost not read")
    if assessment_partial["standard_shipping_applicable"]:
        if assessment_partial["standard_shipping_available"] is False:
            reasons.append("AliExpress Standard Shipping unavailable")
        elif assessment_partial["standard_shipping_available"] is None:
            reasons.append("AliExpress Standard Shipping not verified")
        elif assessment_partial["standard_shipping_cost"] is None:
            reasons.append("AliExpress Standard Shipping cost not read")
        elif assessment_partial["standard_shipping_days_min"] is None and assessment_partial["standard_shipping_days_max"] is None:
            reasons.append("AliExpress Standard Shipping estimate not read")
    if not assessment_partial["review_verified"]:
        reasons.append("review rating not read")
    elif not assessment_partial["review_good"]:
        if assessment_partial["review_count"] is None:
            reasons.append("review count not read")
        else:
            reasons.append("review rating below preferred threshold")
    url = str(_get(product, "url", "") or "").strip()
    if not url.startswith(("http://", "https://")):
        reasons.append("verified listing URL missing")
    if not bool(_get(product, "verified", True)):
        reasons.append("source not verified")
    return reasons


def assess_supplier(product: Any, destination_market: str = "GB") -> SourcingAssessment:
    """Assess one supplier row without comparing it to peers."""
    source = str(_get(product, "source", "") or "")
    price = _as_float(_get(product, "price"))
    shipping_known = _shipping_known(product)
    shipping_cost = _shipping_cost(product)
    stock_status = _stock_state(product)
    stock_verified = bool(stock_status or str(_get(product, "stock_raw", "") or "").strip())
    stock_available = stock_status in _IN_STOCK_STATES
    match_tier = str(_get(product, "match_tier", "") or "")
    product_match_verified = match_tier == "verified"
    review_rating, review_count, review_verified = _parse_review(product)
    # A verified rating with no verified review volume is real evidence of a
    # score, but not of "good customer reviews": the count is what makes the
    # feedback auditable. Missing volume is reported, not treated as good.
    review_good = (
        review_verified
        and review_rating is not None
        and review_rating >= DEFAULT_MIN_REVIEW_RATING
        and review_count is not None
        and review_count > 0
    )

    is_aliexpress = source.lower().startswith("aliexpress")
    standard_available, standard_cost, standard_min, standard_max, standard_raw = (
        _aliexpress_standard_shipping(product) if is_aliexpress
        else (None, None, None, None, "")
    )
    standard_applicable = is_aliexpress

    # When AliExpress Standard Shipping is the verified method, its cost is
    # the cost that matters. A generic shipping figure from the same card is
    # not a substitute for the method we actually require.
    if standard_applicable and standard_available is True and standard_cost is not None:
        standard_known = standard_cost > 0 or (
            standard_cost == 0
            and bool(standard_raw)
            and ("free" in standard_raw.lower()
                 or bool(_ZERO_SHIPPING.search(standard_raw.lower())))
        )
        if standard_known:
            shipping_known = True
            shipping_cost = standard_cost

    total = None
    if price is not None and price > 0 and shipping_known and shipping_cost is not None:
        total = price + shipping_cost

    partial = {
        "product_match_verified": product_match_verified,
        "stock_status": stock_status,
        "shipping_known": shipping_known,
        "standard_shipping_applicable": standard_applicable,
        "standard_shipping_available": standard_available,
        "standard_shipping_cost": standard_cost,
        "standard_shipping_days_min": standard_min,
        "standard_shipping_days_max": standard_max,
        "review_verified": review_verified,
        "review_good": review_good,
        "review_count": review_count,
    }
    reasons = _reasons(product, partial)

    mandatory_ok = (
        price is not None and price > 0
        and product_match_verified
        and stock_available
        and shipping_known
        and (not standard_applicable or standard_available is True)
        and (not standard_applicable or standard_cost is not None)
        and bool(str(_get(product, "url", "") or "").strip().startswith(("http://", "https://")))
        and bool(_get(product, "verified", True))
    )
    if standard_applicable and standard_available is True:
        if standard_min is None and standard_max is None:
            mandatory_ok = False
    # Mandatory failures make a supplier non-preferred. Missing review data
    # is reported, but it is a ranking signal rather than a mandatory gate:
    # a verified, in-stock, shipped product is still a usable option when no
    # review was read.
    preferred = mandatory_ok

    delivery_days = _delivery_days(product)
    if standard_applicable and standard_available is True:
        if standard_min is not None or standard_max is not None:
            delivery_days = standard_max or standard_min or delivery_days

    return SourcingAssessment(
        preferred=preferred,
        eligible=mandatory_ok,
        reasons=tuple(reasons),
        total_landed_cost=total,
        review_verified=review_verified,
        review_rating=review_rating,
        review_count=review_count,
        review_good=review_good,
        stock_status=stock_status or "unknown",
        stock_verified=stock_verified,
        shipping_known=shipping_known,
        shipping_cost=shipping_cost,
        standard_shipping_applicable=standard_applicable,
        standard_shipping_available=standard_available,
        standard_shipping_cost=standard_cost,
        standard_shipping_days_min=standard_min,
        standard_shipping_days_max=standard_max,
        delivery_days=delivery_days,
        product_match_verified=product_match_verified,
        sourcing_score=0.0,
        policy_version=SOURCING_POLICY_VERSION,
    )


def _normalize(values: list[Optional[float]], higher_is_better: bool) -> list[float]:
    """Normalize a list, treating missing values as 0.0."""
    present = [v for v in values if v is not None]
    if not present:
        return [0.0 for _ in values]
    lo = min(present)
    hi = max(present)
    if hi == lo:
        return [100.0 if v is not None else 0.0 for v in values]
    out: list[float] = []
    for value in values:
        if value is None:
            out.append(0.0)
            continue
        if higher_is_better:
            out.append(100.0 * (value - lo) / (hi - lo))
        else:
            out.append(100.0 * (hi - value) / (hi - lo))
    return out


def rank_suppliers(
    products: Iterable[Any],
    destination_market: str = "GB",
) -> list[tuple[Any, SourcingAssessment]]:
    """Assess and rank suppliers. Returns (product, assessment) pairs."""
    product_list = list(products)
    assessments = [assess_supplier(p, destination_market) for p in product_list]

    totals = [a.total_landed_cost for a in assessments]
    review_ratings = [
        a.review_rating if a.review_verified else None for a in assessments
    ]
    delivery_days = [a.delivery_days for a in assessments]
    stock_scores = [
        100.0 if a.stock_status == "in_stock"
        else 50.0 if a.stock_status == "low_stock"
        else 0.0
        for a in assessments
    ]
    match_scores = [
        (_get(p, "match_score", 0.0) or 0.0) * 100.0 for p in product_list
    ]
    supplier_reliability = [
        min(100.0, float(a.review_count)) if a.review_count is not None else 0.0
        for a in assessments
    ]

    cost_scores = _normalize(totals, higher_is_better=False)
    review_scores = _normalize(review_ratings, higher_is_better=True)
    delivery_scores = _normalize(delivery_days, higher_is_better=False)

    scored: list[tuple[Any, SourcingAssessment]] = []
    for index, (product, assessment) in enumerate(zip(product_list, assessments)):
        score = (
            0.35 * cost_scores[index]
            + 0.20 * review_scores[index]
            + 0.15 * delivery_scores[index]
            + 0.15 * stock_scores[index]
            + 0.10 * match_scores[index]
            + 0.05 * supplier_reliability[index]
        )
        assessment = SourcingAssessment(
            preferred=assessment.preferred,
            eligible=assessment.eligible,
            reasons=assessment.reasons,
            total_landed_cost=assessment.total_landed_cost,
            review_verified=assessment.review_verified,
            review_rating=assessment.review_rating,
            review_count=assessment.review_count,
            review_good=assessment.review_good,
            stock_status=assessment.stock_status,
            stock_verified=assessment.stock_verified,
            shipping_known=assessment.shipping_known,
            shipping_cost=assessment.shipping_cost,
            standard_shipping_applicable=assessment.standard_shipping_applicable,
            standard_shipping_available=assessment.standard_shipping_available,
            standard_shipping_cost=assessment.standard_shipping_cost,
            standard_shipping_days_min=assessment.standard_shipping_days_min,
            standard_shipping_days_max=assessment.standard_shipping_days_max,
            delivery_days=assessment.delivery_days,
            product_match_verified=assessment.product_match_verified,
            sourcing_score=round(score, 1),
            policy_version=assessment.policy_version,
        )
        scored.append((product, assessment))

    def sort_key(item: tuple[Any, SourcingAssessment]) -> tuple:
        product, assessment = item
        price = _as_float(_get(product, "price"))
        total = assessment.total_landed_cost
        review_rating = assessment.review_rating if assessment.review_verified else None
        shipping = assessment.shipping_cost if assessment.shipping_known else None
        days = assessment.delivery_days
        source = str(_get(product, "source", "") or "")
        url = str(_get(product, "url", "") or "")
        return (
            0 if assessment.preferred else 1,
            0 if total is not None else 1,
            total if total is not None else float("inf"),
            0 if assessment.review_good else 1,
            -(review_rating or 0.0),
            0 if assessment.review_verified else 1,
            shipping if shipping is not None else float("inf"),
            days if days is not None else 10**9,
            price if price is not None else float("inf"),
            source,
            url,
        )

    scored.sort(key=sort_key)
    return scored


def apply_assessment(product: Any, assessment: SourcingAssessment) -> None:
    """Write an assessment back onto a product or supplier dict."""
    values = {
        "sourcing_preferred": assessment.preferred,
        "sourcing_eligible": assessment.eligible,
        "sourcing_reasons": list(assessment.reasons),
        "total_landed_cost": assessment.total_landed_cost,
        "review_verified": assessment.review_verified,
        "review_rating": assessment.review_rating,
        "review_count": assessment.review_count,
        "review_good": assessment.review_good,
        "stock_status": assessment.stock_status,
        "stock_verified": assessment.stock_verified,
        "shipping_known": assessment.shipping_known,
        "shipping_cost": assessment.shipping_cost,
        "standard_shipping_available": assessment.standard_shipping_available,
        "standard_shipping_cost": assessment.standard_shipping_cost,
        "standard_shipping_days_min": assessment.standard_shipping_days_min,
        "standard_shipping_days_max": assessment.standard_shipping_days_max,
        "delivery_days": assessment.delivery_days,
        "product_match_verified": assessment.product_match_verified,
        "sourcing_score": assessment.sourcing_score,
        "sourcing_policy_version": assessment.policy_version,
    }
    if isinstance(product, Mapping):
        product.update(values)
    else:
        for key, value in values.items():
            setattr(product, key, value)


# Public name for callers that need to know whether a shipping cost was read.
shipping_is_known = _shipping_known


def apply_ranking(products: Iterable[Any], destination_market: str = "GB") -> list[Any]:
    """Rank suppliers in place and return them in ranked order."""
    ranked = rank_suppliers(products, destination_market)
    ordered: list[Any] = []
    for product, assessment in ranked:
        apply_assessment(product, assessment)
        ordered.append(product)
    return ordered
