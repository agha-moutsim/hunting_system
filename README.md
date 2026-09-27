# eBay Hunter

Sourcing intelligence for eBay UK resellers. The system takes an eBay listing or search query and returns a sourcing decision: real sold-listing demand, matched prices from seven approved suppliers, profit after eBay fees, and a pass/fail verdict against configurable business rules.

The design priorities are data integrity and bounded execution. The system never estimates a value it could not measure — unavailable fields are reported as Unverified — and every stage of processing runs under an explicit time budget, degrading to partial results instead of blocking.

## Features

**Analysis**
- Single-product analysis: eBay listing → demand → supplier comparison → AI verdict → profit scorecard
- Deep search research mode, with a fast variant that skips the LLM (~20s) and a full variant with LLM analysis (≤ 2 min)
- Bulk analysis of multiple queries with CSV/JSON export

**Discovery**
- Category Hunter: scan a category against active filters, then resolve supplier matches
- Watchlist with saved searches; saved searches can be re-run individually or in bulk

**Monitoring**
- Price tracker with price-history tables and configurable drop alerts
- Dashboard: sales KPIs, revenue and profit trends, category breakdowns, manual sales log

**Reporting**
- Complete analysis history with filtering by verdict
- CSV and XLSX/JSON export for sales, analyses, and bulk results

## Architecture

### Overview

The system runs as three local services plus a file database:

```
┌────────────┐   HTTPS/JSON    ┌───────────────┐    async calls    ┌────────────┐
│  Next.js   │ ──────────────► │    FastAPI    │ ────────────────► │   Ollama   │
│  frontend  │  /api/*         │   backend     │                   │ llama3.1:8b│
│  :3000     │ ◄────────────── │    :8000      │                   │  :11434    │
└────────────┘   scorecard     └──────┬────────┘                   └────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
             ┌────────────┐   ┌──────────────┐   ┌────────────┐
             │ eBay API   │   │  Supplier    │   │  SQLite    │
             │ (listings, │   │  clients     │   │  13 tables │
             │  sold data)│   │  (7 sources) │   │            │
             └────────────┘   └──────────────┘   └────────────┘
```

- **Frontend** — Next.js 16 (App Router) served by Vercel or `next start`. All data access goes through the REST API; there is no direct database access from the browser.
- **Backend** — FastAPI with 10 routers and 40 endpoints. All business logic (pipeline, engine, scrapers, LLM) lives here and is shared with the legacy Streamlit client through common imports.
- **LLM** — Ollama running locally. The LLM is used only for brand and demand judgement; every LLM-dependent field has a non-LLM fallback.
- **Database** — SQLite file at `backend/data/ebay_hunter.db`, accessed through SQLAlchemy 2. `DATABASE_URL` switches the same models to PostgreSQL without code changes.

### Processing pipeline

`backend/analysis_pipeline.py` is the single source of truth for analysis, used by both the API and the Streamlit client. One call executes:

1. **eBay product retrieval** — Browse API for listing data (price, condition, seller, format).
2. **Demand measurement** — sold-listings scrape producing actual 30-day and 7-day sold counts and the observed price range. Values are written only when observed; otherwise the demand fields are marked Unverified.
3. **Supplier search** — all seven suppliers queried for the same product. Each supplier prefers a direct API where one exists (eBay, Amazon PA, CJ, RapidAPI) and falls back to Playwright otherwise. Two browsers run concurrently; each scraper is capped at 45s and the stage at 90s.
4. **LLM analysis** — brand verdict and demand assessment, capped at 45s. On timeout or Ollama failure the step is skipped and affected fields are marked Unverified.
5. **Decision engine** — five business-rule filters plus profit calculation (12.8% final value fee and 3% returns buffer).
6. **Scorecard and persistence** — formatted verdict, saved to SQLite, returned to the client.

### Execution limits

| Bound | Value | Behaviour on expiry |
|---|---|---|
| Full pipeline | 150s | Structured error response |
| Supplier stage | 90s | Partial supplier results |
| Individual scraper | 45s | That supplier skipped, marked Unverified |
| LLM step | 45s | Rule-based fallback, Unverified fields |
| Concurrent browsers | 2 | Queue |
| Deep search (full) | 120s | Partial result with timeout note |
| Deep search (fast) | 75s | Partial result with timeout note |
| Client-side timeout | 90–240s depending on endpoint | Cancelled request with explicit message |

Client-side timeouts are defined in `frontend/lib/api.ts` and match the server-side budgets plus network margin.

## Technology stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend | Next.js 16.3, React 19, TypeScript 5.7 | App Router; 8 routes, statically prerendered |
| Styling | Tailwind CSS 3.4 | Design tokens in `tailwind.config.js` |
| Charts | Recharts 2.15 | Dashboard visualisations |
| Backend | FastAPI ≥ 0.115, Uvicorn | Async request handling; OpenAPI at `/docs` |
| HTTP clients | httpx, requests | Async in scrapers, sync for simple calls |
| Browser automation | Playwright ≥ 1.48, playwright-stealth | JS-rendered supplier pages |
| HTML parsing | BeautifulSoup 4 | Static page extraction |
| ORM | SQLAlchemy ≥ 2.0 | Declarative models, shared across API and legacy client |
| Validation | Pydantic ≥ 2.0 | Request/response schemas |
| LLM | Ollama, `llama3.1:8b` | Local inference; rule-based fallback when unavailable |
| Data/export | pandas, openpyxl | CSV and XLSX export |
| Tests | pytest | `tests/` with path bootstrap in `conftest.py` |

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer
- Ollama (optional) — without it, LLM steps use the rule-based fallback
- eBay Developer API keys (required for product search)

## Installation

```bash
git clone https://github.com/agha-moutsim/hunting_system.git
cd ebay-hunter
```

**Backend**

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows: source venv/bin/activate on macOS/Linux
pip install -r requirements.txt
playwright install chromium
```

**Frontend**

```bash
cd frontend
npm install
```

## Configuration

Copy the root `.env.example` to `.env` and fill in the values you have:

| Variable | Required | Purpose |
|---|---|---|
| `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` | Yes | eBay Browse API (free, 5,000 calls/day) |
| `EBAY_ENVIRONMENT`, `EBAY_MARKETPLACE` | No | Defaults: `production`, `EBAY_GB` |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | No | Defaults: `http://localhost:11434`, `llama3.1:8b` |
| `DATABASE_URL` | No | Defaults to SQLite file; set for PostgreSQL |
| `CJ_API_KEY`, `CJ_ACCESS_TOKEN` | No | CJ Dropshipping API |
| `AMAZON_PA_ACCESS_KEY`, `AMAZON_PA_SECRET_KEY`, `AMAZON_PA_PARTNER_TAG` | No | Amazon Product Advertising API |
| `RAPIDAPI_KEY` | No | AliExpress API |
| `SERPAPI_KEY` | No | Google Shopping results for B&Q and Toolstation |
| `SCRAPINGBEE_API_KEY`, `SCRAPERAPI_KEY` | No | Paid anti-bot bypass services |

Suppliers without an API key fall back to browser scraping, which is slower and subject to rate limiting.

## Usage

```bash
# Backend (terminal 1)
cd backend
python -m uvicorn main:app --port 8000

# Frontend (terminal 2)
cd frontend
npm run dev                      # http://localhost:3000
```

Production build:

```bash
cd frontend && npm run build && npm run start
```

Interactive API documentation is served at `http://localhost:8000/docs`.

## API reference

Base URL: `http://localhost:8000`

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/status` | Service health: database, Ollama, eBay credentials |
| POST | `/api/analyze` | Full single-product pipeline |
| POST | `/api/deep-search` | Deep research with LLM (≤ 120s) |
| POST | `/api/deep-search/fast` | Deep research without LLM (≤ 75s) |
| POST | `/api/bulk` | Batch queries |
| POST | `/api/hunter/scan` | Category scan against filters |
| POST | `/api/hunter/lookup` | Supplier lookup for scan results |
| GET | `/api/tracker` | Tracked products |
| POST | `/api/tracker` | Start tracking / trigger check |
| DELETE | `/api/tracker/{id}` | Stop tracking |
| GET | `/api/tracker/{id}/history` | Price history |
| GET | `/api/tracker/alerts` | Price alerts |
| GET | `/api/watchlist` | Watchlist items |
| POST | `/api/watchlist` | Add to watchlist |
| GET | `/api/searches` | Saved searches |
| POST | `/api/searches/run-all` | Run all saved searches |
| GET | `/api/dashboard/kpis` | Dashboard KPI figures |
| GET | `/api/dashboard/charts/*` | Revenue, profit, category, monthly series |
| GET/POST/DELETE | `/api/sales` | Sales log |
| GET | `/api/history` | Past analyses |
| GET/POST | `/api/export/csv`, `/api/export/json` | Exports |

## Business rules

Enforced by `backend/engine/`, configured in `backend/config.py`.

| Rule | Threshold |
|---|---|
| Buy price | £5 – £25 |
| Minimum margin | ≥ 25% |
| Demand (30 days) | ≥ 10 sold |
| Demand (7 days) | ≥ 1 sold |
| Delivery | ≤ 8 days (≤ 25 days when sales ≥ 30/month) |
| Brand | Generic only; branded items fail |
| Listing condition | New, Buy It Now, UK only |
| eBay fees | 12.8% final value + 3% returns buffer |

```
profit = sale_price − supplier_price − (sale_price × 0.158)
margin = profit / sale_price × 100
```

Approved suppliers: AliExpress, Amazon UK, CJ Dropshipping, GoDropship, Joybuy UK, B&Q, Toolstation. No other source is accepted.

## Data model

13 tables in SQLite (models in `backend/db/models.py`):

| Domain | Tables |
|---|---|
| Product and analysis | `products`, `demand_data`, `supplier_matches`, `analyses`, `verdicts` |
| Price monitoring | `tracked_products`, `price_history`, `price_alerts` |
| Watchlist | `watchlist_items`, `saved_searches`, `search_results` |
| Sales reporting | `sales`, `monthly_stats` |

## Testing

```bash
cd ebay-hunter
pytest tests/ -v
```

The suite runs against live services where available and degrades gracefully when keys are absent (a scraper test reports API mode or scraping mode rather than failing). Debug scripts for the eBay API are in `tests/debug_ebay.py` and `tests/debug_listing.py`.

## Deployment

- **Frontend** — Vercel. Build command `npm run build`, output automatic. Production origin must be added to the backend CORS list in `backend/main.py`.
- **Backend** — Render. Definition in `backend/render.yaml`. Free tier sleeps after ~15 minutes idle; the first request after cold start takes ~30 seconds.
- **Database** — SQLite on the Render disk for v1, or any PostgreSQL via `DATABASE_URL`.
- **Migration** — `backend/scripts/migrate_pg_to_sqlite.py` converts an existing PostgreSQL database to SQLite.

## Known limitations

- GoDropship and Joybuy have no public API and rely on Playwright; anti-bot protection may block them. Affected results are marked Unverified rather than inferred.
- Amazon, AliExpress, and CJ are rate-limited unless their API keys are configured.
- Ollama is not available on Render; the deployed instance runs LLM steps through the rule-based fallback.
- No authentication in v1. The deployment model is a private link within a trusted group.

## License

Private — eBay Hunter. Interface icons from [Noun Project](https://nounproject.com) (Keyy Creative, Trimanggolo Mulyo, Awicon, Hermanto, VectorVibe Designs, Lulis Dian RP, Mia Elysia) used under the Noun Project license.
