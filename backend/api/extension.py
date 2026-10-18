"""Browser-extension bridge — verified 7-day purchase-history captures (P5).

The purchase-history page is login-walled, so the only path to verified
7-day sales data (CONSTRAINTS.md C4) is the MV3 extension in extension/
posting the raw page HTML here. Nothing is ever fabricated: if the parser
cannot read the page, nothing is stored (C1).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from utils.purchase_history import parse_purchase_history

router = APIRouter()
logger = logging.getLogger(__name__)


class SoldHistoryCapture(BaseModel):
    item_id: str = Field(..., min_length=1)
    url: Optional[str] = None
    html: str  # raw purchase-history page HTML (required, may be unparseable)
    captured_at: Optional[str] = None  # ISO 8601, when the page was captured


def _normalise_captured_at(raw: Optional[str]) -> Optional[datetime]:
    """ISO string -> naive UTC datetime (repo convention); None if unusable."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _not_stored_reason(parsed: dict) -> str:
    if parsed["rows_seen"] == 0:
        return "No recognisable sale rows on the captured page."
    return (
        f"Found {parsed['rows_seen']} candidate row(s) but none had both "
        "a parseable date and a parseable price."
    )


@router.post("/extension/sold-history")
def capture_sold_history(req: SoldHistoryCapture):
    """Store a purchase-history capture. Never stores unparseable pages."""
    from db.database import SessionLocal
    from db.queries import upsert_purchase_capture

    # The 7/30-day windows are relative to when the page was captured.
    captured_at = _normalise_captured_at(req.captured_at) or datetime.utcnow()
    parsed = parse_purchase_history(req.html, now=captured_at)

    if parsed["sold_7d"] is None:
        reason = _not_stored_reason(parsed)
        logger.info("Purchase history NOT stored for item %s: %s", req.item_id, reason)
        return {"stored": False, "reason": reason}

    db = SessionLocal()
    try:
        row = upsert_purchase_capture(
            db,
            item_id=req.item_id,
            url=req.url,
            sold_7d=parsed["sold_7d"],
            sold_30d=parsed["sold_30d"],
            sales_json=json.dumps(parsed["sales"]),
            captured_at=captured_at,
        )
    finally:
        db.close()

    return {
        "stored": True,
        "item_id": row.item_id,
        "sold_7d": row.sold_7d,
        "sold_30d": row.sold_30d,
        "captured_at": row.captured_at.isoformat(),
    }


@router.get("/extension/sold-history/{item_id}")
def get_sold_history(item_id: str):
    """Latest capture for an item, or 404 with an {"error": ...} body."""
    from db.database import SessionLocal
    from db.queries import get_latest_purchase_capture

    db = SessionLocal()
    try:
        row = get_latest_purchase_capture(db, item_id)
    finally:
        db.close()

    if row is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"No purchase-history capture for item {item_id}"},
        )

    try:
        sales = json.loads(row.sales_json or "[]")
    except ValueError:
        sales = []
    return {
        "item_id": row.item_id,
        "sold_7d": row.sold_7d,
        "sold_30d": row.sold_30d,
        "sales": sales,
        "captured_at": row.captured_at.isoformat() if row.captured_at else None,
        "url": row.url,
        "source": row.source,
    }


@router.get("/extension/status")
def extension_status():
    """What the dataset actually holds — a pure read, nothing is fetched here.

    Exists so the extension popup can state the stored row count instead of
    inferring it from its own request counter.
    """
    from db.database import SessionLocal
    from db.queries import purchase_capture_stats

    db = SessionLocal()
    try:
        return purchase_capture_stats(db)
    finally:
        db.close()
