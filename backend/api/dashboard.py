"""Dashboard endpoints — KPIs and charts over user-declared sales.

Sales CRUD, the P&L summary and CSV import live in `api/sales.py` now. These
legacy read routes remain for callers that still use the chart shapes; the
dashboard itself reads `/api/sales/summary`.
"""

import logging

from fastapi import APIRouter

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
