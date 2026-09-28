# CONSTRAINTS: Price Band (Hard Gate)

Companion to `CONSTRAINTS.md`. Where this file disagrees with any other
document or default value, this file wins.

Status: effective for all environments from the date of commit.
Config source of truth: `backend/config.py` → `FILTERS["price_min"]`,
`FILTERS["price_max"]`.

---

## PR-1 — The Band

- **Minimum:** £5.00 GBP
- **Maximum:** £35.00 GBP
- A product is only eligible if its price falls inside this band,
  inclusive of both endpoints.

The band applies to ALL of the following figures, with no exceptions:

1. eBay listing price (Buy It Now price of the product being analysed)
2. Every supplier price shown in supplier comparison tables
3. All sold-history statistics: minimum, maximum, average, median
4. Any price displayed in exports (CSV / JSON / XLSX)

## PR-2 — Enforcement Layers (all four are mandatory)

The band must be enforced at four separate points. Enforcing only one
layer is a defect.

| # | Layer | Rule |
|---|-------|------|
| 1 | Search time | The band is pushed into the eBay query itself (Browse API `price:[5..35]`, scrape `_udlo`/`_udhi`), so out-of-band data is never fetched |
| 2 | Selection time | The analysis pipeline never selects an out-of-band listing — not as result #1, not ever |
| 3 | Aggregation time | Supplier matches and sold-data rows are filtered before they are collected into any result |
| 4 | Display time | No API response and no UI table may contain an out-of-band figure |

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
The supplier table is empty and the response states how many were
excluded (see PR-4). The analysis continues with the eBay side.

## PR-4 — Transparency

Excluded items are counted and reported. Silent removal is forbidden —
the user must always know that data existed and was filtered out:

    4 supplier matches excluded (over £35)
    12 sold listings excluded from demand stats (over £35)

This keeps the "never fabricate data" rule intact: we neither show
out-of-band figures nor pretend they never existed.

## PR-5 — Single Source of Truth

- The band lives in exactly one place: `backend/config.py` →
  `FILTERS["price_min"] = 5.00`, `FILTERS["price_max"] = 35.00`.
- No hardcoded price literals anywhere else in the backend
  (grep for `25.00`, `price_max` defaults must find config only).
- API schemas (`HunterScanRequest`, `SearchCreate`) default to
  5.0 / 35.0, mirroring config.
- Frontend defaults (Hunter price inputs, saved searches) are 5 / 35.
- The active band is visible in the UI on Analyze and Deep Search
  pages so the user always knows what gate is applied.

## PR-6 — Scope

This constraint applies to every feature that touches prices:

- Analyze (single product, query or URL)
- Deep Search — Fast and Full
- Bulk Analysis
- Category Hunter (scan + supplier lookup)
- Price Tracker and Watchlist results
- Saved searches and their stored results
- Dashboard sales figures entered manually are unaffected —
  they record history, not sourcing candidates
- All exports

## PR-7 — Non-Goals

- This file does not change the other business rules (demand,
  brand, delivery, margin). Only prices are in scope.
- This file does not change the fee model (12.8% + 3%).
- No user-configurable band in the UI for v1 — the band is fixed
  at £5–£35 by this specification. Changing it means amending this
  file, not editing input fields.

---

## Acceptance Criteria

1. Analyze on a generic query returns an eBay product priced ≤ £35.
2. Analyze on a URL over £35 returns the refusal message in < 2s,
   with zero scraper/LLM calls.
3. Deep Search Fast response contains no supplier row or sold
   statistic above £35.
4. Supplier tables show the excluded count when rows were removed.
5. `grep -r "price_max" backend/` shows 35.0 only in config and
   schema mirrors.
6. Hunter and saved-search default inputs read 5 and 35.
