"""History endpoints — past analyses + product detail."""

import logging

from fastapi import APIRouter, HTTPException

from engine.price_gate import in_band
from utils.filters import active_range, outside_range, price_in_range, resolve_range

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/history")
def list_history(
    verdict: str = "All",
    q: str = "",
    limit: int = 50,
    price_min: float | None = None,
    price_max: float | None = None,
):
    """Recent analyses with optional verdict filter, text search and range view filter.

    PR-6/PR-7: rows are stored regardless of price; the default view shows only
    rows inside the active range (user may override with price_min/price_max),
    rows inside the view but outside the active range carry `outside_band`.
    """
    from db.database import SessionLocal
    from db.queries import get_recent_products

    db = SessionLocal()
    try:
        products = get_recent_products(db, limit=limit)
        active = active_range()
        view = resolve_range(price_min, price_max)

        products = [
            p for p in products
            if price_in_range(p.get("price"), view)
        ]
        for p in products:
            p["outside_band"] = outside_range(p.get("price"), active)

        if verdict and verdict != "All":
            products = [p for p in products if (p.get("verdict") or "pending") == verdict]

        if q:
            ql = q.lower()
            products = [
                p for p in products
                if ql in (p.get("title") or "").lower()
            ]

        return {"products": products, "count": len(products), "range_filter": view}
    finally:
        db.close()


@router.get("/history/{product_id}")
def product_detail(product_id: int):
    """Full detail for one saved analysis (product, demand, suppliers, LLM, verdict).

    PR-2 layer 4: every figure served from storage is re-checked against the
    band — pre-gate rows never leak an out-of-band price to the UI.
    """
    from db.database import SessionLocal
    from db.models import Product, DemandData, SupplierMatch, Analysis, Verdict

    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        demand = db.query(DemandData).filter(DemandData.product_id == product_id).first()
        suppliers = db.query(SupplierMatch).filter(SupplierMatch.product_id == product_id).all()
        analysis = db.query(Analysis).filter(Analysis.product_id == product_id).first()
        verdict = db.query(Verdict).filter(Verdict.product_id == product_id).first()

        # Supplier prices are never range-gated (PR-1) — show every row.
        kept_suppliers = suppliers

        def _stat(v):
            return v if in_band(v) else None

        resp = {
            "product": {
                "id": product.id,
                "title": product.title,
                "price": product.price,
                # Same semantics as the list endpoint: a missing price is
                # never flagged, only a real price outside the active range.
                "outside_band": outside_range(product.price, active_range()),
                "condition": product.condition,
                "format": product.format,
                "seller": product.seller,
                "image_url": product.image_url,
                "category": product.category,
                "ebay_url": product.ebay_url,
                "created_at": product.created_at.isoformat() if product.created_at else None,
                "updated_at": product.updated_at.isoformat() if product.updated_at else None,
            },
            "demand": {
                "sold_count_30d": demand.sold_count_30d,
                "sold_count_7d": demand.sold_count_7d,
                "avg_sold_price": _stat(demand.avg_sold_price),
                "lowest_sold_price": _stat(demand.lowest_sold_price),
                "highest_sold_price": _stat(demand.highest_sold_price),
                "data_source": demand.data_source,
                "verified": demand.verified,
            } if demand else None,
            "suppliers": [
                {
                    "supplier_name": s.supplier_name,
                    "supplier_url": s.supplier_url,
                    "supplier_title": s.supplier_title,
                    "supplier_price": s.supplier_price,
                    "delivery_days_min": s.delivery_days_min,
                    "delivery_days_max": s.delivery_days_max,
                }
                for s in kept_suppliers
            ],
            "analysis": {
                "brand_verdict": analysis.brand_verdict,
                "brand_reasoning": analysis.brand_reasoning,
                "demand_assessment": analysis.demand_assessment,
                "demand_reasoning": analysis.demand_reasoning,
                "supplier_match_notes": analysis.supplier_match_notes,
                "llm_raw_response": analysis.llm_raw_response,
            } if analysis else None,
            "verdict": {
                "verdict": verdict.verdict,
                "profit_amount": verdict.profit_amount,
                "profit_margin": verdict.profit_margin,
                "filter_results": verdict.filter_results,
                "scorecard": verdict.scorecard,
            } if verdict else None,
        }
        return resp
    finally:
        db.close()
