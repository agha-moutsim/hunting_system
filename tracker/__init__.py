"""Price Tracker module — track products and get alerts."""

from tracker.price_tracker import add_to_tracker, remove_from_tracker, get_tracked_products, update_tracked_product
from tracker.price_checker import check_all_prices, check_single_price
from tracker.alerts import get_alerts, mark_alert_read, generate_alert
from tracker.history import get_price_history, get_price_trend

__all__ = [
    "add_to_tracker",
    "remove_from_tracker",
    "get_tracked_products",
    "update_tracked_product",
    "check_all_prices",
    "check_single_price",
    "get_alerts",
    "mark_alert_read",
    "generate_alert",
    "get_price_history",
    "get_price_trend",
]
