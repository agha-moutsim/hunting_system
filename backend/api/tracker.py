"""Price Tracker CRUD + check endpoints."""

import logging

from fastapi import APIRouter, HTTPException

from api.schemas import TrackerCreate

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/tracker")
def list_tracker():
    from tracker import get_tracked_products

    return {"products": get_tracked_products()}


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
    return {"id": item.id, "product_name": item.product_name}


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
    from tracker import get_price_history, get_price_trend

    return {
        "history": get_price_history(tracked_id, days=days),
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
