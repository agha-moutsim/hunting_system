"""Export endpoints — CSV / JSON downloads."""

import io
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.schemas import ExportResultRequest
from engine.price_gate import band_label, in_band

router = APIRouter()
logger = logging.getLogger(__name__)

# eBay-side price keys gated by the active range (PR-1 figure types 1/3).
# Supplier keys (item_cost, best_supplier_price) are NEVER gated (PR-1).
_EXPORT_NUMERIC_PRICE_KEYS = (
    "price", "ebay_avg_price",
    "ebay_price_min", "ebay_price_max", "ebay_price_median",
)


def _band_gate_result(payload: dict) -> dict:
    """Display-time gate for client-supplied export payloads (PR-2 layer 4).

    eBay-side scalar price fields become null when out of the active range
    and the exclusion note is attached (PR-4) — null, never a fabricated 0
    (C1: a zeroed price reads as a real figure). Supplier rows and supplier
    prices pass through untouched — they are never range-gated (PR-1).
    """
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    notes = []

    for key in _EXPORT_NUMERIC_PRICE_KEYS:
        val = out.get(key)
        if isinstance(val, (int, float)) and val and not in_band(val):
            notes.append(f"{key} \u00a3{val:.2f} removed (outside {band_label()} range)")
            out[key] = None

    # Nested price range statistics (eBay-side)
    rng = out.get("ebay_price_range")
    if isinstance(rng, dict):
        for stat in ("min", "max", "avg", "median"):
            v = rng.get(stat)
            if isinstance(v, (int, float)) and v and not in_band(v):
                notes.append(f"eBay_price_range.{stat} £{v:.2f} removed (outside {band_label()} range)")
                rng[stat] = None

    if notes:
        existing = out.get("band_notes")
        out["band_notes"] = (f"{existing}; " if existing else "") + "; ".join(notes)
    return out


class _R:
    """Adapter so exporters can consume a plain (possibly partial) dict.

    Missing attributes resolve to None instead of raising, so a partial
    payload exports blank cells rather than a 500.
    """

    def __init__(self, d: dict):
        for k, v in d.items():
            setattr(self, k, v)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return None


def _csv_response(content: str, filename: str):
    buf = io.StringIO(content)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _json_response(content: str, filename: str):
    buf = io.StringIO(content)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/csv")
def export_csv(type: str = "sales"):
    """Export sales history as CSV. type=sales"""
    if type != "sales":
        raise HTTPException(status_code=400, detail="type must be 'sales' for GET; use POST for analysis")

    from dashboard.sales import get_sales

    sales = get_sales(limit=10000)

    import csv

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date", "Product", "Category", "Sale Price", "Cost",
        "Shipping", "Fees", "Profit", "Margin %", "Qty", "User Declared",
    ])
    for s in sales:
        writer.writerow([
            (s["sale_date"] or "")[:10],
            s["product_name"],
            s["category"],
            s["sale_price"],
            s["supplier_cost"],
            s["shipping_cost"],
            s["ebay_fees"],
            s["profit"],
            s["margin_percent"],
            s["quantity"],
            "yes",
        ])

    return _csv_response(output.getvalue(), "sales_history.csv")


@router.get("/export/json")
def export_json(type: str = "sales"):
    """Export sales history as JSON. type=sales"""
    if type != "sales":
        raise HTTPException(status_code=400, detail="type must be 'sales' for GET; use POST for analysis")

    from dashboard.sales import get_sales
    import json

    sales = get_sales(limit=10000)
    return _json_response(
        json.dumps(sales, indent=2, default=str),
        "sales_history.json",
    )


@router.post("/export/csv")
def export_analysis_csv(req: ExportResultRequest):
    """Export a deep-search result as CSV. Body: {\"result\": {...}}"""
    from export.csv_export import export_to_csv

    try:
        csv_text = export_to_csv(_R(_band_gate_result(req.result)))
    except Exception as e:
        logger.exception("CSV export failed")
        raise HTTPException(status_code=500, detail=str(e))

    return _csv_response(csv_text, "ebay_hunter_analysis.csv")


@router.post("/export/json")
def export_analysis_json(req: ExportResultRequest):
    """Export a deep-search result as JSON. Body: {\"result\": {...}}"""
    from export.json_export import export_to_json

    try:
        json_text = export_to_json(_R(_band_gate_result(req.result)), pretty=True)
    except Exception as e:
        logger.exception("JSON export failed")
        raise HTTPException(status_code=500, detail=str(e))

    return _json_response(json_text, "ebay_hunter_analysis.json")
