"""History endpoints — past analyses + product detail."""

import logging

from fastapi import APIRouter, HTTPException

from engine.price_gate import band_label, excluded_note, in_band

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/history")
def list_history(verdict: str = "All", q: str = "", limit: int = 50):
    """Recent analyses with optional verdict filter and text search.

    PR-2 layer 4: out-of-band rows stored before the gate existed are
    filtered on read and counted — never shown, never silently dropped.
    """
    from db.database import SessionLocal
    from db.queries import get_recent_products

    db = SessionLocal()
    try:
        products = get_recent_products(db, limit=limit)
        before = len(products)
        products = [p for p in products if in_band(p.get("price"))]
        excluded = before - len(products)

        if verdict and verdict != "All":
            products = [p for p in products if (p.get("verdict") or "pending") == verdict]

        if q:
            ql = q.lower()
            products = [
                p for p in products
                if ql in (p.get("title") or "").lower()
            ]

        resp = {"products": products, "count": len(products)}
        if excluded:
            resp["excluded_note"] = excluded_note("saved analyses", excluded)
        return resp
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
        if not in_band(product.price):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"This saved listing is £{product.price:.2f} — outside your "
                    f"{band_label()} band."
                ),
            )

        demand = db.query(DemandData).filter(DemandData.product_id == product_id).first()
        suppliers = db.query(SupplierMatch).filter(SupplierMatch.product_id == product_id).all()
        analysis = db.query(Analysis).filter(Analysis.product_id == product_id).first()
        verdict = db.query(Verdict).filter(Verdict.product_id == product_id).first()

        kept_suppliers = [s for s in suppliers if in_band(s.supplier_price)]
        excluded_suppliers = len(suppliers) - len(kept_suppliers)

        def _stat(v):
            return v if in_band(v) else None

        resp = {
            "product": {
                "id": product.id,
                "title": product.title,
                "price": product.price,
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
        if excluded_suppliers:
            resp["excluded_note"] = excluded_note("supplier matches", excluded_suppliers)
        return resp
    finally:
        db.close()
