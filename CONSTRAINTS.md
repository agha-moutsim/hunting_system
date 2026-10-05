# eBay Hunter — Product Constraints & Specifications

> Version 1.1 · September 2026
> Status: **Reviewed — amendments applied September 2026; C10–C14 added (condition gate, multi-store, supplier cap, provenance, matching)**

---

## 1. What we're building

We're turning the current Streamlit prototype into a proper web product. The goal is to have something you can put in your portfolio, hand to your brother and his friends, and show to potential clients — without anyone having to install Python or run a terminal command.

The stack is **FastAPI (Python) + Next.js (React)**. All the existing scraping, LLM, and business logic stays as-is. We're rebuilding the interface and adding an API layer around what already works.

**Budget: £0/month.** Everything has to run on free tiers.

---

## 2. Hard constraints

These are the rules that don't bend. If something in the build conflicts with these, the build changes — not the constraint.

| #     | Constraint                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Why                                                                                                                               |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| C1    | **Never fabricate data.** If we don't have a value, we show "Unverified" with a ⚠️ label. No guessing, no filling in blanks.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | This is a sourcing tool. A wrong number costs real money.                                                                         |
| C2    | **Only these 7 suppliers:** AliExpress, Amazon UK, CJ Dropshipping, GoDropship, Joybuy UK, B&Q, Toolstation. No others without a spec change.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | User-approved list. Keeps results consistent.                                                                                     |
| C3    | **Fee model (v1 static):** 13.5% final value fee + 0.03% listing fee + 20% UK VAT applied to eBay's fees + 3% returns buffer, subtracted from every profit calculation. Official eBay UK schedule (category-based FVF 6.9–14.9%, per-order fee £0.40 above £10 since 12 Feb 2026, ~0.35% regulatory operating fee) is documented in docs/p0-research.md; a fee-calculator API integration is planned and will replace these static numbers — the calculation stays behind one function (engine/profit.py).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Matches user's real eBay selling costs.                                                                                           |
| C4    | **Demand thresholds: ≥30 sold in 30 days AND ≥8 sold in 7 days = has demand.** 7-day figures come from eBay's Item Purchase History data (verified); when 7-day data is unavailable the verdict is PENDING (never assumed). The old delivery exception (≥30 sold → ≤25 days) is withdrawn — delivery is no longer a pass/fail rule (see C-new).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | User's buying rules.                                                                                                              |
| C5    | **Generic products only.** The LLM extracts the brand name from title/item specifics; a brand name that is registered in eBay's VeRO programme = FAIL (counterfeit-listing risk). 'Branded'/'Unbranded' tags with no specific brand name, and brand names NOT on VeRO, are acceptable (compatible/generic products). Brand evidence feeds the verdict engine as verified (registered), pass (not registered), or unverified (name ambiguous → PENDING). Condition = New, Buy It Now, UK only. **STATUS 2026-10-03: NOT IMPLEMENTED.** No VeRO catalogue is wired into the product path - `utils/vero.check_vero` exists but is not driven by a real brand list, so no product is actually being failed for being a registered brand. The dead `brand_filter: "vero"` config key was deleted rather than left claiming a check that never runs. Until it is built, a product whose brand is ambiguous reports Brand = Unverified, which holds the verdict at PENDING; it is never silently passed. | User only resells unbranded goods.                                                                                                |
| C-new | **Delivery is advisory, not a gate:** every result shows eBay's estimated delivery and the supplier's stated delivery side by side ('eBay says 3–8 days · Supplier says 12–20 days — confirm your eBay policy'). No verdict ever flips on delivery alone.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | Delivery informs the user's own eBay policy — it never decides a buy.                                                             |
| C6    | **Price range filter, default £5–£35.** The range is enforced as a gate at all four layers from CONSTRAINTS_PRICING.md with whatever value is active; the user may widen/narrow it (new sellers start low, experienced sellers go high). Supplier prices are NEVER gated — a cheap supplier is an advantage; margin decides buyability. Full specification in [`CONSTRAINTS_PRICING.md`](CONSTRAINTS_PRICING.md) — that file wins on any price question.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | User's buying range; out-of-range candidates never pass the gate — but stored rows stay visible, flagged, never silently deleted. |
| C7    | **Minimum margin: 25%.** Configurable per search (measured on the sale price: profit ÷ eBay price). Anything below is FAIL.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | User's floor for a viable product.                                                                                                |
| C8    | **No user accounts in v1.** The app is shared by link. Auth can come later if needed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | Faster to ship; trusted circle of users.                                                                                          |
| C9    | **All data persists in one database file** (SQLite for now). Easy to swap to PostgreSQL later via a single env var.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | Free hosting, zero ops.                                                                                                           |
| C10   | **Condition is New-only, enforced at query time.** Every eBay call sends `conditions:{NEW}` (Browse API) / `LH_ItemCondition=1000` (HTML), including the sold-listings demand search. A listing whose condition is not `New` is rejected **before** supplier search and LLM spend, not at verdict time. A missing/blank/unknown condition is **not** New — it fails. `FILTERS["condition"]` is the single source of truth and is validated against an allow-list (`New` only in v1); the verdict engine reads it instead of a hardcoded literal.                                                                                                                                                                                                                                                                                                                                                                                                                                                  | User only resells new goods. Used/Refurbished/Pre-owned never appear in results.                                                  |
| C11   | **Every analysis surfaces up to 4 eBay stores.** Analyze, URL-hunt, Deep Search, Bulk and Category Hunter all return a competitor-store list from **real** `seller.username` values — never fewer sources because one path was skipped, and never padded with invented names. Store `sold_count` is labelled for what it actually is: listings observed in the search window (cap 50), **not** eBay's sold count; true sold figures come only from the 7-day/30-day demand source. Store URLs are derived as `ebay.co.uk/str/{username}` and marked derived, not API-provided.                                                                                                                                                                                                                                                                                                                                                                                                                    | User wants competitor context on every product, not just Deep Search.                                                             |
| C12   | **Up to 7 suppliers; fewer is correct.** Only the C2 list. A supplier row appears only when its product was actually retrieved from that supplier's API or a successfully parsed page and passed the C14 match threshold. **Never invent, pad, or duplicate a row to approach 7.** If 2 suppliers are verifiable, show 2 and say so.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | Results must be genuine; a padded list is worse than a short one.                                                                 |
| C13   | **Four-tier provenance on every factual field.** `verified` (real API/page), `estimated` (transparent stated method), `unverified` (could not confirm — shown, never gates), `ai_insight` (LLM analysis). **`ai_insight` is structurally barred from factual fields** — it may never populate price, link, stock, sold count, store name or supplier name, and never influences PASS/FAIL. Every row carries `provenance` + `source_url` where one exists; exports include the provenance column. The LLM's role is analysis of facts it was handed, comparison, categorisation and insight — never fabrication.                                                                                                                                                                                                                                                                                                                                                                                  | A sourcing tool that invents numbers costs real money. Traceability beats volume.                                                 |
| C14   | **Deterministic product matching is mandatory.** An eBay item and a supplier item are the same product only when a defined, code-level matcher scores them at or above threshold (title tokens + brand + key attributes + price plausibility; image phash when both images exist). Below threshold = `unverified` / **"no confirmed match"** — shown as absent, not fudged. `match_score` is computed, never a constant; LLM confidence is display-only and never a substitute for the matcher.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Similar titles are not proof of identical products.                                                                               |

---

## 3. What stays exactly the same

The following already works and **must not be rewritten from scratch.** We wrap it, we don't rebuild it.

```
scrapers/          All 7 supplier scrapers + eBay sold-listings scraper
engine/            Filter logic, profit calculator, verdict rules
deep_search.py     deep_search_product() and deep_search_fast()
hunter/            Category scan, demand check, supplier lookup, report
tracker/           Price tracker, checker, alerts, history
watchlist/         Watchlist items, saved searches, search runner
dashboard/         Sales logging, KPIs, chart data
export/            CSV/JSON export with the fixed schema
db/models.py       Every SQLAlchemy model (products, sales, watchlist, ...)
utils/             Theme colors, filter persistence
config.py          FILTERS dict + all business constants
```

If a bug is found in any of these, fix it in place. Don't fork a "v2" version.

---

## 4. New files we're adding

### Backend (`backend/`)

| File                 | Responsibility                                                               |
| -------------------- | ---------------------------------------------------------------------------- |
| `main.py`            | FastAPI app, CORS, mounts all routers, `/api/health`                         |
| `requirements.txt`   | Pinned dependencies                                                          |
| `render.yaml`        | Render.com deploy config                                                     |
| `api/schemas.py`     | Pydantic request/response models                                             |
| `api/status.py`      | `GET /api/status` — DB, Ollama, eBay key health                              |
| `api/analyze.py`     | `POST /api/analyze` — full single-product pipeline                           |
| `api/deep_search.py` | `POST /api/deep-search` (with LLM) and `POST /api/deep-search/fast` (no LLM) |
| `api/bulk.py`        | `POST /api/bulk` — many queries at once, fast mode only                      |
| `api/hunter.py`      | `POST /api/hunter/scan`, `POST /api/hunter/lookup`                           |
| `api/tracker.py`     | CRUD for tracked products + `POST /check/{id}`                               |
| `api/watchlist.py`   | CRUD for watchlist items + saved searches + run search                       |
| `api/dashboard.py`   | KPIs, chart data, sales CRUD                                                 |
| `api/history.py`     | `GET /api/history` with verdict + text search filters                        |
| `api/export_api.py`  | CSV and JSON download endpoints                                              |

Existing directories (`scrapers/`, `engine/`, etc.) get **moved** into `backend/` using `git mv` so history is preserved. They are not duplicated.

### Frontend (`frontend/`)

| File / Folder                 | Responsibility                                                 |
| ----------------------------- | -------------------------------------------------------------- |
| `app/layout.tsx`              | Shell: sidebar nav, status indicators, mobile menu             |
| `app/page.tsx`                | Redirects to `/analyze`                                        |
| `app/analyze/page.tsx`        | Single product analysis + scorecard                            |
| `app/deep-search/page.tsx`    | Deep research with suppliers + sold data                       |
| `app/bulk/page.tsx`           | Batch analysis, CSV/JSON export                                |
| `app/hunter/page.tsx`         | Category scanner                                               |
| `app/tracker/page.tsx`        | Price tracker + alerts                                         |
| `app/watchlist/page.tsx`      | Watchlist + saved searches + new finds                         |
| `app/dashboard/page.tsx`      | Sales KPIs + charts + log sale                                 |
| `app/history/page.tsx`        | Past analyses, search, filter                                  |
| `components/Layout.tsx`       | Sidebar + topbar (shared)                                      |
| `components/KpiCard.tsx`      | Reusable metric card                                           |
| `components/DataTable.tsx`    | Sortable table                                                 |
| `components/Scorecard.tsx`    | The analysis result card (same format as Streamlit version)    |
| `components/SupplierCard.tsx` | One supplier row (store, rating, price, delivery)              |
| `components/charts/*`         | Line, Pie, Bar wrappers for Recharts                           |
| `components/ui/*`             | Button, Input, Badge, Card, Spinner, EmptyState, ConfirmDialog |
| `lib/api.ts`                  | One `apiFetch()` helper used by every page                     |
| `lib/types.ts`                | TypeScript interfaces matching every API response              |
| `lib/format.ts`               | `formatGBP()`, `formatPercent()`, `formatDate()`               |
| `tailwind.config.js`          | Dark theme tokens copied from `utils/theme.py`                 |
| `.env.local`                  | `NEXT_PUBLIC_API_URL`                                          |

---

## 5. API surface (what the frontend is allowed to call)

Only these endpoints. If a page needs data not listed here, we add the endpoint — we don't let the frontend reach into the database directly.

```
GET    /api/status
GET    /api/health

POST   /api/analyze
POST   /api/deep-search
POST   /api/deep-search/fast
POST   /api/bulk

POST   /api/hunter/scan
POST   /api/hunter/lookup

GET    /api/tracker?price_min=&price_max=
POST   /api/tracker
DELETE /api/tracker/{id}
POST   /api/tracker/{id}/check

GET    /api/watchlist?price_min=&price_max=
POST   /api/watchlist
DELETE /api/watchlist/{id}

GET    /api/searches
POST   /api/searches
DELETE /api/searches/{id}
POST   /api/searches/{id}/run
GET    /api/searches/results          # new finds (unread)

GET    /api/dashboard/kpis?days=30
GET    /api/dashboard/charts/revenue-trend?days=30
GET    /api/dashboard/charts/profit-trend?days=30
GET    /api/dashboard/charts/categories
GET    /api/dashboard/charts/monthly
GET    /api/dashboard/top-products
GET    /api/dashboard/top-categories

GET    /api/sales
POST   /api/sales
DELETE /api/sales/{id}

GET    /api/history?verdict=&q=&limit=50&price_min=&price_max=
GET    /api/history/{product_id}

GET    /api/filters
PUT    /api/filters                        # active price range + condition (validated, 422 on bad range or non-"New" condition)
POST   /api/extension/sold-history         # browser extension: purchase-history capture (7-day data)
GET    /api/extension/sold-history/{item_id}  # latest capture for one item (404 when none)

GET    /api/export/csv?type=sales|analysis
GET    /api/export/json?type=sales|analysis
```

**Response shape rule:** every endpoint returns either the data directly or `{ "error": "..." }` with an appropriate HTTP status. No empty 200s.

---

## 6. UI / UX constraints

- **Dark theme only** for v1. Colors: primary `#0D1CC4`, hover `#0B17A8`, success/profit `#CBFD03`, success-soft `#BEC97D`, app bg `#27233F`, white `#FFFFFF`, gray `#4B525E`. Danger `#FF5C5C`, warning/Unverified `#FFC857`. Fonts: Plus Jakarta Sans (UI) + JetBrains Mono (numbers). See `design.md` for full token set. (Amended by UI redesign — supersedes old `#0B1120` / `#3B82F6` palette.)
- **Responsive from day one.** Must work at 360px wide (phone) and 1920px (desktop). Breakpoints: 640px, 1024px.
- **Every result that can be exported has Export CSV and Export JSON buttons.**
- **Destructive actions** (delete tracker item, delete watchlist item, delete sale) require a confirmation step. No one-click deletes.
- **Empty states get a real message**, not a blank area. Example: "No sales logged yet — use the form above to log your first sale."
- **Loading states everywhere.** Skeleton placeholders while fetching; never a frozen screen.
- **Keyboard shortcuts preserved:** Ctrl+1 through Ctrl+8 jump to the eight pages. Show a small hint under the header.
- **The scorecard format from the Streamlit version is the reference.** Same sections, same order, same ⚠️ Unverified labels. Clients reviewing the old version must recognize the new one.

### Non-goals for v1 (explicitly out of scope)

- User login / accounts / multi-tenant
- Payments or subscription tiers
- Mobile native apps (responsive web only)
- Real-time websockets (polling / button-triggered refresh is fine)
- Rewriting scrapers in TypeScript
- Test-coverage thresholds or a CI quality gate (a regression suite exists
  and must stay green; enforcing coverage % or flakiness budgets is out of scope for v1)

---

## 7. Deployment constraints

| Piece    | Service                                                                                                                                                                                                        | Free-tier notes                                                                                                           |
| -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Frontend | **Vercel**                                                                                                                                                                                                     | Unlimited static/serverless. Auto-deploys from `main`.                                                                    |
| Backend  | **Render.com**                                                                                                                                                                                                 | Free web service. Sleeps after ~15 min idle; first request wakes it (~30s). Build must run `playwright install chromium`. |
| Database | **SQLite** file in the repo / Render disk. Swap to Supabase Postgres later by changing `DATABASE_URL` only.                                                                                                    |
| Source   | **GitHub** `agha-moutsim/hunting_system`                                                                                                                                                                       | Public for portfolio.                                                                                                     |
| LLM      | **Ollama** is local during development. In production we use the existing **rule-based fallback** (already in `deep_search.py`) unless a free hosted Ollama is configured. Must never crash if Ollama is down. |

CORS: backend must allow exactly `https://ebay-hunter.vercel.app` and `http://localhost:3000`.

The legacy `app.py` (Streamlit) stays in the repo untouched until the new stack passes a full smoke test. Then it moves to `legacy/` — not deleted on day one.

---

## 8. Quality bar — "done" means

- [ ] Every endpoint in section 5 returns correct JSON from real (or empty) data
- [ ] Every page in section 4 loads, submits, and renders results
- [ ] Profit numbers on screen match the Streamlit version for the same query
- [ ] App usable on a phone (360px) without horizontal page scroll (tables may scroll inside their container)
- [ ] Export CSV downloads a valid file that opens in Excel
- [ ] Ollama offline → deep search still returns results with ⚠️ Unverified labels, no crash
- [ ] No console errors in the browser
- [ ] `git status` clean after each phase; pushed to `main` after each task
- [ ] README written with live demo link, features, tech stack, screenshots

---

## 9. Risks we've already thought about

| Risk                          | What we do                                                                                                         |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Render free tier sleeps       | Show a "waking up…" state on first API call; consider Fly.io if too annoying                                       |
| Playwright heavy on free tier | CJ / GoDropship / Joybuy may be slow or blocked on Render; AliExpress + Amazon + B&Q + Toolstation must still work |
| Ollama unavailable in prod    | Rule-based fallback is mandatory, already coded                                                                    |
| SQLite file lost on redeploy  | For v1, acceptable (demo data). Before real users: switch `DATABASE_URL` to Supabase                               |
| Scraper breaks (anti-bot)     | Same as today — surface the error, mark results Unverified, never fake a price                                     |

---

## 10. Sign-off

This document is the contract for Phases A–D. Anything not written here is either a bug fix or a v2 feature.

- [ ] Constraints approved
- [ ] File structure approved
- [ ] API surface approved
- [ ] UI rules approved
- [ ] Ready to start **Phase A (FastAPI backend)**

**Approved by:** _________________ **Date:** _________
