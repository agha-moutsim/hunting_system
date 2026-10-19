"""Alert decisions: which price comparisons earn a `price_alerts` row.

Phase E. `price_alerts` was a table nothing wrote to; this module is the one
place that decides whether a comparison deserves a row, and every decision
carries the two values it compared.

The rules from the phase spec are refusals first:

  * An alert must name the two values it compared. No comparison, no row.
  * A missing price never generates a price alert. In this database "unread"
    appears as `NULL` or as the tracker's older `0.0` writer (see the
    `price_history` rows from 2026-09-22, written when the page could not be
    read). Neither is a price, so a comparison that needs one is dropped
    rather than defaulted - a zero invented here would read later as a real
    collapse.
  * Prices are compared to the penny, the precision this app shows and
    charges in, so float noise is not a change.

What this module deliberately does not do: decide how big a change must be to
matter, how loud it should be, or how it is displayed. It answers one
question - did these two readings differ, and by how much - and returns the
sentence that names them, so the caller can store it verbatim.
"""

from dataclasses import dataclass
from typing import Optional

#: Every comparison in this module happens at the penny.
_PENNY = 0.01


@dataclass(frozen=True)
class AlertDecision:
    """One row `price_alerts` should carry, with the comparison that earned it.

    `old_price` and `new_price` are the two values compared - for a target row
    they are the target and the latest reading - and `message` names both in
    words. A decision that cannot state its comparison is never constructed:
    the fields exist to make that visible to a reader of the row.
    """

    alert_type: str  # price_drop | price_increase | target_hit
    old_price: float
    new_price: float
    message: str


def _penny(value: Optional[float]) -> Optional[float]:
    """The reading as this app shows it (2dp), or None when there is no reading.

    Zero and negatives are not readings: the tracker's price checks write 0.0
    when the page could not be read, and a price that cannot exist is not a
    price. `None` (never read) and `0.0` (read as nothing) both mean "no
    comparison is possible", which is a different fact from "free".
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return round(number, 2)


def decide_alerts(
    previous: Optional[float],
    latest: Optional[float],
    *,
    label: str,
    price_label: str = "price",
    target: Optional[float] = None,
    target_label: str = "target",
    target_type: str = "target_hit",
) -> list[AlertDecision]:
    """Every alert these readings earn - usually none, sometimes two.

    `previous` and `latest` are the two observations, oldest first. The price
    change needs BOTH readings real; the target comparison needs the target
    and the latest reading real (it is a comparison between those two, so a
    missing previous does not stop it).

    `label` names what was observed and `price_label` says what kind of price
    it is - "item price" for one listing, "average asking price" for a query -
    because the row must be honest about the thing it measured, not just the
    numbers.
    """
    decisions: list[AlertDecision] = []

    before = _penny(previous)
    after = _penny(latest)

    if before is not None and after is not None and before != after:
        dropped = after < before
        decisions.append(
            AlertDecision(
                alert_type="price_drop" if dropped else "price_increase",
                old_price=before,
                new_price=after,
                message=(
                    f"{label} {price_label} "
                    f"{'dropped' if dropped else 'rose'} "
                    f"from £{before:.2f} to £{after:.2f}"
                ),
            )
        )

    goal = _penny(target)
    if goal is not None and after is not None and after <= goal:
        decisions.append(
            AlertDecision(
                alert_type=target_type,
                old_price=goal,
                new_price=after,
                message=(
                    f"{label} {price_label} is £{after:.2f} - at or below "
                    f"your £{goal:.2f} {target_label}"
                ),
            )
        )

    return decisions
