"""The C3 money rule - now a profile-driven view over engine/fees.py.

The arithmetic itself lives in engine/fees.py (Phase D), so the pipeline
verdict and the fee calculator call ONE implementation and cannot disagree
about what a sale costs (docs/plans/2026-10-19-feature-expansion,
constraints.md section 5: one implementation per calculation).

What this module keeps is the contract every caller already reads: the same
dict, the same keys, the same rounded figures. Since Phase D's switch it
computes from the PUBLISHED UK rate card (engine/fees.ACTIVE_TABLE) and the
seller side comes from config.SELLER_PROFILE - unless a caller overrides
either. Every result states the fee table that made it, so a figure computed
under the retired v1 model can never masquerade as one computed today. The
v1-static table stays selectable for reproducing pre-switch verdicts.
"""

from typing import Optional

from config import PROFIT_CONFIG, SELLER_PROFILE
from engine import fees


def calculate_profit(
    ebay_price: float,
    supplier_price: float,
    shipping_cost: float = 0.0,
    *,
    fee_table: Optional[str] = None,
    seller_type: Optional[str] = None,
    uk_resident: Optional[bool] = None,
    vat_registered: Optional[bool] = None,
    promoted_rate: Optional[float] = None,
    category=None,
    buyer_region: str = "uk",
) -> dict:
    """Calculate profit breakdown for a sourced product.

    The ONE money rule (CONSTRAINTS.md C3), implemented by engine/fees.py -
    see that module for the fee tables, their sources, and the rules a price
    must satisfy to be priced at all (a missing or zero price raises rather
    than producing a calculation).

    The seller side - type, VAT registration, promoted rate, category, fee
    table - defaults from config.SELLER_PROFILE; pass an override when a
    call site knows better (e.g. a private-seller drill-down).

    `shipping_cost` is the SELLER's postage to the buyer, which C3 did not
    model. It is optional because most paths never read it - but when it is
    absent the result is not a complete profit figure, so the dict says so
    rather than presenting a partial number as the whole truth (C1/C13).
    `shipping_cost=0.0` therefore means UNKNOWN, not "free": pass the real
    figure when you have it, and check `shipping_known` before quoting it.

    Returns dict with keys: profit, margin, ebay_fee, listing_fee,
    vat_on_fees, returns_buffer, total_fees, packaging_cost, shipping_cost,
    shipping_known, profit_is_complete, fee_table, breakdown. `breakdown`
    is the engine's full view of the sale (fee_lines included) for display
    surfaces - the same numbers, itemised, never a second calculation.
    """
    profile = SELLER_PROFILE
    outcome = fees.sale_outcome(
        ebay_price,
        supplier_cost=supplier_price,
        postage_paid=shipping_cost,
        risk_buffer_percent=PROFIT_CONFIG["returns_buffer_percent"],
        packaging_cost=PROFIT_CONFIG["packaging_cost"],
        category=category if category is not None else profile["category"],
        promoted_rate=(
            profile["promoted_rate"] if promoted_rate is None else promoted_rate
        ),
        seller_type=profile["seller_type"] if seller_type is None else seller_type,
        uk_resident=profile["uk_resident"] if uk_resident is None else uk_resident,
        vat_registered=(
            profile["vat_registered"] if vat_registered is None else vat_registered
        ),
        buyer_region=buyer_region,
        fee_table=fee_table or profile["fee_table"] or fees.ACTIVE_TABLE,
    )

    # The legacy contract: `total_fees` is everything subtracted from the
    # sale besides the supplier - eBay's fees, the returns buffer,
    # packaging and the postage itself - so callers that print it keep
    # their meaning.
    total_fees = (
        outcome["_cost_raw"]
        + outcome["_buffer_raw"]
        + outcome["_packaging_raw"]
        + outcome["_shipping_displayed"]
    )
    supplier_known = outcome["supplier_cost"] is not None

    return {
        "ebay_price": outcome["price"],
        "supplier_price": outcome["supplier_cost"],
        "ebay_fee": outcome["fees"]["fvf"],
        "listing_fee": outcome["fees"]["listing_fee"],
        "vat_on_fees": outcome["fees"]["vat_on_fees"],
        "returns_buffer": outcome["risk_buffer"],
        "packaging_cost": outcome["packaging_cost"],
        "shipping_cost": outcome["postage_paid"],
        # C1/C13 - these two are the difference between "this product makes
        # GBPx" and "this product makes at least GBPx, postage not known".
        "shipping_known": outcome["postage_paid_known"],
        "profit_is_complete": bool(outcome["postage_paid_known"] and supplier_known),
        "total_fees": round(total_fees, 2),
        "profit": outcome["profit"],
        "margin": outcome["margin"],
        # Every money figure states which fee table made it, so a verdict
        # computed under an old model can never masquerade as one computed
        # under the current card.
        "fee_table": outcome["fees"]["fee_table"],
        # The engine's own view of the sale, itemised (fee_lines, the fee
        # keys, assumptions and notes). Display surfaces render this;
        # nothing recomputes from constants beside it.
        "breakdown": {k: v for k, v in outcome.items() if not k.startswith("_")},
    }
