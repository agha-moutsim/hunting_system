"""Category Hunter module — auto-scan eBay categories for profitable products."""

from hunter.category_scan import scan_category, EBAY_CATEGORIES
from hunter.demand_check import batch_demand_check
from hunter.supplier_lookup import batch_supplier_lookup
from hunter.profit_calc import batch_profit_calc
from hunter.report import generate_report, HunterResult

__all__ = [
    "scan_category",
    "EBAY_CATEGORIES",
    "batch_demand_check",
    "batch_supplier_lookup",
    "batch_profit_calc",
    "generate_report",
    "HunterResult",
]
