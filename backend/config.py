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

# Raised from 45s on 2026-10-03 by product decision: at 45s the local model
# was still finishing long analyses, and the timeout threw away the brand and
# condition extraction that supplier matching depends on. Deep Search is
# interactive, so waiting on the rare slow call beats losing the analysis.
#
# ONE constant for a reason: this value used to be written as a literal `45.0`
# in four separate places (ollama_client, analysis_pipeline, deep_search's
# wrapper and deep_search's call site), which is how the four drifted apart in
# the first place. Override with OLLAMA_TIMEOUT_S in .env - no code edit.
#
# Note this is NOT the scraper timeout (SCRAPER_TIMEOUT_S below) and must not
# be changed with it.
OLLAMA_TIMEOUT_S = float(os.getenv("OLLAMA_TIMEOUT_S", "120"))

# How long Ollama keeps the model in RAM after its last use, in seconds.
# -1 means forever.
#
# Measured on this machine (2026-10-08): llama3.1:8b is 4.9 GB and takes
# ~21.2s to load, then generates at ~8.6 tok/s. Ollama's default is to
# unload five minutes after the last request, so any analysis after an
# idle gap paid 21.2s before it could generate a single token — on a box
# whose LLM already cannot finish inside the route budget. Keeping it
# resident moves that cost to once per process instead of once per gap.
#
# Override with OLLAMA_KEEP_ALIVE in .env. One constant because the two
# call sites (llm/ollama_client and deep_search._ollama_generate) do not
# share a client and would otherwise drift.
OLLAMA_KEEP_ALIVE = int(os.getenv("OLLAMA_KEEP_ALIVE", "-1"))

# Maximum tokens the model may generate for one analysis.
#
# Measured on this machine (2026-10-08) with each path's real payload:
#
#   Analyze      203 tokens, 57.5s, done_reason=stop
#   Deep Search  411 tokens, 149.7s, done_reason=stop
#
# so num_predict is NOT a speed setting on either happy path - the model
# stops on its own. It is the ceiling on a runaway answer, and it is set
# by the LARGER consumer: 350 would have truncated Deep Search's 411
# mid-JSON, and a truncated JSON is not a slower answer, it is no answer
# (the parser raises and the whole LLM stage is discarded).
#
# 500 gives Deep Search headroom over 411 while cutting its worst case
# from ~291s (at the old literal 800) to ~185s. Analyze stops at 203 and
# is unaffected.
#
# ONE constant because the two call sites (llm/ollama_client and
# deep_search._ollama_generate) do not share a client, and they had
# already drifted to 500 and 800 - the same failure that put a literal
# 45.0 in four places before OLLAMA_TIMEOUT_S.
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "500"))




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

# ============================================================
# Marketplace registry (Phase J)
# ============================================================
#
# One record per eBay marketplace this app may query. The Browse routes read
# the marketplace id, site base, currency and delivery country from here;
# nothing else hardcodes EBAY_GB or a £ sign.
#
# `fee_table` is the engine/fees.py key that prices a sale in that market.
# Only the UK has a table. None is deliberate: a UK rate must never be applied
# to a USD/EUR/AUD/CAD sale. The API refuses to price those markets instead.
#
# `deals_url` is marketplace-specific. Each URL below returned HTTP 200 on
# 2026-10-21, and the cards were read from the returned page (UK 72, US 21,
# DE 80, AU 76, CA 57). eBay US redirects /deals to /globaldeals, whose cards
# use the nested shape `parse_deals_page` also handles. eBay Ireland's /deals
# redirected into eBay's splashui challenge, not the deals board, so EBAY_IE
# is deliberately absent rather than offered with an unverified URL.
#
# `deals_checked_at` is evidence, not a promise: eBay can bot-wall the page
# later, and the deals refresh reports that failure instead of inventing zero
# cards.
MARKETPLACES = {
    "EBAY_GB": {
        "id": "EBAY_GB",
        "label": "United Kingdom",
        "country_code": "GB",
        "site_base": "https://www.ebay.co.uk",
        "currency": "GBP",
        "currency_symbol": "£",
        "delivery_country": "GB",
        "fee_table": "uk-rate-card-2026-09-30",
        "fee_calculator_ready": True,
        "deals_url": "https://www.ebay.co.uk/deals",
        "deals_http_status": 200,
        "deals_checked_at": "2026-10-21",
        "offered": True,
    },
    "EBAY_US": {
        "id": "EBAY_US",
        "label": "United States",
        "country_code": "US",
        "site_base": "https://www.ebay.com",
        "currency": "USD",
        "currency_symbol": "$",
        "delivery_country": "US",
        "fee_table": None,
        "fee_calculator_ready": False,
        "deals_url": "https://www.ebay.com/deals",
        "deals_http_status": 200,
        "deals_checked_at": "2026-10-21",
        "offered": True,
    },
    "EBAY_DE": {
        "id": "EBAY_DE",
        "label": "Germany",
        "country_code": "DE",
        "site_base": "https://www.ebay.de",
        "currency": "EUR",
        "currency_symbol": "€",
        "delivery_country": "DE",
        "fee_table": None,
        "fee_calculator_ready": False,
        "deals_url": "https://www.ebay.de/deals",
        "deals_http_status": 200,
        "deals_checked_at": "2026-10-21",
        "offered": True,
    },
    "EBAY_AU": {
        "id": "EBAY_AU",
        "label": "Australia",
        "country_code": "AU",
        "site_base": "https://www.ebay.com.au",
        "currency": "AUD",
        "currency_symbol": "A$",
        "delivery_country": "AU",
        "fee_table": "au-rate-card-2026-10-09",
        "fee_calculator_ready": False,
        "deals_url": "https://www.ebay.com.au/deals",
        "deals_http_status": 200,
        "deals_checked_at": "2026-10-21",
        "offered": True,
    },
    "EBAY_CA": {
        "id": "EBAY_CA",
        "label": "Canada",
        "country_code": "CA",
        "site_base": "https://www.ebay.ca",
        "currency": "CAD",
        "currency_symbol": "C$",
        "delivery_country": "CA",
        "fee_table": None,
        "fee_calculator_ready": False,
        "deals_url": "https://www.ebay.ca/deals",
        "deals_http_status": 200,
        "deals_checked_at": "2026-10-21",
        "offered": True,
    },
}

#: Used when a caller sends nothing. EBAY_MARKETPLACE stays the environment
#: override for existing deployments that set it explicitly.
DEFAULT_MARKETPLACE = (
    EBAY_MARKETPLACE if EBAY_MARKETPLACE in MARKETPLACES else "EBAY_GB"
)

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
    # The v1 model's rates (CONSTRAINTS.md C3). Live fee arithmetic reads the
    # tables in engine/fees.py; these pins stay so pre-switch numbers remain
    # reproducible and independently tested.
    "ebay_fee_percent": 13.5,       # eBay final value fee (user's v1 model, C3)
    "listing_fee_percent": 0.03,    # Listing fee (C3)
    "vat_on_fees_percent": 20.0,    # UK VAT applied to eBay's fees (C3)
    "returns_buffer_percent": 3.0,  # Conservative returns estimate
    "packaging_cost": 0.0,          # Dropship = no packaging cost
}

# ============================================================
# Seller profile - the seller side of every money question (Phase D)
# ============================================================
# The pipeline verdict and the fee calculator must answer the same question
# ("what does THIS seller make on this listing?"), so the seller side lives in
# one place too. Fee RATES never live here - they come from the tables in
# engine/fees.py; `fee_table: None` means "use the engine's ACTIVE_TABLE", so
# refreshing the card never means editing this file.

SELLER_PROFILE = {
    "seller_type": "business",  # business | private (engine refuses others)
    "uk_resident": True,        # matters to the private-page schedule
    "vat_registered": False,    # True -> VAT on eBay's fees is recoverable
    "promoted_rate": 0.0,       # the ad rate actually being paid, e.g. 2.0
    "category": None,           # per-listing; None -> the engine's stated default
    "fee_table": None,          # None -> engine/fees.ACTIVE_TABLE (the card)
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
