from config import PROFIT_CONFIG


def calculate_profit(
    ebay_price: float,
    supplier_price: float,
    shipping_cost: float = 0.0,
) -> dict:
    """Calculate profit breakdown for a sourced product.

    The ONE money rule (CONSTRAINTS.md C3): eBay final value fee +
    listing fee, UK VAT applied to those fees, returns buffer, packaging,
    plus any shipping we actually know about.

    `shipping_cost` is the SELLER's postage to the buyer, which C3 did not
    model. It is optional because most paths never read it - but when it is
    absent the result is not a complete profit figure, so the dict says so
    rather than presenting a partial number as the whole truth (C1/C13).
    `shipping_cost=0.0` therefore means UNKNOWN, not "free": pass the real
    figure when you have it, and check `shipping_known` before quoting it.

    Returns dict with keys: profit, margin, ebay_fee, listing_fee,
    vat_on_fees, returns_buffer, total_fees, packaging_cost, shipping_cost,
    shipping_known, profit_is_complete.
    """
    ebay_fee = ebay_price * (PROFIT_CONFIG["ebay_fee_percent"] / 100)
    listing_fee = ebay_price * (PROFIT_CONFIG["listing_fee_percent"] / 100)
    vat_on_fees = (ebay_fee + listing_fee) * (PROFIT_CONFIG["vat_on_fees_percent"] / 100)
    returns_buffer = ebay_price * (PROFIT_CONFIG["returns_buffer_percent"] / 100)
    packaging_cost = PROFIT_CONFIG["packaging_cost"]
    total_fees = ebay_fee + listing_fee + vat_on_fees + returns_buffer + packaging_cost

    # A negative figure would be nonsense to add, and 0.0 is the "we did not
    # read one" sentinel used across the scrapers, so treat it as unknown.
    try:
        shipping = float(shipping_cost)
    except (TypeError, ValueError):
        shipping = 0.0
    # Known means known AS DISPLAYED: anything that rounds away to £0.00 is
    # noise, not a postage reading. Deciding on the raw value let a £0.004
    # reading through - subtracted from the profit, printed as £0.00, and
    # still stamped shipping_known/profit_is_complete - which produced a
    # profit a penny below the sum of its own printed parts.
    shipping_known = round(shipping, 2) > 0
    shipping_cost = round(shipping, 2) if shipping_known else 0.0

    profit = ebay_price - supplier_price - total_fees - shipping_cost
    margin = (profit / ebay_price * 100) if ebay_price > 0 else 0.0

    return {
        "ebay_price": ebay_price,
        "supplier_price": supplier_price,
        "ebay_fee": round(ebay_fee, 2),
        "listing_fee": round(listing_fee, 2),
        "vat_on_fees": round(vat_on_fees, 2),
        "returns_buffer": round(returns_buffer, 2),
        "packaging_cost": round(packaging_cost, 2),
        "shipping_cost": round(shipping_cost, 2),
        # C1/C13 - these two are the difference between "this product makes
        # GBPx" and "this product makes at least GBPx, postage not known".
        "shipping_known": shipping_known,
        "profit_is_complete": shipping_known,
        "total_fees": round(total_fees + shipping_cost, 2),
        "profit": round(profit, 2),
        "margin": round(margin, 1),
    }
