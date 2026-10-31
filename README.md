<div align="center">

<img src="assets/brand/hero.svg" width="100%" alt="The eBay Hunter wordmark: a pair of lime selection brackets around a white point, beside the name set in white on deep indigo.">

# eBay Hunter

**Sourcing intelligence and multi-marketplace analytics for eBay resellers.**

Turn a product idea into a sourcing decision in about 90 seconds — what it actually sells for, what it costs from approved suppliers, profit after eBay's fees, and a pass/fail verdict against rules you control.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js%2016-000000?logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React%2019-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript%205.7-3178C6?logo=typescript&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind%204-06B6D4?logo=tailwindcss&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-2EAD33?logo=playwright&logoColor=white)

![Tests](https://img.shields.io/badge/tests-1979%20passing-brightgreen)
![License](https://img.shields.io/badge/license-all%20rights%20reserved-lightgrey)

</div>

---

## Overview

eBay Hunter answers one question: **should I buy this and where from?**

It is architected for resellers sourcing high-velocity generic products across **eBay UK** (`ebay.co.uk`, default £5–£35 band) and **eBay Australia** (`ebay.com.au`, default A$0.99–A$50.00 band). It eliminates manual cross-referencing by evaluating real sold history, querying market-scoped supplier benches, computing net profit using official transcribed rate cards, and evaluating a deterministic verdict pipeline. A full analysis completes in roughly 90 seconds and surfaces an actionable decision backed by strict provenance tracking.

Two design principles run through every layer:

> **No fabricated values.** Every figure is either measured or explicitly labelled `Unverified`, together with the reason. A blocked supplier is reported as blocked — never silently replaced with a plausible-looking number.

> **Bounded execution.** Every stage has a hard time budget. Exceeding one degrades that stage to partial results and says so; it never hangs the request.

---

## Capabilities

|                                                                                                                                                                                        | Feature              | What it does                                                                                                                                   |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| <picture><source srcset="icons/readme-dark/noun_analyze_8392548.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_analyze_8392548.svg" width="26" alt=""></picture>       | **Analyze**          | The complete pipeline on a single product: listing data, sold history, supplier prices, brand and demand assessment, profit scorecard, verdict |
| <picture><source srcset="icons/readme-dark/noun_DeepDive_7968343.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_DeepDive_7968343.svg" width="26" alt=""></picture>     | **Deep Search**      | Two research speeds. _Fast_ returns real eBay sold data in ~20s with no LLM. _Full_ adds deeper analysis inside a 2-minute budget              |
| <picture><source srcset="icons/readme-dark/noun_categories_8378322.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_categories_8378322.svg" width="26" alt=""></picture> | **Category Hunter**  | Scan an entire eBay category against your filters, then resolve supplier matches for the hits                                                  |
| <picture><source srcset="icons/readme-dark/noun_bulk_7761163.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_bulk_7761163.svg" width="26" alt=""></picture>             | **Bulk**             | Run a list of queries through the pipeline in one pass, with per-row status                                                                    |
| <picture><source srcset="icons/readme-dark/noun_Pricing_8447584.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_Pricing_8447584.svg" width="26" alt=""></picture>       | **Price Tracker**    | Follow listings over time, with price-drop alerts                                                                                              |
| <picture><source srcset="icons/readme-dark/noun_wishlist_8254557.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_wishlist_8254557.svg" width="26" alt=""></picture>     | **Watchlist**        | Save searches and re-run them individually or in bulk                                                                                          |
| <picture><source srcset="icons/readme-dark/noun_dashboard_8450002.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_dashboard_8450002.svg" width="26" alt=""></picture>   | **Dashboard**        | Sales KPIs, revenue and profit trends, category breakdowns                                                                                     |
| <picture><source srcset="icons/readme-dark/noun_History_8203921.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_History_8203921.svg" width="26" alt=""></picture>       | **History**          | Every past analysis, replayable with its verdict and provenance intact                                                                         |
| <picture><source srcset="icons/readme-dark/noun_Pricing_8447584.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_Pricing_8447584.svg" width="26" alt=""></picture>       | **Fee Calculator**   | Standalone reverse margin engine evaluating official UK and AU rate cards, buyer region fees, and break-even targets                           |
| <picture><source srcset="icons/readme-dark/noun_analyze_8392548.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_analyze_8392548.svg" width="26" alt=""></picture>       | **Title Helper**     | Algorithmic title scorer analyzing keyword density, character limits, and search rank potential                                                |
| <picture><source srcset="icons/readme-dark/noun_DeepDive_7968343.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_DeepDive_7968343.svg" width="26" alt=""></picture>     | **Market Churn**     | Listing age distribution and velocity tracker measuring active vs sold saturation ratios                                                       |
| <picture><source srcset="icons/readme-dark/noun_dashboard_8450002.svg" media="(prefers-color-scheme: dark)"><img src="icons/noun_dashboard_8450002.svg" width="26" alt=""></picture>   | **Seller Footprint** | Competitor concentration mapping, identifying dominant store handles and listing clusters                                                      |


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
                        │  analysis_pipeline.py   │  ◄── the single source of truth
                        │  6 sequential stages    │      for the API layer
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

## Verification, matching, and provenance

Most sourcing tools show an unverified number and let the user assume it is true. eBay Hunter labels every factual field with **how it was obtained**, records an audit trail, and refuses to fabricate missing values.

| Label        | Meaning                                                                      |
| ------------ | ---------------------------------------------------------------------------- |
| `verified`   | Read directly from a verified API payload, parsed page, or browser capture   |
| `estimated`  | Derived by a transparent, stated algorithm (e.g., 30d sold listing cadence)  |
| `unverified` | Data could not be validated — _the underlying reason travels with the field_ |
| `ai_insight` | Produced by LLM semantic evaluation. Structurally prohibited from numbers    |

### Deterministic product matching (C14)

Similar titles are not proof of identical products. Every candidate supplier listing is evaluated through `backend/engine/match.py` against a multi-modal deterministic scoring engine:

1. **Token Overlap & Normalization:** Strips stop words, normalizes technical dimensions, and evaluates title token intersection weighted by term specificity.
2. **Price Plausibility Bounding:** Rejects accessory, part, or mismatch anomalies where supplier unit pricing falls outside a plausible ratio relative to the target item.
3. **Perceptual Image Hashing (`pHash`):** Compares perceptual hash Hamming distances when both listing images are accessible, verifying visual packaging and form factor.
4. **Hard Score Thresholding:** Match scores are computed dynamically (never static constants). Candidates scoring below threshold are discarded or marked `unverified` (_"no confirmed match"_). Padding supplier counts is strictly forbidden.

### Passive browser capture pipeline (`extension/`)

While eBay's public search API yields 30-day sold listings, 7-day high-resolution velocity is verified using the Chrome MV3 passive extension:

- Captures verified Item Purchase History from live authenticated listing pages.
- Transmits cryptographic session-safe payload to `POST /api/extension/capture`.
- Upgrades demand provenance from `estimated` to `verified` with an immutable `captured_at` timestamp.
- Enforces a 24-hour staleness TTL, ensuring expired captures degrade to unverified status rather than serving outdated demand signals.

---

## Suppliers and market benches

The supplier bench is a first-class marketplace property. Sourcing queries instantiate only the active bench configured for the target marketplace:

| Supplier            | UK Bench    | AU Bench    | Access path & implementation                                               |
| ------------------- | ----------- | ----------- | -------------------------------------------------------------------------- |
| **AliExpress**      | ✅ Enabled  | ✅ Enabled  | Direct API when keyed; stealth Playwright fallback with localized AliGate  |
| **CJ Dropshipping** | ✅ Enabled  | ✅ Enabled  | Official API when keyed; Playwright automation fallback                    |
| **B&Q**             | ✅ Enabled  | ⛔ Disabled | Playwright + Google Shopping discovery (UK domestic retailer)              |
| **Toolstation**     | ✅ Enabled  | ⛔ Disabled | Playwright + Google Shopping discovery (UK domestic retailer)              |
| **Joybuy UK**       | ⚠️ Link-out | ⛔ Disabled | Google web index scraper (zero direct bot challenge bypass); UK only       |
| **Amazon UK**       | ⛔ Disabled | ⛔ Disabled | PA-API 5 deprecated; terms prohibit aggregating catalog data for analytics |
| **GoDropship**      | ⛔ Disabled | ⛔ Disabled | Domain parked / inactive supplier                                          |

Entries in `backend/suppliers.json` document active status, access rationale, and `revisit_if` triggers.

### Currency isolation and FX policy

To eliminate phantom margins caused by unhedged FX rate assumptions, pricing enforces strict currency boundary isolation:

- **Targeted AliGate Routing:** AliExpress requests specify market-specific locales (`en_GB`/`GBP` for UK, `en_AU`/`AUD` for Australia).
- **CJ Dropshipping Policy:** CJ quotes denominated in USD pass through a pinned 0.79 USD→GBP FX path for UK calculations. In the AU pipeline, unhedged USD supplier rows are tagged `USD` and excluded from AUD margin comparison with an explicit explanatory notice rather than silently converted.
- **Strict Tagging:** Any supplier row without an explicit verified currency tag is rejected from margin gates — currency is never inferred.

---

## Business rules

| Rule           | Threshold                                                                                                         |
| -------------- | ----------------------------------------------------------------------------------------------------------------- |
| Buy price      | UK: £5 – £35 default · AU: A$0.99 – A$50.00 default, user-adjustable (supplier prices never gated)                |
| Minimum margin | ≥ 25% of sale price (configurable per search filter)                                                              |
| Demand         | UK: ≥ 30 sold / 30d, ≥ 8 sold / 7d · AU: ≥ 15 sold / 30d, ≥ 10 sold / 7d (7d verified via purchase history)       |
| Condition      | New only — non-New listings are refused at query time before supplier or LLM spend                                |
| Delivery       | Advisory — compares marketplace estimate against supplier stated transit; never flips verdict                     |
| Brand          | Generic products only — registered VeRO brands fail; unbranded/generic pass; ambiguous hold at `PENDING`          |
| Fees           | Official transcribed rate card (`uk-rate-card-2026-09-30` / `au-rate-card-2026-10-09`) + 3% seller returns buffer |
| Packaging      | £0.00 / A$0.00 — dropship fulfilment model carries zero unit packaging overhead                                   |

### Fee engine and rate cards

Rather than relying on flat percentage approximations, fee calculations are driven by deterministic rate cards transcribed from verified official schedule snapshots and audited against published worked examples:

- **eBay UK (`uk-rate-card-2026-09-30`):** Models category-specific Final Value Fees (6.9%–14.9%) with tiered maxima, fixed per-order fees (£0.30 for orders ≤ £10, £0.40 above), 0.35% regulatory operating fee, 20% VAT applied to fees (recoverable for VAT-registered entities), and distinct private seller exemptions.
- **eBay Australia (`au-rate-card-2026-10-09`):** Implements dual seller branches:
  - _eBay Pro (Business):_ Four subscription plans (Basic to Enterprise), Tier 1–4 category rates, per-order fee (A$0.33), over-A$4,000 step-down, and 1.1% international transaction fees.
  - _Free Selling (Individual):_ 0% FVF, 3% international transaction fee, with mandatory label requirements verified as predicates rather than fees. GST is handled as inclusive per ATO requirements and never double-levied.
- **Unified Mathematical Authority:** All pipeline stages, batch evaluation, and the interactive UI calculator execute through `backend/engine/fees.py` (`sale_outcome()`), guaranteeing identical fee, net profit, and margin figures across every touchpoint by construction.

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
| Tests              | pytest (1979 passing), TypeScript typecheck, husky pre-commit      |

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
