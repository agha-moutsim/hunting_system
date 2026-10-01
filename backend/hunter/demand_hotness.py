"""Is this product HOT? A computed answer, never an assigned label.

The user asked for "hot items" in the Category Hunter. The trap is a badge
that is really a guess: showing "trending" because a product exists, or
because a number looked big. So the badge is derived from the two demand
counts we actually read off eBay, and when those counts are missing the
answer is "we do not know" rather than "not hot".

Definition used here:

    meets_demand  the 30d AND 7d counts clear the configured floors
    accelerating  the 7-day pace beats the 30-day pace
    hot           meets_demand AND accelerating

A product selling a steady 40 a month is not hot. One that went from ~5 a
month to ~30 is. Both facts are shown either way, so the user can judge the
call rather than trust it.
"""

from __future__ import annotations

from typing import Any

WEEKS_IN_MONTH = 4.345  # 30 / 7


def hotness(
    sold_30d: int,
    sold_7d: int,
    demand_min_30d: int,
    demand_min_7d: int,
) -> dict[str, Any]:
    """Decide whether a product is hot, and explain the decision.

    Returns a dict with `hot`, `meets_demand`, both paces, a short `basis`
    for the UI, and a `provenance` of "verified" (we read the counts) or
    "unverified" (we did not - C13).
    """
    s30 = _count(sold_30d)
    s7 = _count(sold_7d)

    if s30 <= 0 and s7 <= 0:
        # C1/C13 - no demand data is UNKNOWN, not "cold". Saying "not hot"
        # here would be a confident claim about something we never measured.
        return {
            "hot": False,
            "meets_demand": False,
            "pace_30d_per_week": None,
            "pace_7d_per_week": None,
            "basis": "no eBay sold data retrieved",
            "provenance": "unverified",
            "reason": "no eBay demand data, so trending cannot be assessed",
        }

    meets = s30 >= demand_min_30d and s7 >= demand_min_7d

    # The 7d count is a SUBSET of the 30d count, so comparing the two rates
    # directly would always lose. The baseline for the recent week is the
    # product's own pace over the weeks that are NOT in the window:
    #     baseline_per_week = (sold_30d - sold_7d) / (30 - 7)
    # A product is accelerating when its last 7 days beat that baseline.
    prior_total = max(0, s30 - s7)
    baseline_30 = prior_total / (30.0 - 7.0) if prior_total > 0 else None
    pace_7 = s7 / 7.0
    pace_30 = s30 / WEEKS_IN_MONTH

    if baseline_30 is None:
        # Everything sold was sold this week: fast, but there is no prior
        # period to have accelerated from, so the call is made on demand
        # floors alone and says so.
        accelerating = bool(s7 >= demand_min_7d)
        basis = (
            f"all {s7} sales in the last 7d, no earlier sales to compare; "
            f"clears the {demand_min_7d}/7d demand floor"
        )
    else:
        accelerating = pace_7 > baseline_30
        if accelerating:
            basis = (
                f"accelerating: {s7} in 7d ({pace_7:.1f}/wk) vs "
                f"{baseline_30:.1f}/wk over the previous 3 weeks"
            )
        else:
            basis = (
                f"steady or slowing: {s7} in 7d ({pace_7:.1f}/wk) vs "
                f"{baseline_30:.1f}/wk over the previous 3 weeks"
            )

    hot = bool(meets and accelerating)

    if not meets:
        # Demand floors come first: a fast week on a product nobody buys is
        # not an opportunity, and that is the reason worth showing.
        basis = (
            f"below demand floor: {s7} in 7d / {s30} in 30d "
            f"(needs {demand_min_7d} / {demand_min_30d})"
        )

    return {
        "hot": hot,
        "meets_demand": meets,
        "pace_30d_per_week": round(pace_30, 1),
        "pace_7d_per_week": round(pace_7, 1),
        "baseline_pace_per_week": (
            None if baseline_30 is None else round(baseline_30, 1)
        ),
        "basis": basis,
        "provenance": "verified",
        "reason": "",
    }


def _count(value: Any) -> int:
    """A sold count as a non-negative int; unread means 0."""
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, n)


def apply_hotness(products, demand_min_30d: int, demand_min_7d: int) -> None:
    """Stamp `hot` / `hot_basis` / `hot_provenance` onto each row, in place."""
    for p in products or []:
        result = hotness(
            getattr(p, "sold_30d", 0),
            getattr(p, "sold_7d", 0),
            demand_min_30d,
            demand_min_7d,
        )
        p.hot = result["hot"]
        p.hot_basis = result["basis"]
        p.hot_provenance = result["provenance"]
        p.hot_reason = result.get("reason", "")
        p.demand_pace_7d_per_week = result["pace_7d_per_week"]
        p.demand_pace_30d_per_week = result["pace_30d_per_week"]


def sort_key(p) -> tuple:
    """Rank hot + profitable rows first.

    Order: hot first, then margin, then 7-day pace. `hot` is a bool so False
    sorts after True; the negations keep "descending" for the numbers.
    """
    return (
        0 if getattr(p, "hot", False) else 1,
        -float(getattr(p, "margin", 0.0) or 0.0),
        -float(getattr(p, "demand_pace_7d_per_week", 0.0) or 0.0),
    )
