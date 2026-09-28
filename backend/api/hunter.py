"""Category Hunter endpoints."""

import logging

from fastapi import APIRouter

from api.schemas import HunterLookupRequest, HunterScanRequest

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/hunter/scan")
def hunter_scan(req: HunterScanRequest):
    """Scan an eBay category within the price range + run demand check."""
    from hunter.category_scan import scan_category
    from hunter.demand_check import batch_demand_check
    from config import FILTERS
    from engine.price_gate import PRICE_MAX

    # Hard band: client values are clamped, never allowed above £35 (PR-7)
    products = scan_category(
        req.category,
        price_min=max(req.price_min, FILTERS["price_min"]),
        price_max=min(req.price_max, PRICE_MAX),
        max_results=req.max_results,
    )
    total_scanned = len(products)

    with_demand = batch_demand_check(products)

    return {
        "products": [_product_dict(p) for p in with_demand],
        "total_scanned": total_scanned,
        "total_with_demand": len(with_demand),
    }


@router.post("/hunter/lookup")
def hunter_lookup(req: HunterLookupRequest):
    """Supplier lookup + profit calc + report for scanned products.

    Products are sent back from the client (stateless).
    Supplier lookup runs sequentially with a 15s timeout per product.
    """
    from hunter.category_scan import CategoryProduct
    from hunter.supplier_lookup import batch_supplier_lookup
    from hunter.profit_calc import batch_profit_calc
    from hunter.report import generate_report
    from config import FILTERS

    filters = req.filters or FILTERS

    # Rebuild CategoryProduct dataclasses from client dicts
    fields = {f for f in CategoryProduct.__dataclass_fields__}
    products = []
    for d in req.products:
        kwargs = {k: v for k, v in d.items() if k in fields}
        products.append(CategoryProduct(**kwargs))

    total_scanned = int(req.products[0].get("_total_scanned", len(products))) if req.products else len(products)
    total_with_demand = len(products)

    with_supplier = batch_supplier_lookup(products)
    final = batch_profit_calc(with_supplier, filters)

    report = generate_report(
        final,
        category=req.products[0].get("category", "") if req.products else "",
        price_min=float(req.products[0].get("_price_min", filters.get("price_min", 5))) if req.products else 5.0,
        price_max=float(req.products[0].get("_price_max", filters.get("price_max", 35))) if req.products else 35.0,
        total_scanned=total_scanned,
        total_with_demand=total_with_demand,
        total_with_supplier=len(with_supplier),
    )

    return report.to_dict()


def _product_dict(p) -> dict:
    from dataclasses import asdict, fields as dc_fields

    d = asdict(p)
    # Only include fields HunterResult.products expects + useful extras
    keep = {f.name for f in dc_fields(p)}
    return {k: d[k] for k in keep if k in d}
