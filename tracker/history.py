"""Price history queries and trend analysis."""

from datetime import datetime, timedelta
from typing import Optional

from db.database import SessionLocal
from db.models import PriceHistory, TrackedProduct


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
    """Get price trend (up/down/stable) over time."""
    history = get_price_history(tracked_id, days)

    if len(history) < 2:
        return {"trend": "stable", "change": 0.0, "change_percent": 0.0}

    oldest_price = history[0]["ebay_price"]
    newest_price = history[-1]["ebay_price"]

    if oldest_price <= 0 or newest_price <= 0:
        return {"trend": "stable", "change": 0.0, "change_percent": 0.0}

    change = newest_price - oldest_price
    change_percent = (change / oldest_price) * 100 if oldest_price > 0 else 0

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
