"""Listing age and churn - Phase G.

Age is read from eBay's own ``itemCreationDate``. It is never inferred from
the day this app first saw a listing: those are two different facts, and a
listing first seen yesterday may have been on eBay for years. When both are
shown, the UI labels them differently.

Churn is a statement about search result sets, not about eBay's listing
status. A stored query observation is the set of listings one Browse search
returned at one moment. A listing in an earlier observation and absent from
the latest one is reported as ``no longer listed`` with the date it was last
seen. The module never says why it disappeared - eBay does not give this app
that answer.

The rules the tests pin:

* Fewer than two observations means no churn claim at all. ``churned`` is
  ``None`` and a sentence says why, never an empty list standing in for an
  unknown.
* Two observations must have used the same price filter and sample size.
  Different settings describe different result sets, so churn is refused
  rather than claimed across them.
* A listing that reappears in the latest observation is not churned. A
  listing last seen several observations ago is still reported, with that
  older last-seen date.
* There is no rate, percentage, rank or reason field. The module counts only
  what the stored samples contain.
* The word that means a completed sale does not appear in this module or in
  any label it builds. The copy is "no longer listed".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

__all__ = [
    "AGE_INFO_MAX_DAYS",
    "NO_LONGER_LISTED",
    "normalise_query",
    "age_days",
    "describe_age",
    "build_churn_report",
]

#: A listing this fresh is shown with the informational tone; older listings
#: use the neutral tone. This is presentation only - both are measured ages.
AGE_INFO_MAX_DAYS = 6

#: The machine-readable status for a listing missing from the latest sample.
NO_LONGER_LISTED = "no_longer_listed"


def normalise_query(value: Any) -> str:
    """The lane a query belongs to: trimmed, whitespace-collapsed, lower-case.

    eBay search is not case-sensitive, so "Garden Hose" and "garden  hose"
    are one query. Without this, two spellings would split the history and a
    churn page would refuse for lack of observations that are in fact there.
    """
    return " ".join(str(value or "").split()).lower()


def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    """A datetime as naive UTC, the convention every stored timestamp uses."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _moment(value: Any) -> Optional[datetime]:
    """A stored datetime or ISO string as naive UTC, or None when unreadable."""
    if isinstance(value, datetime):
        return _naive_utc(value)
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            return _naive_utc(datetime.fromisoformat(text))
        except ValueError:
            return None
    return None


def _iso_z(value: Any) -> Optional[str]:
    """A stored moment rendered as an exact UTC instant, or None.

    The trailing Z is deliberate: the browser must not read a zone-less
    stored value as local time. The API and the churn report both use this.
    """
    moment = _moment(value)
    return f"{moment.isoformat()}Z" if moment is not None else None


def age_days(creation: Any, now: Any = None) -> Optional[int]:
    """Whole days since eBay's creation date, or None when it cannot be said.

    A missing date is None. A date in the future is also None: it is not an
    age of zero, it is a value that cannot be trusted. The caller reports
    the reason rather than inventing an age.
    """
    created = _moment(creation)
    if created is None:
        return None
    current = _moment(now) or datetime.utcnow()
    if created > current:
        return None
    return (current - created).days


def describe_age(creation: Any, now: Any = None) -> dict:
    """The age block and, when absent, the sentence explaining why.

    Returns ``{"age": {...}, "reason": None}`` when eBay supplied a usable
    creation date, or ``{"age": None, "reason": "<sentence>"}`` when it did
    not. The age block carries days and a display tone; the label belongs to
    the UI, so the copy is written once.
    """
    created = _moment(creation)
    if created is None:
        return {
            "age": None,
            "reason": (
                "eBay did not return a readable creation date for this "
                "listing, so its age is not claimed."
            ),
        }

    current = _moment(now) or datetime.utcnow()
    if created > current:
        return {
            "age": None,
            "reason": (
                "eBay's creation date for this listing is in the future, so "
                "its age is not claimed."
            ),
        }

    days = (current - created).days
    return {
        "age": {
            "days": days,
            "tone": "info" if days <= AGE_INFO_MAX_DAYS else "neutral",
            "basis": "ebay_item_creation_date",
        },
        "reason": None,
    }


def _listing_id(listing: Any) -> str:
    if not isinstance(listing, dict):
        return ""
    value = listing.get("listing_id")
    return str(value) if value is not None else ""


def _dedupe(listings: Iterable[Any]) -> list[dict]:
    """One row per listing id, keeping the first occurrence in the run."""
    rows: list[dict] = []
    seen: set[str] = set()
    for listing in listings or []:
        listing_id = _listing_id(listing)
        if not listing_id or listing_id in seen:
            continue
        seen.add(listing_id)
        rows.append(dict(listing))
    return rows


def _display_row(
    listing: dict, *, first_seen: Any, last_seen: Any
) -> dict:
    """The fields the churn page needs from one stored snapshot."""
    return {
        "listing_id": _listing_id(listing),
        "title": listing.get("title"),
        "item_url": listing.get("item_url"),
        "price": listing.get("price"),
        "currency": listing.get("currency"),
        "item_creation_date": _iso_z(listing.get("item_creation_date")),
        "first_seen_at": _iso_z(first_seen),
        "last_seen_at": _iso_z(last_seen),
    }


def _query_sets_differ(runs: list[dict]) -> Optional[str]:
    """Why the observations are not comparable, or None when they are.

    Two searches only describe the same population when the exact filter and
    the sample ceiling match. Comparing a banded search with an unbanded one
    would turn a price change into a false "no longer listed" claim.
    """
    filters = {run.get("filter") for run in runs}
    limits = {run.get("limit") for run in runs}
    if len(filters) <= 1 and len(limits) <= 1:
        return None

    parts: list[str] = []
    if len(filters) > 1:
        parts.append("different price filters")
    if len(limits) > 1:
        parts.append("different sample sizes")
    return (
        "The stored observations used "
        + " and ".join(parts)
        + ", so they describe different result sets. Churn is not claimed "
        "across them."
    )


def build_churn_report(runs: Iterable[Any], now: Any = None) -> dict:
    """Compare stored query observations and report what is missing now.

    ``runs`` is newest first, as the database returns them. Each run is a
    mapping with ``observed_at``, ``filter``, ``limit`` and ``listings``.
    A listing row carries ``listing_id``, ``title``, ``item_url``, ``price``,
    ``currency`` and ``item_creation_date``.

    The comparison is against every earlier stored observation, not only the
    one before the latest. A listing that vanished three observations ago is
    still "observed before, not present in the latest observation", and its
    last-seen date is the last run that actually contained it. A listing that
    reappears in the latest run is not reported.
    """
    sampled = [run for run in (runs or []) if isinstance(run, dict)]
    observations = len(sampled)
    latest = sampled[0] if sampled else None
    earlier = sampled[1:]

    latest_listings = _dedupe(latest.get("listings") if latest else [])
    latest_ids = {_listing_id(listing) for listing in latest_listings}

    # Oldest to newest, so the last write for a listing is its most recent
    # sighting and the first write is its first sighting.
    sightings: dict[str, dict] = {}
    for run in reversed(sampled):
        observed_at = run.get("observed_at")
        for listing in _dedupe(run.get("listings") or []):
            listing_id = _listing_id(listing)
            if not listing_id:
                continue
            current = sightings.get(listing_id)
            if current is None:
                sightings[listing_id] = {
                    "listing": dict(listing),
                    "first_seen_at": observed_at,
                    "last_seen_at": observed_at,
                }
            else:
                current["listing"] = dict(listing)
                current["last_seen_at"] = observed_at

    latest_rows: list[dict] = []
    for listing in latest_listings:
        listing_id = _listing_id(listing)
        seen = sightings.get(listing_id) or {}
        row = _display_row(
            listing,
            first_seen=seen.get("first_seen_at", latest.get("observed_at")),
            last_seen=seen.get("last_seen_at", latest.get("observed_at")),
        )
        age = describe_age(listing.get("item_creation_date"), now)
        row["age"] = age["age"]
        row["age_reason"] = age["reason"]
        latest_rows.append(row)

    earlier_ids: set[str] = set()
    for run in earlier:
        earlier_ids.update(
            _listing_id(listing)
            for listing in _dedupe(run.get("listings") or [])
        )
    earlier_ids.discard("")

    report = {
        "observations": observations,
        "comparable": False,
        "latest_observed_at": _iso_z(latest.get("observed_at")) if latest else None,
        "previous_observed_at": (
            _iso_z(earlier[0].get("observed_at")) if earlier else None
        ),
        "earliest_observed_at": (
            _iso_z(sampled[-1].get("observed_at")) if sampled else None
        ),
        "latest_listing_count": len(latest_listings),
        "earlier_listing_count": len(earlier_ids),
        # The request knobs behind the latest sample. They are shown so the
        # page can name the sample ceiling and state why two observations
        # were refused as incomparable. They are not figures about eBay.
        "filter": latest.get("filter") if latest else None,
        "limit": latest.get("limit") if latest else None,
        "latest": latest_rows,
        "churned": None,
        "reason": None,
    }

    if observations < 2:
        report["reason"] = (
            "No search observation is stored for this query yet."
            if observations == 0
            else (
                "Only one search observation is stored for this query. A "
                "second is needed before a listing can be called no longer "
                "listed."
            )
        )
        return report

    mismatch = _query_sets_differ(sampled)
    if mismatch is not None:
        report["reason"] = mismatch
        return report

    report["comparable"] = True
    churned: list[dict] = []
    for listing_id, seen in sightings.items():
        if listing_id in latest_ids:
            continue
        row = _display_row(
            seen["listing"],
            first_seen=seen["first_seen_at"],
            last_seen=seen["last_seen_at"],
        )
        row["status"] = NO_LONGER_LISTED
        churned.append(row)

    # Most recently seen first; ties alphabetical so the page is stable.
    churned.sort(key=lambda row: (row.get("title") or "").casefold())
    churned.sort(key=lambda row: row.get("last_seen_at") or "", reverse=True)
    report["churned"] = churned
    if not churned:
        report["reason"] = (
            "No listing observed earlier is missing from the latest "
            "observation."
        )
    return report
