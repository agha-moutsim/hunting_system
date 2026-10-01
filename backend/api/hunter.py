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
    from utils.filters import load_filters

    # Active range (user-adjustable, PR-5/PR-7): omitted client values
    # resolve to the ACTIVE range; a client value is honoured only when
    # it forms a sane range, otherwise we fall back to the active one.
    rng = load_filters()
    price_min = rng["price_min"] if req.price_min is None else float(req.price_min)
    price_max = rng["price_max"] if req.price_max is None else float(req.price_max)
    if not (0 < price_min < price_max <= 10000):
        price_min, price_max = rng["price_min"], rng["price_max"]
    products = scan_category(
        req.category,
        price_min=price_min,
        price_max=price_max,
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
    from engine.price_gate import clamp_band
    from utils.filters import load_filters

    # PR-5/PR-7: thresholds may come per-request; the price range always
    # resolves to the PERSISTED active value (same gate as the scan).
    active = load_filters()
    filters = clamp_band(req.filters)
    filters["price_min"] = active["price_min"]
    filters["price_max"] = active["price_max"]

    # Rebuild CategoryProduct dataclasses from client dicts
    fields = {f for f in CategoryProduct.__dataclass_fields__}
    products = []
    for d in req.products:
        kwargs = {k: v for k, v in d.items() if k in fields}
        products.append(CategoryProduct(**kwargs))

    total_scanned = int(req.products[0].get("_total_scanned", len(products))) if req.products else len(products)
    total_with_demand = len(products)

    with_supplier, excluded_suppliers = batch_supplier_lookup(products)
    final = batch_profit_calc(with_supplier, filters)

    rng = filters
    # Report header range: client echo of the scan band is shown only when
    # it forms a sane range; otherwise the active range is reported (never a
    # crash or an inverted headline from garbage input).
    p0 = req.products[0] if req.products else {}
    pmn, pmx = p0.get("_price_min"), p0.get("_price_max")
    ok = (
        isinstance(pmn, (int, float)) and not isinstance(pmn, bool)
        and isinstance(pmx, (int, float)) and not isinstance(pmx, bool)
        and 0 < pmn < pmx <= 10000
    )
    if not ok:
        pmn, pmx = rng["price_min"], rng["price_max"]
    report = generate_report(
        final,
        category=p0.get("category", ""),
        price_min=float(pmn),
        price_max=float(pmx),
        total_scanned=total_scanned,
        total_with_demand=total_with_demand,
        total_with_supplier=len(with_supplier),
    )
    # PR-4: surface what the active range removed (eBay listings only —
    # supplier rows are never range-gated, PR-1)
    if excluded_suppliers:
        from engine.price_gate import excluded_note
        report.notes = excluded_note("eBay listings", excluded_suppliers)

    payload = report.to_dict()
    # C11/C13 — every report row carries the store stamp the scan path
    # carries, so a lookup response never shows unstamped store lists.
    _stamp_report_stores(payload)
    return payload


def _stamp_report_stores(payload: dict) -> None:
    """C11/C13 — attach ebay_stores_provenance to each report product row."""
    from engine.stores import store_provenance_block

    for row in payload.get("products") or []:
        if (isinstance(row, dict) and "ebay_stores" in row
                and not row.get("ebay_stores_provenance")):
            row["ebay_stores_provenance"] = store_provenance_block(
                row.get("ebay_stores") or [])


def _product_dict(p) -> dict:
    from dataclasses import asdict, fields as dc_fields

    from engine.stores import store_provenance_block

    d = asdict(p)
    # Only include fields HunterResult.products expects + useful extras
    keep = {f.name for f in dc_fields(p)}
    out = {k: d[k] for k in keep if k in d}
    # C11/C13 — the store block's stamp travels with the stores it
    # describes (present-but-empty must never read as "not applicable").
    if "ebay_stores" in out:
        out["ebay_stores_provenance"] = store_provenance_block(
            out.get("ebay_stores") or [])
    return out
