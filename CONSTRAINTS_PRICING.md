# CONSTRAINTS: Price Band (Hard Gate)

Companion to `CONSTRAINTS.md`. Where this file disagrees with any other
document or default value, this file wins.

Status: **Reviewed — amendments applied September 2026**
Config source of truth: `backend/config.py` → `FILTERS["price_min"]`,
`FILTERS["price_max"]`.

---

## PR-1 — The Band

- **Default minimum:** £5.00 GBP
- **Default maximum:** £35.00 GBP
- The active range is user-adjustable (PR-7); defaults are what a fresh
  install uses.
- A product is only eligible if its price falls inside the **active**
  range, inclusive of both endpoints.

The band applies to ALL of the following figures:

1. eBay listing price (Buy It Now price of the product being analysed)
2. All sold-history statistics: minimum, maximum, average, median
3. Any price displayed in exports (CSV / JSON / XLSX)

Supplier prices are exempt — never excluded for being cheap (margin
decides); they are displayed in full.

## PR-2 — Enforcement Layers (all four are mandatory)

The band must be enforced at four separate points. Enforcing only one
layer is a defect.

| #   | Layer            | Rule                                                                                                                                                                                                                                                                                   |
| --- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Search time      | The **active range** is pushed into the eBay query itself (Browse API `price:[min..max]`, scrape `_udlo`/`_udhi`), so out-of-range data is never fetched                                                                                                                               |
| 2   | Selection time   | The analysis pipeline never selects an out-of-range listing — not as result #1, not ever. Tracker/watchlist storage is not selection: they store any price (PR-6)                                                                                                                      |
| 3   | Aggregation time | Sold-data rows are filtered before they are collected into any result; supplier rows are never excluded by price                                                                                                                                                                       |
| 4   | Display time     | No analysis response (Analyze, Deep Search, Bulk, Hunter) and no analysis table may present an out-of-range figure as an in-band one. Stored rows (tracker/watchlist/history) may display out-of-range prices **flagged `outside_band`** per PR-6, and PR-4 exclusion counts are shown |

## PR-3 — Out-of-Band Behaviour

**Case A — User pastes a URL of a listing over £35.**
The pipeline refuses before doing any work. Response:

> This listing is £257.00 — outside your £5–£35 band.

No eBay demand fetch, no supplier search, no LLM call. The refusal
includes the actual price and the band.

**Case B — User enters a search query.**
The system selects the first listing that falls inside the band.
Out-of-band results are discarded during selection.

**Case C — No listing exists inside the band.**
Return an honest empty result:

> No eBay listing for "…" found in the £5–£35 band.

Never fall back to an out-of-band listing. Never guess a price.

**Case D — Supplier search returns only over-£35 prices.**
Superseded by the supplier-price exemption (PR-1): all supplier prices
display in full; margin decides buyability. The analysis continues with
the eBay side.

## PR-4 — Transparency

Excluded items are counted and reported. Silent removal is forbidden —
the user must always know that data existed and was filtered out:

    12 sold listings excluded from demand stats (outside the £5.00–£35.00 range)

This keeps the "never fabricate data" rule intact: we neither show
out-of-band figures nor pretend they never existed.

## PR-5 — Single Source of Truth

- The defaults live in exactly one place: `backend/config.py` →
  `FILTERS["price_min"] = 5.00`, `FILTERS["price_max"] = 35.00`.
  `FILTERS["price_min"]` / `FILTERS["price_max"]` are the DEFAULTS;
  the active range is user-adjustable and still visible in the UI.
- No hardcoded price literals anywhere else in the backend
  (grep for `25.00`, `price_max` defaults must find config only).
- API schemas (`HunterScanRequest`, `SearchCreate`) leave the range
  unset by default and resolve it server-side to the ACTIVE range;
  config's 5.00/35.00 is the mirror used only when no user-adjusted
  range exists.
- Frontend defaults (Hunter price inputs, saved searches) show the
  ACTIVE range (5 / 35 until the user adjusts it).
- The active band is visible in the UI on Analyze and Deep Search
  pages so the user always knows what gate is applied.

## PR-6 — Scope

This constraint applies to every feature that touches prices:

- Analyze (single product, query or URL)
- Deep Search — Fast and Full
- Bulk Analysis
- Category Hunter (scan + supplier lookup)
- Price Tracker and Watchlist: store any price, flag rows outside the
  active range as `outside_band`, list endpoints accept price_min/price_max
  view-filter params (default = active range)
- Saved searches and their stored results
- Dashboard sales figures entered manually are unaffected —
  they record history, not sourcing candidates
- All exports

## PR-7 — Non-Goals

- This file does not change the other business rules (demand,
  brand, delivery, margin). Only prices are in scope.
- This file does not change the fee model (see `CONSTRAINTS.md`, C3).
- The range is user-configurable with default £5–£35; analysis pages
  expose the range inputs, tracker/watchlist/history expose view filters;
  enforcement layers always use the active value.

---

## Acceptance Criteria

1. Analyze on a generic query returns an eBay product inside the active range (default £5–£35).
2. Analyze on a URL outside the active range returns the refusal message in < 2s,
   with zero scraper/LLM calls.
3. Deep Search Fast response contains no sold statistic outside the active range.
4. Supplier tables show every supplier price in full; no supplier row
   is excluded by price.
5. `grep -r "price_max" backend/` finds literals only in `config.py` (the
   defaults), schema/db mirrors that reference config, and validation bounds
   in `utils/filters.py` — never a gate-level literal.
6. Hunter and saved-search default inputs read 5 and 35.
