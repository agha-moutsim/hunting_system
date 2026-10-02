"""Demand monitor endpoints - run the watchlist sampler and read trends.

Why this exists: a real 7-day trend needs the same product observed more
than once over a week, which is why a single search never has one. This
appends one real, timestamped count per run, so after a few days the Hot
Items 7d window stops being empty and starts meaning something.
"""

import logging

from fastapi import APIRouter, Query

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/demand-monitor/run")
def run_demand_monitor():
    """Sample every tracked product and record a real sold-count.

    Each tracked product costs one eBay Browse call, so 20 products sampled
    every 6 hours is ~80 calls/day - a rounding error against the 5,000/day
    budget. That is the intelligent use of the capacity: one observation per
    product per run, so trends become real instead of estimated.
    """
    from db.database import SessionLocal
    from db.models import TrackedProduct
    from hunter.demand_monitor import fetch_and_record

    db = SessionLocal()
    try:
        products = (
            db.query(TrackedProduct)
            .filter(TrackedProduct.alert_enabled == True)  # noqa: E712
            .all()
        )
        sampled = 0
        errors = 0
        for p in products:
            try:
                fetch_and_record(p.product_name, source="track_monitor")
                sampled += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("demand monitor failed for %r: %s", p.product_name, e)
                errors += 1
        return {
            "sampled": sampled,
            "errors": errors,
            "tracked_total": len(products),
            "note": (
                "one real eBay call per tracked product sampled; a verified "
                "7d trend needs at least two snapshots ~24h apart"
            ),
        }
    finally:
        db.close()


@router.get("/demand-monitor/trend")
def demand_trend(query: str = Query(..., min_length=1)):
    """The verified-or-honest trend for one query, from its snapshot series."""
    from hunter.demand_monitor import compute_trend, series_for_query

    snaps = series_for_query(query)
    return compute_trend(snaps)


@router.get("/demand-monitor/series")
def demand_series(query: str = Query(..., min_length=1), limit: int = 90):
    from hunter.demand_monitor import series_for_query

    rows = series_for_query(query, limit=limit)
    return {
        "query": query,
        "count": len(rows),
        "points": [
            {
                "captured_at": r.captured_at.isoformat() if r.captured_at else None,
                "sold_30d": r.sold_30d,
                "sold_7d": r.sold_7d,
                "avg_price": r.avg_price,
            }
            for r in rows
        ],
    }
