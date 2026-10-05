"""
eBay Hunter — Central Configuration

All thresholds, supplier definitions, fee percentages, and system settings.
Modify this file to adjust business rules without touching code.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# Paths
# ============================================================

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
SUPPLIERS_JSON = BASE_DIR / "suppliers.json"

# ============================================================
# Database (SQLite by default; set DATABASE_URL to override)
# ============================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{BASE_DIR / 'data' / 'ebay_hunter.db'}",
)

# ============================================================
# Ollama (Local LLM)
# ============================================================

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_TEMPERATURE = 0.1

# ============================================================
# eBay UK
# ============================================================

EBAY_UK_BASE = "https://www.ebay.co.uk"
EBAY_SOLD_SEARCH = (
    "{base}/sch/i.html?"
    "_nkw={query}"
    "&LH_Complete=1"
    "&LH_Sold=1"
    "&_sop=13"
    "&LH_PrefLoc=1"
)

# eBay Browse API (free tier: 5000 calls/day)
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET", "")
EBAY_MARKETPLACE = os.getenv("EBAY_MARKETPLACE", "EBAY_GB")

# Environment: "production" (real eBay) or "sandbox" (test data)
EBAY_ENVIRONMENT = os.getenv("EBAY_ENVIRONMENT", "production").lower()

if EBAY_ENVIRONMENT == "sandbox":
    EBAY_API_BASE = "https://api.sandbox.ebay.com"
else:
    EBAY_API_BASE = "https://api.ebay.com"

# ============================================================
# Filter Thresholds (Non-Negotiable)
# Price band is governed by CONSTRAINTS_PRICING.md (PR-1..PR-7).
# ============================================================

FILTERS = {
    # Price range (GBP) — DEFAULT; user-adjustable active range
    # (CONSTRAINTS_PRICING.md PR-5/PR-7), gate applied at all four layers.
    "price_min": 5.00,
    "price_max": 35.00,

    # Demand requirements (CONSTRAINTS.md C4)
    "demand_min_30d": 30,      # Minimum sold in last 30 days
    "demand_min_7d": 8,        # Minimum sold in last 7 days

    # Delivery targets (days) — ADVISORY only, never gates a verdict (C-new)
    "delivery_min": 3,
    "delivery_target_max": 8,

    # Profit requirements
    "margin_min": 25.0,         # Minimum profit margin percentage (on sale price)

    # Product filters
    # NOTE: "brand_filter": "vero" was removed on 2026-10-03 by product
    # decision. It had zero readers - the VeRO brand gate (CONSTRAINTS.md C5)
    # is NOT implemented, and a key that claims a check nobody performs is
    # worse than no key at all. See utils/vero.py and engine/decisions.py:
    # an extracted brand is still reported as an unverified row rather than
    # being quietly passed.
    "condition": "New",
    "buy_it_now": True,
    "uk_only": True,
}

# C10 — condition allow-list. Lives here (the leaf module) so BOTH the gate
# and the persistence layer can validate without importing each other.
ALLOWED_CONDITIONS = ("New",)

# C11 — every analysis surfaces up to 4 REAL eBay competitor stores.
# Sits here (not in the engine) so the cap is tunable without touching the
# discovery code, and so no renderer can hardcode its own number.
STORE_COUNT = 4

# C12 — up to 7 approved suppliers, and fewer is correct. This is a ceiling,
# never a target: a row exists only because its product was retrieved AND
# cleared the C14 match threshold. Nothing anywhere pads toward this number.
MAX_SUPPLIERS = 7

# ============================================================
# Profit Calculation
# ============================================================

PROFIT_CONFIG = {
    "ebay_fee_percent": 13.5,       # eBay final value fee (user's v1 model, C3)
    "listing_fee_percent": 0.03,    # Listing fee (C3)
    "vat_on_fees_percent": 20.0,    # UK VAT applied to eBay's fees (C3)
    "returns_buffer_percent": 3.0,  # Conservative returns estimate
    "packaging_cost": 0.0,          # Dropship = no packaging cost
}

# ============================================================
# Scraping
# ============================================================

SCRAPE_CONFIG = {
    "timeout": 30.0,
    "max_retries": 2,
    "retry_delay": 1.0,
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "accept_language": "en-GB,en;q=0.9",
}

# ============================================================
# Data Freshness (Reconcile Pattern)
# ============================================================

FRESHNESS_CONFIG = {
    "max_age_hours": 24,  # Data older than this is considered stale
}
