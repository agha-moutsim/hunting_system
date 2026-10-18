# Context

State of the system at the start of this feature work, limited to what the new features touch.
All figures measured on 2026-10-19 unless stated.

## Stack

| Layer        | Technology                                                                             |
| ------------ | -------------------------------------------------------------------------------------- |
| Backend      | FastAPI on Python 3.14, SQLAlchemy, SQLite                                             |
| Database     | `backend/data/ebay_hunter.db`                                                          |
| Frontend     | Next.js 16.3.6 (Turbopack), React, TypeScript, production build via `next start`       |
| Extension    | Chrome MV3, plain JS, no build step, in `extension/`                                   |
| Analysis LLM | Ollama `llama3.1:8b`, local, used for narrative analysis only - never a source of fact |

## How it runs

```
backend    python -m uvicorn main:app --port 8000     (from backend/)
frontend   npm --prefix frontend run start            (serves the production build)
scripts    start.ps1 / stop.ps1 / check.ps1           logs in .logs/
```

Important: `start.ps1` runs **`next start`**, which serves the build output, not the source. A
frontend change is not visible until `npm --prefix frontend run build` runs again.

## API routers already mounted

```
status  analyze  deep_search  bulk  hunter  tracker  watchlist
dashboard  history  demand_monitor  filters  export_api  extension  deals
```

The extension already has its endpoints, mounted under `/api`:

```
POST /api/extension/sold-history            body {item_id, url, html}
GET  /api/extension/sold-history/{item_id}
```

## Data actually present

```
analyses              24 rows
deal_items            73 rows
demand_data           39 rows
demand_snapshots      58 rows
monthly_stats          0 rows   <- dormant
price_alerts           0 rows   <- dormant
price_history          2 rows
products              40 rows
purchase_captures      1 row    <- the asset, nearly empty
sales                  0 rows   <- dormant
saved_searches         0 rows   <- dormant
search_results         0 rows   <- dormant
supplier_matches     155 rows
tracked_products       2 rows
verdicts              38 rows
watchlist_items        2 rows
```

Five tables have schema, have (in three cases) a UI page, and receive nothing. Two of the ten
features exist to feed them.

## The extension as it stands

`extension/` contains `manifest.json`, `background.js`, `popup.js`, `popup.html`, `README.md`.
`manifest_version: 3`, `host_permissions: ["https://www.ebay.co.uk/*"]`, permissions
`["storage", "activeTab"]`. No content script. No `webNavigation`. No badge.

Flow today: user clicks the toolbar icon, clicks "Capture sold history", `background.js` resolves
the item id from the active tab, fetches the login-gated purchase-history page with
`credentials: "include"`, POSTs the raw HTML, and the popup renders the returned counts.

It works. It requires three deliberate actions per item.

## Browse API: what is received but not kept

Verified by calling `GET /buy/browse/v1/item_summary/search` on 2026-10-19 with marketplace
`EBAY_GB`. Every listing carries:

```
itemCreationDate      2026-03-25T08:12:22.000Z     <- listing age
itemOriginDate        2025-08-16T06:23:52.000Z
seller                {username, feedbackPercentage, feedbackScore, sellerAccountType}
itemLocation          {postalCode: "WR4***", country: "GB"}
condition / conditionId
categories / leafCategoryIds
shippingOptions       postage cost and speed
buyingOptions
topRatedBuyingExperience / priorityListing
itemGroupType         SELLER_DEFINED_VARIATIONS
itemId                v1|157783405092|459206478552
legacyItemId          157783405092
```

`Product` stores only `condition`, `seller`, `category`. `DealItem` stores `seller`, `store_name`,
`store_url`, `condition`. Everything else - age, feedback, account type, region, postage - is
discarded on every call already being made. That is the cheapest available win in this plan.

Note `sellerAccountType` distinguishes business from individual sellers. Nothing else in the
system does.

## The 39 history rows problem

Every one of the 39 `demand_data` rows holds live-listing evidence under sold-labelled columns.

Measured: **0 rows** have a non-null `sold_count_7d` or a `last_sale_date`. Both can only be
produced by reading real sale dates, which only a purchase-history capture does. No row carries
`+purchase_history` in `data_source`. All 39 have `sold_count_30d <= 50` (the Browse page limit),
12 of them exactly 50 with 48-50 attached prices.

The write path was fixed on 2026-10-19 (commit `e3fccad`); the stored rows were not rewritten.
This is why Phase C (verified-first and Sources) matters: it is the presentation-level fix for a
data-history problem, and it gives the user a way to see which rows are which.

## Provenance machinery that already exists

- `Provenance` enum with `VERIFIED`, `ESTIMATED`, `UNVERIFIED` and UI tones
  pass / fail / pending / info / neutral / warn / verified / estimated / unverified.
- `frontend/lib/fieldProvenance.ts` with `HEADER_FIELDS` mapping.
- `supplier_matches` persists `provenance`, `provenance_label`, `fetch_method`.
- `demand_data.data_source` is a human-readable sentence stating what produced the row.

The vocabulary is complete. Phase C is about _using_ it as the primary signal rather than a badge.

## Conventions the new work must follow

- Tables self-heal: `ensure_*` helpers in `backend/db/database.py` ALTER columns on import;
  `ensure_deal_items_table()` runs at the end of `db/models.py` because it needs the model class.
  `create_all` only creates missing tables - it never alters existing ones.
- Naive UTC datetimes throughout the backend, matching `db/models.py`. Mixing aware and naive
  raises on subtraction. Timezone conversion happens on the client.
- Price and sold never share a column. `NULL` means "not read", never zero - the deals board
  renders "See price on eBay" for an unread price, and a test pins `price_label(0.0, "GBP")`
  to "GBP 0.00".
- `deal_items` is upsert-by-listing-id so primary keys survive a refresh and the client does not
  remount cards.
- Banned-column tests exist: `TestTheTableCannotHoldAPopularityClaim` asserts no popularity column
  can be added to `deal_items`. Any new popularity-shaped column needs the same treatment.
- Frontend: `Card(title, action, className)`, `Badge(tone)`, `Button`, `Spinner`, `EmptyState`,
  `Metric(label, prov, value, emphasis?)`. Plain `<img>`. `apiFetch<T>` from `@/lib/api`.

## Baselines to preserve

```
backend    python -m pytest tests/ -q     ->  1203 passed, 9 deselected
frontend   npx vitest run                 ->  54 passed (4 files)
types      npx tsc --noEmit               ->  exit 0
build      npm --prefix frontend run build -> 11 routes prerendered
```

The 9 deselected are `test_phase3.py` (2) and `test_live_smoke.py` (7); the live lane is
`pytest -m live`. `test_ebay_details` fails by environment design.

## External blockers

- **SerpApi quota: 0 of 250 left**, plan Free, resets **2026-11-08**. Supplier discovery (B&Q,
  Toolstation) returns nothing until then, and the Analyze pipeline cannot be driven end to end.
  This delays live verification of any new Analyze-adjacent feature.
- **Marketplace Insights API: HTTP 403**, scope `buy.marketplace.insights` not granted. The only
  official route to real sold data, closed to new users.
- **eBay sold and search pages: HTTP 403** directly, HTTP 500 via ScrapingBee. Only `/deals` and
  the six `/deals/featured/<slug>` pages are reachable.
- **`mock_data.get_mock_demand()` exists but nothing imports it**, so there is no mock route to
  render Analyze-dependent UI while SerpApi is down.

## Repository facts

- Commit author must be `Agha Moutsim <131957706+agha-moutsim@users.noreply.github.com>` so the
  contribution graph renders.
- **No usable git hooks**: `core.hooksPath` points at `.husky/_` which contains no hook scripts.
  Nothing validates a commit automatically - run the suite by hand before every push.
- Push requires the inline credential-helper override; the keyring token lacks repo access.
- `frontend/AGENTS.md` and `frontend/CLAUDE.md` are gitignored, regenerated by `next dev`.
- Editing gotchas: `edit` fails on files containing mojibake (patch those with Python);
  `grep` is not on PATH (use `Select-String`); a dirty `backend/data/custom_filters.json` fails
  about 10 price-band tests (`git checkout -- backend/data/custom_filters.json` first).
- Stale-process gotcha: old `node`/`python` processes hold :3000/:8000. Find them with
  `Get-NetTCPConnection -LocalPort 3000,8000 -State Listen`, kill matching `*ebay-hunter*`, then
  `Remove-Item frontend\.next\dev -Recurse -Force` before restarting.
