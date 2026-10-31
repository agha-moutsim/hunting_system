# eBay Hunter

Sourcing intelligence and multi-marketplace analytics for eBay resellers.

eBay Hunter turns a product idea into a sourcing decision: what it actually sells for, what it costs from approved suppliers, profit after eBay fees, and a pass/fail verdict against rules you control. A full analysis completes in roughly 90 seconds.

## Overview

- Markets: eBay UK (`ebay.co.uk`, GBP) and eBay Australia (`ebay.com.au`, AUD).
- Inputs: a product query or eBay listing URL.
- Outputs: sold-history evidence, supplier matches, fee breakdown, profit, margin, verdict, and a scorecard.
- Storage: SQLite by default, PostgreSQL via `DATABASE_URL`.
- Optional LLM: Ollama (`llama3.1:8b` by default), with deterministic fallback.

Two rules apply throughout the system:

- No fabricated values. Every figure is either measured or explicitly marked `Unverified`, with a reason.
- Bounded execution. Every stage has a time budget; overruns degrade to partial results and are reported rather than hidden.

## Capabilities

| Feature | Description |
|---|---|
| Analyze | Full pipeline for one product: listing data, sold history, supplier prices, demand, profit, verdict |
| Deep Search | Fast mode returns real eBay sold data in about 20 seconds without an LLM; full mode adds deeper analysis |
| Category Hunter | Scan an eBay category and resolve supplier matches for qualifying listings |
| Bulk | Run multiple queries through the pipeline in one pass |
| Price Tracker | Track listings over time and raise price-drop alerts |
| Watchlist | Save and re-run searches individually or in bulk |
| Dashboard | Sales KPIs, revenue, profit, and category breakdowns |
| History | Replay past analyses with verdict and provenance; market-aware currency |
| Fee Calculator | Standalone fee and break-even calculator using official UK and AU rate cards |
| Title Helper | Title keyword and phrase frequency analysis against eBay's 80-character limit |
| Market Churn | Listing age distribution and active-vs-sold saturation analysis |
| Seller Footprint | Competitor concentration and store-handle analysis |
| Browser Capture | Chrome extension captures verified purchase-history data to upgrade demand evidence |

## Multi-market support

| Market | Currency | Price band | Demand floors | Supplier bench | Fee card |
|---|---|---|---|---|---|
| eBay UK | GBP | 5.00-35.00 default | 30 sold / 30d, 8 sold / 7d | AliExpress, CJ, B&Q, Toolstation, Joybuy UK | `uk-rate-card-2026-09-30` |
| eBay Australia | AUD | 0.99-50.00 default | 15 sold / 30d, 10 sold / 7d | AliExpress, CJ only | `au-rate-card-2026-10-09` |

Australian results carry their own currency through Analyze, Deep Search, Bulk, Category Hunter, Fees, Deals, Titles, and History. Amounts are never converted between GBP and AUD.

## Architecture

The backend owns all business logic. The frontend renders API results and does not re-derive business numbers.

```text
Browser (Next.js 16 :3000)
  -> FastAPI (:8000)
      -> analysis_pipeline.py (single source of truth)
          -> eBay API + sold listings
          -> supplier fan-out and matching
          -> deterministic decision engine
          -> optional Ollama LLM enrichment
          -> SQLite / PostgreSQL
```

Backend layout:

```text
backend/
  api/                 FastAPI routers
  analysis_pipeline.py Shared pipeline
  engine/              Fees, matching, price gate, condition gate, decisions
  scrapers/            eBay, sold listings, suppliers, SerpApi discovery
  hunter/              Category scan and supplier lookup
  tracker/             Price tracking and alerts
  watchlist/           Saved searches and bulk re-runs
  dashboard/           Aggregate KPIs
  db/                  SQLAlchemy models and queries
  export/              CSV, XLSX, JSON
  extension/           Chrome MV3 capture extension
```

## Verification and provenance

Every factual field is labelled with how it was obtained:

| Label | Meaning |
|---|---|
| `verified` | Read directly from an API payload, parsed page, or browser capture |
| `estimated` | Derived by a transparent stated algorithm |
| `unverified` | Could not be validated; the reason is attached |
| `ai_insight` | Produced by LLM evaluation; structurally prohibited from carrying numbers |

Product matching is deterministic: title token overlap, price plausibility, perceptual image hashing where images are available, and thresholded match scores. Candidates below threshold are discarded or marked unverified rather than padded into results.

## Suppliers and currency isolation

The supplier bench is a marketplace property, not a global list.

- UK: AliExpress, CJ Dropshipping, B&Q, Toolstation, Joybuy UK.
- Australia: AliExpress and CJ Dropshipping only.

Currency rules:

- AliExpress is scoped to the market's locale and currency.
- CJ USD rows are tagged `USD` and excluded from AUD comparisons rather than converted.
- UK keeps its historical USD-to-GBP path.
- Supplier rows without an explicit currency tag are not used for margin calculations.

## Fees

Fee calculations use transcribed official rate cards:

- UK: `uk-rate-card-2026-09-30`
- Australia: `au-rate-card-2026-10-09`

The Australia card has two branches:

- eBay Pro business plans: Starter, Basic, Featured, Anchor.
- Free selling / Individual branch.

GST is handled as inclusive on the AU card. The fee calculator supports forward pricing, reverse solving for a target margin, and break-even calculation.

## Business rules

| Rule | Value |
|---|---|
| UK buy price band | 5.00-35.00 GBP default |
| AU buy price band | 0.99-50.00 AUD default |
| Minimum margin | 25% default, configurable |
| UK demand | 30 sold / 30d, 8 sold / 7d |
| AU demand | 15 sold / 30d, 10 sold / 7d |
| Condition | New only |
| Packaging | 0.00 in dropship model |
| Returns buffer | 3% |

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript 5.7, Tailwind CSS 4, Recharts |
| Backend | FastAPI, Uvicorn, Pydantic 2 |
| Scraping | Playwright, BeautifulSoup 4 |
| Supplier discovery | SerpApi |
| LLM | Ollama (`llama3.1:8b`), with deterministic fallback |
| Database | SQLite via SQLAlchemy 2; PostgreSQL via `DATABASE_URL` |
| Export | pandas, openpyxl |
| Extension | Chrome MV3 |
| Tests | pytest, TypeScript typecheck, husky pre-commit |

## Getting started

Prerequisites: Python 3.11+, Node 20+, and optionally Ollama with `llama3.1:8b`.

```bash
git clone https://github.com/agha-moutsim/hunting_system.git
cd hunting_system

cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python -m uvicorn main:app --host 127.0.0.1 --port 8000

cd ../frontend
npm install
npm run dev
```

Frontend: `http://localhost:3000`
Backend API docs: `http://localhost:8000/docs`

Windows helpers from the repository root:

```powershell
.\start.ps1
.\check.ps1
.\stop.ps1
```

### Configuration

Copy `.env.example` to `.env` and fill in required values:

| Variable | Required | Purpose |
|---|---|---|
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | Yes | eBay listing and sold-data access |
| `SERPAPI_KEY` | Recommended | Supplier discovery |
| `SCRAPINGBEE_API_KEY` | Optional | Storefront verification |
| `CJ_API_KEY` / `CJ_ACCESS_TOKEN` | Optional | CJ Dropshipping path |
| `DATABASE_URL` | Optional | Defaults to SQLite |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Optional | Local LLM endpoint and model |

`.env` is gitignored. Never commit it.

## Testing

```bash
npm test
npm run typecheck
npm --prefix frontend run build
```

The backend suite currently has 1,972 passing tests with 9 deselected. The frontend suite has 220 passing tests. A husky pre-commit hook runs lint, typecheck, and the full backend suite.

## Limitations

- No authentication in v1. The intended deployment is a private link within a trusted group.
- Supplier coverage is partial and reported honestly. Missing sources are absent, not substituted.
- Scraping is fragile. Failures surface as `unverified` with a reason.
- The LLM is optional. Without Ollama, analyses fall back to deterministic rules and still produce a verdict.
- Demand figures can be `PENDING` where eBay does not publish a reliable 7-day count.
- AU History writes are enabled only after the currency migration; stored rows default to GBP.

## License

No licence is granted for reuse. All rights reserved.

Interface icons from [Noun Project](https://nounproject.com).