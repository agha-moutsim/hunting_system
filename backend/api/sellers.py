"""Seller footprint - one read-only door over stored Browse readings.

`GET /api/sellers/{username}` aggregates the readings this app already
recorded for one eBay seller. It spends no Browse call and writes nothing.
The optional `query` filter narrows the listings to the latest stored search
result set for that query, so a panel can say which query it describes
without mixing samples from different moments or filters.

The response carries the seller's own feedback and account type verbatim,
their item location, and distributions over the observed listings. It
deliberately carries no revenue, sales, sold or turnover figure: Browse
returns active listings, and this app never sees a seller's transactions.
Missing readings are null plus a sentence, never zero.

The aggregate is a reading of a sample, not a statement about the seller's
whole business. Every section carries its own sample count and the page keeps
those counts beside the numbers.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Path, Query

from engine.listing_age import normalise_query
from engine.sellers import build_seller_footprint

router = APIRouter()


def _iso_z(value) -> str | None:
    """A stored naive-UTC datetime as an exact instant, or None."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return f"{value.isoformat()}Z"


def _reading_payload(row) -> dict:
    """The columns the seller engine reads, copied across one boundary."""
    return {
        "id": row.id,
        "listing_id": row.listing_id,
        "observed_at": row.observed_at,
        "item_creation_date": row.item_creation_date,
        "seller_username": row.seller_username,
        "seller_feedback_percentage": row.seller_feedback_percentage,
        "seller_feedback_score": row.seller_feedback_score,
        "seller_account_type": row.seller_account_type,
        "item_country": row.item_country,
        "item_postal_code": row.item_postal_code,
        "condition_text": row.condition_text,
        "price": row.price,
        "currency": row.currency,
    }


def _latest_listing_ids(run) -> list[str]:
    """The listing ids in one stored search set, without duplicates."""
    seen: set[str] = set()
    for item in (run.listings if run is not None else None) or []:
        if not isinstance(item, dict):
            continue
        listing_id = item.get("listing_id")
        if listing_id is not None and str(listing_id).strip():
            seen.add(str(listing_id).strip())
    return sorted(seen)


@router.get("/sellers/{username}")
def seller_footprint(
    username: str = Path(..., min_length=1, max_length=64),
    query: str | None = Query(None, max_length=200),
):
    """Aggregate stored readings for one seller, optionally within one query.

    The username match is case-insensitive because eBay's is. The response
    echoes the stored spelling rather than normalising it into something the
    seller does not use.

    `query` is optional. When present it is normalised with the same function
    the churn lane uses, and only listings in that lane's latest stored set
    are aggregated. The query context reports how many observations are
    stored and the latest sample size, so an old listing is not silently
    presented as part of the newest result set.
    """
    requested = username.strip()
    if not requested:
        raise HTTPException(status_code=422, detail="username must not be blank")

    key = None
    if query is not None:
        key = normalise_query(query)
        if not key:
            raise HTTPException(status_code=422, detail="query must not be blank")

    from db.database import SessionLocal
    from db.queries import get_query_observations, get_seller_observations

    db = SessionLocal()
    try:
        runs = get_query_observations(db, key) if key else []
        latest = runs[0] if runs else None
        listing_ids = _latest_listing_ids(latest) if key else None
        rows = get_seller_observations(db, requested, listing_ids)
    finally:
        db.close()

    payload = build_seller_footprint(
        [_reading_payload(row) for row in rows], requested
    )
    payload["query"] = key
    if key:
        payload["query_context"] = {
            "observations": len(runs),
            "latest_listing_count": (
                int(latest.listing_count or 0) if latest is not None else 0
            ),
            "latest_observed_at": (
                _iso_z(latest.observed_at) if latest is not None else None
            ),
        }
    else:
        payload["query_context"] = None

    if key and not runs:
        payload["reason"] = (
            "No search observation is stored for this query yet, so there "
            "is no query sample to describe."
        )
    elif key and not listing_ids:
        payload["reason"] = (
            "The latest stored observation for this query contains no "
            "listings, so there is no seller sample to describe."
        )
    elif payload["observed_listings"] == 0 and key:
        payload["reason"] = (
            f"No stored Browse reading names {requested} in the latest "
            "stored observation for this query."
        )
    elif payload["observed_listings"] == 0:
        payload["reason"] = f"No stored Browse reading names {requested}."
    else:
        payload["reason"] = None

    return payload
