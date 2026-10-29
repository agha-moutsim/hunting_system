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
from marketplaces import seller_defaults

router = APIRouter()


def _market_table(market: dict, requested_key: Optional[str] = None) -> dict:
    """The card this market may price with, or a 422 sentence.

    The market's registered card is the default. An explicit key is allowed
    only when its currency matches the market's: a GBP card under an AUD
    heading would turn a real rate into a fabricated cross-currency number.
    """
    from engine import fees as engine_fees
    from marketplaces import fee_warning

    key = requested_key or market.get("fee_table")
    if not key:
        raise HTTPException(status_code=422, detail=fee_warning(market))
    try:
        table = engine_fees.get_fee_table(key)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if table["currency"] != market["currency"]:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Fee table {table['key']} prices in {table['currency']}; "
                f"{market['label']} prices in {market['currency']}. "
                "A fee card is never applied across currencies."
            ),
        )
    return table


def _seller_side(req: FeeCalculateRequest, market: dict) -> dict:
    """What the client sent, else the market's defaults, then the profile.

    The market answer comes first because "business, UK resident, domestic UK
    buyer" is a UK branch, not a universal one. The AU card starts private and
    domestic-AU; its Pro Starter plan is only materialised when the caller
    selects a business sale. The seller's own profile still fills fields the
    market does not state, so an unset field remains a real answer.
    """
    defaults = seller_defaults(market)
    seller_type = req.seller_type
    if seller_type is None:
        seller_type = defaults["seller_type"] or SELLER_PROFILE["seller_type"]

    seller_plan = req.seller_plan
    if seller_plan is None and seller_type == "business":
        seller_plan = defaults["seller_plan"]

    uk_resident = req.uk_resident
    if uk_resident is None:
        uk_resident = defaults["uk_resident"]
    if uk_resident is None:
        uk_resident = SELLER_PROFILE["uk_resident"]

    vat_registered = req.vat_registered
    if vat_registered is None:
        vat_registered = defaults["vat_registered"]
    if vat_registered is None:
        vat_registered = SELLER_PROFILE["vat_registered"]

    return {
        "category": (
            req.category if req.category is not None else SELLER_PROFILE["category"]
        ),
        "promoted_rate": (
            req.promoted_rate
            if req.promoted_rate is not None
            else SELLER_PROFILE["promoted_rate"]
        ),
        "seller_type": seller_type,
        "seller_plan": seller_plan,
        "uk_resident": uk_resident,
        "vat_registered": vat_registered,
        "listing_fee": req.listing_fee,
        "buyer_region": req.buyer_region or defaults["buyer_region"],
        "fee_table": req.fee_table or market.get("fee_table"),
    }


@router.get("/fees/table")
def fee_table(request: Request = None, key: Optional[str] = None):
    """The table the calculator prices with, plus who is selling.

    `key` selects a specific table; omitted means the market's own registered
    card, never the engine's active table by accident. An unknown key is
    refused with the known tables listed, and a table whose currency differs
    from the market's is refused rather than applied across currencies.
    """
    from engine import fees as engine_fees

    market = marketplace_for_optional_request(request)
    require_fee_market(market)
    table = _market_table(market, key)

    return {
        "fee_table": table,
        "categories": engine_fees.list_categories(table),
        "profile": SELLER_PROFILE,
        "market_defaults": seller_defaults(market),
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

    table = _market_table(market, req.fee_table)
    seller_side = _seller_side(req, market)
    seller_side["fee_table"] = table["key"]

    if req.target_margin is not None:
        try:
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
