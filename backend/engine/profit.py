from config import PROFIT_CONFIG


def calculate_profit(ebay_price: float, supplier_price: float) -> dict:
    """Calculate profit breakdown for a sourced product.

    The ONE money rule (CONSTRAINTS.md C3): eBay final value fee +
    listing fee, UK VAT applied to those fees, returns buffer, packaging.

    Returns dict with keys: profit, margin, ebay_fee, listing_fee,
    vat_on_fees, returns_buffer, total_fees, packaging_cost.
    """
    ebay_fee = ebay_price * (PROFIT_CONFIG["ebay_fee_percent"] / 100)
    listing_fee = ebay_price * (PROFIT_CONFIG["listing_fee_percent"] / 100)
    vat_on_fees = (ebay_fee + listing_fee) * (PROFIT_CONFIG["vat_on_fees_percent"] / 100)
    returns_buffer = ebay_price * (PROFIT_CONFIG["returns_buffer_percent"] / 100)
    packaging_cost = PROFIT_CONFIG["packaging_cost"]
    total_fees = ebay_fee + listing_fee + vat_on_fees + returns_buffer + packaging_cost

    profit = ebay_price - supplier_price - total_fees
    margin = (profit / ebay_price * 100) if ebay_price > 0 else 0.0

    return {
        "ebay_price": ebay_price,
        "supplier_price": supplier_price,
        "ebay_fee": round(ebay_fee, 2),
        "listing_fee": round(listing_fee, 2),
        "vat_on_fees": round(vat_on_fees, 2),
        "returns_buffer": round(returns_buffer, 2),
        "packaging_cost": round(packaging_cost, 2),
        "total_fees": round(total_fees, 2),
        "profit": round(profit, 2),
        "margin": round(margin, 1),
    }
