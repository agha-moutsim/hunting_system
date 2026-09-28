# eBay Hunter

**Sourcing intelligence for eBay UK resellers.**

eBay Hunter turns a product idea into a sourcing decision. Give it an eBay listing or a search term and it returns the numbers that decide the buy: what the item actually sells for, what the same product costs at seven approved suppliers, profit after eBay's fees, and a pass/fail verdict against your buying rules.

Built for resellers working the £5–£35 generic-product range who need to validate dozens of candidates without spending twenty minutes researching each one. A full analysis takes about 90 seconds.

## Capabilities

- **Analyze** — the complete pipeline on one product: listing data, sold history, supplier prices, AI brand/demand verdict, profit scorecard
- **Deep Search** — research mode in two speeds: Fast returns real eBay sold data in ~20 seconds without the LLM; Full adds LLM analysis within a 2-minute budget
- **Category Hunter** — scan an entire category against your filters, then resolve supplier matches for the hits
- **Price Tracker & Watchlist** — follow listings over time with price-drop alerts; save searches and re-run them individually or in bulk
- **Dashboard & History** — sales KPIs, revenue and profit trends, category breakdowns, and every past analysis with its verdict

## Architecture

Three services, one file database:

```
Browser ──► Next.js frontend (:3000)
                │  REST /api/*, every call with a client timeout
                ▼
           FastAPI backend (:8000)
                │
    ┌───────────┼─────────────┬──────────────┐
    ▼           ▼             ▼              ▼
 eBay API   7 suppliers   Ollama LLM     Decision engine
 listings   (API-first,  (llama3.1:8b,  (filters, profit,
 sold data   Playwright   rule-based      scorecard)
             fallback)    fallback)
    └───────────┴─────────────┴──────────────┘
                ▼
          SQLite (13 tables)
```

A single analysis request runs through six stages: eBay product lookup, sold-listing demand measurement, supplier search across all seven sources, LLM brand and demand judgement, business-rule evaluation with profit calculation, then persistence and scorecard. The pipeline in `backend/analysis_pipeline.py` is shared by the API and the legacy Streamlit client, so both produce identical results.

Two properties are enforced throughout:

- **No fabricated values.** Every figure is either measured or explicitly marked Unverified. If a supplier is unreachable or the LLM fails, the field says so rather than guessing.
- **Bounded execution.** Each stage has a hard budget — 150s for the whole pipeline, 90s for suppliers, 45s per scraper, 45s for the LLM — and only two browsers run concurrently. Exceeding a budget degrades that stage to partial results; it never blocks the request.

## Tech stack

| Layer    | Technology                                                       |
| -------- | ---------------------------------------------------------------- |
| Frontend | Next.js 16, React 19, TypeScript 5.7, Tailwind CSS 3.4, Recharts |
| Backend  | FastAPI, Uvicorn, Pydantic 2, httpx                              |
| Scraping | Playwright + playwright-stealth, BeautifulSoup 4                 |
| LLM      | Ollama (`llama3.1:8b`), local, with rule-based fallback          |
| Database | SQLite via SQLAlchemy 2 (`DATABASE_URL` switches to PostgreSQL)  |
| Export   | pandas, openpyxl (CSV / XLSX / JSON)                             |
| Hosting  | Vercel (frontend), Render (backend) — free tiers                 |

## Getting started

Prerequisites: Python 3.11+, Node 20+, and optionally [Ollama](https://ollama.com) with `llama3.1:8b`.

```bash
git clone https://github.com/agha-moutsim/hunting_system.git
cd ebay-hunter

# Backend
cd backend
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python -m uvicorn main:app --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev          # http://localhost:3000
```

API documentation is served at `http://localhost:8000/docs`.

**eBay API keys are required.** Create an app at [developer.ebay.com](https://developer.ebay.com) and add `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` to `.env`. Optional keys for CJ, Amazon, AliExpress, and SerpApi unlock faster supplier paths — see `.env.example`.

## Business rules

| Rule           | Threshold                                                                            |
| -------------- | ------------------------------------------------------------------------------------ |
| Buy price      | £5 – £35 default, user-adjustable range (supplier prices never gated)                |
| Minimum margin | ≥ 25% of sale price                                                                  |
| Demand         | ≥ 30 sold / 30 days, ≥ 8 sold / 7 days (7d from purchase-history data, else PENDING) |
| Delivery       | Advisory only — shows eBay estimate vs supplier's stated days, never gates           |
| Brand          | VeRO check — brand registered on eBay's VeRO list fails, unregistered names OK       |
| Fees           | 13.5% final value + 0.03% listing + 20% VAT on fees + 3% returns buffer              |

```
profit = sale_price − supplier_price − (13.5% + 0.03% + VAT-on-fees + 3%) × sale_price
margin = profit / sale_price × 100
```

Approved suppliers: AliExpress, Amazon UK, CJ Dropshipping, GoDropship, Joybuy UK, B&Q, Toolstation.

## Limitations

- GoDropship and Joybuy have no API and rely on Playwright; anti-bot protection can block them. Those results are marked Unverified.
- Amazon, AliExpress, and CJ are rate-limited without their API keys.
- The production build on Render has no Ollama available, so LLM steps use the rule-based fallback.
- No authentication in v1 — the deployment model is a private link within a trusted group.

## License

Private — eBay Hunter. Interface icons from [Noun Project](https://nounproject.com).
