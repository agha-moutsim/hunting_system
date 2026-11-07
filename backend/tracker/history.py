"""Price history queries and trend analysis."""

import math
from datetime import datetime, timedelta
from typing import Optional

from db.database import SessionLocal
from db.models import PriceHistory, TrackedProduct


def _read_price(value) -> Optional[float]:
    """A positive price, or None. Zero is the tracker's "not read" writer."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def get_price_history(tracked_id: int, days: int = 30) -> list[dict]:
    """Get price history for a tracked product."""
    db = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        history = (
            db.query(PriceHistory)
            .filter(
                PriceHistory.tracked_product_id == tracked_id,
                PriceHistory.checked_at >= since,
            )
            .order_by(PriceHistory.checked_at.asc())
            .all()
        )

        return [
            {
                "ebay_price": h.ebay_price,
                "supplier_price": h.supplier_price,
                "checked_at": h.checked_at.isoformat() if h.checked_at else None,
            }
            for h in history
        ]

    except Exception as e:
        print(f"[ERROR] Failed to get price history: {e}")
        return []
    finally:
        db.close()


def get_price_trend(tracked_id: int, days: int = 7) -> dict:
    """Get price trend (up/down/stable) over time.

    A trend is a comparison of two real readings. With fewer than two of them
    there is nothing to compare, so the answer is `unknown` with a null
    change - the old "stable, 0.0%" claimed a measured flat market from no
    evidence. Unread points (0.0, None, NaN) are skipped rather than allowed
    to become an endpoint.
    """
    history = get_price_history(tracked_id, days)
    prices = [
        price
        for price in (_read_price(point.get("ebay_price")) for point in history)
        if price is not None
    ]

    if len(prices) < 2:
        return {"trend": "unknown", "change": None, "change_percent": None}

    oldest_price = prices[0]
    newest_price = prices[-1]

    change = newest_price - oldest_price
    change_percent = (change / oldest_price) * 100

    if change < -0.50:
        trend = "down"
    elif change > 0.50:
        trend = "up"
    else:
        trend = "stable"

    return {
        "trend": trend,
        "change": round(change, 2),
        "change_percent": round(change_percent, 1),
    }


def get_all_price_trends(days: int = 7) -> dict:
    """Get price trends for all tracked products."""
    from tracker.price_tracker import get_tracked_products

    products = get_tracked_products()
    trends = {}

    for product in products:
        trend = get_price_trend(product["id"], days)
        trends[product["id"]] = trend

    return trends
