"""Pure parser for eBay's server-side purchase-history page (P5, Track B).

The page (https://www.ebay.co.uk/bin/purchaseHistory?item={id}) sits behind a
login wall, so its real markup has never been captured in this repo.

★ ASSUMPTION (fixture shape): the row shapes accepted below — a table of rows
with data cells, or list items whose class/id mentions purchase/order/sold/
sale/history/transaction — are a best guess and must be verified against ONE
real browser capture before these counts are fully trusted in production.
The fixture HTML in tests/test_extension_bridge.py is deliberately synthetic.

Never guesses (CONSTRAINTS.md C1): a row only counts as a sale when BOTH its
date and its price parse; everything else is merely counted in `rows_seen`.
"""

import re
from datetime import date, datetime, timedelta
from typing import Optional

from bs4 import BeautifulSoup, Tag

# ── date parsing (common UK formats: "12 Sep 2026", "12/09/2026", ISO) ──

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_DMY_TEXT_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b")
_MDY_TEXT_RE = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b")
_DMY_NUM_RE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")

# ── price parsing (£12.99 / GBP 12.99 / bare 1,299.00 or 12.99) ──────────

_PRICE_RE = re.compile(r"(?:£|GBP\s*)(\d[\d,]*(?:\.\d{1,2})?)", re.IGNORECASE)
_BARE_PRICE_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+\.\d{2})(?![\d.,])"
)

# Heuristic class/id hints for list-style markup (fallback when no <table>).
_ROW_HINTS = ("purchase", "order", "sold", "sale", "history", "transaction")


def _to_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date(text: str) -> Optional[date]:
    """First parseable date in `text`, or None — never guesses."""
    if not text:
        return None

    m = _ISO_DATE_RE.search(text)
    if m:
        d = _to_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d

    m = _DMY_TEXT_RE.search(text)
    if m:
        month = _MONTHS.get(m.group(2).lower()[:3])
        if month:
            d = _to_date(int(m.group(3)), month, int(m.group(1)))
            if d:
                return d

    m = _MDY_TEXT_RE.search(text)
    if m:
        month = _MONTHS.get(m.group(1).lower()[:3])
        if month:
            d = _to_date(int(m.group(3)), month, int(m.group(2)))
            if d:
                return d

    m = _DMY_NUM_RE.search(text)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if b > 12 and a <= 12:
            # Unambiguous month-first input (e.g. 09/13/2026).
            day, month = b, a
        else:
            # UK default is day-first (e.g. 17/09/2026).
            day, month = a, b
        d = _to_date(year, month, day)
        if d:
            return d

    return None


def parse_price(text: str) -> Optional[float]:
    """First parseable price in `text`, or None — never guesses."""
    if not text:
        return None
    m = _PRICE_RE.search(text) or _BARE_PRICE_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _row_text(el: Tag) -> str:
    return el.get_text(" ", strip=True)


def _candidate_row_texts(html: str) -> list[str]:
    """Text of every plausible sale row on the page (see ★ note above)."""
    soup = BeautifulSoup(html, "html.parser")

    # Preferred shape: table rows that actually have data cells.
    table_rows = [tr for tr in soup.find_all("tr") if tr.find("td") is not None]
    if table_rows:
        return [_row_text(tr) for tr in table_rows]

    # Fallback shape: list/div rows whose class or id looks like a sale row.
    def _hinted(el: Tag) -> bool:
        blob = " ".join(el.get("class") or []) + " " + (el.get("id") or "")
        blob = blob.lower()
        return any(token in blob for token in _ROW_HINTS)

    matched = [el for el in soup.find_all(["li", "div"]) if _hinted(el)]
    # Keep only the deepest matches so a container and its rows aren't
    # counted twice.
    matched_ids = {id(el) for el in matched}
    deepest = [
        el for el in matched
        if not any(id(d) in matched_ids for d in el.descendants if isinstance(d, Tag))
    ]
    return [_row_text(el) for el in deepest]


def parse_purchase_history(html: str, now: datetime | None = None) -> dict:
    """Parse a captured purchase-history page into verified sale counts.

    Returns:
        {"sales": [{"date": "YYYY-MM-DD", "price": float}, ...],
         "sold_7d": int | None, "sold_30d": int | None, "rows_seen": int}

    Rules:
      * `rows_seen` counts every candidate row examined; rows missing a date
        or a price are counted but NEVER guessed (C1).
      * `sold_7d` = sales dated within 7 days of `now`; 0 when sales rows
        exist but none are in the window; None when nothing parsed.
      * `sold_30d` = sales within 30 days ONLY when the capture demonstrably
        covers the whole window (earliest sale >= 30 days before `now`),
        otherwise None — we never undercount silently.
      * Unrecognised/empty page -> all None/empty with rows_seen 0.
    """
    empty = {"sales": [], "sold_7d": None, "sold_30d": None, "rows_seen": 0}
    if not html or not html.strip():
        return empty

    row_texts = _candidate_row_texts(html)
    if not row_texts:
        return empty

    sales: list[dict] = []
    for text in row_texts:
        sale_date = parse_date(text)
        price = parse_price(text)
        if sale_date is None or price is None:
            continue
        sales.append({"date": sale_date.isoformat(), "price": price})

    if not sales:
        # Rows existed but none was a parseable sale — nothing to count.
        return {"sales": [], "sold_7d": None, "sold_30d": None,
                "rows_seen": len(row_texts)}

    if isinstance(now, datetime):
        today = now.date()
    elif isinstance(now, date):
        today = now
    else:
        today = datetime.utcnow().date()

    cutoff_7 = today - timedelta(days=7)
    cutoff_30 = today - timedelta(days=30)
    dates = [date.fromisoformat(s["date"]) for s in sales]
    # Future-dated rows (clock skew / parse anomaly) stay in `sales` but are
    # never counted — a verified figure must not be inflated (C1).
    countable = [d for d in dates if d <= today]

    sold_7d = sum(1 for d in countable if d >= cutoff_7)
    # 30-day coverage: only report it when the capture reaches back at least
    # 30 days (★ assumes the page lists the complete history in between).
    if countable and min(countable) <= cutoff_30:
        sold_30d = sum(1 for d in countable if d >= cutoff_30)
    else:
        sold_30d = None

    return {"sales": sales, "sold_7d": sold_7d, "sold_30d": sold_30d,
            "rows_seen": len(row_texts)}


def extract_item_id(url: str | None) -> Optional[str]:
    """eBay item id from a listing URL (/itm/…/1234567890) or a ?item= param."""
    if not url:
        return None
    m = re.search(r"[?&]item=(\d+)", url) or re.search(
        r"/itm/(?:[^/?#]+/)*(\d+)", url
    )
    return m.group(1) if m else None
