# eBay Hunter

Deep research system for eBay UK product sourcing. Scrapes real data from eBay and 7 approved suppliers, analyzes with local AI, applies fixed business rules, and outputs detailed scorecards.

## Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Ollama (for local LLM)

## Quick Start

```bash
# 1. Create database
psql -U postgres -c "CREATE DATABASE ebay_hunter;"

# 2. Setup environment
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
playwright install chromium

# 3. Configure
copy .env.example .env
# Edit .env with your PostgreSQL password

# 4. Install Ollama + model
ollama pull llama3.1:8b

# 5. Run
uvicorn api.main:app --reload --port 8000
streamlit run app.py         # New terminal
```

## Project Structure

```
ebay-hunter/
├── app.py              # Streamlit dashboard
├── config.py           # All configuration
├── suppliers.json      # Supplier catalog
├── requirements.txt
├── .env.example
│
├── api/                # FastAPI backend
├── scrapers/           # eBay + supplier scrapers
│   └── suppliers/      # One scraper per supplier
├── llm/                # Ollama LLM analysis
├── engine/             # Filters, profit calc, scorecard
├── db/                 # PostgreSQL models + queries
└── tests/              # Tests
```

## Architecture

- **Catalog Pattern**: `suppliers.json` defines approved suppliers
- **Ledger Pattern**: PostgreSQL tracks every analysis
- **Render Pattern**: Deterministic scorecard generation
- **Reconcile Pattern**: Data freshness checks (24h)
