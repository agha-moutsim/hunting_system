"""Category Hunter report generation."""

import csv
import io
import json
from dataclasses import dataclass, field, asdict
from typing import List

from hunter.category_scan import CategoryProduct


@dataclass
class HunterResult:
    """Complete category hunt result."""
    category: str = ""
    price_min: float = 0.0
    price_max: float = 0.0
    total_scanned: int = 0
    total_with_demand: int = 0
    total_with_supplier: int = 0
    total_pass: int = 0
    # How many rows earned the hot badge, counted not asserted.
    hot_count: int = 0
    products: List[dict] = field(default_factory=list)
    scanned_at: str = ""
    notes: str = ""  # PR-4 transparency (excluded-count line)
    # REGRESSION-005 - the C13 stamp for the money columns. The Hunter was
    # the only analysis endpoint that returned none.
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def generate_report(
    products: list[CategoryProduct],
    category: str,
    price_min: float,
    price_max: float,
    total_scanned: int = 0,
    total_with_demand: int = 0,
    total_with_supplier: int = 0,
) -> HunterResult:
    """Generate a category hunt report."""
    from datetime import datetime

    result = HunterResult(
        category=category,
        price_min=price_min,
        price_max=price_max,
        total_scanned=total_scanned,
        total_with_demand=total_with_demand,
        total_with_supplier=total_with_supplier,
        total_pass=sum(1 for p in products if p.verdict == "PASS"),
        scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    # Hot/trending is stamped on the rows BEFORE they are serialised, so the
    # dict below carries the computed badge rather than a default. The badge
    # comes from the demand counts each row already has; it is never assigned
    # by hand, and a row we could not judge is stamped unverified.
    from hunter.demand_hotness import apply_hotness
    from utils.filters import load_filters

    _active = load_filters()
    apply_hotness(products, _active["demand_min_30d"], _active["demand_min_7d"])

    for product in products:
        result.products.append({
            "hot": bool(getattr(product, "hot", False)),
            "hot_basis": getattr(product, "hot_basis", ""),
            "hot_provenance": getattr(product, "hot_provenance", ""),
            "hot_reason": getattr(product, "hot_reason", ""),
            "demand_pace_7d_per_week": getattr(product, "demand_pace_7d_per_week", None),
            "demand_pace_30d_per_week": getattr(product, "demand_pace_30d_per_week", None),
            "title": product.title,
            "price": product.price,
            "url": product.url,
            "category": product.category,
            # 1.6 - what was really searched, not what the user typed.
            "search_mode": getattr(product, "search_mode", ""),
            "search_query": getattr(product, "search_query", ""),
            "sold_30d": product.sold_30d,
            "sold_7d": product.sold_7d,
            "supplier_price": product.supplier_price,
            "supplier_name": product.supplier_name,
            "supplier_url": product.supplier_url,
            # REGRESSION-004/005 - a row says WHY it has or lacks a supplier,
            # and the money figures carry provenance so a 0 can never be read
            # as a measured zero.
            "supplier_status": getattr(product, "supplier_status", ""),
            "supplier_status_reason": getattr(product, "supplier_status_reason", ""),
            "profit": product.profit,
            "margin": product.margin,
            "verdict": product.verdict,
            "profit_provenance": getattr(product, "profit_provenance", ""),
            "profit_provenance_label": getattr(product, "profit_provenance_label", ""),
            "profit_provenance_reason": getattr(product, "profit_provenance_reason", ""),
            "profit_provenance_method": getattr(product, "profit_provenance_method", ""),
            "profit_status": getattr(product, "profit_status", ""),
            "shipping_cost": getattr(product, "shipping_cost", 0.0),
            "shipping_raw": getattr(product, "shipping_raw", ""),
            "ebay_stores": product.ebay_stores,
        })

    # REGRESSION-005 - the Hunter was the only analysis endpoint with no
    # provenance block at all. Counted from the rows so the number can never
    # disagree with what the table shows.
    statuses: dict[str, int] = {}
    for product in products:
        key = getattr(product, "profit_status", "") or "unknown"
        statuses[key] = statuses.get(key, 0) + 1
    result.provenance = {
        "profit": _profit_provenance_block(products),
        "supplier_status_counts": statuses,
    }

    # The user asked for hot items: rank the hot, profitable rows first.
    # `hot` was stamped on the rows before serialisation, above.
    result.products.sort(
        key=lambda row: (
            0 if row.get("hot") else 1,
            -float(row.get("margin") or 0.0),
            -float(row.get("demand_pace_7d_per_week") or 0.0),
        )
    )
    result.hot_count = sum(1 for p in products if getattr(p, "hot", False))

    return result


def _profit_provenance_block(products) -> dict:
    """The C13 stamp for the whole profit column.

    ESTIMATED when every row with a price actually had a supplier to compute
    from; UNVERIFIED as soon as any row did not, with the reason. Never
    VERIFIED - a margin is arithmetic on two prices, not a measurement of
    what will happen.
    """
    from engine.provenance import Provenance

    unverified = [
        p for p in products
        if getattr(p, "profit_provenance", "") == Provenance.UNVERIFIED.value
    ]
    if unverified:
        reasons = sorted({
            (getattr(p, "profit_provenance_reason", "") or "no supplier data")
            for p in unverified
        })
        block = {
            "provenance": Provenance.UNVERIFIED.value,
            "label": Provenance.UNVERIFIED.label,
            "reason": "; ".join(reasons[:3]),
        }
    else:
        block = {
            "provenance": Provenance.ESTIMATED.value,
            "label": Provenance.ESTIMATED.label,
            "method": "CONSTRAINTS.md C3 fee model applied to the eBay and supplier prices",
        }
    block["rows_unverified"] = len(unverified)
    block["rows_total"] = len(products)
    return block


def export_report_csv(result: HunterResult) -> str:
    """Export report to CSV."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "Rank",
        "Product",
        "Category",
        "eBay Price",
        "Sold (30d)",
        "Supplier",
        "Supplier Price",
        "Profit",
        "Margin %",
        "Verdict",
        "eBay URL",
        "Supplier URL",
    ])

    # Data rows
    for i, p in enumerate(result.products, 1):
        writer.writerow([
            i,
            p.get("title", ""),
            p.get("category", ""),
            f"£{p.get('price', 0):.2f}",
            p.get("sold_30d", 0),
            p.get("supplier_name", ""),
            f"£{p.get('supplier_price', 0):.2f}",
            f"£{p.get('profit', 0):.2f}",
            f"{p.get('margin', 0):.1f}%",
            p.get("verdict", ""),
            p.get("url", ""),
            p.get("supplier_url", ""),
        ])

    return output.getvalue()


def export_report_json(result: HunterResult, pretty: bool = True) -> str:
    """Export report to JSON."""
    if pretty:
        return json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
    return json.dumps(result.to_dict(), ensure_ascii=False)
