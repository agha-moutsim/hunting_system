"""Format results to the user's exact JSON schema."""

from typing import Any


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
    """
    # Calculate eBay fees
    ebay_price = result.ebay_avg_price
    supplier_cost = result.best_supplier_price
    
    ebay_fee_pct = 0.128
    returns_buffer_pct = 0.03
    total_fee_pct = ebay_fee_pct + returns_buffer_pct
    ebay_fees = ebay_price * total_fee_pct
    total_cost = supplier_cost + ebay_fees
    profit = ebay_price - total_cost
    margin = (profit / ebay_price * 100) if ebay_price > 0 else 0

    # Format top sellers
    top_sellers = []
    for seller in result.ebay_top_sellers[:5]:
        top_sellers.append({
            "name": seller.get("name", ""),
            "url": seller.get("url", ""),
        })

    # Format suppliers
    suppliers = []
    for supplier in result.suppliers:
        suppliers.append({
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

    # Build output
    output = {
        "product_name": result.product_name,
        "category": result.product_category or "Unknown",
        "most_items_sold_on_eBay": result.ebay_items_sold_month or "Unknown",
        "top_eBay_sellers": top_sellers,
        "monthly_sales": result.ebay_items_sold_month or "Unknown",
        "eBay_price_range": {
            "min": result.ebay_price_min,
            "max": result.ebay_price_max,
            "avg": result.ebay_avg_price,
            "median": result.ebay_price_median,
        },
        "suppliers": suppliers,
        "profit_analysis": {
            "ebay_fees": round(ebay_fees, 2),
            "total_cost": round(total_cost, 2),
            "profit": round(profit, 2),
            "margin_percent": round(margin, 1),
            "verdict": result.verdict or "PENDING",
        },
    }

    return output


def format_bulk_to_schema(results: list) -> list[dict]:
    """Format multiple results to the user's exact JSON schema."""
    return [format_to_schema(r) for r in results]
