# Implementation

Per-phase work. Each phase is one commit, and each ends with the verification block from
`outcome.md`.

Run before every push (no git hooks exist):

```
cd backend  && python -m pytest tests/ -q      expect 1203 passed, 9 deselected
cd frontend && npx vitest run                  expect 54 passed
cd frontend && npx tsc --noEmit                expect exit 0
npm --prefix frontend run build                expect 11 routes
```

Restore `backend/data/custom_filters.json` first or about 10 price-band tests fail.

---

## Phase A - Passive capture

**Goal:** captures happen without the user asking.

### Files

| File                                | Change                                                                                                     |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `extension/manifest.json`           | add `content_scripts` for `https://www.ebay.co.uk/itm/*`; add `webNavigation`; keep `storage`, `activeTab` |
| `extension/content.js`              | NEW - detect item id from the URL, message the worker, no DOM scraping                                     |
| `extension/background.js`           | CHANGED - dedupe window, capture counter, badge, quiet mode                                                |
| `extension/popup.js` / `popup.html` | CHANGED - today's count, last capture, backend reachability, quiet toggle, seed button                     |
| `extension/README.md`               | CHANGED - document passive behaviour and the safety boundary                                               |
| `backend/api/extension.py`          | CHANGED - add `GET /extension/status`; keep POST and GET-by-id unchanged                                   |
| `tests/test_extension_api.py`       | NEW - offline tests for status, dedupe acceptance, quiet mode                                              |

### Behaviour

1. `content.js` fires on item pages, extracts the id with the existing regex
   (`/itm/(?:[^/?#]+\/)*(\d+)/`), and sends `{type: "item-seen", itemId}` to the worker.
2. `background.js` checks a dedupe map in `chrome.storage.local`
   (`{itemId: lastCapturedMs}`). Outside the window (default 6 hours, configurable) it fetches
   the purchase-history page and POSTs it.
3. On success it increments a per-day counter keyed by local date, stores the last-capture time,
   and sets the badge.
4. Quiet mode is a stored flag; when set, `content.js` returns immediately, no network occurs.
5. Failures are recorded in storage with a reason and surfaced in the popup - never silently
   dropped.

### Safety limits to enforce in code

- One capture per item per dedupe window. Non-negotiable.
- A hard cap on captures per hour (recommend 60), after which the worker stops and the popup says
  why. The cap must be lower than anything resembling automation.
- No navigation. The extension never opens a tab. It only reacts to pages the user opened.
- The seed queue accepts a bounded list (recommend max 25), spaces captures by a visible delay,
  and refuses to run while quiet mode is on.

### Acceptance

Browse ten item pages normally. Expect: ten rows in `purchase_captures`, no duplicates,
badge showing 10, and `GET /api/extension/status` reporting the same count.

---

## Phase B - Rich field persistence

**Goal:** stop discarding fields already in hand.

### Files

| File                                        | Change                                                                                                                                                |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/scrapers/browse_fields.py`         | NEW - one extractor: given a Browse item summary, return creation date, origin date, seller triple, region, condition, postage, buying options, flags |
| `backend/scrapers/ebay_deals.py`            | CHANGED - call the extractor rather than reading fields ad hoc                                                                                        |
| `backend/scrapers/ebay_sold.py` / `ebay.py` | CHANGED - same extractor at the demand sites                                                                                                          |
| `backend/db/models.py`                      | NEW `ListingObservation` model; `ensure_listing_observations_table()` at the END of the module                                                        |
| `backend/db/database.py`                    | CHANGED - idempotent `ensure_observation_columns()`                                                                                                   |
| `backend/db/queries.py`                     | CHANGED - insert observations; replay them for History                                                                                                |
| `backend/api/history.py`                    | CHANGED - replay the new fields                                                                                                                       |
| `tests/test_observations.py`                | NEW - extractor, persistence, idempotent migration, NULL-preservation                                                                                 |

### Rules

- One row per listing per observation. Never upsert.
- `NULL` for anything Browse did not return. A missing `item_creation_date` is "not read", not
  an epoch.
- The extractor must be pure - no I/O, no session - so it is trivially testable.
- Insertion must be a side effect of runs that already happen. **No new API calls.**

### Acceptance

Run one Analyze. Confirm the observation rows carry creation date, seller feedback, account type,
region and postage. Replay the same run from History and confirm identical values.

---

## Phase C - Verified-first and Sources

**Goal:** the differentiator becomes visible.

### Files

| File                                                        | Change                                                                                 |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `backend/db/models.py`                                      | `DemandData` gains columns identifying a verified sold source and its capture time     |
| `backend/db/queries.py`                                     | write them; `data_source` sentence states which produced the sold figure               |
| `backend/api/history.py`, `api/schemas.py`                  | serialise `{value, origin, observed_at}`                                               |
| `frontend/lib/types.ts`                                     | add the origin-triple shape                                                            |
| `frontend/lib/fieldProvenance.ts`                           | map new origins to badge tones                                                         |
| `frontend/components/Scorecard.tsx`                         | verified block as primary; search count demoted and re-labelled                        |
| `frontend/app/history/page.tsx`, `app/deep-search/page.tsx` | Sources link per product                                                               |
| `frontend/app/sources/page.tsx`                             | NEW - the per-product Sources view with the unknowns list                              |
| `tests/test_verified_priority.py`                           | NEW - verified outranks a search count; absent capture falls back with the right label |
| `frontend/lib/fieldProvenance.test.ts`                      | CHANGED - cover the new origins                                                        |

### Rules

- A verified capture outranks every Browse-derived figure for the same product.
- When no capture exists, the copy states that a search-page count is being shown and that it is
  not a sales total.
- The unknowns list is generated from which fields are null, not hard-coded prose.

### Acceptance

Open a product with a capture: verified figure first with the capture date. Open one without:
search count, correctly labelled, plus the explanatory sentence. Sources view lists every field
and the unknowns.

---

## Phase D - Fee and break-even calculator

**Goal:** the money numbers are defensible and exist in exactly one place.

### Files

| File                                         | Change                                                                                                                                                              |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/engine/fees.py`                     | NEW - the only fee implementation. Takes price, postage, category, promoted rate, seller type, VAT flag; returns a breakdown; `solve_for_margin()` for reverse mode |
| `backend/api/fees.py`                        | NEW - `POST /api/fees/calculate`                                                                                                                                    |
| `backend/engine/scorecard.py`, `pipeline.py` | CHANGED - verdict profit and margin come from `engine/fees.py`, removing any duplicate arithmetic                                                                   |
| `frontend/app/fees/page.tsx`                 | NEW - calculator with reverse-mode toggle                                                                                                                           |
| `frontend/components/FeeBreakdown.tsx`       | NEW - shared breakdown table                                                                                                                                        |
| `tests/test_fees.py`                         | NEW - forward and reverse round-trip, business vs private, VAT, zero-price, unread price                                                                            |

### Rules

- Every response states the fee table version used.
- Reverse mode must round-trip: solving for a margin then recomputing must return the same margin
  within a penny.
- An unread price is not a zero price. `price=None` must not produce a calculation.
- Do not guess a fee. If a category is unknown, say so and use an explicit, stated default.

### Acceptance

For a business seller at GBP 24.99 with 2% promoted and GBP 3.20 postage paid, the breakdown is
arithmetically consistent; the same inputs through the pipeline verdict give the same profit.

### Shipped 2026-10-20

Beyond the file table above: `GET /api/fees/table` (active table with version and sources, UI-ready category rows, the seller profile), `tests/test_fees_api.py` (27 tests through the HTTP door) and `frontend/lib/fees.ts` (typed client plus a pure form-to-request mapper with vitest coverage). The seller defaults live in `config.SELLER_PROFILE` and are carried - never guessed - into the verdict, the scorecard, the CLI and the calculator.

Live evidence from the running stack, 2026-10-20:

| What                | Inputs                                                                                                          | Answer                                                                                              |
| ------------------- | --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Acceptance, forward | business seller, GBP 24.99, no category (stated default), 2% promoted, GBP 3.20 postage paid, GBP 9.40 supplier | 3.22 + 0.40 + 0.09 + 0.50 fees, 0.84 VAT, cost 5.05, net 19.94, profit **6.59**, margin **26.4%**   |
| Reverse round-trip  | target 30% on the same costs                                                                                    | list at **26.86**; check recomputes profit 8.06 / margin 30.0; forward at 26.86 returns margin 30.0 |
| Break-even          | 0% target on the same costs                                                                                     | **16.63** (rounded up to the penny; recomputed profit 0.01 at it)                                   |
| Refusal             | sale price GBP 0                                                                                                | 422 - "sale_price must be greater than zero..."                                                     |
| Table route         | -                                                                                                               | `uk-rate-card-2026-09-30`, 55 category rows, profile defaults carried                               |
| Page                | -                                                                                                               | `/fees` 200; nav entry and break-even wording present in the shipped chunks                         |

The same acceptance inputs through the pipeline verdict return the same profit (6.59 / 26.4%) - both call `engine/fees.py sale_outcome()`, so they cannot disagree.

---

## Phase E - Alerts

**Goal:** feed two dead tables and make the tool push.

### Files

| File                                                    | Change                                                                                                      |
| ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `backend/hunter/alerts.py`                              | NEW - compare latest price observations against the previous and previous target; write `price_alerts` rows |
| `backend/hunter/saved_searches.py`                      | NEW - run a saved search through Hunter and write `search_results` rows                                     |
| `backend/api/alerts.py`                                 | NEW - list, mark read, count unread                                                                         |
| `backend/api/history.py` or a new `api/saved_search.py` | saved-search CRUD and run                                                                                   |
| `backend/scripts/run_alerts.py`                         | NEW - scheduled entry point, no Browse cost                                                                 |
| `frontend/app/alerts/page.tsx`                          | NEW - inbox with filters                                                                                    |
| `frontend/components/Layout.tsx`                        | CHANGED - unread badge and NAV entries                                                                      |
| `tests/test_alerts.py`                                  | NEW - alert row written only when two real prices differ; no alert on a missing price                       |

### Rules

- An alert must name the two values it compared. No comparison, no row.
- A missing price never generates a price alert.
- Saved-search runs consume Browse quota: ship alerts first with zero Browse cost, then enable
  saved-search runs with a stated budget.

### Acceptance

Change a tracked price; a `price_alerts` row appears with old and new values and renders in the
inbox. Run a saved search; `search_results` rows appear.

---

## Phase F - Title helper

### Files

| File                           | Change                                                                  |
| ------------------------------ | ----------------------------------------------------------------------- |
| `backend/engine/titles.py`     | NEW - tokenise titles, count unigrams and bigrams, return counts plus N |
| `backend/api/titles.py`        | NEW - `GET /api/titles?q=`                                              |
| `frontend/app/titles/page.tsx` | NEW - frequency tables and an 80-character meter                        |
| `tests/test_titles.py`         | NEW - tokenisation, stop words, N reported, no volume field can exist   |

### Rules

- Always report **how many listings** produced the counts.
- No field may be named or shaped like search volume. Add the same style of test used for the
  banned popularity column.
- Counts come from listings actually fetched for that query, not a global corpus.

---

## Phase G - Listing age and churn

### Files

| File                                 | Change                                                                                   |
| ------------------------------------ | ---------------------------------------------------------------------------------------- |
| `backend/engine/listing_age.py`      | NEW - age from `item_creation_date`; churn by diffing consecutive observations per query |
| `backend/api/observations.py`        | NEW - `GET /api/observations/{listing_id}`, `GET /api/observations/churn?query=`         |
| `frontend/components/ListingAge.tsx` | NEW - the age chip                                                                       |
| `frontend/app/churn/page.tsx`        | NEW - "observed before, not present now"                                                 |
| `tests/test_listing_age.py`          | NEW - churn never yields the word "sold"; single observation yields no churn claim       |

### Rules

- Fewer than two observations means no churn claim at all - suppress, do not zero-fill.
- The copy is "no longer listed" with the last-seen date. The word "sold" must not appear in this
  module, and a test should assert that.
- Age is computed from eBay's own creation date, not from our first sighting, and the two are
  labelled differently when both are shown.

---

## Phase H - Seller footprint

### Files

| File                                       | Change                                                                                  |
| ------------------------------------------ | --------------------------------------------------------------------------------------- |
| `backend/engine/sellers.py`                | NEW - aggregate observations by username                                                |
| `backend/api/sellers.py`                   | NEW - `GET /api/sellers/{username}`                                                     |
| `frontend/app/sellers/[username]/page.tsx` | NEW - footprint panel                                                                   |
| `tests/test_sellers.py`                    | NEW - aggregation, feedback formatting, and a test that no revenue or sold field exists |

### Rules

- Feedback and account type come from Browse, verbatim. Do not compute a "score".
- Account type is displayed raw (`BUSINESS` / `INDIVIDUAL`), because inferring it from other
  signals would be a guess.
- The panel carries the standing disclaimer that it describes active listings only.

---

## Phase I - Own-sales P&L and feedback

### Files

| File                              | Change                                                                                                                     |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `backend/api/sales.py`            | NEW - CRUD, summary, CSV import                                                                                            |
| `backend/db/queries.py`           | CHANGED - recompute `monthly_stats` on write                                                                               |
| `backend/engine/thresholds.py`    | NEW - replay stored verdicts and observations against the C14 thresholds to show what would have been filtered differently |
| `frontend/app/sales/page.tsx`     | NEW - entry and import                                                                                                     |
| `frontend/app/dashboard/page.tsx` | CHANGED - real revenue, profit, margin, monthly trend                                                                      |
| `tests/test_sales.py`             | NEW - arithmetic, import parsing, user-declared labelling                                                                  |

### Rules

- Sales are **user-declared**. Label them so. They are not observations and must not be presented
  as such.
- `monthly_stats` has `unique=True` on both `year` and `month` separately, which prevents storing
  the same month in two different years. Fix that to a composite unique constraint as part of this
  phase, with a migration, and note it in the commit.
- Threshold replay reports differences; it never auto-changes a threshold.

---

## Phase J - Marketplace expansion

### Files

| File                                                  | Change                                                                   |
| ----------------------------------------------------- | ------------------------------------------------------------------------ |
| `backend/config.py`                                   | marketplace registry: id, currency, fee-table reference                  |
| `backend/scrapers/ebay_deals.py` and the Browse sites | take the marketplace from a single source instead of the module constant |
| `backend/api/*`                                       | accept and validate a marketplace parameter on Browse-backed routes      |
| `frontend/components/Layout.tsx`                      | marketplace selector                                                     |
| `frontend/lib/types.ts`                               | currency on monetary fields                                              |
| `tests/test_markets.py`                               | NEW - no cross-currency arithmetic; fee table warning for non-UK markets |

### Rules

- Deals pages are marketplace-specific; a non-UK marketplace means a different deals URL, which
  must be verified reachable before that marketplace is offered.
- Fee tables are UK-specific until proven otherwise. Show the warning rather than applying a UK
  rate to a US sale.
- Never sum across currencies.

---

## Migration pattern to reuse

```python
# backend/db/database.py  -- called on import, must be idempotent
def ensure_observation_columns() -> list[str]:
    """ALTER any missing column onto an existing table. Returns what it added."""
    ...
```

```python
# backend/db/models.py  -- at the END of the module, after the model class exists
ensure_listing_observations_table()
```

`create_all` creates missing tables only; it never alters existing ones. Both helpers must be safe
to run repeatedly and must be covered by a test that calls them twice.
