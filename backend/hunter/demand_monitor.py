"""Honest, time-series demand monitoring for Hot Items.

A 30-day sold count is available on every search. A *7-day trend*, however,
can only exist when the same product is observed more than once over that
window - which is why DemandData.sold_count_7d is almost always None and a
browser extension is the only usual source. That is the honest constraint the
user hit, so this module manufactures nothing.

What it does do:

  * `snapshot_query` records one run's real sold-30d for a query, with the
    timestamp, into a `demand_snapshots` table.
  * `compute_trend` answers "is this hot over the window?" ONLY when there
    are at least two snapshots of that query spanning enough of the window to
    trust the slope. Otherwise it says so - unverified with the reason - and
    never returns a number.

Cost discipline (C10/C4, the 5,000/day budget): the monitor touches one eBay
query per tracked product per run, and the table is append-only. A default
watchlist of ~20 products sampled every 6 hours is ~80 calls, a rounding
error of the daily budget - far below the 5,000.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from db.database import SessionLocal, engine
from db.models import DemandSnapshot

logger = logging.getLogger(__name__)

_ENSURED = False


def _ensure_table() -> None:
    """Create demand_snapshots if the running app predated the model.

    Tables are otherwise provisioned out of band, so a new model must create
    its own table or every query would fail with "no such table".
    """
    global _ENSURED
    if not _ENSURED:
        try:
            DemandSnapshot.__table__.create(engine, checkfirst=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("could not ensure demand_snapshots table: %s", e)
        _ENSURED = True


def snapshot_query(
    query: str,
    sold_data: Any,
    source: str = "watchlist_monitor",
    captured_at: Optional[datetime] = None,
) -> DemandSnapshot:
    """Record one real fetch for `query`."""
    _ensure_table()
    db = SessionLocal()
    try:
        row = DemandSnapshot(
            query=(query or "").strip(),
            sold_30d=getattr(sold_data, "sold_count_30d", None)
            or getattr(sold_data, "total_sold_30d", None),
            sold_7d=getattr(sold_data, "sold_count_7d", None)
            or getattr(sold_data, "total_sold_7d", None),
            avg_price=(
                getattr(sold_data, "avg_sold_price", None)
                or getattr(sold_data, "price_avg", None)
            ),
            source=source,
            captured_at=captured_at or datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def fetch_and_record(
    query: str,
    scraper_factory: Optional[Callable[[], Any]] = None,
    source: str = "watchlist_monitor",
    captured_at: Optional[datetime] = None,
) -> DemandSnapshot:
    """Fetch a real sold-count for `query`, and record it.

    Separated so tests can inject `scraper_factory` and never touch the
    network: the honesty of the module lives in what it RECORDS, not in being
    able to invent it.
    """
    if scraper_factory is None:
        from scrapers.ebay_sold import EbaySoldScraper

        scraper_factory = EbaySoldScraper
    scraper = scraper_factory()
    sold = scraper.get_sold_data(query)
    return snapshot_query(query, sold, source=source, captured_at=captured_at)


def compute_trend(
    snapshots: list[DemandSnapshot],
    now: Optional[datetime] = None,
    min_span_hours: float = 24.0,
) -> dict[str, Any]:
    """The trend for one query, only when the data can carry one.

    Honesty is the product:
      * < 2 snapshots or span < min_span_hours => provenance "unverified",
        reason, and NO trend value (C1/C13). A single point cannot have a
        slope, and a slope is the only thing that makes "trending" more than
        "exists".
      * otherwise: slope of sold_30d over the observed span, normalised to a
        7-day pace, with the two endpoints it compares shown so the user can
        audit the call.
    """
    now = now or datetime.utcnow()
    pts = [s for s in snapshots if s.captured_at is not None]
    pts.sort(key=lambda s: s.captured_at)

    if len(pts) < 2:
        return {
            "hot": False,
            "provenance": "unverified",
            "reason": f"only {len(pts)} monitor snapshot(s) - a trend needs at least two",
            "pace_7d": None,
            "window_days": None,
            "points": len(pts),
        }

    span_hours = (pts[-1].captured_at - pts[0].captured_at).total_seconds() / 3600.0
    if span_hours < min_span_hours:
        return {
            "hot": False,
            "provenance": "unverified",
            "reason": (
                f"snapshots span only {span_hours:.1f}h - need at least "
                f"{min_span_hours:.0f}h to call a slope a trend"
            ),
            "pace_7d": None,
            "window_days": round(span_hours / 24.0, 2),
            "points": len(pts),
        }

    first, last = pts[0], pts[-1]
    if first.sold_30d is None or last.sold_30d is None:
        return {
            "hot": False,
            "provenance": "unverified",
            "reason": "one endpoint snapshot has no real 30d count",
            "pace_7d": None,
            "window_days": round(span_hours / 24.0, 2),
            "points": len(pts),
        }

    # sold_30d is itself a 30-day figure, so its DELTA over the observed span
    # is the closest thing to sales in that span. Normalise to a 7-day pace so
    # the number is comparable across windows.
    span_days = max(span_hours / 24.0, 1e-9)
    delta = (last.sold_30d or 0) - (first.sold_30d or 0)
    pace_7d = delta * (7.0 / span_days)

    return {
        "hot": bool(pace_7d > 0 and len(pts) >= 2),
        "provenance": "verified",
        "reason": "",
        "pace_7d": round(pace_7d, 1),
        "delta_sold_30d": delta,
        "window_days": round(span_days, 2),
        "points": len(pts),
        "first": {
            "at": first.captured_at.isoformat(),
            "sold_30d": first.sold_30d,
        },
        "last": {
            "at": last.captured_at.isoformat(),
            "sold_30d": last.sold_30d,
        },
    }


def series_for_query(query: str, limit: int = 90) -> list[DemandSnapshot]:
    """Snapshots for one query, oldest first."""
    _ensure_table()
    db = SessionLocal()
    try:
        rows = (
            db.query(DemandSnapshot)
            .filter(DemandSnapshot.query == (query or "").strip())
            .order_by(DemandSnapshot.captured_at.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(rows))
    finally:
        db.close()
