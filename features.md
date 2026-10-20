# eBay Hunter — Implemented Features

Last updated: **2026-10-21**
Scope: the ten-feature expansion in `docs/plans/2026-10-19-feature-expansion/`.

This is the short, durable feature report. The phase-by-phase implementation detail and live
measurements remain in `implementation.md`; the current operating state remains in `HANDOFF.md`.

## Status at a glance

| Phase | Feature                       | Status                                       | Main surface                                     |
| ----- | ----------------------------- | -------------------------------------------- | ------------------------------------------------ |
| A     | Passive capture (extension)   | Shipped — one real-browser run still pending | Chrome extension + `/api/extension/*`            |
| B     | Rich field persistence        | Shipped                                      | `listing_observations`, History                  |
| C     | Verified-first and Sources    | Shipped                                      | Scorecard, `/sources`, `/history`                |
| D     | Fee and break-even calculator | Shipped                                      | `/fees`, `/api/fees/*`                           |
| E     | Alerts and saved searches     | Shipped                                      | `/alerts`, `/api/alerts`, `/api/searches`        |
| F     | Title helper                  | Shipped                                      | `/titles`, `/api/titles`                         |
| G     | Listing age and churn         | Shipped                                      | `/churn`, `/api/observations/*`                  |
| H     | Seller footprint              | Shipped                                      | `/sellers/[username]`, `/api/sellers/{username}` |
| I     | Own-sales P&L and feedback    | Shipped                                      | `/sales`, `/dashboard`, `/api/sales/*`           |
| J     | Marketplace expansion         | Shipped                                      | `/api/markets`, header selector, `/deals`        |

The existing Analyze, Deep Search, Category Hunter, Bulk, Tracker, Watchlist, Dashboard and
History stack is the base these features sit on. It is not re-described here.

---

## A. Passive capture (Chrome extension)

**What it does.** While the user browses eBay UK item pages (`/itm/*`), the extension extracts
the item id and asks for the login-required purchase-history page. It posts that page's HTML to
the local backend. The backend stores a capture only when it can parse both a date and a price
from at least one row.

**User-facing surface.**

- Popup: stored today, requests this hour, backend `items_captured`, last request, quiet mode,
  manual **Capture this item now**, and editable API base.
- **Items captured** is the backend's own row count, not the extension's request counter.
- `service worker (inactive)` is normal; it wakes on a popup or page event.

**Safety rules enforced in code.**

- One request per item per **6 hours** (`DEDUPE_MS`); the manual button deliberately overrides
  the dedupe window.
- Hard cap of **60 attempts per hour** (`MAX_PER_HOUR`), counted as attempts so a failed page is
  not retried on every view.
- Quiet mode stops passive and manual capture.
- The extension never navigates or crawls; it only reacts to pages the user opened.
- No parsed row means nothing is stored; the popup shows the backend's reason.

**Backend API.**

- `POST /api/extension/sold-history`
- `GET /api/extension/sold-history/{item_id}`
- `GET /api/extension/status`

**Manifest and access.** The content script is scoped to `https://www.ebay.co.uk/itm/*`.
Host permissions cover eBay UK plus `http://localhost:8000/*` and
`http://127.0.0.1:8000/*` so the service worker can reach the local API.

**Verification gap.** The code, parser tests and API tests are shipped, but the real-browser
acceptance run has not completed. The extension is loaded, the backend is reachable, and the
current failure while signed out is eBay's login/bot challenge on the purchase-history URL.
A successful run requires the user to be signed in to eBay UK and able to open the
purchase-history page in the same browser profile. The parser's accepted row shapes were written
from an assumption and still need one real capture to confirm.

---

## B. Rich field persistence

**What it does.** Every Browse observation now keeps the fields that were previously discarded:
creation date, origin date, seller feedback and account type, region, condition, postage,
buying options and listing flags.

**Rules.**

- One row per listing per observation; observations are inserted, never upserted.
- A field Browse did not return stays `NULL`; it is never replaced with an epoch, zero or a guess.
- The extractor is pure and has no I/O or database session.
- Observation writes are a side effect of runs that already happen; no extra eBay calls.
- History replays the same values from the stored observation.

**Code.** `backend/scrapers/browse_fields.py`, `backend/db/models.py` (`ListingObservation`),
`backend/db/queries.py`, `backend/api/history.py`.

---

## C. Verified-first and Sources

**What it does.** A verified purchase-history capture outranks every Browse-derived sold figure
for the same product. When no capture exists, the UI says that a search-page count is being
shown and that it is **not a sales total**.

**Rules.**

- Values carry `{value, origin, observed_at}` provenance.
- The verified block is primary on the Scorecard; the search count is demoted and labelled.
- The `/sources` view lists every field and generates the unknowns list from null fields, not
  hard-coded prose.
- `verified`, `estimated`, `unverified` and `ai_insight` are distinct provenance states.

**Code.** `backend/db/models.py`, `backend/db/queries.py`, `backend/api/history.py`,
`backend/api/schemas.py`, `frontend/lib/fieldProvenance.ts`, `frontend/components/Scorecard.tsx`,
`frontend/app/sources/page.tsx`.

---

## D. Fee and break-even calculator

**What it does.** A single fee engine calculates a full breakdown and supports reverse mode:
solve for the list price that reaches a target margin, or the break-even price.

**Inputs covered.** Sale price, postage, category, promoted-listing rate, seller type, VAT flag,
supplier cost and shipping cost. The response states the fee-table version used.

**Rules.**

- `backend/engine/fees.py` is the only fee implementation; the pipeline verdict and calculator
  call the same `sale_outcome()` path and cannot disagree.
- Reverse mode round-trips within a penny.
- `price=None` is an unread price, not a zero; it produces no calculation.
- Unknown categories use an explicit, stated default rather than a guessed fee.
- The active UK table is `uk-rate-card-2026-09-30` with 55 category rows; seller defaults come
  from `SELLER_PROFILE`.

**Surfaces.**

- UI: `/fees` (forward and reverse modes).
- API: `GET /api/fees/table`, `POST /api/fees/calculate`.
- Shared component: `frontend/components/FeeBreakdown.tsx`.

**Limits.** Only the UK has a fee table. Every other marketplace returns a UK-only refusal
rather than applying the UK card to a foreign sale (see Phase J).

---

## E. Alerts and saved searches

**What it does.** A scheduled pass compares real price readings and writes an alert only when
there are two values to compare. Saved searches run through the Hunter path and store only
results that have a real supplier price and a real margin.

**Alert rules.**

- An alert names the two values it compared: old and new price, or old and new margin.
- A missing, zero, negative or non-numeric price is **unread**, never zero, and creates no alert.
- Item lane compares `price_history` readings and the product target; query lane compares
  consecutive `demand_snapshots.avg_price` readings and labels the number **average asking
  price**.
- A per-item target is not applied to a market average.
- Dedupe prevents the same product/alert type/new price/message from being written repeatedly.
- Margin alerts require a real supplier cost; the postage caveat appears when profit is
  incomplete.

**Saved-search budget.**

- At most **10** searches per pass.
- One Browse search call per run.
- Default budget **30 seconds**.
- Every report states `searches_run`, `searches_not_run` and `browse_calls`.
- A result row requires a named listing URL, eBay price > 0, real supplier price > 0, price
  inside the search band, profit > 0 and margin at or above the search's own minimum.
- An empty run still stamps `last_run` with a sentence; it does not fabricate a result.

**Surfaces.**

- UI: `/alerts` inbox with four filters and unread badge; saved-search controls live with the
  existing Watchlist surface.
- API: `GET /api/alerts`, `GET /api/alerts/count`, `POST /api/alerts/read-all`,
  `POST /api/alerts/{alert_id}/read`; saved-search routes under `/api/searches`.
- Scheduled entry point: `backend/scripts/run_alerts.py` / `.cmd`; Windows task
  **eBayHunter Alerts** runs hourly at zero Browse cost.

**Honest limits.** The item lane is silent while eBay `/itm/` pages return 403 through the
scraper. SerpApi is at 0/250 until **2026-11-08**, so saved-search runs may legitimately refuse
with "no real supplier price was found".

---

## F. Title helper

**What it does.** Reads one real Browse page of New listings for a query and reports which words
and adjacent word pairs appear in the titles, always with the number of listings analysed.

**Rules.**

- A count is the number of **listings** containing the word or pair, not the number of
  occurrences. One listing contributes at most once.
- Bigrams are literal adjacent pairs; stop words break a pair rather than being skipped.
- The response is exactly `query`, `listings_analysed`, `unigrams`, `bigrams`, `reason`. No
  volume, popularity, rank or score field exists.
- A measured zero is only when eBay returned no listings, and it carries a sentence. A failed
  Browse call is a 502; missing credentials are a 503. Neither is "nothing exists".
- The sample is New listings for the query with no buying price band, capped at 50; the helper
  describes that page, not every matching title on eBay.
- The 80-character meter counts characters with `Array.from`; the draft can exceed 80 so the
  over-limit state is visible.

**Surfaces.** UI `/titles`; API `GET /api/titles?q=`. No table writes.

---

## G. Listing age and churn

**What it does.** Computes listing age from eBay's own `item_creation_date` and reports whether
listings seen in an earlier completed search are missing from the latest comparable search.

**Rules.**

- Age is from eBay's creation date, not from this app's first sighting; "first seen here" is a
  separate label.
- Fewer than two observations means no churn claim: `churned: null` with a sentence, not a
  zero-filled result.
- Churn compares the latest set with **every** earlier set, not just the previous one. A listing
  that reappears is not reported.
- The copy is **"no longer listed"** with the last-seen date. The module does not say "sold".
- Two observations with different filters or sample limits are not comparable and return
  `null`.
- A search completed before a pipeline timeout is still stored; a timeout before any search
  writes nothing.
- There is no rate, percentage or trend field; the sample size is reported, not extrapolated.

**Surfaces.** UI `/churn`; API `GET /api/observations/churn?query=`,
`GET /api/observations/{listing_id}`. Read-only; spends no Browse call.

---

## H. Seller footprint

**What it does.** Aggregates the stored observations for one seller into a read-only footprint.

**Rules.**

- Seller names match case-insensitively; the response echoes the stored spelling.
- Feedback percentage and score, account type, region and condition come from the latest
  reading that carried them; values are never stitched across readings.
- Account type is displayed raw (`BUSINESS` / `INDIVIDUAL`); it is not inferred.
- Condition shares divide by listings whose condition was actually read; unknowns are separate.
- Price range and median use one price per listing. A mixed-currency sample returns `null` with
  a sentence rather than converting.
- A single observed price is shown once, not as a fake low-high range.
- No computed seller score, revenue, sales, sold or turnover field exists.
- An unknown seller is HTTP 200 with `observed_listings: 0`, null sections and a sentence — not a
  404 and not a zero-filled panel.

**Surfaces.** UI `/sellers/[username]`; API `GET /api/sellers/{username}`. The page carries the
standing disclaimer that it describes active listings only, not a seller-wide census. Read-only;
spends no Browse call.

---

## I. Own-sales P&L and feedback

**What it does.** User-entered sales, CSV import, revenue/profit/margin summaries, monthly trend
and a read-only C14 threshold replay.

**Sales rules.**

- Sales are **user-declared** and labelled as such. They are not eBay observations.
- A sale requires `sale_price`, `supplier_cost`, `shipping_cost`, `ebay_fees`, `quantity` and
  `sale_date`. A blank cost is a 422, not a zero; an explicit `0` is accepted.
- Costs are per unit and multiplied by quantity. The backend recomputes profit and margin; CSV
  profit and margin columns are ignored.
- If any contributing sale has unknown profit, totals are `null` with a sentence naming the
  missing count; the monthly chart draws a gap, not a zero bar.
- A growth percentage is reported only when both current and previous windows contain real
  user-declared sales.
- `monthly_stats` is recomputed on every create, update, delete and import. The live constraint
  is `uq_monthly_stats_year_month` on `(year, month)`, migrated from the old separate unique
  constraints.

**C14 feedback.** `GET /api/sales/thresholds` replays stored supplier-match scores and verdicts
against proposed thresholds. It reports differences; it never writes a threshold or a match.
Rows below the original matcher thresholds were never stored and are outside the sample.

**Surfaces.** UI `/sales` and `/dashboard`; API `/api/sales`, `/api/sales/summary`,
`/api/sales/thresholds`, `/api/sales/import`. The dashboard carries the **User-declared** badge
and the sentence that these are the user's records, not eBay observations.

**Live state.** The sales table was intentionally left empty; no demo sale was inserted. Write
path evidence is the test suite and import tests, not an invented record.

---

## J. Marketplace expansion

**What it does.** Adds a marketplace registry, a header selector and market-aware Browse,
Analyze and Deals paths without allowing cross-currency arithmetic.

**Registered markets.** `EBAY_GB` (default), `EBAY_US`, `EBAY_DE`, `EBAY_AU`, `EBAY_CA`.
`EBAY_IE` is deliberately absent because its `/deals` URL redirected into eBay's splashui
challenge, not a deals board.

**Rules.**

- `X-Ebay-Marketplace` is sent on every frontend API call; `?marketplace=` is accepted for direct
  callers and wins when both are present.
- An unknown marketplace is a 422; there is no silent UK fallback.
- Only `EBAY_GB` has a fee table. `/api/fees/table`, `/api/fees/calculate`, Deep Search, Bulk and
  Category Hunter return 422 with a UK-only sentence for other markets.
- Non-UK Analyze is **search-only**: one real Browse search and demand read, no supplier
  matches, no profit, no verdict, no GBP price band and no History write. The response carries
  `marketplace`, `currency` and both refusal sentences.
- Deals are stored per market with `UNIQUE(marketplace, listing_id)`. A refresh deletes only that
  market's absent cards; other markets and the UK hourly job are untouched.
- Non-UK deals refresh skips `listing_observations` because that evidence store is not
  marketplace-keyed; the result says so.
- The deals parser handles both flat UK/DE cards and nested US/globaldeals/AU/CA cards.
- `formatMoney` formats one amount in its own currency and never converts or adds. Supplier rows
  stay explicitly GBP; `None` stays an em dash; `0` stays a measured zero.
- A non-200 deals page or a failed refresh is reported (`502` synchronously,
  `last_refresh_error` in the board meta), never rendered as a measured empty board.

**Surfaces.** Header selector, `/deals`, `/api/markets`, market-aware Analyze and currency
formatting. Live check on **2026-10-21**: five markets, all deals URLs HTTP 200; only GB has a
fee table. The observed card samples were GB 72, US 21, DE 80, AU 76, CA 57 — page observations,
not sales counts. The US refresh stored 21 US rows, all USD; the UK board remained 73 rows.

**Limits.** No non-UK fee table exists, so non-UK fee/profit figures are absent by design.
`EbaySoldScraper` and the Deep Search/Hunter supplier paths remain UK-only and were not
market-wired.

---

## Cross-cutting guarantees

- **No fabricated values.** Every figure is measured or explicitly `None`; a refusal carries a
  sentence. Missing is never zero.
- **Provenance travels with values.** Verified, estimated, unverified and AI insight are distinct
  labels.
- **Samples are declared.** Counts describe the listings or rows actually read; they are not
  extrapolated into market totals.
- **Currencies are never summed or converted.** Each amount stays in its own currency.
- **Execution is bounded.** Pipeline stages have time budgets; timeout paths report partial
  results rather than hanging.
- **User-declared is separate from observed.** Sales entered by the user are labelled as such and
  never presented as eBay observations.

## Running locally

- Frontend: <http://localhost:3000>
- Backend health: <http://127.0.0.1:8000/api/health>
- API docs: <http://127.0.0.1:8000/docs>
- Extension status: <http://127.0.0.1:8000/api/extension/status>
- Markets: <http://127.0.0.1:8000/api/markets>

Start and stop from the repo root:

```powershell
.\start.ps1
.\stop.ps1
```

`start.ps1` starts the backend on `127.0.0.1:8000` and the frontend on `localhost:3000`.
Logs are written to `.logs/`.

## Verification

Measured at the Phase J close on **2026-10-21**:

- Backend: **1712 passed, 9 deselected**.
- Frontend: **216 tests across 16 files**, typecheck clean.
- Production build: **18 route rows**, including `/sales`, `/churn`, `/titles` and the dynamic
  `/sellers/[username]`.
- Phase J live evidence: **5** registered markets, all deals URLs HTTP 200, only GB with a fee
  table; US deals refresh **21/21 priced**, all USD.
- Phase A: extension code, manifest and backend tests pass; the real-browser capture run is the
  one remaining verification gap.

## Known limits and deferred items

- **Phase A browser run.** The extension has not completed a real capture. It needs a signed-in
  eBay UK session; eBay's login/bot challenge on the purchase-history URL currently blocks the
  background fetch. Do not fabricate a capture to close this.
- **eBay page access.** eBay `/itm/` pages return 403 through the scraper and Marketplace
  Insights returns 403; item-lane alerts stay silent until tracker checks can read pages.
- **SerpApi.** At 0/250 until **2026-11-08**; supplier discovery and saved-search runs may
  legitimately refuse.
- **Credentials.** The previously exposed GitHub token and ScrapingBee key remain to be rotated.
- **User decisions pending.**
  - the history migration offer;
  - four redundant `listing_observations` rows on listing `266923866336`;
  - Deep Search / batch demand-check observation wiring;
  - the deferred seed button.
- **No Phase K.** The ten planned phases are complete; the remaining items are verification,
  security and user decisions.

## Where the detail lives

| Document                                                    | Purpose                                                   |
| ----------------------------------------------------------- | --------------------------------------------------------- |
| `docs/plans/2026-10-19-feature-expansion/HANDOFF.md`        | Current state, live evidence, blockers, next move         |
| `docs/plans/2026-10-19-feature-expansion/implementation.md` | Phase specs, rules and shipped evidence                   |
| `docs/plans/2026-10-19-feature-expansion/design.md`         | UI surfaces and design rules                              |
| `CONSTRAINTS.md`                                            | Non-negotiable money, labelling and non-fabrication rules |
