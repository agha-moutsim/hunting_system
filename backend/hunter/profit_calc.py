"""Batch profit calculation — one decision rule, many products.

Money math and the verdict rule live in engine/ (calculate_profit +
DecisionEngine). This module only adapts CategoryProduct rows to the
engine's evidence interface — no rules of its own (C1).
"""

from typing import Optional

from config import STORE_COUNT
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
    """Adapt one CategoryProduct to DecisionEngine evidence.

    REGRESSION-005: when there is no supplier price this used to write
    `profit = 0` / `margin = 0` and stop, which the frontend rendered as a
    real red "GBP0.00 (0.0%)". The numbers still start at 0 because that is
    genuinely all we know, but the row is now stamped UNVERIFIED with the
    reason, so a missing value can never be read as a measured zero (C1/C13).
    """
    from engine.decisions import DecisionEngine
    from engine.provenance import Provenance

    if product.price <= 0 or product.supplier_price <= 0:
        product.verdict = "PENDING"
        product.profit = 0
        product.margin = 0
        product.profit_provenance = Provenance.UNVERIFIED.value
        product.profit_provenance_label = Provenance.UNVERIFIED.label
        product.profit_provenance_method = ""
        product.profit_status = product.supplier_status or "no_supplier"
        product.profit_provenance_reason = (
            product.supplier_status_reason
            or "no approved supplier returned a matching offer, so no profit "
               "could be calculated"
        )
        return

    evidence = ScrapedProduct(
        source="ebay_uk",
        title=product.title,
        price=product.price,
        url=product.url,
        # C10 — pass the condition through verbatim. '' means unread, and the
        # engine marks that row Unverified rather than inventing "New".
        condition=product.condition,
        # eBay-side delivery estimate is unknown here - C-new shows it as
        # Unknown rather than borrowing the supplier's ceiling (C1).
        delivery_days_max=None,
        # REGRESSION-005 - the supplier's postage, when the source stated it.
        # 0.0 means unread, and calculate_profit reports the figure as
        # incomplete in that case rather than pretending postage was free.
        shipping_cost=product.shipping_cost or 0.0,
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
        # C11 - the real store count reaches the verdict as an ADVISORY row.
        # It is reported and never gated (there is no competitor threshold to
        # gate against), and fewer than STORE_COUNT stores means the ladder
        # broadened its search, so the count is a floor, not a total.
        competitor_store_count=len(product.ebay_stores),
        competitor_stores_verified=len(product.ebay_stores) >= STORE_COUNT,
    )
    product.profit = verdict.profit
    product.margin = verdict.margin
    product.verdict = verdict.verdict.upper()
    # C13 - this figure is COMPUTED from two real prices, so it is an
    # estimate with a stated method, not a verified fact and not an insight.
    from engine import fees as fee_engine
    from engine.provenance import Provenance
    product.profit_provenance = Provenance.ESTIMATED.value
    product.profit_provenance_label = Provenance.ESTIMATED.label
    _fee_table = fee_engine.get_fee_table()
    product.profit_provenance_method = (
        f"eBay UK rate card {_fee_table['key']} ({_fee_table['version']}): "
        "final value fee by category + per-order fee + regulatory operating "
        f"fee, plus {_fee_table['vat_rate']:g}% VAT on eBay's fees, the "
        "returns buffer and packaging"
        + ("" if not product.shipping_cost else " + supplier shipping")
    )
    product.profit_status = product.supplier_status or "found"
    product.profit_provenance_reason = (
        product.supplier_status_reason or "supplier price confirmed"
    )


def _supplier_delivery_max(supplier_name: str) -> int | None:
    """Estimated delivery ceiling for a supplier (CONSTRAINTS.md map)."""
    if not supplier_name:
        return None
    from utils.filters import get_supplier_delivery_range
    return get_supplier_delivery_range(supplier_name)[1]
