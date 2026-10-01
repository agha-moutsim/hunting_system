"""Batch profit calculation — one decision rule, many products.

Money math and the verdict rule live in engine/ (calculate_profit +
DecisionEngine). This module only adapts CategoryProduct rows to the
engine's evidence interface — no rules of its own (C1).
"""

from typing import Optional

from hunter.category_scan import CategoryProduct
from scrapers.base import DemandData, ScrapedProduct


def batch_profit_calc(
    products: list[CategoryProduct],
    filters: Optional[dict] = None,
) -> list[CategoryProduct]:
    """Calculate profit and verdict for multiple products."""
    from config import FILTERS

    if filters is None:
        filters = FILTERS

    for product in products:
        _calc_single(product, filters)

    # Sort by margin (highest first)
    products.sort(key=lambda p: p.margin, reverse=True)

    return products


def _calc_single(product: CategoryProduct, filters: dict):
    """Adapt one CategoryProduct to DecisionEngine evidence."""
    from engine.decisions import DecisionEngine

    if product.price <= 0 or product.supplier_price <= 0:
        product.verdict = "PENDING"
        product.profit = 0
        product.margin = 0
        return

    evidence = ScrapedProduct(
        source="ebay_uk",
        title=product.title,
        price=product.price,
        url=product.url,
        # C10 — pass the condition through verbatim. '' means unread, and the
        # engine marks that row Unverified rather than inventing "New".
        condition=product.condition,
        # eBay-side delivery estimate is unknown here — C-new shows it as
        # Unknown rather than borrowing the supplier's ceiling (C1).
        delivery_days_max=None,
        verified=True,
    )
    demand = DemandData(
        sold_count_30d=product.sold_30d,
        sold_count_7d=product.sold_7d,
        verified=True,
        verified_7d=False,  # sold-search dates are not purchase history (C4)
    )
    # P5: a fresh purchase-history capture verifies the 7-day figure on its own.
    try:
        from analysis_pipeline import apply_purchase_history
        apply_purchase_history(demand, product.url)
    except Exception:
        pass

    verdict = DecisionEngine(filters).evaluate(
        evidence,
        demand,
        product.supplier_price,
        supplier_delivery_days=_supplier_delivery_max(product.supplier_name),
    )
    product.profit = verdict.profit
    product.margin = verdict.margin
    product.verdict = verdict.verdict.upper()


def _supplier_delivery_max(supplier_name: str) -> int | None:
    """Estimated delivery ceiling for a supplier (CONSTRAINTS.md map)."""
    if not supplier_name:
        return None
    from utils.filters import get_supplier_delivery_range
    return get_supplier_delivery_range(supplier_name)[1]
