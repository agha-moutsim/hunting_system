"""The alerts inbox - a pure read of the stored price_alerts rows.

Why the route does not generate: comparing prices costs nothing, but doing
it inside a page request would make the inbox mirror the viewer - an alert
would only come into existence once someone opened the page, which is the
opposite of a tool that pushes. The comparisons are written by hunter.alerts
(the tracker's inline check and the scheduled pass); this route reports the
rows and the unread count, and flips the read flag.

Nothing here invents a value. A row only exists if the comparison that
earned it named two real readings (see hunter/alerts.py), so the stored
message is returned verbatim rather than re-rendered.
"""

import logging

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
logger = logging.getLogger(__name__)

#: The alert types this app writes. Kept here for the query door's refusal
#: message; the writing side is hunter.alerts.
KNOWN_TYPES = ("price_drop", "price_increase", "target_hit", "margin_alert")


def _row(alert) -> dict:
    return {
        "id": alert.id,
        "product_id": alert.tracked_product_id,
        "product_name": (
            alert.tracked_product.product_name if alert.tracked_product else ""
        ),
        "alert_type": alert.alert_type,
        "message": alert.message,
        "old_price": alert.old_price,
        "new_price": alert.new_price,
        "is_read": bool(alert.is_read),
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
    }


@router.get("/alerts")
def list_alerts(
    unread_only: bool = Query(False),
    alert_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """The inbox, newest first.

    `alert_type` may be a comma-separated list so a tab like "Price" can ask
    for the two price-change types in one request. An unknown type is refused
    with the known ones listed - silently returning an empty inbox for a
    typo would look like "nothing happened", which is a lie with a delay.
    """
    from db.database import SessionLocal
    from db.models import PriceAlert, TrackedProduct

    types = None
    if alert_type:
        types = [part.strip() for part in alert_type.split(",") if part.strip()]
        unknown = [part for part in types if part not in KNOWN_TYPES]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"unknown alert_type {unknown[0]!r}; "
                    f"known types: {list(KNOWN_TYPES)}"
                ),
            )

    db = SessionLocal()
    try:
        # outerjoin: an alert without a tracked product must not silently
        # vanish from the inbox (the bug class the legacy reader has).
        query = db.query(PriceAlert).outerjoin(
            TrackedProduct, PriceAlert.tracked_product_id == TrackedProduct.id
        )
        if unread_only:
            query = query.filter(PriceAlert.is_read == False)  # noqa: E712
        if types:
            query = query.filter(PriceAlert.alert_type.in_(types))

        total = query.count()
        unread = (
            db.query(PriceAlert).filter(PriceAlert.is_read == False).count()  # noqa: E712
        )
        rows = (
            query.order_by(PriceAlert.created_at.desc(), PriceAlert.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "alerts": [_row(alert) for alert in rows],
            "count": len(rows),
            "total": total,
            "unread": unread,
        }
    finally:
        db.close()


@router.get("/alerts/count")
def unread_count():
    """Just the number, for the sidebar badge."""
    from db.database import SessionLocal
    from db.models import PriceAlert

    db = SessionLocal()
    try:
        unread = (
            db.query(PriceAlert).filter(PriceAlert.is_read == False).count()  # noqa: E712
        )
        return {"unread": unread}
    finally:
        db.close()


@router.post("/alerts/read-all")
def mark_all_read():
    """Mark every unread alert read, in one call - the inbox's 'mark all'."""
    from db.database import SessionLocal
    from db.models import PriceAlert

    db = SessionLocal()
    try:
        marked = (
            db.query(PriceAlert)
            .filter(PriceAlert.is_read == False)  # noqa: E712
            .update({PriceAlert.is_read: True})
        )
        db.commit()
        return {"ok": True, "marked": marked, "unread": 0}
    finally:
        db.close()


@router.post("/alerts/{alert_id}/read")
def mark_read(alert_id: int):
    """Mark one alert read.

    404 when the id does not exist: a silent ok would let a UI bug look like
    a working click, and the unread badge would keep arguing with the row.
    """
    from db.database import SessionLocal
    from db.models import PriceAlert

    db = SessionLocal()
    try:
        alert = db.query(PriceAlert).filter(PriceAlert.id == alert_id).first()
        if alert is None:
            raise HTTPException(status_code=404, detail=f"no alert with id {alert_id}")
        alert.is_read = True
        db.commit()
        unread = (
            db.query(PriceAlert).filter(PriceAlert.is_read == False).count()  # noqa: E712
        )
        return {"ok": True, "unread": unread}
    finally:
        db.close()
