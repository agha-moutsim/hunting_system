"""Batch profit calculation — calculate profit for multiple products."""

from typing import Optional

from hunter.category_scan import CategoryProduct


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
    """Calculate profit and verdict for a single product."""
    ebay_price = product.price
    supplier_cost = product.supplier_price

    if ebay_price <= 0 or supplier_cost <= 0:
        product.verdict = "PENDING"
        product.profit = 0
        product.margin = 0
        return

    # eBay fees: 12.8% final value + 3% returns buffer
    ebay_fee_pct = 0.128
    returns_buffer_pct = 0.03
    total_fee_pct = ebay_fee_pct + returns_buffer_pct

    ebay_fees = ebay_price * total_fee_pct
    profit = ebay_price - supplier_cost - ebay_fees
    margin = (profit / ebay_price * 100) if ebay_price > 0 else 0

    product.profit = round(profit, 2)
    product.margin = round(margin, 1)

    # Apply filters — price band fallback mirrors config (CONSTRAINTS_PRICING.md PR-5)
    from config import FILTERS
    price_ok = filters.get("price_min", FILTERS["price_min"]) <= supplier_cost <= filters.get("price_max", FILTERS["price_max"])
    margin_ok = margin >= filters.get("margin_min", 25)
    profit_ok = profit > 0
    demand_ok = product.sold_30d >= filters.get("demand_min_30d", 10)

    if price_ok and margin_ok and profit_ok and demand_ok:
        product.verdict = "PASS"
    elif not price_ok or not margin_ok or not profit_ok or not demand_ok:
        product.verdict = "FAIL"
    else:
        product.verdict = "PENDING"
