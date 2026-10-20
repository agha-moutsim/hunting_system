"""Seller footprint from Browse readings this app already stored.

The panel this feeds describes the active listings a seller put in front of
this app. It is not a sales report: Browse returns live listings only, so the
only facts available are the seller's own feedback and account type, where the
item is based, and the shape of the listings that were observed. There is no
revenue, sales, sold or turnover figure here, and there cannot be one from
these readings.

Every figure is measured from a stored reading:

* feedback and account type are eBay's values, never a computed score;
* the region is the item location eBay returned, not an inference from a name;
* the condition mix counts listings with a condition actually read;
* the asking range and median use one price per listing, and refuse to mix
  currencies;
* the age range comes from eBay's creation date, not from first sighting.

Absent is ``None``. A section with no usable readings is ``None`` plus a
sentence, never a zero-filled panel. The caller must keep the sample size
beside every aggregate, because a handful of observed listings is not the
seller's whole business.
"""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any, Iterable, Optional

from engine.listing_age import describe_age


def _moment(value: Any) -> Optional[datetime]:
    """A datetime in the naive-UTC convention used by the database."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value.strip():
        try:
            moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def _iso_z(value: Any) -> Optional[str]:
    moment = _moment(value)
    return f"{moment.isoformat()}Z" if moment is not None else None


def _text(value: Any) -> Optional[str]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _integer(value: Any) -> Optional[int]:
    number = _number(value)
    return int(number) if number is not None else None


def _reading_key(reading: dict) -> tuple[datetime, int]:
    """Sort key for one reading; oldest first, id breaks a same-instant tie."""
    return (
        _moment(reading.get("observed_at")) or datetime.min,
        int(reading.get("id") or 0),
    )


def _rows_by_listing(readings: Iterable[Any]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for raw in readings or []:
        if not isinstance(raw, dict):
            continue
        listing_id = _text(raw.get("listing_id"))
        if not listing_id:
            continue
        grouped.setdefault(listing_id, []).append(dict(raw))
    for rows in grouped.values():
        rows.sort(key=_reading_key)
    return grouped


def _latest(rows: list[dict], field: str) -> Any:
    """The newest non-empty value of one field, or None.

    A later reading that omitted a field must not erase a value an earlier
    reading actually returned. This is the same stance the age route takes
    for `item_creation_date`.
    """
    for row in reversed(rows):
        value = row.get(field)
        if isinstance(value, str):
            value = _text(value)
        if value is not None:
            return value
    return None


def _feedback(rows: list[dict]) -> Optional[dict]:
    """The newest reading that carried either feedback value.

    Both values are taken from that one reading, so a percentage and a score
    are never stitched together from different moments. A later summary that
    omitted the score therefore reports the percentage with no score rather
    than borrowing an older score and presenting the pair as one reading.
    """
    for row in reversed(rows):
        percentage = _number(row.get("seller_feedback_percentage"))
        score = _integer(row.get("seller_feedback_score"))
        if percentage is not None or score is not None:
            return {
                "percentage": percentage,
                "score": score,
                "observed_at": _iso_z(row.get("observed_at")),
            }
    return None


def _region(rows: list[dict]) -> Optional[dict]:
    """The newest item location that carried a country or postal code.

    Both parts come from one reading so a country is never paired with a
    postal code from a different moment. A missing part stays null.
    """
    for row in reversed(rows):
        country = _text(row.get("item_country"))
        postal_code = _text(row.get("item_postal_code"))
        if country or postal_code:
            return {"country": country, "postal_code": postal_code}
    return None


def _group_stats(grouped: dict[str, list[dict]], now: Any = None) -> dict:
    """Seller-level fields and per-listing aggregates for one username."""
    observed_listings = len(grouped)
    all_readings = [row for listing_rows in grouped.values() for row in listing_rows]
    all_readings.sort(key=_reading_key)

    display_username = None
    for row in reversed(all_readings):
        display_username = _text(row.get("seller_username"))
        if display_username:
            break

    feedback = _feedback(all_readings)
    account_type = _latest(all_readings, "seller_account_type")
    region = _region(all_readings)

    conditions: dict[str, int] = {}
    condition_unknown = 0
    prices: list[tuple[float, str]] = []
    ages: list[int] = []

    for listing_rows in grouped.values():
        condition = _latest(listing_rows, "condition_text")
        if condition is None:
            condition_unknown += 1
        else:
            conditions[condition] = conditions.get(condition, 0) + 1

        price = _number(_latest(listing_rows, "price"))
        currency = _text(_latest(listing_rows, "currency"))
        if price is not None and currency:
            prices.append((price, currency.upper()))

        creation = _latest(listing_rows, "item_creation_date")
        described = describe_age(creation, now=now)
        aged = described.get("age")
        if isinstance(aged, dict) and aged.get("days") is not None:
            ages.append(int(aged["days"]))

    condition_known = sum(conditions.values())
    condition_mix = {
        "known": condition_known,
        "unknown": condition_unknown,
        "values": [
            {
                "condition": condition,
                "count": count,
                "share": count / condition_known,
            }
            for condition, count in sorted(
                conditions.items(), key=lambda item: (-item[1], item[0].lower())
            )
        ],
    }

    currencies = sorted({currency for _, currency in prices})
    asking_prices = None
    asking_prices_reason = None
    if not prices:
        asking_prices_reason = (
            "No asking price and currency were read for these listings."
        )
    elif len(currencies) > 1:
        asking_prices_reason = (
            "Observed asking prices use more than one currency ("
            + ", ".join(currencies)
            + "), so no single range or median is shown."
        )
    else:
        amounts = [amount for amount, _ in prices]
        asking_prices = {
            "currency": currencies[0],
            "min": min(amounts),
            "max": max(amounts),
            "median": median(amounts),
            "sample": len(amounts),
        }

    listed_age = None
    listed_age_reason = None
    if not ages:
        listed_age_reason = (
            "No usable eBay creation date was read for these listings, so no "
            "age range is shown."
        )
    else:
        listed_age = {
            "min_days": min(ages),
            "max_days": max(ages),
            "sample": len(ages),
        }

    return {
        "username": display_username or "",
        "observed_listings": observed_listings,
        "readings": len(all_readings),
        "latest_observed_at": _iso_z(
            all_readings[-1].get("observed_at") if all_readings else None
        ),
        "feedback": feedback,
        "account_type": account_type,
        "region": region,
        "condition_mix": condition_mix,
        "asking_prices": asking_prices,
        "asking_prices_reason": asking_prices_reason,
        "listed_age": listed_age,
        "listed_age_reason": listed_age_reason,
    }


def build_seller_footprint(
    readings: Iterable[Any],
    username: str,
    *,
    now: Any = None,
) -> dict:
    """Aggregate stored Browse readings for one seller.

    ``readings`` are mappings with the listing id, observation time and the
    seller/item fields held by `listing_observations`. They may arrive in any
    order and may include other sellers; the function filters to ``username``
    case-insensitively.

    The result is deliberately only a supply-side picture. The caller adds the
    query context and the sentence explaining an empty result; this function
    never invents one.
    """
    wanted = _text(username)
    if not wanted:
        return {
            "username": "",
            "observed_listings": 0,
            "readings": 0,
            "latest_observed_at": None,
            "feedback": None,
            "account_type": None,
            "region": None,
            "condition_mix": {"known": 0, "unknown": 0, "values": []},
            "asking_prices": None,
            "asking_prices_reason": "No seller username was supplied.",
            "listed_age": None,
            "listed_age_reason": "No seller username was supplied.",
        }

    wanted_key = wanted.lower()
    grouped = _rows_by_listing(readings)
    for listing_id in list(grouped):
        rows = grouped[listing_id]
        seller = _latest(rows, "seller_username")
        if seller is None or seller.lower() != wanted_key:
            del grouped[listing_id]
            continue
        # Keep the readings that name this seller, plus readings that omitted
        # the username (a summary can still carry a price or condition). A
        # reading naming a different seller must not leak into this footprint
        # just because the same listing id appeared under that seller earlier.
        grouped[listing_id] = [
            row
            for row in rows
            if _text(row.get("seller_username")) is None
            or _text(row.get("seller_username")).lower() == wanted_key
        ]

    # `now` is accepted so age arithmetic can be pinned in tests. It is not
    # stored or reported: the panel's ages are whole days from eBay's date.
    if now is not None:
        described_now = _moment(now)
    else:
        described_now = None

    result = _group_stats(grouped, now=described_now)
    if not result["username"]:
        result["username"] = wanted
    return result
