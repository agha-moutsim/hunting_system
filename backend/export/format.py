"""Format results to the user's exact JSON schema."""

from typing import Any

from engine.price_gate import band_label, in_band
from engine.profit import calculate_profit


def format_to_schema(result: Any) -> dict:
    """Format a single DeepSearchResult to the user's exact JSON schema.

    Schema:
    {
      "product_name": "string",
      "category": "string",
      "most_items_sold_on_eBay": "string",
      "top_eBay_sellers": [{"name": str, "url": str}],
      "monthly_sales": "string",
      "eBay_price_range": {"min": float, "max": float, "avg": float, "median": float},
      "suppliers": [{"name": str, "item_cost": float, "link": str, "type": str, "delivery_days": str}],
      "profit_analysis": {"ebay_fees": float, "total_cost": float, "profit": float, "margin_percent": float, "verdict": str}
    }

    PR-1/PR-6: no exported eBay-side figure may sit outside the active
    range — price-range statistics are nulled when out of range and
    `band_notes` reports what was removed (PR-4). Supplier prices are
    NEVER gated (PR-1) and export in full.
    """
    # Preserve any exclusion notes an earlier gate layer already recorded.
    prior = getattr(result, "band_notes", None)
    band_notes: list[str] = [prior] if prior else []

    # Calculate eBay fees
    ebay_price = result.ebay_avg_price if in_band(result.ebay_avg_price) else 0.0
    if result.ebay_avg_price and not in_band(result.ebay_avg_price):
        band_notes.append(
            f"eBay avg price £{result.ebay_avg_price:.2f} removed (not in {band_label()} range)"
        )
    supplier_cost = result.best_supplier_price or 0.0

    # Money from the single engine source (PROFIT_CONFIG) — C1/C3.
    # With no usable in-band eBay price there is nothing to compute fees
    # or profit FROM: export nulls, never arithmetic on a gated 0.
    has_price = bool(ebay_price)
    calc = calculate_profit(ebay_price, supplier_cost)
    ebay_fees = calc["total_fees"] if has_price else None
    total_cost = (supplier_cost + calc["total_fees"]) if has_price else None
    profit = calc["profit"] if has_price else None
    margin = calc["margin"] if has_price else None

    # Format top sellers
    top_sellers = []
    for seller in (result.ebay_top_sellers or [])[:5]:
        top_sellers.append({
            "name": seller.get("name", ""),
            "url": seller.get("url", ""),
        })

    # Format suppliers — never range-gated (PR-1)
    suppliers = result.suppliers or []

    export_suppliers = []
    for supplier in suppliers:
        export_suppliers.append({
            "name": supplier.get("name", ""),
            "full_name": supplier.get("full_name", ""),
            "item_cost": supplier.get("price", 0),
            "link": supplier.get("url", ""),
            "type": supplier.get("supplier_type", "unknown"),
            "delivery_days": supplier.get("delivery_days", "unknown"),
            "seller_rating": supplier.get("seller_rating", ""),
            "seller_orders": supplier.get("seller_orders", ""),
            "product_title": supplier.get("product_title", ""),
            "image_url": supplier.get("image_url", ""),
        })

    # Sold-history statistics (PR-1 figure type 3) — out of band becomes null,
    # never a stale/guessed number (C1: don't fabricate).
    def _stat(v: float) -> float | None:
        if not v:
            return None
        if in_band(v):
            return v
        band_notes.append(f"eBay sold statistic £{v:.2f} removed (not in band)")
        return None

    # Build output
    output = {
        "product_name": result.product_name,
        "category": result.product_category or "Unknown",
        "most_items_sold_on_eBay": result.ebay_items_sold_month or "Unknown",
        "top_eBay_sellers": top_sellers,
        "monthly_sales": result.ebay_items_sold_month or "Unknown",
        "eBay_price_range": {
            "min": _stat(result.ebay_price_min),
            "max": _stat(result.ebay_price_max),
            "avg": _stat(result.ebay_avg_price),
            "median": _stat(result.ebay_price_median),
        },
        "suppliers": export_suppliers,
        "profit_analysis": {
            "ebay_fees": round(ebay_fees, 2) if ebay_fees is not None else None,
            "total_cost": round(total_cost, 2) if total_cost is not None else None,
            "profit": round(profit, 2) if profit is not None else None,
            "margin_percent": round(margin, 1) if margin is not None else None,
            "verdict": result.verdict or "PENDING",
        },
    }
    if band_notes:
        output["band_notes"] = "; ".join(band_notes)

    return output


def format_bulk_to_schema(results: list) -> list[dict]:
    """Format multiple results to the user's exact JSON schema."""
    return [format_to_schema(r) for r in results]
