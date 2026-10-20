"""The fee calculator API - every figure comes from engine/fees.py.

Two routes:

  GET  /api/fees/table      the table the calculator prices with: version
                            and sources, UI-ready category rows, and the
                            seller's own defaults (config.SELLER_PROFILE)
  POST /api/fees/calculate  one sale: forward (fees, profit and the itemised
                            lines the UI renders) or reverse (the price that
                            reaches a target margin, via `target_margin`)

The routes add no arithmetic and keep no fee constants. They validate
presence, hand the caller's values to the engine, and return what it
returns - including its refusal sentence when it declines to price a sale
(a zero or unread price never becomes a calculation), surfaced as 422.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from api.market_context import marketplace_for_optional_request, require_fee_market
from api.schemas import FeeCalculateRequest
from config import SELLER_PROFILE

router = APIRouter()


def _seller_side(req: FeeCalculateRequest) -> dict:
    """What the client sent, else the seller's own settings, field by field.

    The calculator must answer like the pipeline by default - same engine,
    same profile - so an unset field is a real answer, not a gap.
    """
    return {
        "category": (
            req.category if req.category is not None else SELLER_PROFILE["category"]
        ),
        "promoted_rate": (
            req.promoted_rate
            if req.promoted_rate is not None
            else SELLER_PROFILE["promoted_rate"]
        ),
        "seller_type": (
            req.seller_type
            if req.seller_type is not None
            else SELLER_PROFILE["seller_type"]
        ),
        "uk_resident": (
            req.uk_resident
            if req.uk_resident is not None
            else SELLER_PROFILE["uk_resident"]
        ),
        "vat_registered": (
            req.vat_registered
            if req.vat_registered is not None
            else SELLER_PROFILE["vat_registered"]
        ),
        "listing_fee": req.listing_fee,
        "buyer_region": req.buyer_region,
        "fee_table": req.fee_table or SELLER_PROFILE["fee_table"],
    }


@router.get("/fees/table")
def fee_table(request: Request = None, key: Optional[str] = None):
    """The table the calculator prices with, plus who is selling.

    `key` selects a specific table; omitted means the active one. An unknown
    key is refused with the known tables listed rather than silently priced
    under a different card. A non-UK marketplace is refused with a sentence:
    the only table shipped is eBay UK's.
    """
    from engine import fees as engine_fees

    market = marketplace_for_optional_request(request)
    require_fee_market(market)

    try:
        table = engine_fees.get_fee_table(key)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "fee_table": table,
        "categories": engine_fees.list_categories(table),
        "profile": SELLER_PROFILE,
        "marketplace": market["id"],
        "currency": market["currency"],
    }


@router.post("/fees/calculate")
def calculate(req: FeeCalculateRequest, request: Request = None):
    """One sale, forward or reverse, priced by the engine.

    Forward: `{mode, fee_table, calculation}` - the full money view, whose
    `fees.fee_table` also names the table. Reverse: `{mode, fee_table,
    achievable, price, reason, check, calculation?}` - the solved price, its
    recomputed check, and the same money view at that price so the caller
    can show the breakdown it just solved for.
    """
    from engine import fees as engine_fees

    market = marketplace_for_optional_request(request)
    require_fee_market(market)

    if req.sale_price is not None and req.target_margin is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                "send either sale_price (forward) or target_margin (reverse), "
                "not both"
            ),
        )
    if req.sale_price is None and req.target_margin is None:
        raise HTTPException(
            status_code=422,
            detail="sale_price (forward) or target_margin (reverse) is required",
        )

    seller_side = _seller_side(req)

    if req.target_margin is not None:
        try:
            table = engine_fees.get_fee_table(req.fee_table)
            solved = engine_fees.solve_for_margin(
                req.target_margin,
                supplier_cost=req.supplier_cost,
                postage_paid=req.postage_paid,
                risk_buffer_percent=req.risk_buffer_percent,
                packaging_cost=req.packaging_cost,
                postage_charged=req.postage_charged,
                **seller_side,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        payload = {
            "mode": "reverse",
            "fee_table": {
                "key": table["key"],
                "version": table["version"],
                "currency": table["currency"],
            },
            **{k: v for k, v in solved.items() if not k.startswith("_")},
        }
        if solved.get("achievable") and solved.get("price") is not None:
            try:
                payload["calculation"] = engine_fees.sale_outcome(
                    solved["price"],
                    supplier_cost=req.supplier_cost,
                    postage_paid=req.postage_paid,
                    risk_buffer_percent=req.risk_buffer_percent,
                    packaging_cost=req.packaging_cost,
                    postage_charged=req.postage_charged,
                    **seller_side,
                )
            except (KeyError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc))
        return payload

    try:
        outcome = engine_fees.sale_outcome(
            req.sale_price,
            supplier_cost=req.supplier_cost,
            postage_paid=req.postage_paid,
            risk_buffer_percent=req.risk_buffer_percent,
            packaging_cost=req.packaging_cost,
            postage_charged=req.postage_charged,
            **seller_side,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "mode": "forward",
        "fee_table": outcome["fees"]["fee_table"],
        "calculation": outcome,
    }
