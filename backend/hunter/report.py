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
    products: List[dict] = field(default_factory=list)
    scanned_at: str = ""

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

    for product in products:
        result.products.append({
            "title": product.title,
            "price": product.price,
            "url": product.url,
            "category": product.category,
            "sold_30d": product.sold_30d,
            "sold_7d": product.sold_7d,
            "supplier_price": product.supplier_price,
            "supplier_name": product.supplier_name,
            "supplier_url": product.supplier_url,
            "profit": product.profit,
            "margin": product.margin,
            "verdict": product.verdict,
        })

    return result


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
