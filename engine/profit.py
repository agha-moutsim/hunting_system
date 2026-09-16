from config import PROFIT_CONFIG


def calculate_profit(ebay_price: float, supplier_price: float) -> dict:
    """Calculate profit breakdown for a sourced product.

    Returns dict with keys: profit, margin, ebay_fee, returns_buffer,
    total_fees, packaging_cost.
    """
    ebay_fee = ebay_price * (PROFIT_CONFIG["ebay_fee_percent"] / 100)
    returns_buffer = ebay_price * (PROFIT_CONFIG["returns_buffer_percent"] / 100)
    packaging_cost = PROFIT_CONFIG["packaging_cost"]
    total_fees = ebay_fee + returns_buffer + packaging_cost

    profit = ebay_price - supplier_price - total_fees
    margin = (profit / ebay_price * 100) if ebay_price > 0 else 0.0

    return {
        "ebay_price": ebay_price,
        "supplier_price": supplier_price,
        "ebay_fee": round(ebay_fee, 2),
        "returns_buffer": round(returns_buffer, 2),
        "packaging_cost": round(packaging_cost, 2),
        "total_fees": round(total_fees, 2),
        "profit": round(profit, 2),
        "margin": round(margin, 1),
    }
