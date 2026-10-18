<div align="center">

<img src="assets/brand/hero.svg" width="100%" alt="The eBay Hunter wordmark: a pair of lime selection brackets around a white point, beside the name set in white on deep indigo.">

# eBay Hunter

**Sourcing intelligence for eBay UK resellers.**

Turn a product idea into a sourcing decision in about 90 seconds — what it actually sells for, what it costs from approved suppliers, profit after eBay's fees, and a pass/fail verdict against rules you control.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js%2016-000000?logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React%2019-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript%205.7-3178C6?logo=typescript&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind%204-06B6D4?logo=tailwindcss&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-2EAD33?logo=playwright&logoColor=white)

![Tests](https://img.shields.io/badge/tests-1163%20passing-brightgreen)
![License](https://img.shields.io/badge/license-all%20rights%20reserved-lightgrey)

</div>

---

## Overview

eBay Hunter answers one question: **should I buy this and where from?**

It is built for resellers working the **£5–£35 generic-product range**, who need to screen dozens of candidates without spending twenty minutes of manual research on each one. A full analysis runs end to end in roughly 90 seconds and returns a decision, not a pile of raw data.

Two design principles run through every layer:

> **No fabricated values.** Every figure is either measured or explicitly labelled `Unverified`, together with the reason. A blocked supplier is reported as blocked — never silently replaced with a plausible-looking number.

> **Bounded execution.** Every stage has a hard time budget. Exceeding one degrades that stage to partial results and says so; it never hangs the request.

---

## Capabilities

|                                                                                                                                                                                        | Feature             | What it does                                                                                                                                   |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| <picture><source srcset="icons/readme-dark/noun_analyze_8392548.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_analyze_8392548.svg" width="26" alt=""></picture>       | **Analyze**         | The complete pipeline on a single product: listing data, sold history, supplier prices, brand and demand assessment, profit scorecard, verdict |
| <picture><source srcset="icons/readme-dark/noun_DeepDive_7968343.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_DeepDive_7968343.svg" width="26" alt=""></picture>     | **Deep Search**     | Two research speeds. _Fast_ returns real eBay sold data in ~20s with no LLM. _Full_ adds deeper analysis inside a 2-minute budget              |
| <picture><source srcset="icons/readme-dark/noun_categories_8378322.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_categories_8378322.svg" width="26" alt=""></picture> | **Category Hunter** | Scan an entire eBay category against your filters, then resolve supplier matches for the hits                                                  |
| <picture><source srcset="icons/readme-dark/noun_bulk_7761163.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_bulk_7761163.svg" width="26" alt=""></picture>             | **Bulk**            | Run a list of queries through the pipeline in one pass, with per-row status                                                                    |
| <picture><source srcset="icons/readme-dark/noun_Pricing_8447584.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_Pricing_8447584.svg" width="26" alt=""></picture>       | **Price Tracker**   | Follow listings over time, with price-drop alerts                                                                                              |
| <picture><source srcset="icons/readme-dark/noun_wishlist_8254557.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_wishlist_8254557.svg" width="26" alt=""></picture>     | **Watchlist**       | Save searches and re-run them individually or in bulk                                                                                          |
| <picture><source srcset="icons/readme-dark/noun_dashboard_8450002.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_dashboard_8450002.svg" width="26" alt=""></picture>   | **Dashboard**       | Sales KPIs, revenue and profit trends, category breakdowns                                                                                     |
| <picture><source srcset="icons/readme-dark/noun_History_8203921.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_History_8203921.svg" width="26" alt=""></picture>       | **History**         | Every past analysis, replayable with its verdict and provenance intact                                                                         |

A Chrome extension (`extension/`) captures eBay purchase-history data from a live listing page, which upgrades the 7-day demand figure from _estimated_ to _verified_.

---

## Architecture

Three services, one database, and a strict rule that business logic lives in exactly one place.

```
                        ┌─────────────────────────┐
                        │  Browser                │
                        │  Next.js 16  :3000      │
                        └────────────┬────────────┘
                                     │ REST  /api/*   (per-call timeouts)
                                     ▼
                        ┌─────────────────────────┐
                        │  FastAPI       :8000    │
                        │  backend/api/*          │
                        └────────────┬────────────┘
                                     │
                        ┌────────────▼────────────┐
                        │  analysis_pipeline.py   │  ◄── shared by API
                        │  6 sequential stages    │      and Streamlit
                        └────────────┬────────────┘
                                     │
      ┌──────────────┬───────────────┼───────────────┬──────────────┐
      ▼              ▼               ▼               ▼              ▼
 ┌─────────┐   ┌──────────┐   ┌────────────┐   ┌───────────┐  ┌──────────┐
 │ eBay    │   │ Supplier │   │ Matching   │   │ Decision  │  │ Ollama   │
 │ API +   │   │ fan-out  │   │ engine     │   │ engine    │  │ LLM      │
 │ sold    │   │ (5 live) │   │            │   │           │  │ optional │
 └─────────┘   └──────────┘   └────────────┘   └───────────┘  └──────────┘
      │              │               │               │              │
      └──────────────┴───────────────┴───────────────┴──────────────┘
                                     ▼
                    ┌────────────────────────────────┐
                    │  SQLite  ·  15 tables          │
                    │  DATABASE_URL → PostgreSQL     │
                    └────────────────────────────────┘
```

### Request lifecycle

A single Analyze request passes through six stages, each timed and reported:

| #   | Stage            | Source                                                            | Budget                                    |
| --- | ---------------- | ----------------------------------------------------------------- | ----------------------------------------- |
| 1   | **eBay product** | Listing lookup by URL, or search + price-band and condition gates | 25s                                       |
| 2   | **Demand**       | Sold listings (30d / 7d), competitor store discovery              | —                                         |
| 3   | **Suppliers**    | Parallel fan-out across enabled suppliers, then match scoring     | 90s search, 70s per supplier, 15s scoring |
| 4   | **AI analysis**  | Brand/demand judgement — background enrichment, not blocking      | —                                         |
| 5   | **Decision**     | Business rules, fees, profit, verdict                             | —                                         |
| 6   | **Persistence**  | Product, demand, supplier rows, verdict, scorecard                | —                                         |

Whole-pipeline ceiling: **150 seconds**. Overrun is reported in the response's `timing` / `budget` blocks rather than failing silently.

### Backend layout

```
backend/
├── api/            FastAPI routers — analyze, deep_search, bulk, hunter,
│                   tracker, watchlist, dashboard, history, export, extension
├── analysis_pipeline.py    ★ the shared pipeline (single source of truth)
├── engine/         Deterministic business logic, no I/O
│   ├── match.py          product matching (C14) — title, price, image phash
│   ├── price_gate.py     active price band, in/out-of-band classification
│   ├── profit.py         fees, VAT, returns buffer, margin
│   ├── decisions.py      rule evaluation → verdict
│   ├── condition_gate.py New-only enforcement (C10)
│   ├── provenance.py     verified / estimated / unverified / ai_insight
│   ├── source_type.py    who a row came from, derived from its own URL
│   ├── stores.py         competitor-store identity ladder
│   ├── verify.py         storefront existence checks
│   ├── scorecard.py      human-readable output
│   └── query_extract.py  URL → product identity
├── scrapers/       eBay, sold listings, AliExpress, CJ, B&Q, Toolstation,
│                   Joybuy (web index), SerpApi discovery, availability
├── hunter/         category scan + supplier lookup
├── tracker/        price tracking and alerts
├── watchlist/      saved searches and bulk re-runs
├── dashboard/      aggregate KPIs
├── llm/            Ollama client with rule-based fallback
├── db/             SQLAlchemy models and queries
├── export/         CSV / XLSX / JSON
└── scripts/        operational helpers
```

The frontend is a thin presentation layer — it renders what the API computes and never re-derives a business number.

---

## Verification and provenance

Most sourcing tools show a number and let you assume it is true. This one labels every value with **how it was obtained**, and refuses to fill gaps.

| Label        | Meaning                                                                       |
| ------------ | ----------------------------------------------------------------------------- |
| `verified`   | Read from a real API response or a successfully parsed page                   |
| `estimated`  | Derived by a stated method (e.g. a demand figure inferred from sold listings) |
| `unverified` | We could not confirm it — _and the reason travels with the value_             |
| `ai_insight` | Produced by the LLM. Never used for a factual field                           |

Concrete consequences of that rule:

- **Product matching is scored, not guessed.** Every supplier row is scored against the eBay title with a deterministic matcher combining title tokens, price plausibility and perceptual image hashing. Rows below threshold are dropped rather than shown — _fewer suppliers is correct; padding one in is not._
- **Supplier prices are never range-gated.** Only eBay listing selection respects the price band, so a cheap legitimate source cannot be filtered out of the margin calculation.
- **A blocked supplier is reported as blocked.** Rows carry their own stock and shipping wording, read from the source. An unread value stays empty — never `0.00`, which would read as free postage.
- **Store links are checked, not assumed.** eBay storefront URLs are verified before being presented, so a dead shop shows as "store not found" instead of a link to nothing.

---

## Suppliers

Five suppliers are live. Each has a recorded access path, and anything disabled carries the evidence for why.

| Supplier            | Status                | Access path                                                                 |
| ------------------- | --------------------- | --------------------------------------------------------------------------- |
| **AliExpress**      | ✅ Enabled            | API when keyed, Playwright otherwise                                        |
| **CJ Dropshipping** | ✅ Enabled            | API when keyed, Playwright otherwise                                        |
| **B&Q**             | ✅ Enabled            | Playwright + Google Shopping discovery                                      |
| **Toolstation**     | ✅ Enabled            | Playwright + Google Shopping discovery                                      |
| **Joybuy UK**       | ⚠️ Enabled — link-out | Read from Google's web index; the site's own bot protection is not bypassed |
| **Amazon UK**       | ⛔ Disabled           | PA-API 5 deprecated; licence bars aggregating product data for analysis     |
| **GoDropship**      | ⛔ Disabled           | Domain is a for-sale parking page                                           |

Each entry in `backend/suppliers.json` records its `enabled` flag, the evidence behind that state, and a `revisit_if` condition describing what would change the decision.

> **Note on Joybuy:** its own site is defended by a risk-control challenge that survives headless Chromium, stealth and residential proxies. Rather than fake a workaround, the integration reads Google's index of Joybuy and never contacts the supplier. The honest limitation is recorded next to the flag: roughly 20% of its listings come back with a price, so it functions as a link-out source rather than a pricing source.

---

## Business rules

| Rule           | Threshold                                                                                                          |
| -------------- | ------------------------------------------------------------------------------------------------------------------ |
| Buy price      | £5 – £35 default, user-adjustable (supplier prices never gated)                                                    |
| Minimum margin | ≥ 25% of sale price                                                                                                |
| Demand         | ≥ 30 sold / 30 days; ≥ 8 sold / 7 days (7d uses purchase-history data when available, otherwise reports `PENDING`) |
| Condition      | New only — non-New listings are refused before supplier or LLM spend                                               |
| Delivery       | Advisory — compares eBay estimate against the supplier's stated days; never gates                                  |
| Brand          | VeRO check — brands on eBay's VeRO list fail; unregistered names pass                                              |
| Fees           | 13.5% final value + 0.03% listing + 20% VAT on fees + 3% returns buffer                                            |
| Packaging      | £0.00 — dropship model carries no packaging cost                                                                   |

Fees are modelled as they actually accrue, VAT applied to eBay's fees rather than to the sale:

```python
ebay_fee       = sale_price * 0.135
listing_fee    = sale_price * 0.0003
vat_on_fees    = (ebay_fee + listing_fee) * 0.20
returns_buffer = sale_price * 0.03
packaging      = 0.00

total_fees = ebay_fee + listing_fee + vat_on_fees + returns_buffer + packaging
profit     = sale_price - supplier_price - total_fees - shipping_cost
margin     = profit / sale_price * 100
```

Default thresholds live in `backend/config.py` — `PROFIT_CONFIG`, `demand_min_30d: 30`, `demand_min_7d: 8` — and margin minimum defaults to 25% per filter set.

---

## Tech stack

| Layer              | Technology                                                         |
| ------------------ | ------------------------------------------------------------------ |
| Frontend           | Next.js 16, React 19, TypeScript 5.7, Tailwind CSS 4, Recharts     |
| Backend            | FastAPI, Uvicorn, Pydantic 2                                       |
| Scraping           | Playwright + playwright-stealth, BeautifulSoup 4                   |
| Supplier discovery | SerpApi (Google Shopping / Google web)                             |
| LLM                | Ollama (`llama3.1:8b`) locally, with a rule-based fallback         |
| Database           | SQLite via SQLAlchemy 2 — switch to PostgreSQL with `DATABASE_URL` |
| Export             | pandas, openpyxl                                                   |
| Extension          | Chrome MV3                                                         |
| Tests              | pytest (1163 passing), TypeScript typecheck, husky pre-commit      |

---

## Getting started

**Prerequisites:** Python 3.11+, Node 20+, and optionally [Ollama](https://ollama.com) with `llama3.1:8b`.

```bash
git clone https://github.com/agha-moutsim/hunting_system.git
cd hunting_system

# ── Backend ──────────────────────────────────────────────
cd backend
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
playwright install chromium
python -m uvicorn main:app --host 127.0.0.1 --port 8000

# ── Frontend (new terminal) ─────────────────────────────
cd frontend
npm install
npm run dev                      # http://localhost:3000
```

API documentation is served at **http://localhost:8000/docs**.

### Windows shortcut

From the repository root, two scripts manage both servers together and verify they actually bound their ports:

```powershell
.\start.ps1      # detach backend + frontend, wait for both to serve
.\check.ps1      # report status
.\stop.ps1       # stop the whole process tree
```

Equivalent npm scripts: `npm start`, `npm run check`, `npm stop`.

### Configuration

Copy `.env.example` to `.env` and fill in what you need:

| Variable                                | Required    | Purpose                                                                                     |
| --------------------------------------- | ----------- | ------------------------------------------------------------------------------------------- |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | **Yes**     | Listing and sold-data access — get keys at [developer.ebay.com](https://developer.ebay.com) |
| `SERPAPI_KEY`                           | Recommended | Supplier discovery via Google Shopping                                                      |
| `SCRAPINGBEE_API_KEY`                   | Optional    | Storefront verification                                                                     |
| `CJ_API_KEY` / `CJ_ACCESS_TOKEN`        | Optional    | Faster CJ Dropshipping path                                                                 |
| `DATABASE_URL`                          | Optional    | Defaults to SQLite; set for PostgreSQL                                                      |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL`      | Optional    | Local LLM endpoint and model                                                                |

`.env` is gitignored. Never commit it.

> **On optional keys:** without them the system still runs — it falls back to browser reads, marks those rows `verified via browser`, and reports a lower-confidence result rather than failing. Every optional path degrades honestly.

---

## Data model

Fifteen tables across four domains:

| Domain            | Tables                                                                |
| ----------------- | --------------------------------------------------------------------- |
| Analysis          | `products`, `demand_data`, `supplier_matches`, `analyses`, `verdicts` |
| Demand monitoring | `demand_snapshots`, `purchase_captures`                               |
| Tracking          | `tracked_products`, `price_history`, `price_alerts`                   |
| Watchlist         | `watchlist_items`, `saved_searches`, `search_results`                 |
| Reporting         | `sales`, `monthly_stats`                                              |

Filesystem SQLite by default — no server required to get started.

---

## Testing

```bash
npm test                              # backend suite
npm run typecheck                     # frontend types
npm --prefix frontend run build       # production build
```

The suite is regression-oriented: tests are named for the defect they pin, and several verify that a _specific_ failure mode stays fixed. A husky pre-commit hook runs lint, typecheck and the full suite, so a failing regression blocks the commit.

---

## Limitations

Stated plainly, because a tool that hides its limits is worse than one that declares them.

- **No authentication in v1.** The deployment model is a private link within a trusted group.
- **Supplier coverage is partial and honest about it.** Some retail sources are absent from the discovery index; those results simply do not appear rather than being substituted.
- **Scraping is inherently fragile.** Sites change markup and deploy new bot defences. Failures are surfaced as `unverified` with a reason, never as fabricated data.
- **The LLM is optional, not load-bearing.** On hosts without Ollama, analyses fall back to deterministic rules and still produce a verdict.
- **Demand figures can be `PENDING`.** Where eBay does not publish a reliable 7-day count, the system says so instead of estimating.

---

## License

No licence is granted for reuse. All rights reserved.

Interface icons from [Noun Project](https://nounproject.com).
