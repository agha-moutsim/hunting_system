from typing import Optional

from scrapers.base import ScrapedProduct, DemandData
from engine.decisions import Verdict, FilterResult
from engine.profit import calculate_profit


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
        if f.advisory:
            # An advisory row is information, not a rule: the verdict ladder
            # already excludes it, so stamping it [FAIL] (or [PASS]) would
            # read as a decision that was never made. Say what kind of row
            # this is, and whether we could actually confirm it.
            tag = "INFO" if f.verified else "INFO?"
            note = "" if f.verified else " (unverified)"
            lines.append(f"  [{tag}] {f.name}: {f.actual}{note} (expected {f.expected})")
            continue
        tag = _status_icon(f.passed)
        suffix = "" if f.verified else " (unverified)"
        lines.append(f"  [{tag}] {f.name}: {f.actual}{suffix} (expected {f.expected})")
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
        lines.append("  No sold data available")

    # Supply-side evidence under its OWN heading. These are real prices read
    # from eBay, but they are ASKING prices on live listings — a useful picture
    # of what it costs to compete, and not a sale. Printing them under DEMAND is
    # what let a listing price read as an "Avg sold".
    if demand_data and demand_data.active_listings_in_band is not None:
        lines.append("")
        lines.append("LIVE LISTINGS (supply, not sales)")
        lines.append("-" * 55)
        lines.append(f"  In band:    {demand_data.active_listings_in_band}")
        if demand_data.avg_active_price is not None:
            lines.append(f"  Avg asking: \u00a3{demand_data.avg_active_price:.2f}")
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
    # Every line comes from the engine's own view of this sale - the same
    # call the verdict was decided with - so the card cannot quote a rate
    # or a figure the engine does not stand behind. The fee table version
    # is stated because a money figure without its model is not defensible.
    lines.append("PROFIT CALCULATION")
    lines.append("-" * 55)
    lines.append(f"  eBay price:       \u00a3{ebay_product.price:.2f}")
    supplier_price = None
    if supplier_matches:
        candidate = getattr(supplier_matches[0], "price", None)
        if isinstance(candidate, (int, float)):
            supplier_price = candidate
            lines.append(f"  Supplier price:   \u00a3{supplier_price:.2f}")

    money = None
    try:
        money = calculate_profit(
            ebay_product.price,
            supplier_price,
            shipping_cost=getattr(ebay_product, "shipping_cost", 0.0) or 0.0,
        )
    except ValueError as exc:
        # The engine refuses to price a sale it cannot stand behind (a zero
        # or unread price); the card repeats the refusal rather than
        # printing a number nobody computed.
        lines.append(f"  Fee engine:       refused - {exc}")

    if money is not None:
        table = money["fee_table"]
        lines.append(f"  Fee table:        {table['key']} ({table['version']})")
        for row in money["breakdown"]["fee_lines"]:
            label = f"{row['label']}:"
            gap = " " * max(1, 18 - len(label))
            rate = f"{row['rate']} \u00b7 " if row.get("rate") else ""
            lines.append(f"  {label}{gap}{rate}\u00a3{row['amount']:.2f}")
        buffer_percent = money["breakdown"]["risk_buffer_percent"]
        lines.append(
            f"  {'Returns buffer:':<18}{buffer_percent:g}% \u00b7 "
            f"\u00a3{money['returns_buffer']:.2f}"
        )
        if money["supplier_price"] is None:
            lines.append("  Profit:           (no supplier price - not computed)")
            lines.append("  Margin:           (no supplier price - not computed)")
        else:
            lines.append(f"  Profit:           \u00a3{verdict.profit:.2f}")
            lines.append(f"  Margin:           {verdict.margin:.1f}%")
            if not money["profit_is_complete"]:
                lines.append(
                    "  Note:             postage paid is not known (0.00 "
                    "assumed); the profit above is a ceiling (C1)."
                )
    else:
        lines.append(f"  Profit:           \u00a3{verdict.profit:.2f}")
        lines.append(f"  Margin:           {verdict.margin:.1f}%")

    # The fee card's assumptions are part of the money: when one of them
    # holds, the card says so rather than leaving the reader to trust a
    # figure whose basis was printed nowhere.
    if money is not None and money["breakdown"]["fees"]["assumptions"]:
        lines.append("  Assumptions:")
        for assumption in money["breakdown"]["fees"]["assumptions"]:
            lines.append(f"    - {assumption}")
    lines.append("")

    # --- Final verdict ---
    lines.append("=" * 55)
    v = verdict.verdict.upper()
    lines.append(f"  VERDICT: {v}")
    lines.append("=" * 55)

    return "\n".join(lines)
