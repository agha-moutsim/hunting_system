"""Pydantic request/response models."""

from datetime import date
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
    """One sale the user declares.

    Every money field is REQUIRED. A missing cost cannot be read as zero: that
    would turn an unknown fee into profit. A genuine zero is still accepted,
    but the caller has to state it. `sale_date` is required for the same
    reason: defaulting to today would move a real sale into the wrong month.
    """

    product_name: str = Field(..., min_length=1, max_length=500)
    category: str = ""
    sale_price: float = Field(..., gt=0)
    supplier_cost: float = Field(..., ge=0)
    shipping_cost: float = Field(..., ge=0)
    ebay_fees: float = Field(..., ge=0)
    quantity: int = Field(1, ge=1)
    sale_date: date
    buyer_location: str = ""
    notes: str = ""

    @field_validator("product_name")
    @classmethod
    def _product_name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("product_name must not be blank")
        return cleaned


class SalesCsvImport(BaseModel):
    """The text of a CSV file, plus the name for the report.

    The browser reads the file and posts its text, which keeps the API free of
    a multipart dependency while still giving the user a normal file picker.
    """

    csv: str = Field(..., min_length=1, max_length=5_000_000)
    filename: str = ""


# ── Export ──────────────────────────────────────────────────────

class ExportResultRequest(BaseModel):
    """Body = a DeepSearchResult dict (from POST /api/deep-search)."""
    result: dict[str, Any]


# ── Provenance ──────────────────────────────────────────────────

#: The origins a STORED figure can carry, as tokens rather than prose. The UI
#: owns the words (see frontend/lib/fieldProvenance.ts); this end owns the fact.
#: An origin is named by the thing that produced the number, so a badge can
#: never be chosen by which slot the number happens to sit in.
ORIGIN_PURCHASE_HISTORY = "purchase_history"


class SourcedFigure(BaseModel):
    """One measured number plus the two facts that decide what it is worth.

    `value` is what was actually read. None means "not read" — never 0, because
    0 is a real measurement: a free-postage shipping cost is a measured 0.00.

    `origin` names WHAT produced the number, as a token the UI maps to one badge
    and one sentence. It is None when a row holds a figure whose source was
    never recorded — the honest answer for anything stored before this field
    existed. Inventing a source for such a row would be a fabricated citation,
    which is the defect this whole provenance layer exists to prevent.

    `observed_at` is when the SOURCE observed the figure, which is not when the
    analysis ran. The purchase-history capture behind a verified sold figure can
    be a day old, and a screen saying "read just now" about it would be the same
    class of error as counting a live listing as a sale. Serialised as ISO-8601
    ending in Z: the payload's older timestamps are naive because that is what
    SQLite returned and the client patches them, but a new field has no reason
    to inherit that ambiguity.
    """

    value: Any = None
    origin: Optional[str] = None
    observed_at: Optional[str] = None


# ── Fee calculator ──────────────────────────────────────────────

class FeeCalculateRequest(BaseModel):
    """One fee calculation for POST /api/fees/calculate.

    Forward mode: send `sale_price` for the fee breakdown and (with a
    supplier) profit. Reverse mode: send `target_margin` instead and the
    engine solves for the price that reaches it.

    The seller side falls back to config.SELLER_PROFILE field by field, so a
    client that sends nothing extra gets exactly what the pipeline verdict
    would compute. `postage_paid = 0.0` means UNKNOWN, not free (C1): the
    result states when the profit is a ceiling.
    """

    sale_price: Optional[float] = None
    target_margin: Optional[float] = None

    postage_charged: float = 0.0
    postage_paid: float = 0.0
    category: Optional[str] = None
    promoted_rate: Optional[float] = None
    seller_type: Optional[str] = None
    uk_resident: Optional[bool] = None
    vat_registered: Optional[bool] = None
    listing_fee: float = 0.0
    buyer_region: str = "uk"
    fee_table: Optional[str] = None

    supplier_cost: Optional[float] = None
    risk_buffer_percent: Optional[float] = None
    packaging_cost: Optional[float] = None
