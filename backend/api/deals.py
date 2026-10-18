"""The deals board endpoint — a pure read of the stored eBay deals pool.

Why the route does not fetch: pricing the cards costs 108 Browse calls for a
full page (measured — one per card, plus a second for the cards whose bare
legacy id does not resolve). Waiting on that inside a request would time out,
and doing it per page view would spend the 5,000/day allowance in under a
couple of hours of one tab being left open. So the pool is refreshed by
`backend/scripts/run_deals_refresh.py` on a schedule, and this route reports how
old what it returns actually is rather than implying it is live.

The board is eBay's own curated discount page. It is NOT a best-seller list and
carries no sold count, because none is measurable from this app (see
scrapers/ebay_deals.py for what was measured and rejected).
"""

import logging

from fastapi import APIRouter, Query

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/deals")
def list_deals(
    limit: int = Query(0, ge=0, le=200),
    refresh: bool = Query(False),
):
    """Every stored deal, in the order eBay presented them.

    `limit=0` (the default) returns the whole pool, because the client rotates
    through it a window at a time and needs the pool, not a page of it.

    When the pool is empty or past its TTL and auto-refresh is allowed, a
    refresh starts on a worker thread so the caller still gets an immediate
    answer. The response always carries `stale` and `age_seconds`, so a client
    can say how old the data is instead of pretending it is fresh.
    """
    from db.database import SessionLocal
    from hunter import deals

    db = SessionLocal()
    try:
        meta = deals.board_meta(db)
        wants_refresh = refresh or (
            deals.auto_refresh_enabled() and (meta["stale"] or not meta["total"])
        )
        if wants_refresh:
            deals.start_background_refresh()
        meta["refresh_started"] = wants_refresh

        items = deals.load_deals(db, limit or None)
        return {"meta": meta, "count": len(items), "items": items}
    finally:
        db.close()


@router.post("/deals/refresh")
def refresh_deals(
    limit: int = Query(0, ge=0, le=200),
    enrich: bool = Query(True),
):
    """Fetch eBay's deals page and store it. Synchronous.

    The scheduled job uses this; so does setting up a fresh install, where it
    is quicker to wait once here than to poll the read endpoint until the
    worker thread has finished. `limit` prices only the first N cards and is
    the cheap way to check the pipeline end to end.
    """
    from hunter import deals

    result = deals.refresh(limit=limit or None, enrich=enrich)
    return result
