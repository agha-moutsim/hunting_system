"""Price Tracker CRUD + check endpoints."""

import logging

from fastapi import APIRouter, HTTPException

from api.schemas import TrackerCreate
from utils.filters import active_range, outside_range, price_in_range, resolve_range

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/tracker")
def list_tracker(price_min: float | None = None, price_max: float | None = None):
    """All tracked products — view-filtered by range, out-of-range rows flagged (PR-6)."""
    from tracker import get_tracked_products

    active = active_range()
    view = resolve_range(price_min, price_max)
    rows = []
    for product in get_tracked_products():
        if not price_in_range(product.get("ebay_price"), view):
            continue
        row = dict(product)
        row["outside_band"] = outside_range(product.get("ebay_price"), active)
        rows.append(row)
    return {"products": rows, "range_filter": view}


@router.post("/tracker")
def create_tracker(req: TrackerCreate):
    from tracker import add_to_tracker

    item = add_to_tracker(
        product_name=req.product_name,
        ebay_url=req.ebay_url,
        ebay_price=req.ebay_price,
        target_price=req.target_price,
        supplier_price=req.supplier_price,
        supplier_url=req.supplier_url,
        supplier_name=req.supplier_name,
    )
    if not item:
        raise HTTPException(status_code=500, detail="Failed to add product")
    return {
        "id": item.id,
        "product_name": item.product_name,
        "outside_band": outside_range(item.ebay_price, active_range()),
    }


@router.delete("/tracker/{tracked_id}")
def delete_tracker(tracked_id: int):
    from tracker import remove_from_tracker

    if not remove_from_tracker(tracked_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}


@router.post("/tracker/{tracked_id}/check")
def check_price(tracked_id: int):
    from tracker import check_single_price

    new_price = check_single_price(tracked_id)
    return {"new_price": new_price, "checked": new_price is not None}


@router.get("/tracker/{tracked_id}/history")
def price_history(tracked_id: int, days: int = 30):
    """Price history — stored regardless of range; points outside the active
    range are flagged, never hidden (PR-6 stores any price)."""
    from tracker import get_price_history, get_price_trend

    active = active_range()
    rows = get_price_history(tracked_id, days=days)
    for r in rows:
        r["outside_band"] = outside_range(r.get("ebay_price"), active)

    return {
        "history": rows,
        "trend": get_price_trend(tracked_id, days=min(days, 7)),
    }


@router.get("/tracker/alerts")
def list_alerts(unread_only: bool = False, limit: int = 50):
    from tracker import get_alerts

    return {"alerts": get_alerts(unread_only=unread_only, limit=limit)}


@router.post("/tracker/alerts/{alert_id}/read")
def mark_alert_read(alert_id: int):
    from tracker import mark_alert_read

    return {"ok": mark_alert_read(alert_id)}
