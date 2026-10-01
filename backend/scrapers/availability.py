"""
Availability — P4 stock & shipping capture.

Every stock state and shipping figure in a supplier row must come from
text an API or page actually printed. These parsers read that text and
return the structured value TOGETHER with the exact raw string it came
from (C13 — the origin travels with the fact, so a row can show "Only 3
left" beside low_stock and a human can check it).

Unknown is a real answer, not a gap: text that does not state the fact
comes back ("", text) / (0.0, 0, text) and the caller leaves the field
empty — never a plausible default (C1 — this is a sourcing tool; the
silent-"New" and silent-"dropship" bugs were exactly this shape).

NOTE shipping_cost 0.0 is ambiguous BY DESIGN: it means both "the
source said free" and "we could not tell". The number alone cannot
separate them, so shipping_raw ALWAYS carries the exact source text and
CALLERS MUST TRUST shipping_raw WHEN shipping_cost IS 0.0. The unread
case is shipping_raw == "".

Leaf module: stdlib only, no project imports, no network.
"""

import math
import re
from datetime import datetime, timezone

# C1 — only wording that states the fact outright resolves to a state.
# Checked most-negative first so "3 left in stock" reads as low stock
# (never as in stock) and "unavailable"/"not in stock" can never fall
# through to the "available"/"in stock" patterns. `_`/`-` are turned
# into spaces before matching, so the enum/URL spellings OUT_OF_STOCK
# and schema.org/InStock are the same words as their spaced forms.
_OUT_PAT = re.compile(
    r"out\s+of\s+stock|sold\s+out|temporarily\s+unavailable|"
    r"unavailable|not\s+(?:available|in\s+stock)|no\s+longer\s+available",
    re.I,
)
_LOW_PAT = re.compile(
    r"(?:only\s+)?\d+\s*\+?\s*(?:left|remaining)\b|"
    r"(?:low|limited)\s+stock\b|limited\s+availability\b|"
    r"stock\s+(?:running\s+out|low)\b",
    re.I,
)
_IN_PAT = re.compile(r"\b(?:in\s+stock|available)\b", re.I)

# schema.org states availability as a token inside markup —
# '"availability": "https://schema.org/InStock"' in JSON-LD, or an
# itemprop link. PreOrder/BackOrder/... are matched too but parse to
# unknown: they are not one of our three states (C1).
_SCHEMA_AVAIL = re.compile(
    r"(?:https?://)?schema\.org/"
    r"(InStock|OutOfStock|SoldOut|PreOrder|BackOrder|Discontinued"
    r"|LimitedAvailability|PreSale)",
    re.I,
)

# Shipping context words. Only text inside a clause containing one of
# these (or a clause that IS a bare price / a bare day count) may
# contribute a figure — a product price in the next clause of a snippet
# must never become postage (C1).
_DELIVERY_CONTEXT = re.compile(
    r"deliver(?:y|ies|ing|ed)|shipping|postage|dispatch|carriage|courier",
    re.I,
)
# A £ preceded by "over"/"when you spend"/... is a threshold for FREE
# delivery, not this item's cost ("Free delivery on orders over £50").
_CONDITIONAL_HINT = re.compile(
    r"\b(?:over|above|exceeding|when\s+you\s+spend|orders?\s+of"
    r"|minimum\s+spend|free\s+over|free\s+when)\b",
    re.I,
)
_GBP = re.compile(
    r"£\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"
    r"|([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:gbp|pounds?)\b"
    r"|(?:gbp|pounds?)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
    re.I,
)
# A clause that is nothing but a price: the `delivery` field sometimes
# is just "£2.99". Only trusted when it is the ENTIRE text — a bare
# "£12.99" clause inside a longer snippet is the product price.
_BARE_PRICE = re.compile(
    r"^\s*(?:£|gbp\s*)?([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:£|gbp|pounds?)?\s*$",
    re.I,
)
_FREE = re.compile(r"\bfree\b", re.I)
# A clause that is nothing but a day count ("2-3 days", "next day").
_BARE_DAYS = re.compile(
    r"^\s*(?:next[-\s]day|same[-\s]day|tomorrow"
    r"|(?:in\s+|within\s+)?\d+\s*(?:[-\u2013\u2014]|to)?\s*\d*"
    r"\s*(?:working|business)?\s*days?)\s*$",
    re.I,
)
_NEXT_DAY = re.compile(r"\b(?:next|following)[-\s]day\b", re.I)
_RANGE_DAYS = re.compile(
    r"\b(\d+)\s*(?:[-\u2013\u2014]|to)\s*(\d+)\s*(?:working|business)?\s*days?\b",
    re.I,
)
_SOME_DAYS = re.compile(
    r"\b(\d+)\s*(?:working|business)?\s*days?\b", re.I
)
_CLAUSE_SPLIT = re.compile(r"\s*[,;\u00b7|]\s*|\s+(?:and|&)\s+", re.I)


def parse_stock_text(text: str) -> tuple[str, str]:
    """(in_stock_state, raw) for one piece of source text.

    States: "in_stock" | "low_stock" | "out_of_stock" | "" (could not
    tell). Recognises, case-insensitively: "in stock", "only N left",
    "N left in stock", "out of stock", "sold out", "available",
    "limited availability" (the schema.org LimitedAvailability token,
    same words as its visible-text phrasing -> low_stock), "temporarily
    unavailable" — plus the enum/URL spellings
    OUT_OF_STOCK and schema.org/InStock, which are the same words once
    `_`/`-` are spaces.

    Returns ("", text) when the text does not say — unknown is the
    correct answer, not a guess (C1). `raw` is always the text exactly
    as received, even when the state stays unknown, so the row can show
    what the source printed (C13).
    """
    if not isinstance(text, str):
        return "", ""
    if not text.strip():
        return "", text

    # C13 — normalise only for matching; the raw keeps the original.
    words = " ".join(
        text.lower().replace("_", " ").replace("-", " ").split()
    )
    for joined, spaced in (
        ("outofstock", "out of stock"),
        ("soldout", "sold out"),
        ("instock", "in stock"),
        ("limitedavailability", "limited availability"),
    ):
        words = words.replace(joined, spaced)

    if _OUT_PAT.search(words):
        return "out_of_stock", text
    if _LOW_PAT.search(words):
        return "low_stock", text
    if _IN_PAT.search(words):
        return "in_stock", text
    return "", text


def parse_shipping_text(text: str) -> tuple[float, int, str]:
    """(cost, days, raw) for one piece of source text.

    Cost — scanned clause by clause (clauses split on , ; | and "and").
    A clause may contribute only if it contains delivery wording
    ("delivery", "shipping", "postage", ...) — or if the WHOLE text is
    a single bare price (the `delivery` field is sometimes just
    "£2.99"). Within a qualifying clause: a £/GBP figure not preceded
    by a threshold hint ("over £50") is the cost; an explicitly stated
    "free" yields 0.0 when no figure was found. 0.0 means BOTH "source
    said free" and "could not tell" — indistinguishable by number
    alone — so `raw` always carries the exact source text and CALLERS
    MUST TRUST raw WHEN cost IS 0.0. The unread case is raw == "".
    Never converts a non-£ amount: "$4.99 delivery" stays 0.0 (C1).

    Days — read from clauses carrying delivery wording or that ARE a
    bare day count: "next day" -> 1; "2-3 days" -> 3, the range's UPPER
    bound so we never quote a lead time faster than the source did;
    "delivery in 5 days" -> 5. 0 = unknown. Weekday names ("Thursday")
    and "same day" are deliberately NOT parsed — they would need 0,
    which already means unknown.

    Returns (0.0, 0, text) when the text states none of this (C1).
    """
    if not isinstance(text, str):
        return 0.0, 0, ""
    if not text.strip():
        return 0.0, 0, text

    clauses = [c for c in _CLAUSE_SPLIT.split(text) if c.strip()]
    single = len(clauses) == 1

    cost = 0.0
    free_stated = False
    for clause in clauses:
        qualifies = bool(_DELIVERY_CONTEXT.search(clause)) or (
            single and bool(_BARE_PRICE.match(clause))
        )
        if not qualifies:
            continue
        if _FREE.search(clause):
            free_stated = True
        for match in _GBP.finditer(clause):
            window = clause[max(0, match.start() - 44):match.start()]
            if _CONDITIONAL_HINT.search(window):
                continue  # a threshold for free delivery, not a cost
            cost = float(
                (match.group(1) or match.group(2) or match.group(3))
                .replace(",", "")
            )
            break
        if cost:
            break
    if not cost and free_stated:
        cost = 0.0  # stated "free" — 0.0; shipping_raw carries the wording

    days = 0
    for clause in clauses:
        if not (
            _DELIVERY_CONTEXT.search(clause) or _BARE_DAYS.match(clause)
        ):
            continue
        if _NEXT_DAY.search(clause):
            days = 1
            break
        match = _RANGE_DAYS.search(clause)
        if match:
            days = int(match.group(2))  # upper bound — conservative
            break
        match = _SOME_DAYS.search(clause)
        if match:
            days = int(match.group(1))
            break

    return cost, days, text


def parse_structured_availability(text: str) -> tuple[str, str]:
    """(state, raw) from schema.org availability inside page markup.

    Many pages state stock only in structured data —
    `"availability": "https://schema.org/InStock"` in JSON-LD, or an
    itemprop link — never in visible text. This pulls that token out and
    parses it; raw is the token exactly as printed (C13). ("", "") when
    the markup carries no availability token (C1).
    """
    if not isinstance(text, str) or not text.strip():
        return "", ""
    match = _SCHEMA_AVAIL.search(text)
    if not match:
        return "", ""
    return parse_stock_text(match.group(1))


# C13 — eBay's own availability enum, mapped code-for-code. A code we do
# not recognise maps to "" (unknown), never to a state we inferred.
_EBAY_AVAILABILITY = {
    "IN_STOCK": "in_stock",
    "OUT_OF_STOCK": "out_of_stock",
    "TEMPORARILY_OUT_OF_STOCK": "out_of_stock",
    "SOLD_OUT": "out_of_stock",
    "LIMITED_STOCK": "low_stock",
    "LOW_STOCK": "low_stock",
}


def ebay_item_availability(item) -> dict:
    """The six P4 fields read off one eBay Browse-API item / item summary.

    Only keys the response actually carries are read: `availability`
    (enum string or {"code": ...}) and `shippingOptions[]` for the
    shipping cost / estimated delivery date. Anything absent stays
    unknown (C1) — shipping_cost is never a plausible default.

    shipping_raw is the API's own "value currency" text, so a real
    0.00 (free delivery) is told apart from an unread field by raw
    being non-empty (C13). availability_url is the item's web URL, set
    only when a stock figure was actually read.
    """
    state, stock_raw = "", ""
    url = ""
    if isinstance(item, dict):
        url = str(item.get("itemWebUrl") or "")
        avail = item.get("availability")
        if isinstance(avail, dict):
            avail = avail.get("code") or avail.get("status") or ""
        if isinstance(avail, str) and avail.strip():
            stock_raw = avail.strip()
            state = _EBAY_AVAILABILITY.get(
                re.sub(r"[\s-]+", "_", stock_raw.upper()), ""
            )

    cost, days, ship_raw = _ebay_shipping(item)
    return {
        "in_stock": state,
        "stock_raw": stock_raw,
        "availability_url": url if stock_raw else "",
        "shipping_cost": cost,
        "shipping_days": days,
        "shipping_raw": ship_raw,
    }


def _ebay_shipping(item) -> tuple[float, int, str]:
    """(cost, days, raw) from one item's shippingOptions.

    No shippingOptions in the response = (0.0, 0, "") — the field was
    not read, never a default (C1).
    """
    if not isinstance(item, dict):
        return 0.0, 0, ""
    options = item.get("shippingOptions")
    if isinstance(options, dict):
        options = [options]
    if not isinstance(options, list):
        return 0.0, 0, ""

    cost, days, raw = 0.0, 0, ""
    for option in options:
        if not isinstance(option, dict):
            continue
        if not raw:
            shipped = option.get("shippingCost")
            if isinstance(shipped, dict) and shipped.get("value") not in (None, ""):
                value = str(shipped.get("value")).strip()
                currency = str(shipped.get("currency") or "").strip()
                raw = f"{value} {currency}".strip()
                # C1 — only GBP is a figure we can state without a
                # conversion we would have to invent. A non-GBP cost
                # stays 0.0 (unknown); raw keeps the source value.
                if currency.upper() == "GBP":
                    try:
                        cost = float(value.replace(",", ""))
                    except ValueError:
                        cost = 0.0
        if not days:
            days = _days_from_stamp(
                option.get("maxEstimatedDeliveryDate")
                or option.get("minEstimatedDeliveryDate")
                or item.get("maxEstimatedDeliveryDate")
                or item.get("minEstimatedDeliveryDate")
            )
        if raw and days:
            break
    return cost, days, raw


def _days_from_stamp(stamp) -> int:
    """Whole days from now until an ISO-8601 date the API stated.

    Rounded UP — part of a day still costs part of a day, so we never
    quote a lead time faster than the source's own date; a date already
    in the past clamps to 0. 0 is also returned when the value is
    missing or unparsable: unknown, not a default (C1).
    """
    if not isinstance(stamp, str) or not stamp.strip():
        return 0
    try:
        when = datetime.fromisoformat(stamp.strip().replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - datetime.now(timezone.utc)).total_seconds()
        return max(0, math.ceil(seconds / 86400))
    except ValueError:
        return 0


def serpapi_item_availability(item) -> dict:
    """The six P4 fields read off one SerpApi google_shopping result.

    Stock comes from the result's own `stock` / `stock_status` /
    `availability` values; delivery wording from `delivery`, falling
    back to `shipping`, then `snippet`. Whatever the response does not
    carry stays unknown (C1) — no default stock state, no plausible
    postage. A stock value that is not text (number, object) is skipped
    rather than interpreted. availability_url is the result's own link,
    set only when stock text was read.
    """
    state, stock_raw, url = "", "", ""
    ship_text = ""
    if isinstance(item, dict):
        url = str(item.get("link") or "")
        for key in ("stock", "stock_status", "availability"):
            value = item.get(key)
            if isinstance(value, bool):
                # The API's own true/false — quoted, not interpreted.
                cand_state = "in_stock" if value else "out_of_stock"
                cand_raw = "true" if value else "false"
            elif isinstance(value, str):
                cand_state, cand_raw = parse_stock_text(value)
            else:
                continue  # numbers/objects: not text, not interpreted
            if cand_state:
                state, stock_raw = cand_state, cand_raw
                break
            if cand_raw.strip() and not stock_raw:
                stock_raw = cand_raw  # text seen, state still unknown
        for key in ("delivery", "shipping", "snippet"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                ship_text = value
                break

    cost, days, ship_raw = parse_shipping_text(ship_text)
    return {
        "in_stock": state,
        "stock_raw": stock_raw,
        "availability_url": url if stock_raw else "",
        "shipping_cost": cost,
        "shipping_days": days,
        "shipping_raw": ship_raw,
    }
