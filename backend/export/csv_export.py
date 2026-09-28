"""CSV export for eBay Hunter results."""

import csv
import io
from typing import Any

from engine.profit import calculate_profit


def export_to_csv(result: Any) -> str:
    """Export a single result to CSV format."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "Product Name",
        "Category",
        "eBay Sold (30d)",
        "eBay Sold (7d)",
        "Price Min",
        "Price Max",
        "Price Avg",
        "Price Median",
        "Top Seller 1",
        "Top Seller 1 URL",
        "Top Seller 2",
        "Top Seller 2 URL",
        "Supplier 1",
        "Supplier 1 Cost",
        "Supplier 1 URL",
        "Supplier 1 Type",
        "Supplier 1 Delivery",
        "Supplier 2",
        "Supplier 2 Cost",
        "Supplier 2 URL",
        "Supplier 2 Type",
        "Supplier 2 Delivery",
        "eBay Fees",
        "Total Cost",
        "Profit",
        "Margin %",
        "Verdict",
    ])

    # Data row
    top_sellers = result.ebay_top_sellers or []
    suppliers = result.suppliers or []

    # Money from the single engine source (PROFIT_CONFIG) — C1
    calc = calculate_profit(
        result.ebay_avg_price or 0, result.best_supplier_price or 0
    )
    ebay_fees = calc["ebay_fee"] + calc["returns_buffer"]
    total_cost = (result.best_supplier_price or 0) + calc["total_fees"]
    profit = calc["profit"]
    margin = calc["margin"]

    writer.writerow([
        result.product_name,
        result.product_category or "Unknown",
        result.ebay_total_sold_30d or result.ebay_items_sold_month or "",
        result.ebay_total_sold_7d or "",
        f"£{result.ebay_price_min:.2f}" if result.ebay_price_min else "",
        f"£{result.ebay_price_max:.2f}" if result.ebay_price_max else "",
        f"£{result.ebay_avg_price:.2f}" if result.ebay_avg_price else "",
        f"£{result.ebay_price_median:.2f}" if result.ebay_price_median else "",
        top_sellers[0].get("name", "") if len(top_sellers) > 0 else "",
        top_sellers[0].get("url", "") if len(top_sellers) > 0 else "",
        top_sellers[1].get("name", "") if len(top_sellers) > 1 else "",
        top_sellers[1].get("url", "") if len(top_sellers) > 1 else "",
        suppliers[0].get("name", "") if len(suppliers) > 0 else "",
        f"£{suppliers[0].get('price', 0):.2f}" if len(suppliers) > 0 else "",
        suppliers[0].get("url", "") if len(suppliers) > 0 else "",
        suppliers[0].get("supplier_type", "") if len(suppliers) > 0 else "",
        suppliers[0].get("delivery_days", "") if len(suppliers) > 0 else "",
        suppliers[1].get("name", "") if len(suppliers) > 1 else "",
        f"£{suppliers[1].get('price', 0):.2f}" if len(suppliers) > 1 else "",
        suppliers[1].get("url", "") if len(suppliers) > 1 else "",
        suppliers[1].get("supplier_type", "") if len(suppliers) > 1 else "",
        suppliers[1].get("delivery_days", "") if len(suppliers) > 1 else "",
        f"£{ebay_fees:.2f}",
        f"£{total_cost:.2f}",
        f"£{profit:.2f}",
        f"{margin:.1f}%",
        result.verdict or "PENDING",
    ])

    # PR-4: exclusions must be reported even in CSV form.
    prior_notes = getattr(result, "band_notes", None)
    if prior_notes:
        writer.writerow([])
        writer.writerow([f"NOTE: {prior_notes}"])

    return output.getvalue()


def export_bulk_to_csv(results: list) -> str:
    """Export multiple results to CSV format."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "Product Name",
        "Category",
        "eBay Sold (30d)",
        "Price Avg",
        "Best Supplier",
        "Supplier Cost",
        "eBay Fees",
        "Profit",
        "Margin %",
        "Verdict",
    ])

    # Data rows
    for result in results:
        # Money from the single engine source (PROFIT_CONFIG) — C1
        supplier_cost = result.best_supplier_price or 0
        calc = calculate_profit(result.ebay_avg_price or 0, supplier_cost)
        ebay_fees = calc["ebay_fee"] + calc["returns_buffer"]
        total_cost = supplier_cost + calc["total_fees"]
        profit = calc["profit"]
        margin = calc["margin"]

        # Find best supplier
        best_supplier = ""
        if result.suppliers:
            valid = [s for s in result.suppliers if isinstance(s.get("price"), (int, float)) and s["price"] > 0]
            if valid:
                best = min(valid, key=lambda s: s["price"])
                best_supplier = best.get("name", "")

        writer.writerow([
            result.product_name,
            result.product_category or "Unknown",
            result.ebay_total_sold_30d or result.ebay_items_sold_month or "",
            f"£{result.ebay_avg_price:.2f}" if result.ebay_avg_price else "",
            best_supplier,
            f"£{supplier_cost:.2f}" if supplier_cost else "",
            f"£{ebay_fees:.2f}",
            f"£{profit:.2f}",
            f"{margin:.1f}%",
            result.verdict or "PENDING",
        ])

    return output.getvalue()
