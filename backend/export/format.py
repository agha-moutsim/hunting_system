"""Format results to the user's exact JSON schema."""

from typing import Any

from engine.price_gate import excluded_note, filter_dicts, in_band


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

    PR-1/PR-6: no exported figure may sit outside the £5–£35 band —
    supplier rows are filtered, price-range statistics are nulled when
    out of band, and `band_notes` reports what was removed (PR-4).
    """
    # Preserve any exclusion notes an earlier gate layer already recorded.
    prior = getattr(result, "band_notes", None)
    band_notes: list[str] = [prior] if prior else []

    # Calculate eBay fees
    ebay_price = result.ebay_avg_price if in_band(result.ebay_avg_price) else 0.0
    if result.ebay_avg_price and not in_band(result.ebay_avg_price):
        band_notes.append(
            f"eBay avg price £{result.ebay_avg_price:.2f} removed (not in band)"
        )
    supplier_cost = result.best_supplier_price if in_band(result.best_supplier_price) else 0.0
    if result.best_supplier_price and not in_band(result.best_supplier_price):
        band_notes.append(
            f"best supplier price £{result.best_supplier_price:.2f} removed (not in band)"
        )

    ebay_fee_pct = 0.128
    returns_buffer_pct = 0.03
    total_fee_pct = ebay_fee_pct + returns_buffer_pct
    ebay_fees = ebay_price * total_fee_pct
    total_cost = supplier_cost + ebay_fees
    profit = ebay_price - total_cost
    margin = (profit / ebay_price * 100) if ebay_price > 0 else 0

    # Format top sellers
    top_sellers = []
    for seller in (result.ebay_top_sellers or [])[:5]:
        top_sellers.append({
            "name": seller.get("name", ""),
            "url": seller.get("url", ""),
        })

    # Format suppliers — band gate (PR-1 figure type 2)
    suppliers, excluded_suppliers = filter_dicts(result.suppliers or [], "price")
    if excluded_suppliers:
        band_notes.append(excluded_note("supplier matches", excluded_suppliers))

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
            "ebay_fees": round(ebay_fees, 2),
            "total_cost": round(total_cost, 2),
            "profit": round(profit, 2),
            "margin_percent": round(margin, 1),
            "verdict": result.verdict or "PENDING",
        },
    }
    if band_notes:
        output["band_notes"] = "; ".join(band_notes)

    return output


def format_bulk_to_schema(results: list) -> list[dict]:
    """Format multiple results to the user's exact JSON schema."""
    return [format_to_schema(r) for r in results]
