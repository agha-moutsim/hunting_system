"""History endpoints — past analyses + product detail."""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

from engine.price_gate import in_band
from utils.filters import active_range, outside_range, price_in_range, resolve_range
from api.schemas import SourcedFigure

router = APIRouter()
logger = logging.getLogger(__name__)


def _as_utc_z(value) -> dict:
    """A stored datetime as an exact instant, or None when nothing was stored.

    Naive-and-assumed-UTC is what every other timestamp in this payload is, and
    the client carries `asUtc()` to patch that legacy; a figure read here can
    simply say which instant it is, so it does.
    """
    if value is None:
        return None
    return f"{value.isoformat()}Z"


def _figure(value, origin, observed_at=None):
    """One figure as {value, origin, observed_at}, or None when there is none.

    A figure with no value is not a figure, so the slot is dropped entirely
    rather than emitted as {"value": null, "origin": ...}: an origin badge must
    never be able to render over a number that does not exist. A value that IS
    present but whose origin was never recorded still comes through, with
    origin=None, and the UI says so rather than guessing.
    """
    if value is None:
        return None
    return SourcedFigure(
        value=value,
        origin=origin,
        observed_at=_as_utc_z(observed_at),
    ).model_dump()


def _serialize_observation(row) -> dict:
    """One stored Browse reading, replayed exactly as it was recorded.

    Built from `browse_fields.FIELDS` rather than a second hand-written list, so
    a field can never be added to the extractor and silently omitted from the
    replay. A null value means the Browse API did not return that field, and the
    client must never be able to read it as a zero.
    """
    from scrapers.browse_fields import FIELDS

    payload = {
        "listing_id": row.listing_id,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "source": row.source,
    }
    for name in FIELDS:
        value = getattr(row, name)
        payload[name] = value.isoformat() if isinstance(value, datetime) else value
    return payload


def _observations_block(db, listing_id) -> dict:
    """The Browse readings held for this product's listing.

    A product whose listing was never observed returns an empty block rather
    than a placeholder: History must not imply a reading that was never taken.
    """
    if not listing_id:
        return {"listing_id": "", "returned": 0, "readings": []}

    from db.queries import get_listing_observations

    rows = get_listing_observations(db, listing_id)
    return {
        "listing_id": str(listing_id),
        # How many readings this response carries, newest first. Named
        # `returned` on purpose: it is not a total, and a deeper history exists
        # in the table than a single product page needs to draw.
        "returned": len(rows),
        "readings": [_serialize_observation(row) for row in rows],
    }


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
                # The date of the most recent sale, when a capture read one.
                # Served since Phase C: the column existed and the payload did
                # not carry it, so the Sources view would have listed a stored
                # figure as "not known" — the same defect as showing a sale
                # nobody measured, pointed the other way.
                "last_sale_date": demand.last_sale_date,
                "avg_sold_price": _stat(demand.avg_sold_price),
                "lowest_sold_price": _stat(demand.lowest_sold_price),
                "highest_sold_price": _stat(demand.highest_sold_price),
                # A3 — the observations behind those figures, so replaying an
                # old run redraws the same chart the live screen showed. A row
                # saved before this column existed reads None and the chart
                # simply does not render; it never falls back to invented
                # points.
                "sold_prices": list(demand.sold_prices or []),
                # The SUPPLY-side set, replayed beside the sold one and kept
                # separate in the payload for the same reason it is separate in
                # the table. A live run and a replayed one now report the same
                # value for each, which they did not while
                # `active_listings_in_band` went unwritten.
                "active_listings_in_band": demand.active_listings_in_band,
                "avg_active_price": _stat(demand.avg_active_price),
                "lowest_active_price": _stat(demand.lowest_active_price),
                "highest_active_price": _stat(demand.highest_active_price),
                "active_prices": list(demand.active_prices or []),
                "data_source": demand.data_source,
                "verified": demand.verified,
                # PHASE C — the sold figures with their provenance attached, so
                # a screen can render where each number came from and when that
                # source read it, instead of a bare integer whose meaning gets
                # chosen by which slot it sits in.
                #
                # Only the 7-day figure can be attributed, because only it has a
                # recorded producer: the capture extension reading the user's own
                # purchase history. A 30-day sold count has no source this app
                # can reach, so if a value ever appears in that slot this
                # serialiser still reports origin=None rather than filing it
                # under the 7-day figure's source.
                #
                # A slot reading null is not an error state: it is how the
                # Sources view knows a figure was never measured, and it must
                # never be dressed up as a zero.
                "figures": {
                    "sold_count_7d": _figure(
                        demand.sold_count_7d,
                        demand.sold_source,
                        demand.sold_captured_at,
                    ),
                    "sold_count_30d": _figure(demand.sold_count_30d, None, None),
                },
            } if demand else None,
            "suppliers": [
                {
                    "supplier_name": s.supplier_name,
                    "supplier_url": s.supplier_url,
                    "supplier_title": s.supplier_title,
                    "supplier_price": s.supplier_price,
                    "delivery_days_min": s.delivery_days_min,
                    "delivery_days_max": s.delivery_days_max,
                    # C13 — replay what the live screen showed. Rows saved
                    # before these columns existed return NULL, and a NULL
                    # provenance renders no badge: absence is not a claim
                    # that the row was verified.
                    "provenance": s.provenance,
                    "provenance_label": s.provenance_label,
                    "fetch_method": s.fetch_method,
                    "verified": s.verified,
                    "review_rating": s.review_rating,
                    "review_count": s.review_count,
                    "review_verified": s.review_verified,
                    "review_source": s.review_source,
                    "stock_status": s.stock_status,
                    "stock_verified": s.stock_verified,
                    "shipping_known": s.shipping_known,
                    "shipping_methods": s.shipping_methods,
                    "standard_shipping_available": s.standard_shipping_available,
                    "standard_shipping_cost": s.standard_shipping_cost,
                    "standard_shipping_days_min": s.standard_shipping_days_min,
                    "standard_shipping_days_max": s.standard_shipping_days_max,
                    "standard_shipping_raw": s.standard_shipping_raw,
                    "total_landed_cost": s.total_landed_cost,
                    "sourcing_preferred": s.sourcing_preferred,
                    "sourcing_eligible": s.sourcing_eligible,
                    "sourcing_reasons": s.sourcing_reasons,
                    "sourcing_score": s.sourcing_score,
                    "sourcing_policy_version": s.sourcing_policy_version,
                }
                for s in kept_suppliers
            ],
            # The Browse readings behind this listing, replayed so a saved
            # analysis shows what was measured and not merely what was computed
            # from it. Absent for a product whose listing was never observed.
            "observations": _observations_block(db, product.ebay_listing_id),
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
