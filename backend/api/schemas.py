"""Pydantic request/response models."""

from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Analyze ─────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    query: str = Field(..., min_length=1, description="eBay search query or listing URL")
    is_url: bool = False
    filters: Optional[dict] = None


# ── Deep Search ────────────────────────────────────────────────

class DeepSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)


class BulkRequest(BaseModel):
    queries: list[str] = Field(..., min_length=1)


# ── Hunter ──────────────────────────────────────────────────────

class HunterScanRequest(BaseModel):
    category: str = Field(..., min_length=1)
    price_min: float = 5.0
    price_max: float = 25.0
    max_results: int = Field(50, ge=1, le=100)


class HunterLookupRequest(BaseModel):
    products: list[dict] = Field(..., min_length=1)
    filters: Optional[dict] = None


# ── Tracker ─────────────────────────────────────────────────────

class TrackerCreate(BaseModel):
    product_name: str = Field(..., min_length=1)
    ebay_url: str = ""
    ebay_price: float = 0.0
    target_price: float = 0.0
    supplier_price: float = 0.0
    supplier_url: str = ""
    supplier_name: str = ""


# ── Watchlist ───────────────────────────────────────────────────

class WatchlistCreate(BaseModel):
    product_name: str = Field(..., min_length=1)
    ebay_url: str = ""
    ebay_price: float = 0.0
    target_price: float = 0.0
    supplier_price: float = 0.0
    supplier_url: str = ""
    supplier_name: str = ""
    notes: str = ""


class SearchCreate(BaseModel):
    search_name: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    category: str = ""
    price_min: float = 5.0
    price_max: float = 25.0
    min_margin: float = 25.0
    auto_run: bool = True


# ── Sales / Dashboard ──────────────────────────────────────────

class SaleCreate(BaseModel):
    product_name: str = Field(..., min_length=1)
    category: str = ""
    sale_price: float = Field(..., gt=0)
    supplier_cost: float = 0.0
    shipping_cost: float = 0.0
    ebay_fees: float = 0.0
    quantity: int = Field(1, ge=1)
    sale_date: Optional[str] = None  # YYYY-MM-DD
    buyer_location: str = ""
    notes: str = ""


# ── Export ──────────────────────────────────────────────────────

class ExportResultRequest(BaseModel):
    """Body = a DeepSearchResult dict (from POST /api/deep-search)."""
    result: dict[str, Any]
