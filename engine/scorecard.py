from typing import Optional

from scrapers.base import ScrapedProduct, DemandData
from engine.decisions import Verdict, FilterResult


def _status_icon(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def format_scorecard(
    ebay_product: ScrapedProduct,
    supplier_matches: list,
    demand_data: Optional[DemandData],
    verdict: Verdict,
) -> str:
    """Build a human-readable scorecard string for one product."""
    lines: list[str] = []

    lines.append("=" * 55)
    lines.append(f"  SCORECARD: {ebay_product.title[:45]}")
    lines.append("=" * 55)
    lines.append("")

    # --- Filter results ---
    lines.append("FILTERS")
    lines.append("-" * 55)
    for f in verdict.filters:
        tag = _status_icon(f.passed)
        lines.append(f"  [{tag}] {f.name}: {f.actual} (expected {f.expected})")
    lines.append("")

    # --- Demand ---
    lines.append("DEMAND")
    lines.append("-" * 55)
    if demand_data and demand_data.sold_count_30d is not None:
        lines.append(f"  Sold (30d): {demand_data.sold_count_30d}")
        lines.append(f"  Sold (7d):  {demand_data.sold_count_7d or 0}")
        if demand_data.avg_sold_price is not None:
            lines.append(f"  Avg sold:   \u00a3{demand_data.avg_sold_price:.2f}")
        if demand_data.last_sale_date:
            lines.append(f"  Last sale:  {demand_data.last_sale_date}")
    else:
        lines.append("  No demand data available")
    lines.append("")

    # --- Supplier matches ---
    lines.append("SUPPLIER MATCHES")
    lines.append("-" * 55)
    if supplier_matches:
        for s in supplier_matches[:3]:
            title = getattr(s, "title", str(s))[:40]
            price = getattr(s, "price", "?")
            lines.append(f"  \u2022 {title}  \u00a3{price}")
    else:
        lines.append("  No supplier matches found")
    lines.append("")

    # --- Profit ---
    lines.append("PROFIT CALCULATION")
    lines.append("-" * 55)
    lines.append(f"  eBay price:     \u00a3{ebay_product.price:.2f}")
    if supplier_matches:
        best_supplier = supplier_matches[0]
        sp = getattr(best_supplier, "price", 0)
        lines.append(f"  Supplier price: \u00a3{sp:.2f}")
    lines.append(f"  eBay fee:       12.8%")
    lines.append(f"  Returns buffer: 3.0%")
    lines.append(f"  ----------------------------------------")
    lines.append(f"  Profit:         \u00a3{verdict.profit:.2f}")
    lines.append(f"  Margin:         {verdict.margin:.1f}%")
    lines.append("")

    # --- Final verdict ---
    lines.append("=" * 55)
    v = verdict.verdict.upper()
    lines.append(f"  VERDICT: {v}")
    lines.append("=" * 55)

    return "\n".join(lines)
