"""Listing age and churn - the two read-only Phase G doors.

`GET /api/observations/{listing_id}` answers what is known about one listing:
when this app first saw it, when its last stored reading was taken, and how
old eBay says it is. Age comes from eBay's own creation date. A listing whose
creation date was not returned gets no age claim, only a sentence saying so.

`GET /api/observations/churn?query=` compares the stored search result sets
for one query. It spends no Browse call and writes nothing: the rows were
recorded by analyses that already ran. Fewer than two observations produces
`churned: null` and a sentence, never an empty list that would read as a
measured zero.

The copy is deliberately limited to "no longer listed". A listing missing
from a small search sample is not proof that anything happened to it, and
eBay does not tell this app why it disappeared.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Path, Query

from engine.listing_age import build_churn_report, describe_age, normalise_query

router = APIRouter()


def _iso_z(value) -> str | None:
    """A stored naive-UTC datetime as an exact instant, or None.

    The trailing Z matters: without it the browser reads the zone-less string
    as local time and can show the wrong day.
    """
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return f"{value.isoformat()}Z"


def _run_payload(row) -> dict:
    """A stored query observation in the shape the churn engine reads.

    The engine normalises the timestamps it prints. Keeping this adapter thin
    means the database row and the comparison logic have one boundary, not a
    second copy of the shape.
    """
    return {
        "observed_at": row.observed_at,
        "filter": row.price_filter,
        "limit": row.sample_limit,
        "listings": row.listings or [],
    }


@router.get("/observations/churn")
def query_churn(
    query: str = Query(..., min_length=1, max_length=200),
):
    """Compare one query's stored search observations.

    Read-only by design: the page that calls this has no eBay credentials and
    spends no Browse quota. The response names the number of observations and
    the sample sizes, so a small sample cannot be mistaken for a market-wide
    churn figure.
    """
    key = normalise_query(query)
    if not key:
        raise HTTPException(status_code=422, detail="query must not be blank")

    from db.database import SessionLocal
    from db.queries import get_query_observations

    db = SessionLocal()
    try:
        rows = get_query_observations(db, key)
    finally:
        db.close()

    report = build_churn_report([_run_payload(row) for row in rows])
    return {"query": key, **report}


@router.get("/observations/{listing_id}")
def listing_age(
    listing_id: str = Path(..., min_length=1, max_length=64),
):
    """The age and reading summary for one observed listing.

    `first_seen_at` is the first time this app stored a reading for the
    listing. `latest_reading_at` is the latest stored reading, not a last-seen
    time: readings are written only when something changed. The two are named
    for what they are rather than collapsed into a misleading "last seen".
    """
    listing_id = listing_id.strip()
    if not listing_id:
        raise HTTPException(status_code=422, detail="listing_id must not be blank")

    from db.database import SessionLocal
    from db.queries import get_listing_observation_summary

    db = SessionLocal()
    try:
        summary = get_listing_observation_summary(db, listing_id)
    finally:
        db.close()

    if summary["readings"] == 0:
        return {
            "listing_id": listing_id,
            "observed": False,
            "readings": 0,
            "first_seen_at": None,
            "latest_reading_at": None,
            "item_creation_date": None,
            "age": None,
            "reason": "No Browse reading has been stored for this listing yet.",
        }

    described = describe_age(summary["item_creation_date"])
    return {
        "listing_id": listing_id,
        "observed": True,
        "readings": summary["readings"],
        "first_seen_at": _iso_z(summary["first_seen_at"]),
        "latest_reading_at": _iso_z(summary["latest_reading_at"]),
        "item_creation_date": _iso_z(summary["item_creation_date"]),
        "age": described["age"],
        "reason": described["reason"],
    }
