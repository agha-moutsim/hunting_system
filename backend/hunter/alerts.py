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
from datetime import datetime
from typing import Optional

from db.models import DemandSnapshot, PriceAlert, PriceHistory, TrackedProduct


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


def _empty_report() -> dict:
    return {"products": 0, "comparisons": 0, "written": 0, "skipped": 0, "messages": []}


def _record(db, product_id: Optional[int], decision: AlertDecision, observed_at) -> bool:
    """Write one decision, unless the reading it describes is already alerted.

    The dedupe key is (product, type, compared price, message, reading time):
    running the same comparison twice - the tracker's inline check and the
    scheduled pass, for instance - writes one row, while a genuinely new
    reading that lands on the same price still gets its own row, because
    `created_at >= observed_at` stops being true once the reading is newer
    than the alert. The message takes part in the key so the item lane and
    the query lane can never shadow each other.
    """
    already = (
        db.query(PriceAlert)
        .filter(
            PriceAlert.tracked_product_id == product_id,
            PriceAlert.alert_type == decision.alert_type,
            PriceAlert.new_price == decision.new_price,
            PriceAlert.message == decision.message,
            PriceAlert.created_at >= observed_at,
        )
        .first()
    )
    if already is not None:
        return False

    db.add(
        PriceAlert(
            tracked_product_id=product_id,
            alert_type=decision.alert_type,
            message=decision.message,
            old_price=decision.old_price,
            new_price=decision.new_price,
            is_read=False,
            created_at=datetime.utcnow(),
        )
    )
    return True


def _apply(db, product_id, decisions, observed_at, report: dict) -> None:
    for decision in decisions:
        report["comparisons"] += 1
        if _record(db, product_id, decision, observed_at):
            report["written"] += 1
            report["messages"].append(decision.message)
        else:
            report["skipped"] += 1


def _compare_item_readings(db, product, report: dict) -> None:
    """One product's item lane: its two latest real readings and its target.

    Readings with no real price take no part: the failed checks of 2026-09-22
    wrote 0.0, and comparing against that would report a collapse to zero
    that nothing observed. A product with a single real reading can still
    earn its target row (price vs target are both real); only the change row
    needs two.
    """
    readings = (
        db.query(PriceHistory)
        .filter(
            PriceHistory.tracked_product_id == product.id,
            PriceHistory.ebay_price > 0,
        )
        .order_by(PriceHistory.checked_at.desc(), PriceHistory.id.desc())
        .limit(2)
        .all()
    )
    if not readings:
        return
    latest = readings[0]
    previous = readings[1] if len(readings) > 1 else None
    decisions = decide_alerts(
        previous.ebay_price if previous is not None else None,
        latest.ebay_price,
        label=product.product_name or "tracked item",
        price_label="item price",
        target=product.target_price,
        target_label="target price",
    )
    _apply(
        db,
        product.id,
        decisions,
        latest.checked_at or datetime.utcnow(),
        report,
    )


def generate_for_product(product_id: int) -> dict:
    """Compare one product's stored item readings and write what they earn.

    The unit the tracker's inline check needs: after it commits a new reading
    it calls this, so the alert comes from the same rule the scheduled pass
    uses - one event, one row, whichever runner did the comparing. A product
    with alerts switched off is left alone even when checked by hand.
    """
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        report = _empty_report()
        product = (
            db.query(TrackedProduct).filter(TrackedProduct.id == product_id).first()
        )
        if product is None:
            return report
        report["products"] = 1
        if product.alert_enabled:
            _compare_item_readings(db, product, report)
        db.commit()
        return report
    finally:
        db.close()


def generate_for_tracked_items() -> dict:
    """Compare every alert-enabled product's two most recent item readings."""
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        products = (
            db.query(TrackedProduct).filter(TrackedProduct.alert_enabled == True).all()  # noqa: E712
        )
        report = _empty_report()
        for product in products:
            report["products"] += 1
            _compare_item_readings(db, product, report)
        db.commit()
        return report
    finally:
        db.close()


def generate_for_monitored_queries() -> dict:
    """Compare the two most recent real average-price readings per query.

    The lane is `demand_snapshots.avg_price` - the average asking price of
    the live listings the demand monitor saw, a market reading rather than
    this item's price. The product's target price is deliberately NOT applied
    here: a price set for one listing cannot be compared against a market
    average without inventing what the result would mean.
    """
    from db.database import SessionLocal

    db = SessionLocal()
    try:
        products = (
            db.query(TrackedProduct).filter(TrackedProduct.alert_enabled == True).all()  # noqa: E712
        )
        report = _empty_report()
        seen: set = set()
        for product in products:
            query = (product.product_name or "").strip()
            if not query or query in seen:
                continue
            seen.add(query)
            report["products"] += 1
            readings = (
                db.query(DemandSnapshot)
                .filter(DemandSnapshot.query == query, DemandSnapshot.avg_price > 0)
                .order_by(DemandSnapshot.captured_at.desc(), DemandSnapshot.id.desc())
                .limit(2)
                .all()
            )
            if not readings:
                continue
            latest = readings[0]
            previous = readings[1] if len(readings) > 1 else None
            decisions = decide_alerts(
                previous.avg_price if previous is not None else None,
                latest.avg_price,
                label=query,
                price_label="average asking price",
            )
            _apply(
                db,
                product.id,
                decisions,
                latest.captured_at or datetime.utcnow(),
                report,
            )
        db.commit()
        return report
    finally:
        db.close()


def generate_alerts() -> dict:
    """Run both lanes once and report what each compared and wrote.

    Zero Browse calls: every comparison reads rows this app already stored
    (tracker price checks, demand-monitor runs). That is the budget the phase
    rule asks for - alerts first, at no quota cost.
    """
    return {
        "tracked_items": generate_for_tracked_items(),
        "monitored_queries": generate_for_monitored_queries(),
    }
