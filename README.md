# eBay Hunter

Product sourcing intelligence for eBay UK resellers. Enter an eBay listing or a search term, and the system checks sold history, prices the same product at 7 approved suppliers, runs your business rules against it, and returns a pass/fail scorecard with the maths shown.

The target workflow: a decision that takes 20 minutes of tab-hopping, done in about 90 seconds.

Everything is local-first and costs nothing to run — SQLite on disk, a local LLM through Ollama, free-tier hosting. There is no paid API tier anywhere in the stack.

## Tech stack

| Layer | Choice | Why this one |
|---|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript 5.7 | Static pages, fast builds, one deploy target on Vercel's free tier |
| Styling | Tailwind CSS 3.4 | Design tokens live in `tailwind.config.js`, one place to change theme |
| Charts | Recharts | Declarative React charts, fits the component model |
| Backend | FastAPI + Uvicorn | Async by default (the pipeline is I/O-bound), Pydantic validation, `/docs` generated for free |
| HTTP | httpx / requests | httpx for async scraper calls, requests for simple sync paths |
| Scraping | Playwright + playwright-stealth, BeautifulSoup | The supplier sites are JavaScript-rendered — plain HTTP requests get nothing back |
| LLM | Ollama (`llama3.1:8b`) | Runs on the machine, no per-call cost, no data leaves the laptop |
| Database | SQLite via SQLAlchemy 2 | A single file, zero setup, no server to keep alive; `DATABASE_URL` switches to Postgres later without code changes |
| Validation | Pydantic 2 | Same schema shapes shared across API request/response models |
| Export | pandas + openpyxl | CSV and real `.xlsx` files |
| Deploy | Vercel (frontend) + Render (backend) | Both have free tiers; `backend/render.yaml` defines the service |

Legacy note: `app.py` at the repo root is the original Streamlit UI. It imports the same backend modules, so it still works, but the Next.js app is the real interface.

## Architecture

Three processes talk to each other: the Next.js app on port 3000, the FastAPI app on port 8000, and Ollama on port 11434. SQLite sits behind the API as the persistence layer.

```
Browser
  │
  ▼
Next.js (Vercel / localhost:3000)
  │  fetch /api/*  — every call has a client-side timeout
  ▼
FastAPI (Render / localhost:8000)
  │
  ├──► eBay Browse API + sold-listings scraper   (price, demand)
  ├──► 7 supplier sources                        (API first, Playwright fallback)
  ├──► Ollama llama3.1:8b                        (brand / demand judgement)
  └──► decision engine                           (filters, profit, verdict)
  │
  ▼
SQLite — 13 tables
```

### What happens on `/api/analyze`

1. The eBay product is fetched through the Browse API (listings, price, condition, seller).
2. Sold listings are scraped to get real demand: how many sold in 30 days and 7 days, and the actual price range. No estimates — if it can't be measured, the field says Unverified.
3. All 7 suppliers are searched for the same product. Each scraper prefers a real API (eBay, Amazon PA, CJ) and only falls back to Playwright when there isn't one. At most 2 browsers run at once — this used to be 7, which crashed the process.
4. The LLM looks at title, price, and suppliers and judges two things: is this a generic (unbranded) product, and is demand real. It has 45 seconds. If Ollama is slow or offline, the step is skipped and those fields are marked Unverified — the request never hangs on it.
5. The decision engine applies the business rules below and computes profit after eBay's fees.
6. Result is written to SQLite and returned as a scorecard.

### Time budgets

Nothing in this pipeline is allowed to run forever. Every step has a limit, and hitting a limit degrades the answer instead of blocking it:

| Bound | Value |
|---|---|
| Whole pipeline | 150s hard cap |
| Each supplier scraper | 45s |
| Supplier step total | 90s (returns partial results) |
| LLM step | 45s (falls back to Unverified) |
| Concurrent browsers | 2 |
| Frontend timeout | 180s for analyze, 90s fast, 240s deep search |

The same applies to Deep Search: the full variant is capped at 120s and the fast variant at 75s, and both return a partial result with a note if they run out of time.

## Business rules

Configured in `backend/config.py`, enforced by `backend/engine/`.

| Rule | Threshold |
|---|---|
| Buy price | £5 – £25 |
| Minimum margin | ≥ 25% |
| Demand | ≥ 10 sold in 30 days, ≥ 1 sold in 7 days |
| Delivery | ≤ 8 days (≤ 25 days when the product sells ≥ 30/month) |
| Brand | Generic only — branded items fail |
| Listing | New, Buy It Now, UK only |
| eBay fees | 12.8% final value + 3% returns buffer |

```
profit = sale_price − supplier_price − (sale_price × 0.158)
margin = profit / sale_price × 100
```

Approved suppliers, and only these: AliExpress, Amazon UK, CJ Dropshipping, GoDropship, Joybuy UK, B&Q, Toolstation.

## Getting started

Prerequisites: Python 3.11+, Node 20+, and optionally [Ollama](https://ollama.com) with `llama3.1:8b` pulled.

```bash
git clone https://github.com/agha-moutsim/hunting_system.git
cd ebay-hunter

# backend
cd backend
python -m venv venv
venv\Scripts\activate            # Windows; source venv/bin/activate on macOS/Linux
pip install -r requirements.txt
playwright install chromium
python -m uvicorn main:app --port 8000

# frontend — new terminal
cd frontend
npm install
npm run dev                      # http://localhost:3000
```

### API keys

eBay keys are required (the app can't list products without them):

1. Create an app at https://developer.ebay.com
2. Put the credentials in `backend/.env`:

```
EBAY_CLIENT_ID=your_client_id
EBAY_CLIENT_SECRET=your_client_secret
```

Optional keys unlock faster, more reliable paths for individual suppliers:

| Key | Unlocks |
|---|---|
| `SERPAPI_KEY` | B&Q and Toolstation via Google Shopping |
| `AMAZON_PA_*` | Amazon Product Advertising API |
| `CJ_API_KEY` | CJ Dropshipping API |
| `RAPIDAPI_KEY` | AliExpress API |

Without them those suppliers fall back to browser scraping, which is slower and sometimes rate-limited.

## API

Base URL `http://localhost:8000`. Interactive documentation at `/docs`.

```
GET    /api/status                    service health (DB, Ollama, eBay key)
POST   /api/analyze                   full single-product pipeline
POST   /api/deep-search               deep research with LLM (≤ 2 min)
POST   /api/deep-search/fast          deep research without LLM (~20s)
POST   /api/bulk                      batch queries
POST   /api/hunter/scan               category scan
POST   /api/hunter/lookup             supplier lookup for scan results
GET    /api/tracker                   tracked products, price alerts
POST   /api/tracker                   start tracking / check now
DELETE /api/tracker/{id}              stop tracking
GET    /api/watchlist                 watchlist, saved searches
POST   /api/watchlist                 add item
GET    /api/dashboard/kpis            dashboard numbers
GET    /api/dashboard/charts/*        revenue, profit, category, monthly
GET/POST/DELETE /api/sales            sales log
GET    /api/history                   past analyses
GET    /api/export/csv|json           exports
```

## Project layout

```
ebay-hunter/
├── CONSTRAINTS.md          product spec: rules, API surface, quality bar
├── design.md               UI redesign spec: palette, type, structure, plan
├── app.py                  legacy Streamlit UI (shares backend modules)
├── backend/
│   ├── main.py             FastAPI entry, CORS, router mounting
│   ├── api/                10 routers, 40 endpoints
│   ├── analysis_pipeline.py  the shared pipeline (eBay → suppliers → LLM → verdict)
│   ├── scrapers/           eBay + sold-listings + 7 suppliers + API clients
│   ├── engine/             filters, profit calculator, scorecard
│   ├── llm/                Ollama client, prompts, fallback verdicts
│   ├── db/                 SQLAlchemy models, 13 tables, queries
│   ├── hunter/ tracker/ watchlist/ dashboard/ export/
│   └── render.yaml         Render deploy config
├── frontend/
│   ├── app/                8 pages: analyze, deep-search, bulk, hunter,
│   │                       tracker, watchlist, dashboard, history
│   ├── components/         Layout, Scorecard, DataTable, charts, ui/, icons/
│   ├── lib/                api.ts (timeouts), types, formatting
│   └── tailwind.config.js  theme tokens
├── icons/                  Noun Project source SVGs
└── tests/
```

## Design

Dark theme only for v1. Indigo `#0D1CC4` and lime `#CBFD03` on deep indigo `#27233F`. Plus Jakarta Sans for interface text, JetBrains Mono for every number — prices and percentages need tabular figures so columns line up. Full spec in [`design.md`](design.md).

## Known limitations

- GoDropship and Joybuy have no API, so they run through Playwright and get blocked by anti-bot protection sometimes. Results from them are marked Unverified rather than guessed.
- Amazon, AliExpress, and CJ are rate-limited without their API keys.
- Ollama does not exist on Render, so the production build runs on the rule-based fallback for LLM steps. This is by design.
- Render's free tier sleeps after ~15 minutes idle; first request after that takes ~30 seconds.
- No authentication in v1.

## Icons

Navigation icons from [Noun Project](https://nounproject.com), used under the Noun Project license:

- Analyze — Keyy Creative
- Deep Dive & Categories — Trimanggolo Mulyo
- Bulk — Awicon
- Pricing — Hermanto
- Wishlist — VectorVibe Designs
- Dashboard — Lulis Dian RP
- History — Mia Elysia

## License

Private — eBay Hunter
