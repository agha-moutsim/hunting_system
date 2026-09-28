# eBay Hunter — Product Constraints & Specifications

> Version 1.0 · September 2026
> Status: **Awaiting review before build starts**

---

## 1. What we're building

We're turning the current Streamlit prototype into a proper web product. The goal is to have something you can put in your portfolio, hand to your brother and his friends, and show to potential clients — without anyone having to install Python or run a terminal command.

The stack is **FastAPI (Python) + Next.js (React)**. All the existing scraping, LLM, and business logic stays as-is. We're rebuilding the interface and adding an API layer around what already works.

**Budget: £0/month.** Everything has to run on free tiers.

---

## 2. Hard constraints

These are the rules that don't bend. If something in the build conflicts with these, the build changes — not the constraint.

| # | Constraint | Why |
|---|-----------|-----|
| C1 | **Never fabricate data.** If we don't have a value, we show "Unverified" with a ⚠️ label. No guessing, no filling in blanks. | This is a sourcing tool. A wrong number costs real money. |
| C2 | **Only these 7 suppliers:** AliExpress, Amazon UK, CJ Dropshipping, GoDropship, Joybuy UK, B&Q, Toolstation. No others without a spec change. | User-approved list. Keeps results consistent. |
| C3 | **eBay fee model is fixed:** 12.8% final value fee + 3% returns buffer, subtracted from every profit calculation. | Matches user's real eBay selling costs. |
| C4 | **Demand thresholds:** ≥10 sold in 30 days AND ≥1 sold in 7 days = "has demand". Exception: ≥30 sold in 30 days allows delivery up to 25 days instead of the usual 3–8. | User's buying rules. |
| C5 | **Generic products only.** The LLM must flag branded items as FAIL. Condition = New, Buy It Now, UK only. | User only resells unbranded goods. |
| C6 | **Price range:** hard band £5–£35, enforced as a gate (not just a verdict). Full specification in [`CONSTRAINTS_PRICING.md`](CONSTRAINTS_PRICING.md) — that file wins on any price question. | User's buying range; expensive results must never appear. |
| C7 | **Minimum margin: 25%.** Configurable per search. Anything below is FAIL. | User's floor for a viable product. |
| C8 | **No user accounts in v1.** The app is shared by link. Auth can come later if needed. | Faster to ship; trusted circle of users. |
| C9 | **All data persists in one database file** (SQLite for now). Easy to swap to PostgreSQL later via a single env var. | Free hosting, zero ops. |

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

| File | Responsibility |
|------|----------------|
| `main.py` | FastAPI app, CORS, mounts all routers, `/api/health` |
| `requirements.txt` | Pinned dependencies |
| `render.yaml` | Render.com deploy config |
| `api/schemas.py` | Pydantic request/response models |
| `api/status.py` | `GET /api/status` — DB, Ollama, eBay key health |
| `api/analyze.py` | `POST /api/analyze` — full single-product pipeline |
| `api/deep_search.py` | `POST /api/deep-search` (with LLM) and `POST /api/deep-search/fast` (no LLM) |
| `api/bulk.py` | `POST /api/bulk` — many queries at once, fast mode only |
| `api/hunter.py` | `POST /api/hunter/scan`, `POST /api/hunter/lookup` |
| `api/tracker.py` | CRUD for tracked products + `POST /check/{id}` |
| `api/watchlist.py` | CRUD for watchlist items + saved searches + run search |
| `api/dashboard.py` | KPIs, chart data, sales CRUD |
| `api/history.py` | `GET /api/history` with verdict + text search filters |
| `api/export_api.py` | CSV and JSON download endpoints |

Existing directories (`scrapers/`, `engine/`, etc.) get **moved** into `backend/` using `git mv` so history is preserved. They are not duplicated.

### Frontend (`frontend/`)

| File / Folder | Responsibility |
|---------------|----------------|
| `app/layout.tsx` | Shell: sidebar nav, status indicators, mobile menu |
| `app/page.tsx` | Redirects to `/analyze` |
| `app/analyze/page.tsx` | Single product analysis + scorecard |
| `app/deep-search/page.tsx` | Deep research with suppliers + sold data |
| `app/bulk/page.tsx` | Batch analysis, CSV/JSON export |
| `app/hunter/page.tsx` | Category scanner |
| `app/tracker/page.tsx` | Price tracker + alerts |
| `app/watchlist/page.tsx` | Watchlist + saved searches + new finds |
| `app/dashboard/page.tsx` | Sales KPIs + charts + log sale |
| `app/history/page.tsx` | Past analyses, search, filter |
| `components/Layout.tsx` | Sidebar + topbar (shared) |
| `components/KpiCard.tsx` | Reusable metric card |
| `components/DataTable.tsx` | Sortable table |
| `components/Scorecard.tsx` | The analysis result card (same format as Streamlit version) |
| `components/SupplierCard.tsx` | One supplier row (store, rating, price, delivery) |
| `components/charts/*` | Line, Pie, Bar wrappers for Recharts |
| `components/ui/*` | Button, Input, Badge, Card, Spinner, EmptyState, ConfirmDialog |
| `lib/api.ts` | One `apiFetch()` helper used by every page |
| `lib/types.ts` | TypeScript interfaces matching every API response |
| `lib/format.ts` | `formatGBP()`, `formatPercent()`, `formatDate()` |
| `tailwind.config.js` | Dark theme tokens copied from `utils/theme.py` |
| `.env.local` | `NEXT_PUBLIC_API_URL` |

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

GET    /api/tracker
POST   /api/tracker
DELETE /api/tracker/{id}
POST   /api/tracker/{id}/check

GET    /api/watchlist
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

GET    /api/history?verdict=&q=&limit=50
GET    /api/history/{product_id}

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
- Automated testing suite (manual smoke test per endpoint is enough for v1)

---

## 7. Deployment constraints

| Piece | Service | Free-tier notes |
|-------|---------|-----------------|
| Frontend | **Vercel** | Unlimited static/serverless. Auto-deploys from `main`. |
| Backend | **Render.com** | Free web service. Sleeps after ~15 min idle; first request wakes it (~30s). Build must run `playwright install chromium`. |
| Database | **SQLite** file in the repo / Render disk. Swap to Supabase Postgres later by changing `DATABASE_URL` only. |
| Source | **GitHub** `agha-moutsim/hunting_system` | Public for portfolio. |
| LLM | **Ollama** is local during development. In production we use the existing **rule-based fallback** (already in `deep_search.py`) unless a free hosted Ollama is configured. Must never crash if Ollama is down. |

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

| Risk | What we do |
|------|-----------|
| Render free tier sleeps | Show a "waking up…" state on first API call; consider Fly.io if too annoying |
| Playwright heavy on free tier | CJ / GoDropship / Joybuy may be slow or blocked on Render; AliExpress + Amazon + B&Q + Toolstation must still work |
| Ollama unavailable in prod | Rule-based fallback is mandatory, already coded |
| SQLite file lost on redeploy | For v1, acceptable (demo data). Before real users: switch `DATABASE_URL` to Supabase |
| Scraper breaks (anti-bot) | Same as today — surface the error, mark results Unverified, never fake a price |

---

## 10. Sign-off

This document is the contract for Phases A–D. Anything not written here is either a bug fix or a v2 feature.

- [ ] Constraints approved
- [ ] File structure approved
- [ ] API surface approved
- [ ] UI rules approved
- [ ] Ready to start **Phase A (FastAPI backend)**

**Approved by:** _________________  **Date:** _________
