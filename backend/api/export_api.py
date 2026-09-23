"""Export endpoints — CSV / JSON downloads."""

import io
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.schemas import ExportResultRequest

router = APIRouter()
logger = logging.getLogger(__name__)


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
        "Shipping", "Fees", "Profit", "Margin %", "Qty",
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

    class _R:
        """Minimal adapter so export_to_csv can consume a plain dict."""

        def __init__(self, d):
            for k, v in d.items():
                setattr(self, k, v)

    try:
        csv_text = export_to_csv(_R(req.result))
    except Exception as e:
        logger.exception("CSV export failed")
        raise HTTPException(status_code=500, detail=str(e))

    return _csv_response(csv_text, "ebay_hunter_analysis.csv")


@router.post("/export/json")
def export_analysis_json(req: ExportResultRequest):
    """Export a deep-search result as JSON. Body: {\"result\": {...}}"""
    from export.json_export import export_to_json

    class _R:
        def __init__(self, d):
            for k, v in d.items():
                setattr(self, k, v)

    try:
        json_text = export_to_json(_R(req.result), pretty=True)
    except Exception as e:
        logger.exception("JSON export failed")
        raise HTTPException(status_code=500, detail=str(e))

    return _json_response(json_text, "ebay_hunter_analysis.json")
