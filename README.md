# eBay Hunter

**Product sourcing intelligence for eBay UK resellers.**

Search eBay → compare 7 suppliers → AI verdict → profit scorecard — in one click. Built as a full-stack web app (FastAPI + Next.js), designed to answer one question: *should I source and resell this product?*

> **Never fabricate data.** Missing information is shown as ⚠️ Unverified. A wrong number costs real money.

---

## Why it exists

Reselling on eBay UK is a numbers game: buy generic products in the £5–£25 range, resell with ≥25% margin, keep delivery inside 3–8 days. Doing that research by hand — checking sold listings, opening 7 supplier sites, calculating eBay's 12.8% fee + 3% returns buffer — takes 20+ minutes per product.

eBay Hunter does it in ~90 seconds with a pass/fail scorecard you can trust.

## Features

| Page | What it does |
|------|-------------|
| **Analyze** | Full pipeline: eBay listing → demand data → 7 suppliers → LLM brand/demand check → profit verdict + scorecard |
| **Deep Search** | Research mode with real eBay sold history; Fast (~20s, no LLM) or Full (LLM) |
| **Bulk Analysis** | Queue multiple queries, export CSV/JSON |
| **Category Hunter** | Scan a category for products matching your filters, then look up suppliers |
| **Price Tracker** | Track products over time, price-drop alerts |
| **Watchlist** | Save items + saved searches; auto-run finds new opportunities |
| **Dashboard** | Sales KPIs, revenue/profit trends, category breakdowns, log sales |
| **History** | Every past analysis, searchable and filterable by verdict |

**Keyboard:** `Ctrl+1` … `Ctrl+8` jump between pages.

## Business rules (configurable in `config.py`)

| Rule | Threshold |
|------|-----------|
| Buy price | £5 – £25 |
| Minimum margin | ≥ 25% |
| Demand (30d) | ≥ 10 sold, and ≥ 1 sold in 7d |
| Delivery | ≤ 8 days (≤ 25 days if ≥ 30 sold/30d) |
| Brand | Generic only — branded items are FAIL |
| Condition | New · Buy It Now · UK only |
| eBay fees | 12.8% final value + 3% returns buffer |

```
Profit = eBay Price − Supplier Price − (eBay Price × 15.8%)
Margin = Profit / eBay Price × 100
```

**Approved suppliers (only these 7):** AliExpress · Amazon UK · CJ Dropshipping · GoDropship · Joybuy UK · B&Q · Toolstation

## Architecture

```
┌──────────────────────┐     ┌──────────────────────┐
│   Next.js frontend   │     │   Streamlit (legacy)  │
│  Vercel · port 3000  │     │   app.py · port 8501  │
└──────────┬───────────┘     └──────────┬───────────┘
           │  REST /api/*               │ import
           ▼                            ▼
┌──────────────────────────────────────────────────┐
│              FastAPI backend :8000               │
│  main.py · api/ (10 routers, 40+ endpoints)      │
│  analysis_pipeline.py  ← single source of truth  │
└──┬──────────┬──────────┬──────────┬─────────────┘
   │          │          │          │
   ▼          ▼          ▼          ▼
┌───────┐ ┌────────┐ ┌───────┐ ┌─────────┐
│ eBay  │ │ 7 sup- │ │ Ollama│ │ Engine  │
│ Browse│ │ pliers │ │ LLM   │ │ filters │
│  API  │ │(API +  │ │(local,│ │ profit  │
│       │ │Play-   │ │ rule  │ │ verdict │
│       │ │wright) │ │fallbk)│ │ scorecd │
└───────┘ └────────┘ └───────┘ └────┬────┘
                                    ▼
                              ┌──────────┐
                              │ SQLite   │
                              │ 13 tables│
                              └──────────┘
```

- **Frontend** → `frontend/` — Next.js 16, Tailwind, Plus Jakarta Sans + JetBrains Mono, indigo/lime dark theme (`design.md`)
- **Backend** → `backend/` — FastAPI, Pydantic, shared pipeline with Streamlit
- **LLM** → local Ollama (`llama3.1:8b`) with **rule-based fallback** — the app never crashes if the LLM is down
- **Database** → SQLite file (swap to Postgres via `DATABASE_URL` env var only)
- **Timeouts everywhere** — 150s pipeline cap, 45s per scraper, 45s LLM; browser concurrency capped at 2

## Quick start

### Prerequisites

- Python 3.11+, Node 20+
- (optional) [Ollama](https://ollama.com) for local LLM — without it, rule-based fallback is used

### Setup

```bash
git clone https://github.com/agha-moutsim/hunting_system.git
cd ebay-hunter

# Backend
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
playwright install chromium
copy .env.example .env         # add your eBay API keys
python -m uvicorn main:app --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev                    # http://localhost:3000
```

### Getting eBay API keys (free)

1. <https://developer.ebay.com> → create account → Apps → create app
2. Copy **Client ID** + **Client Secret** into `backend/.env`:

```
EBAY_CLIENT_ID=your_client_id
EBAY_CLIENT_SECRET=your_client_secret
```

### Optional keys

| Key | Enables |
|-----|---------|
| `SERPAPI_KEY` | B&Q + Toolstation via Google Shopping |
| `AMAZON_PA_*` | Amazon UK Product Advertising API |
| `CJ_API_KEY` | CJ Dropshipping API (faster than scraping) |
| `RAPIDAPI_KEY` | AliExpress via RapidAPI |

Without them, those suppliers fall back to Playwright scraping (slower, may be rate-limited).

## API

Base URL: `http://localhost:8000` · interactive docs at `/docs`

```
GET    /api/status                     DB / Ollama / eBay key health
POST   /api/analyze                    full single-product pipeline
POST   /api/deep-search                deep research (LLM, ≤2 min)
POST   /api/deep-search/fast           deep research, no LLM (~20s)
POST   /api/bulk                       batch queries
POST   /api/hunter/scan · /lookup      category scan → supplier lookup
GET/POST/DELETE /api/tracker           price tracking + alerts
GET/POST/DELETE /api/watchlist         watchlist + saved searches
GET    /api/dashboard/*                KPIs, charts, top products
GET/POST/DELETE /api/sales             sales log
GET    /api/history                    past analyses
GET    /api/export/csv|json            exports (type=sales|analysis)
```

## Project structure

```
ebay-hunter/
├── design.md              UI redesign spec (theme, structure, plan)
├── CONSTRAINTS.md         Product spec — hard constraints, API surface, quality bar
├── app.py                 Legacy Streamlit UI (kept until full parity)
├── backend/
│   ├── main.py            FastAPI app + CORS
│   ├── api/               10 routers → 40+ endpoints
│   ├── analysis_pipeline.py  shared eBay→suppliers→LLM→verdict pipeline
│   ├── scrapers/          eBay API + 7 supplier scrapers (API-first, Playwright fallback)
│   ├── engine/            filters, profit calculator, scorecard
│   ├── llm/               Ollama client + prompts + safe fallbacks
│   ├── db/                SQLAlchemy models + queries (SQLite)
│   ├── hunter/ tracker/ watchlist/ dashboard/ export/
│   └── render.yaml        Render.com deploy config
├── frontend/
│   ├── app/               8 pages (analyze, deep-search, bulk, hunter, tracker, …)
│   ├── components/        Layout, Scorecard, DataTable, charts, ui/, icons/
│   ├── lib/               api.ts (timeouts), types.ts, format.ts
│   └── tailwind.config.js design tokens
├── icons/                 Noun Project source SVGs
└── tests/
```

## Design

Dark theme, indigo (`#0D1CC4`) + lime (`#CBFD03`) on deep indigo (`#27233F`). **Plus Jakarta Sans** for UI, **JetBrains Mono** for all money and percentages (tabular figures). Full spec in [`design.md`](design.md).

## Icons

Navigation icons from [Noun Project](https://nounproject.com), used under the Noun Project license:

- Analyze — Keyy Creative
- Deep Dive & Categories — Trimanggolo Mulyo
- Bulk — Awicon
- Pricing — Hermanto
- Wishlist — VectorVibe Designs
- Dashboard — Lulis Dian RP
- History — Mia Elysia

## Known limitations

- GoDropship / Joybuy use Playwright and may be blocked by anti-bot (results marked Unverified)
- AliExpress / CJ / Amazon are rate-limited without their API keys
- Ollama unavailable in production → rule-based fallback (by design)
- Render free tier sleeps after ~15 min idle (~30s cold start)
- No auth in v1 — the app is shared by link inside a trusted circle

## License

Private — eBay Hunter
