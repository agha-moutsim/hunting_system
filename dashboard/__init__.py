"""Dashboard module — sales logging and analytics."""

from dashboard.sales import (
    log_sale,
    update_sale,
    delete_sale,
    get_sales,
    get_sales_by_date_range,
)
from dashboard.analytics import (
    get_kpis,
    get_monthly_stats,
    get_top_products,
    get_top_categories,
)
from dashboard.charts import (
    get_revenue_trend,
    get_profit_trend,
    get_category_breakdown,
    get_monthly_comparison,
)

__all__ = [
    "log_sale",
    "update_sale",
    "delete_sale",
    "get_sales",
    "get_sales_by_date_range",
    "get_kpis",
    "get_monthly_stats",
    "get_top_products",
    "get_top_categories",
    "get_revenue_trend",
    "get_profit_trend",
    "get_category_breakdown",
    "get_monthly_comparison",
]
