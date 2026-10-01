"""Pydantic request/response models."""

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


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
    # REGRESSION-001: a blank or whitespace-only search used to be accepted and
    # then silently became the Electronics category. Reject it here so the
    # user is told, rather than being shown a category they never asked for.
    category: str = Field(..., min_length=1)

    @field_validator("category")
    @classmethod
    def _category_must_have_words(cls, v: str) -> str:
        cleaned = " ".join(str(v or "").split())
        if not cleaned:
            raise ValueError(
                "Enter a search term or pick a category"
            )
        return cleaned

    # None = "use the active range" (resolved server-side); a value the
    # client does send is validated before use (PR-5/PR-7).
    price_min: Optional[float] = None
    price_max: Optional[float] = None
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
    # None = "use the ACTIVE range" (resolved server-side) — never baked
    # config defaults; a sent value must form a sane range (PR-5/PR-7).
    price_min: Optional[float] = None
    price_max: Optional[float] = None
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
