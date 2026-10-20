"""One extractor for the Browse fields this app was already being handed.

WHY THIS EXISTS
---------------
Every Browse call this app makes returns far more than it stores. The deals
refresh alone has, since it was written, received each listing's creation date,
the seller's feedback percentage and score, whether that seller is a business
or an individual, where the item physically is, the postage charged, the
category, and the buying options - and thrown all of it away, keeping a price
and a username. That is measurement already paid for and discarded.

So this module is not a new data source. It spends no extra API call, which is
the only reason it is allowed to exist (CONSTRAINTS.md C11: no new upstream
spend to enrich a board that already has its own budget).

WHAT IS MEASURED, NOT ASSUMED
-----------------------------
The shapes below were read off a live payload before this was written, not
guessed, because two of them are traps:

* ``seller.feedbackPercentage`` arrives as the STRING ``"99.1"`` while
  ``seller.feedbackScore`` arrives as the integer ``152255``. A reader that
  assumed one type would store NULL for half of them and never raise.
* On that same payload ``categories`` and ``leafCategoryIds`` were BOTH absent
  while ``categoryId`` was present, so the obvious first choice yields nothing
  and the fallback is the path that actually works.
* ``itemOriginDate`` and ``itemGroupType`` were absent, and ``itemLocation``
  carried ``{"city": "UK", "country": "GB"}`` with no ``postalCode``. All three
  are therefore nullable here, and absent stays NULL - never an epoch, never a
  zero, never ``False``.

THE RULE
--------
Absent is ``None``. An empty string is ``None`` too: eBay sends ``""`` for a
field it did not fill in, and treating that as a distinct value from absent
would make a reading look like it had changed when nothing had.

Pure by design: no I/O, no session, no clock, so the whole field set can be
pinned against a saved payload.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

#: Every field a stored reading carries, in one place. The model's columns, the
#: row builder and the change comparison are all driven off this tuple, so a
#: field can never be added to one and silently missed by another.
FIELDS: tuple[str, ...] = (
    # The listing itself.
    "item_creation_date",
    "item_origin_date",
    # Who is selling it.
    "seller_username",
    "seller_feedback_percentage",
    "seller_feedback_score",
    "seller_account_type",
    "seller_store_name",
    # Where it is.
    "item_country",
    "item_city",
    "item_postal_code",
    # What it is.
    "condition_id",
    "condition_text",
    "category_id",
    "category_name",
    # What eBay says about how it is being sold.
    "top_rated",
    "priority_listing",
    "item_group_type",
    "buying_options",
    # What it costs, and what it costs to receive.
    "price",
    "currency",
    "shipping_cost",
    "shipping_currency",
    "shipping_type",
)

#: What a stored reading must match to count as a repeat of the last one.
#: ``source`` is in here deliberately: a reading taken from a search summary
#: carries different NULLs from one taken from the item itself, and a row's
#: provenance should be true of the row that holds it.
COMPARED: tuple[str, ...] = FIELDS + ("source",)

#: Which Browse surface produced a reading. Both are the same API and the same
#: field names; the difference is completeness, which is what a NULL means.
SOURCE_ITEM = "browse_api_item"
SOURCE_SUMMARY = "browse_api_summary"

#: `itemId` is the RESTful form ("v1|116529177245|0") and its MIDDLE segment is
#: the legacy id; `legacyItemId` is that id on its own. Both appear in real
#: responses, so both are read.
_ITEM_ID_RE = re.compile(r"^(?:v\d+\|)?(\d+)(?:\|\d+)?$")


def _text(value: Any) -> Optional[str]:
    """A non-empty string, or None. ``""`` collapses to None (see module doc)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> Optional[float]:
    """A float, from a number or a numeric string.

    The string case is not defensive padding: ``feedbackPercentage`` really does
    arrive as ``"99.1"`` (measured).
    """
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


def _flag(value: Any) -> Optional[bool]:
    """True or False only when eBay actually said so.

    Absent stays None rather than becoming False: "eBay did not return this" and
    "eBay says no" are different facts, and defaulting would invent a rating.
    """
    return value if isinstance(value, bool) else None


def _moment(value: Any) -> Optional[datetime]:
    """ISO 8601 -> naive UTC datetime, the DateTime convention in db/models.py."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _money(raw: Any) -> tuple[Optional[float], Optional[str]]:
    """(amount, currency) from eBay's ``{"value": "169.00", "currency": "GBP"}``.

    A bare formatted string is also handled, because the two item endpoints are
    not consistent about which they send (the same reason
    ``scrapers.ebay_deals._price_of`` exists).
    """
    if isinstance(raw, dict):
        return _number(raw.get("value")), _text(raw.get("currency"))
    if isinstance(raw, str) and raw.strip():
        match = re.search(r"([\d.,]+)", raw)
        amount = _number(match.group(1).replace(",", "")) if match else None
        return amount, ("GBP" if "£" in raw else None)
    return None, None


def _category(payload: dict) -> tuple[Optional[str], Optional[str]]:
    """(id, name), preferring whichever shape carries both.

    ``categories[]`` gives a name alongside the id, so it is tried first;
    ``leafCategoryIds`` gives ids only, and the top-level ``categoryId`` is the
    fallback that actually fired on the payload this was measured against.
    """
    categories = payload.get("categories")
    if (
        isinstance(categories, list)
        and categories
        and isinstance(categories[0], dict)
    ):
        first = categories[0]
        return _text(first.get("categoryId")), _text(first.get("categoryName"))

    leaves = payload.get("leafCategoryIds")
    if isinstance(leaves, list) and leaves:
        return _text(leaves[0]), None

    return _text(payload.get("categoryId")), _text(payload.get("categoryPath"))


def _postage(payload: dict) -> tuple[Optional[float], Optional[str], Optional[str]]:
    """(cost, currency, service type) from the first shipping option.

    The first option is eBay's own first choice for the listing, and postage is
    kept exactly as offered rather than as a cheapest-case summary.

    A value of 0.00 is a real, measured zero - free postage - and stays 0.0.
    Only an absent ``shippingOptions`` becomes None.
    """
    options = payload.get("shippingOptions")
    if not isinstance(options, list) or not options:
        return None, None, None
    first = options[0]
    if not isinstance(first, dict):
        return None, None, None
    cost, currency = _money(first.get("shippingCost"))
    return cost, currency, _text(first.get("type"))


def _buying_options(payload: dict) -> Optional[list]:
    """``["FIXED_PRICE"]`` / ``["AUCTION"]`` / both, as eBay listed them."""
    options = payload.get("buyingOptions")
    if not isinstance(options, list) or not options:
        return None
    return [str(option) for option in options]


def extract_observation(payload: Any) -> dict:
    """Every field worth keeping from one Browse payload.

    Accepts either a ``get_item_by_legacy_id`` item or one entry from
    ``item_summary/search`` - the field names are the same and only the
    completeness differs. Anything absent becomes None. Anything that is not a
    dict becomes a full row of Nones rather than an exception: a payload that
    could not be read is a reading with nothing in it, and the caller decides
    what to do with that.
    """
    empty = {name: None for name in FIELDS}
    if not isinstance(payload, dict):
        return empty

    seller = payload.get("seller")
    seller = seller if isinstance(seller, dict) else {}
    location = payload.get("itemLocation")
    location = location if isinstance(location, dict) else {}

    price, currency = _money(payload.get("price"))
    shipping_cost, shipping_currency, shipping_type = _postage(payload)
    category_id, category_name = _category(payload)

    return {
        "item_creation_date": _moment(payload.get("itemCreationDate")),
        "item_origin_date": _moment(payload.get("itemOriginDate")),
        "seller_username": _text(seller.get("username")),
        "seller_feedback_percentage": _number(seller.get("feedbackPercentage")),
        "seller_feedback_score": _integer(seller.get("feedbackScore")),
        "seller_account_type": _text(seller.get("sellerAccountType")),
        "seller_store_name": _text(seller.get("storeName")),
        "item_country": _text(location.get("country")),
        "item_city": _text(location.get("city")),
        "item_postal_code": _text(location.get("postalCode")),
        "condition_id": _text(payload.get("conditionId")),
        "condition_text": _text(payload.get("condition")),
        "category_id": category_id,
        "category_name": category_name,
        "top_rated": _flag(payload.get("topRatedBuyingExperience")),
        "priority_listing": _flag(payload.get("priorityListing")),
        "item_group_type": _text(payload.get("itemGroupType")),
        "buying_options": _buying_options(payload),
        "price": price,
        "currency": currency,
        "shipping_cost": shipping_cost,
        "shipping_currency": shipping_currency,
        "shipping_type": shipping_type,
    }


def listing_id_of(payload: Any) -> Optional[str]:
    """The listing id inside a Browse payload, or None.

    A payload that cannot name its listing cannot be observed: there would be
    nothing to attach the reading to, and inventing a key would file two
    different listings under the same row. So this returns None rather than a
    placeholder, and the caller skips it.

    `legacyItemId` is the bare id and the RESTful `itemId` is the fallback -
    measured present on both the item payload and search summaries.
    """
    if not isinstance(payload, dict):
        return None

    legacy = _text(payload.get("legacyItemId"))
    if legacy and legacy.isdigit():
        return legacy

    raw = _text(payload.get("itemId"))
    if not raw:
        return None
    match = _ITEM_ID_RE.match(raw)
    return match.group(1) if match else None


def query_listing(payload: Any) -> Optional[dict]:
    """The display fields of one search summary, for a query observation.

    This is not the change-history field set. A query observation records the
    SET a search returned, so it needs only enough to identify and show each
    row: id, title, URL, price/currency and eBay's creation date. Every value
    is read from the payload; nothing is derived.

    Returns None when the payload cannot name its listing, for the same reason
    `listing_id_of` does: an unkeyed row cannot participate in a set
    comparison without inventing an identity.
    """
    listing_id = listing_id_of(payload)
    if not listing_id:
        return None

    reading = extract_observation(payload)
    creation = reading.get("item_creation_date")
    return {
        "listing_id": listing_id,
        "title": _text(payload.get("title")),
        "item_url": _text(payload.get("itemWebUrl")),
        "price": reading.get("price"),
        "currency": reading.get("currency"),
        "item_creation_date": (
            creation.isoformat() if isinstance(creation, datetime) else None
        ),
    }


def is_change(previous: Optional[dict], current: dict) -> bool:
    """Whether ``current`` says anything the previous reading did not.

    The table exists to show what changed about a listing, so a reading that
    repeats the last one is not stored again. That keeps an hourly refresh of a
    stable board from writing 1,752 identical rows a day, and it makes every
    row mean something: this listing was different at this moment.
    """
    if previous is None:
        return True
    return any(previous.get(name) != current.get(name) for name in COMPARED)
