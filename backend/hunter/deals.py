"""The deals board's storage and refresh policy.

Kept apart from the scraper so the network and the database can each be tested
without the other, and apart from the API so the route stays a pure read.

WHY THE API NEVER FETCHES
-------------------------
eBay's deals page is a single request, but pricing its cards is one Browse call
per card — about 73 of them, against a 5,000/day allowance. So the pool is
refreshed on a schedule and requests only ever read it. A request that waited
on 73 upstream calls would time out, and doing it per page view would spend the
whole daily allowance in under an hour of somebody leaving the tab open.

WHAT THIS BOARD IS NOT
----------------------
It is not a best-seller list, and it carries no sold count, because none is
measurable from here (see scrapers/ebay_deals.py). It is eBay's own curated
discount page, stored faithfully and labelled as such. Nothing in this module
ranks, scores or infers: rows are stored in the order eBay presented them.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta
from typing import Iterable, Optional

from db.models import DealItem as DealItemRow
from db.queries import save_listing_observations
from marketplaces import format_money, get_marketplace
from scrapers.ebay_deals import SOURCE, SOURCE_LABEL, DealItem, EbayDealsScraper

#: How long a pool is considered current. One hour holds the Browse spend at
#: ~108 calls x 24 = ~2,600/day (measured: 108 for a full page), comfortably
#: inside the 5,000/day allowance while still fresh enough that a "deal" is
#: really on offer.
DEALS_TTL_S = 3600

#: Serialises refreshes so two requests arriving together cannot both start
#: one, and so the scheduled job and the API cannot fetch simultaneously.
_refresh_lock = threading.Lock()

# The background thread's failure has no HTTP response to travel on. Without
# this, a fetch that raised would leave an empty board looking like "eBay has
# no deals" ? the exact claim this module refuses to make. Process-local and
# cleared by the next successful refresh; the timestamp says how old it is.
_REFRESH_ERRORS: dict[str, tuple[str, datetime]] = {}
_REFRESH_ERRORS_LOCK = threading.Lock()


def _clear_refresh_error(market_id: str) -> None:
    with _REFRESH_ERRORS_LOCK:
        _REFRESH_ERRORS.pop(market_id, None)


def _record_refresh_error(market_id: str, message: str) -> None:
    with _REFRESH_ERRORS_LOCK:
        _REFRESH_ERRORS[market_id] = (message, datetime.utcnow())

# Naive UTC throughout, matching the DateTime columns in db/models.py. Mixing
# aware and naive values here would raise on the subtraction in `board_meta`,
# so the whole module stays naive on purpose rather than by oversight.


def auto_refresh_enabled() -> bool:
    """Whether the API may kick off a refresh in the background.

    On by default so a first-time visitor sees a populated board instead of an
    empty one. Tests and read-only deployments set DEALS_AUTO_REFRESH=0 so
    merely hitting the endpoint never reaches the network.
    """
    return os.getenv("DEALS_AUTO_REFRESH", "1").strip().lower() not in (
        "0", "false", "no", "",
    )


def price_label(price: Optional[float], currency: str = "") -> str:
    """Format a real price, and return '' for an unread one.

    An unread price must not render as a number at all: '£0.00' would be a
    claim that the item is free, which is the C1 failure in miniature.
    """
    if price is None:
        return ""
    return format_money(price, (currency or "").upper())


def serialize(row: DealItemRow) -> dict:
    """One stored row as the API hands it to the client.

    Every value here traces to eBay: the page it came from or the Browse API
    keyed by that card's listing id. `price_label` is '' when the price was not
    read, and the client shows "See price on eBay" rather than a number.
    """
    return {
        "listing_id": row.listing_id,
        "marketplace": row.marketplace or "EBAY_GB",
        "title": row.title,
        "image_url": row.image_url,
        "item_url": row.item_url,
        "price": row.price,
        "currency": row.currency,
        "price_label": price_label(row.price, row.currency),
        "price_read": row.price is not None,
        "seller": row.seller,
        "store_name": row.store_name,
        "store_url": row.store_url,
        "store_verified": bool(row.store_verified),
        "condition": row.condition,
        "position": row.position,
        "source": row.source or SOURCE,
        "source_label": row.source_label or SOURCE_LABEL,
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else "",
    }


def board_meta(session, marketplace: Optional[str] = None) -> dict:
    """Everything the board needs to describe its own freshness.

    Counts are for ONE market. A pool from eBay US must never make an empty
    eBay UK board look populated, and a stale timestamp from another market
    must not make this one look fresh.
    """
    market = get_marketplace(marketplace)
    market_filter = DealItemRow.marketplace == market["id"]
    newest = (
        session.query(DealItemRow.fetched_at)
        .filter(market_filter)
        .order_by(DealItemRow.fetched_at.desc())
        .first()
    )
    stamped = newest[0] if newest and newest[0] else None
    total = session.query(DealItemRow).filter(market_filter).count()
    priced = (
        session.query(DealItemRow)
        .filter(market_filter)
        .filter(DealItemRow.price.isnot(None))
        .count()
    )
    age = None
    stale = True
    if stamped:
        age = int((datetime.utcnow() - stamped).total_seconds())
        stale = age > DEALS_TTL_S
    with _REFRESH_ERRORS_LOCK:
        last_error = _REFRESH_ERRORS.get(market["id"])
    return {
        "marketplace": market["id"],
        "currency": market["currency"],
        "total": total,
        "priced": priced,
        "unpriced": total - priced,
        "last_fetched": stamped.isoformat() if stamped else "",
        "age_seconds": age,
        "stale": stale,
        "refresh_interval_seconds": DEALS_TTL_S,
        "source": SOURCE,
        "source_label": SOURCE_LABEL,
        "auto_refresh": auto_refresh_enabled(),
        "last_refresh_error": last_error[0] if last_error else None,
        "last_refresh_error_at": (
            last_error[1].isoformat() if last_error else None
        ),
    }


def load_deals(
    session, limit: Optional[int] = None,
    marketplace: Optional[str] = None,
) -> list[dict]:
    """Read one market's stored pool in the order eBay presented it."""
    market = get_marketplace(marketplace)
    query = (
        session.query(DealItemRow)
        .filter(DealItemRow.marketplace == market["id"])
        .order_by(DealItemRow.position.asc(), DealItemRow.id.asc())
    )
    if limit:
        query = query.limit(limit)
    return [serialize(row) for row in query.all()]


def save_deals(
    items: Iterable[DealItem], session,
    marketplace: Optional[str] = None,
) -> dict:
    """Replace one market's board contents with one refresh's observations.

    Upsert-by-listing-id rather than delete-then-insert, so a row keeps its
    primary key across refreshes: a row that vanishes and comes back with a new
    id would make the client re-mount the card and lose its place. Rows eBay
    has stopped featuring in THIS market are removed, because "still on the
    board" has to mean "was on the page at the last refresh". Rows belonging to
    another marketplace are untouched.
    """
    market = get_marketplace(marketplace)
    now = datetime.utcnow()
    existing = {
        row.listing_id: row
        for row in session.query(DealItemRow)
        .filter(DealItemRow.marketplace == market["id"])
        .all()
    }
    seen: set[str] = set()
    added = updated = 0

    for item in items:
        seen.add(item.listing_id)
        row = existing.get(item.listing_id)
        if row is None:
            # Uniqueness is (marketplace, listing_id). The same eBay listing
            # appearing on a second market gets its own row rather than
            # stealing the first market's card or tripping a global index.
            row = DealItemRow(
                listing_id=item.listing_id,
                marketplace=market["id"],
            )
            session.add(row)
            added += 1
        else:
            updated += 1
            row.marketplace = market["id"]
        row.title = item.title
        row.item_url = item.item_url
        row.image_url = item.image_url
        row.price = item.price
        row.currency = item.currency
        row.seller = item.seller
        row.store_name = item.store_name
        row.store_url = item.store_url
        row.store_verified = item.store_verified
        row.condition = item.condition
        row.position = item.position
        row.source = item.source or SOURCE
        row.source_label = item.source_label or SOURCE_LABEL
        row.fetched_at = now

    removed = 0
    for listing_id, row in existing.items():
        if listing_id not in seen:
            session.delete(row)
            removed += 1

    session.commit()
    return {
        "added": added,
        "updated": updated,
        "removed": removed,
        "total": added + updated,
        "saved": added + updated - removed,
    }


def _record_observations(session, readings: list[tuple]) -> dict:
    """Store this refresh's Browse readings, without ever failing the refresh.

    Storing evidence is a side effect of a run that already happened: if it
    breaks, the board keeps its prices and the error is reported in the refresh
    result rather than swallowed. A silent failure here would look exactly like
    "nothing about these listings changed".
    """
    if not readings:
        return {
            "readings": 0,
            "recorded": 0,
            "unchanged": 0,
            "empty": 0,
            "duplicate": 0,
        }
    try:
        return save_listing_observations(session, readings)
    except Exception as exc:  # noqa: BLE001 - reported, never raised upward
        session.rollback()
        return {"error": str(exc)}


def refresh(
    session=None,
    limit: Optional[int] = None,
    enrich: bool = True,
    scraper=None,
    marketplace: Optional[str] = None,
) -> dict:
    """Fetch eBay's deals page and store it.

    `limit` prices only the first N cards and is intended for a cheap partial
    run; the scheduled job passes None and prices the whole page.

    Every payload the scraper fetches is also stored as a listing observation.
    That spends no extra API call - the fields were already in the response the
    price came from - and `scraper` exists so the wiring can be tested without
    touching the network.
    """
    owns_session = session is None
    if owns_session:
        from db.database import SessionLocal
        session = SessionLocal()

    readings: list[tuple] = []
    if scraper is None:
        scraper = EbayDealsScraper(marketplace=marketplace)
    market = getattr(scraper, "marketplace", None) or get_marketplace(marketplace)
    # Readings are collected here and written in one batch after the fetch, so
    # no write transaction is open while ~108 Browse calls are in flight.
    scraper.on_observation = (
        lambda listing_id, payload, source: readings.append(
            (listing_id, payload, source)
        )
    )

    try:
        items = scraper.fetch_deals(limit=limit, enrich=enrich)
        result = save_deals(items, session, marketplace=market["id"])
        # `listing_observations` has no marketplace key. Storing a US reading
        # there would mix it into UK seller footprints and time series, so a
        # non-UK refresh says the evidence store was skipped rather than
        # contaminating the one it cannot label.
        observations = (
            _record_observations(session, readings)
            if market["id"] == "EBAY_GB"
            else {
                "readings": len(readings),
                "skipped": "listing observations are not keyed by marketplace",
            }
        )
        _clear_refresh_error(market["id"])
        result.update({
            "marketplace": market["id"],
            "currency": market["currency"],
            "cards": len(items),
            "priced": sum(1 for i in items if i.price is not None),
            "api_calls": scraper.api_calls,
            "price_failures": scraper.price_failures,
            "source_label": SOURCE_LABEL,
            "observations": observations,
        })
        return result
    finally:
        if owns_session:
            session.close()


def refresh_if_stale(
    session=None, force: bool = False,
    marketplace: Optional[str] = None,
) -> Optional[dict]:
    """Refresh when the pool is missing or older than the TTL.

    Returns the refresh result, or None when the pool was still current or
    another refresh was already running. Never raises: this runs behind a
    request, and a board that is stale is far better than a board that 500s
    because eBay was slow.
    """
    owns_session = session is None
    if owns_session:
        from db.database import SessionLocal
        session = SessionLocal()

    try:
        meta = board_meta(session, marketplace=marketplace)
        if not force and meta["total"] and not meta["stale"]:
            return None
        if not _refresh_lock.acquire(blocking=False):
            return None
        try:
            _clear_refresh_error(get_marketplace(marketplace)["id"])
            return refresh(session=session, marketplace=marketplace)
        except Exception as exc:  # noqa: BLE001 - reported, never raised upward
            market = get_marketplace(marketplace)
            _record_refresh_error(market["id"], str(exc))
            return {
                "error": str(exc),
                "source_label": SOURCE_LABEL,
                "marketplace": market["id"],
            }
        finally:
            _refresh_lock.release()
    finally:
        if owns_session:
            session.close()


def start_background_refresh(marketplace: Optional[str] = None) -> threading.Thread:
    """Kick off one market's refresh on a worker thread and return it.

    Used by the API route so a stale board still answers immediately: the
    response carries whatever is stored plus an honest `stale` flag, and the
    new data is picked up by the client's next poll.
    """
    thread = threading.Thread(
        target=refresh_if_stale,
        kwargs={"marketplace": marketplace},
        name="deals-refresh",
        daemon=True,
    )
    thread.start()
    return thread


def latest_fetch(session, marketplace: Optional[str] = None) -> Optional[datetime]:
    """When one market's pool was last refreshed, or None if it never was."""
    market = get_marketplace(marketplace)
    newest = (
        session.query(DealItemRow.fetched_at)
        .filter(DealItemRow.marketplace == market["id"])
        .order_by(DealItemRow.fetched_at.desc())
        .first()
    )
    return newest[0] if newest and newest[0] else None


def is_within_ttl(stamp: Optional[datetime]) -> bool:
    if stamp is None:
        return False
    return datetime.utcnow() - stamp <= timedelta(seconds=DEALS_TTL_S)
