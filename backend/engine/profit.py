"""The C3 money rule - now a naming layer over engine/fees.py.

The arithmetic itself moved to engine/fees.py (Phase D), so the pipeline
verdict and the fee calculator call ONE implementation and cannot disagree
about what a sale costs (docs/plans/2026-10-19-feature-expansion,
constraints.md section 5: one implementation per calculation).

What this module keeps is the contract every caller already reads: the
same dict, the same keys, the same rounded figures. It computes them from
the v1-static table, which is the exact model CONSTRAINTS.md C3 pinned -
13.5% final value fee + 0.03% listing fee + 20% VAT on eBay's fees + 3%
returns buffer, on the item price. Switching the active model to the
published rate card is a deliberate step taken where the seller profile is
read, not something that happens here by accident.
"""

from typing import Optional

from config import PROFIT_CONFIG
from engine import fees


def calculate_profit(
    ebay_price: float,
    supplier_price: float,
    shipping_cost: float = 0.0,
    *,
    fee_table: Optional[str] = None,
) -> dict:
    """Calculate profit breakdown for a sourced product.

    The ONE money rule (CONSTRAINTS.md C3), implemented by engine/fees.py
    - see that module for the fee tables, their sources, and the rules a
    price must satisfy to be priced at all (a missing or zero price raises
    rather than producing a calculation).

    `shipping_cost` is the SELLER's postage to the buyer, which C3 did not
    model. It is optional because most paths never read it - but when it is
    absent the result is not a complete profit figure, so the dict says so
    rather than presenting a partial number as the whole truth (C1/C13).
    `shipping_cost=0.0` therefore means UNKNOWN, not "free": pass the real
    figure when you have it, and check `shipping_known` before quoting it.

    Returns dict with keys: profit, margin, ebay_fee, listing_fee,
    vat_on_fees, returns_buffer, total_fees, packaging_cost, shipping_cost,
    shipping_known, profit_is_complete, fee_table.

    `fee_table` selects the engine's table; the default is v1-static so
    existing verdicts keep their numbers. Pass
    `fee_table=fees.RATE_CARD_TABLE` to compute from the published card.
    """
    outcome = fees.sale_outcome(
        ebay_price,
        supplier_cost=supplier_price,
        postage_paid=shipping_cost,
        risk_buffer_percent=PROFIT_CONFIG["returns_buffer_percent"],
        packaging_cost=PROFIT_CONFIG["packaging_cost"],
        seller_type="business",
        fee_table=fee_table or fees.V1_STATIC_TABLE,
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
        # New in Phase D: every money figure states which fee table made it,
        # so a verdict computed under an old model can never masquerade as
        # one computed under the current card.
        "fee_table": outcome["fees"]["fee_table"],
    }
