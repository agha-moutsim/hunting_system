# eBay Hunter 🎯

Product sourcing intelligence system for eBay UK resellers.

**Scrapes eBay → Finds Suppliers → AI Analysis → Profit Calculation → Scorecard**

## What It Does

1. **Search eBay UK** for products (via Browse API)
2. **Search 7 suppliers** in parallel (AliExpress, Amazon UK, CJ, GoDropship, Joybuy, B&Q, Toolstation)
3. **LLM Analysis** — AI judges brand, demand, supplier type
4. **Business Rules** — 5 filters (price, demand, brand, delivery)
5. **Profit Calculator** — eBay fees + returns buffer
6. **Scorecard** — PASS/FAIL verdict with full breakdown

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Streamlit Dashboard                       │
│                  (app.py - Web UI)                          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Pipeline Orchestrator                     │
│                 (pipeline.py - 7 steps)                     │
└──┬────────┬────────┬────────┬────────┬────────┬────────────┘
   │        │        │        │        │        │
   ▼        ▼        ▼        ▼        ▼        ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
│eBay  │ │Suppl-│ │ LLM  │ │Filter│ │Profit│ │  DB  │
│API   │ │iers  │ │      │ │Engine│ │Calc  │ │      │
└──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘
   │        │        │        │        │        │
   │        ▼        │        │        │        │
   │   ┌─────────┐   │        │        │        │
   │   │ 7 scrapers  │        │        │        │
   │   │ running  │   │        │        │        │
   │   │ parallel │   │        │        │        │
   │   └─────────┘   │        │        │        │
   │                 ▼        ▼        ▼        ▼
   │          ┌──────────────────────────────────┐
   └──────────│         PostgreSQL DB            │
              └──────────────────────────────────┘
```

## File Structure

```
ebay-hunter/
├── app.py                    # Streamlit dashboard (web UI)
├── pipeline.py               # Orchestrator (runs all steps)
├── cli.py                    # CLI for quick testing
├── config.py                 # All settings (thresholds, URLs)
├── suppliers.json            # List of 7 approved suppliers
├── mock_data.py              # Mock data for testing
├── profit_calc.py            # Standalone profit calculator
├── batch.py                  # Batch analysis
├── export.py                 # CSV/JSON export
├── .env                      # Secrets (DB password, API keys)
├── .env.example              # Template for .env
├── requirements.txt          # Python dependencies
│
├── scrapers/
│   ├── base.py               # Base class (Playwright + stealth)
│   ├── ebay.py               # eBay scraper (Browse API)
│   ├── aliexpress.py         # AliExpress scraper
│   ├── amazon_uk.py          # Amazon UK scraper
│   ├── cjdropshipping.py     # CJ Dropshipping scraper
│   ├── godropship.py         # GoDropship scraper
│   ├── joybuy.py             # Joybuy scraper
│   ├── bandq.py              # B&Q scraper
│   └── toolstation.py        # Toolstation scraper
│
├── llm/
│   ├── analyzer.py           # AI analysis wrapper
│   ├── ollama_client.py      # Ollama API client
│   └── prompts.py            # AI prompts
│
├── engine/
│   ├── decisions.py          # Business rules (5 filters)
│   ├── profit.py             # Profit calculator
│   └── scorecard.py          # Scorecard formatter
│
├── db/
│   ├── database.py           # PostgreSQL connection
│   ├── models.py             # 5 database tables
│   ├── queries.py            # Save/load functions
│   └── init_db.py            # DB setup script
│
└── utils/
    ├── rate_limiter.py       # Rate limiting
    ├── health_check.py       # Scraper health check
    ├── history.py            # Search history
    ├── bookmarks.py          # Product bookmarks
    ├── notifications.py      # Price drop alerts
    ├── price_tracker.py      # Price tracking
    ├── freshness.py          # Data freshness
    ├── supplier_score.py     # Supplier reliability
    ├── profit_trends.py      # Profit trends
    └── theme.py              # Dark/light theme
```

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 14+
- Ollama (for local LLM)

### Setup

```bash
# 1. Clone
git clone https://github.com/agha-moutsim/hunting_system.git
cd ebay-hunter

# 2. Create database
psql -U postgres -c "CREATE DATABASE ebay_hunter;"

# 3. Setup environment
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
playwright install chromium

# 4. Configure
copy .env.example .env
# Edit .env with your PostgreSQL password and eBay API keys

# 5. Install Ollama + model
ollama pull llama3.1:8b

# 6. Run
streamlit run app.py
```

## Getting eBay API Keys (Free)

1. Go to https://developer.ebay.com
2. Create account → Apps → Create new app
3. Copy **Client ID** and **Client Secret**
4. Add to `.env`:
```
EBAY_CLIENT_ID=your_client_id_here
EBAY_CLIENT_SECRET=your_client_secret_here
```

## Usage

### Web Dashboard
```bash
streamlit run app.py
# Open http://localhost:8501
```

### CLI
```bash
# Search eBay
python cli.py search "wireless earbuds"

# Full analysis
python cli.py analyze "wireless earbuds"

# Calculate profit
python cli.py profit 15.99 8.50

# List suppliers
python cli.py suppliers

# System status
python cli.py status
```

## Business Rules

| Filter | Threshold | Description |
|--------|-----------|-------------|
| Price | £5-£25 | Must be in this range |
| Demand (30d) | ≥10 sold | Must have demand |
| Demand (7d) | ≥1 sold | Recent activity |
| Brand | Generic only | No trademarked items |
| Delivery | ≤8 days | Target delivery time |

## Profit Formula

```
Profit = eBay Price - Supplier Price - eBay Fee (12.8%) - Returns Buffer (3%)
```

## Database Tables

1. **products** — eBay listings
2. **demand_data** — Sales counts, prices
3. **supplier_matches** — Supplier comparisons
4. **analyses** — LLM verdicts
5. **verdicts** — Pass/fail decisions

## GitHub Commits

```
73436ab Fix: Show clear error when eBay API keys are missing
15aed79 feat: Phase 8-9 — Streamlit dashboard + pipeline orchestrator
8b9fd16 feat: Phase 5-7 — LLM analyzer, decision engine, DB operations
57c53a8 feat: Phase 4 — 7 supplier scrapers
c86f427 feat: Phase 2-3 — DB models, eBay scraper
2325964 Phase 1: Project setup
```

## License

Private — eBay Hunter
