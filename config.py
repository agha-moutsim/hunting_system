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
# Database (PostgreSQL)
# ============================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/ebay_hunter"
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
# ============================================================

FILTERS = {
    # Price range (GBP)
    "price_min": 5.00,
    "price_max": 25.00,

    # Demand requirements
    "demand_min_30d": 10,       # Minimum sold in last 30 days
    "demand_min_7d": 1,         # Minimum sold in last 7 days
    "demand_strong_30d": 30,    # Threshold for slow delivery exception

    # Delivery targets (days)
    "delivery_min": 3,          # Minimum delivery days
    "delivery_target_max": 8,   # Preferred maximum
    "delivery_exception_max": 25,  # Max for high-demand products

    # Profit requirements
    "margin_min": 25.0,         # Minimum profit margin percentage

    # Product filters
    "brand_filter": "generic_only",  # "generic_only" = reject branded items
    "condition": "New",
    "buy_it_now": True,
    "uk_only": True,
}

# ============================================================
# Profit Calculation
# ============================================================

PROFIT_CONFIG = {
    "ebay_fee_percent": 12.8,       # eBay final value fee
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
