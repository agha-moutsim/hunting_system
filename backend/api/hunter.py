"""Category Hunter endpoints."""

import logging

from fastapi import APIRouter, HTTPException, Request

from api.market_context import marketplace_for_optional_request
from api.schemas import HunterLookupRequest, HunterScanRequest
from marketplaces import analyze_ready, fee_warning, get_marketplace, market_filter_defaults

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_ready_market(request: Request | None, surface: str) -> dict:
    market = marketplace_for_optional_request(request)
    if analyze_ready(market):
        return market
    reason = fee_warning(market) or (
        "No supplier bench is registered for this marketplace."
    )
    raise HTTPException(
        status_code=422,
        detail=f"{surface} is not enabled for {market['label']}. {reason}",
    )


@router.get("/hunter/categories")
def hunter_categories():
    """The categories the UI offers, so the box can be a real picker.

    Free text is still allowed and is searched as typed; this is only the
    list of things we can browse instead of search (REGRESSION-001).
    """
    from hunter.category_resolver import category_choices

    return {"categories": category_choices()}


@router.post("/hunter/scan")
def hunter_scan(req: HunterScanRequest, request: Request = None):
    """Browse a known category, or search eBay for what the user typed.

    REGRESSION-001: this used to resolve the text through
    `EBAY_CATEGORIES.get(name, "293")`, so "garden tools" silently became
    Electronics and the typed words were never sent. The response now carries
    `search` so the UI can state what was actually looked for.
    """
    from hunter.category_resolver import resolve_category
    from hunter.category_scan import scan_category
    from hunter.demand_check import batch_demand_check
    from utils.filters import load_filters

    market = _require_ready_market(request, "Category Hunter")

    # Active range (user-adjustable, PR-5/PR-7): omitted client values
    # resolve to the market's own range; a client value is honoured only when
    # it forms a sane range, otherwise we fall back to that range. UK keeps
    # the persisted active range; AU uses its market band.
    if market["id"] == "EBAY_GB":
        rng = load_filters()
    else:
        defaults = market_filter_defaults(market)
        rng = {
            "price_min": defaults.get("price_min", (market.get("price_band") or {}).get("min", 0.99)),
            "price_max": defaults.get("price_max", (market.get("price_band") or {}).get("max", 50.0)),
        }
    price_min = rng["price_min"] if req.price_min is None else float(req.price_min)
    price_max = rng["price_max"] if req.price_max is None else float(req.price_max)
    if not (0 < price_min < price_max <= 10000):
        price_min, price_max = rng["price_min"], rng["price_max"]

    resolved = resolve_category(req.category)
    scan_kwargs = dict(
        price_min=price_min,
        price_max=price_max,
        max_results=req.max_results,
    )
    if market["id"] != "EBAY_GB":
        scan_kwargs["marketplace"] = market["id"]
    products = scan_category(req.category, **scan_kwargs)
    total_scanned = len(products)

    if market["id"] == "EBAY_GB":
        with_demand = batch_demand_check(products)
    else:
        with_demand = batch_demand_check(products, marketplace=market["id"])

    return {
        "marketplace": market["id"],
        "currency": market["currency"],
        "currency_symbol": market["currency_symbol"],
        "products": [_product_dict(p) for p in with_demand],
        "total_scanned": total_scanned,
        "total_with_demand": len(with_demand),
        # What was really asked of eBay — never a category the user did not
        # choose.
        "search": {
            "text": resolved.text,
            "mode": resolved.mode,
            "label": resolved.label,
            "reason": resolved.reason,
        },
    }


@router.post("/hunter/lookup")
def hunter_lookup(req: HunterLookupRequest, request: Request = None):
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

    market = _require_ready_market(request, "Category Hunter")

    # PR-5/PR-7: thresholds may come per-request; the price range always
    # resolves to the market's own active value (same gate as the scan).
    if market["id"] == "EBAY_GB":
        active = load_filters()
        defaults = None
    else:
        defaults = market_filter_defaults(market)
        active = {
            "price_min": defaults.get("price_min", (market.get("price_band") or {}).get("min", 0.99)),
            "price_max": defaults.get("price_max", (market.get("price_band") or {}).get("max", 50.0)),
        }
    filters = clamp_band(req.filters, defaults=defaults)
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

    with_supplier, excluded_suppliers = batch_supplier_lookup(
        products, marketplace=market["id"]
    )
    if market["id"] == "EBAY_GB":
        final = batch_profit_calc(with_supplier, filters)
    else:
        final = batch_profit_calc(
            with_supplier, filters, marketplace=market["id"]
        )

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
    payload["marketplace"] = market["id"]
    payload["currency"] = market["currency"]
    payload["currency_symbol"] = market["currency_symbol"]
    # C11/C13 — every report row carries the store stamp the scan path
    # carries, so a lookup response never shows unstamped store lists.
    _stamp_report_stores(payload)
    # REGRESSION-005 — an empty result must say WHY it is empty, in real
    # counts. The old response returned products: [] and the UI showed a bare
    # "no products", which was indistinguishable from a genuinely empty
    # category: a run where every supplier lookup timed out looked identical
    # to a category with nothing in it.
    payload["summary"] = _lookup_summary(
        final, total_scanned, excluded_suppliers, marketplace=market["id"]
    )
    return payload


def _lookup_summary(
    products: list, total_scanned: int, excluded_over_band: int,
    marketplace: str = "EBAY_GB",
) -> dict:
    """Real counts for the empty state - never a message invented to fill it.

    The nudge is derived from what actually happened (how many listings were
    seen, how many had a supplier, how many were out of band, and the active
    price range). It never invents a product, a count, or a supplier.
    """
    rows = len(products)
    with_supplier = sum(
        1 for p in products if getattr(p, "supplier_status", "") == "found"
    )
    reasons: dict[str, int] = {}
    for p in products:
        key = getattr(p, "supplier_status", "") or "unknown"
        reasons[key] = reasons.get(key, 0) + 1

    from utils.filters import load_filters
    from marketplaces import get_marketplace, market_filter_defaults

    market = get_marketplace(marketplace)
    if market["id"] == "EBAY_GB":
        rng = load_filters()
    else:
        defaults = market_filter_defaults(market)
        rng = {
            "price_min": defaults.get("price_min", (market.get("price_band") or {}).get("min", 0.99)),
            "price_max": defaults.get("price_max", (market.get("price_band") or {}).get("max", 50.0)),
        }
    return {
        "products_returned": rows,
        "with_supplier": with_supplier,
        "no_supplier": reasons.get("no_supplier", 0),
        "timed_out": reasons.get("timeout", 0),
        "out_of_band": excluded_over_band,
        "scanned": total_scanned,
        "price_min": rng["price_min"],
        "price_max": rng["price_max"],
        "status_counts": reasons,
    }


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
