"""Sales Dashboard endpoints — KPIs, charts, sales CRUD."""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

from api.schemas import SaleCreate

router = APIRouter()
logger = logging.getLogger(__name__)


# ── KPIs & charts ───────────────────────────────────────────────

@router.get("/dashboard/kpis")
def kpis(days: int = 30):
    from dashboard.analytics import get_kpis

    return get_kpis(days=days)


@router.get("/dashboard/charts/revenue-trend")
def revenue_trend(days: int = 30):
    from dashboard.charts import get_revenue_trend

    return get_revenue_trend(days=days)


@router.get("/dashboard/charts/profit-trend")
def profit_trend(days: int = 30):
    from dashboard.charts import get_profit_trend

    return get_profit_trend(days=days)


@router.get("/dashboard/charts/categories")
def category_breakdown():
    from dashboard.charts import get_category_breakdown

    return get_category_breakdown()


@router.get("/dashboard/charts/monthly")
def monthly_comparison(months: int = 6):
    from dashboard.charts import get_monthly_comparison

    return get_monthly_comparison(months=months)


@router.get("/dashboard/top-products")
def top_products(limit: int = 10):
    from dashboard.analytics import get_top_products

    return {"products": get_top_products(limit=limit)}


@router.get("/dashboard/top-categories")
def top_categories(limit: int = 10):
    from dashboard.analytics import get_top_categories

    return {"categories": get_top_categories(limit=limit)}


# ── Sales CRUD ──────────────────────────────────────────────────

@router.get("/sales")
def list_sales(limit: int = 100, offset: int = 0):
    from dashboard.sales import get_sales

    return {"sales": get_sales(limit=limit, offset=offset)}


@router.post("/sales")
def create_sale(req: SaleCreate):
    from dashboard.sales import log_sale

    sale_date = None
    if req.sale_date:
        try:
            sale_date = datetime.strptime(req.sale_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="sale_date must be YYYY-MM-DD")

    sale = log_sale(
        product_name=req.product_name,
        sale_price=req.sale_price,
        supplier_cost=req.supplier_cost,
        shipping_cost=req.shipping_cost,
        ebay_fees=req.ebay_fees,
        quantity=req.quantity,
        sale_date=sale_date,
        category=req.category,
        buyer_location=req.buyer_location,
        notes=req.notes,
    )
    if not sale:
        raise HTTPException(status_code=500, detail="Failed to log sale")
    return {"id": sale.id, "profit": sale.profit, "margin_percent": sale.margin_percent}


@router.delete("/sales/{sale_id}")
def delete_sale(sale_id: int):
    from dashboard.sales import delete_sale as _delete

    if not _delete(sale_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"deleted": True}
