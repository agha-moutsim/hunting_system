"""
Competitor price tracking — monitor eBay listing prices over time.

Usage:
    from utils.price_tracker import PriceTracker
    tracker = PriceTracker()
    tracker.record(product_id, price=12.99)
    history = tracker.get_history(product_id)
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


PRICE_HISTORY_FILE = Path(__file__).parent.parent / "data" / "price_history.json"


class PriceTracker:
    """Track product prices over time."""

    def __init__(self, filepath: str = None):
        self.filepath = Path(filepath) if filepath else PRICE_HISTORY_FILE
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file()

    def _ensure_file(self):
        if not self.filepath.exists():
            self.filepath.write_text("{}")

    def _load(self) -> dict:
        try:
            return json.loads(self.filepath.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save(self, data: dict):
        self.filepath.write_text(json.dumps(data, indent=2, default=str))

    def record(self, product_id: int, price: float, source: str = "ebay"):
        """Record a price observation."""
        data = self._load()
        key = str(product_id)

        if key not in data:
            data[key] = {"product_id": product_id, "observations": []}

        data[key]["observations"].append({
            "price": price,
            "source": source,
            "timestamp": datetime.now().isoformat(),
        })

        # Keep last 100 observations per product
        if len(data[key]["observations"]) > 100:
            data[key]["observations"] = data[key]["observations"][-100:]

        self._save(data)

    def get_history(self, product_id: int, days: int = 30) -> list[dict]:
        """Get price history for a product."""
        data = self._load()
        key = str(product_id)
        if key not in data:
            return []

        cutoff = datetime.now() - timedelta(days=days)
        observations = data[key].get("observations", [])

        return [
            o for o in observations
            if datetime.fromisoformat(o["timestamp"]) >= cutoff
        ]

    def get_latest(self, product_id: int) -> Optional[dict]:
        """Get most recent price observation."""
        history = self.get_history(product_id, days=90)
        return history[-1] if history else None

    def get_price_change(self, product_id: int, days: int = 7) -> Optional[dict]:
        """Calculate price change over a period."""
        history = self.get_history(product_id, days=days + 1)
        if len(history) < 2:
            return None

        old_price = history[0]["price"]
        new_price = history[-1]["price"]
        change = new_price - old_price
        pct = (change / old_price * 100) if old_price > 0 else 0

        return {
            "old_price": old_price,
            "new_price": new_price,
            "change": round(change, 2),
            "change_pct": round(pct, 1),
            "direction": "up" if change > 0 else "down" if change < 0 else "stable",
        }

    def get_all_tracked(self) -> list[dict]:
        """Get all tracked products."""
        data = self._load()
        result = []
        for key, value in data.items():
            history = value.get("observations", [])
            if history:
                result.append({
                    "product_id": value.get("product_id"),
                    "latest_price": history[-1]["price"],
                    "observations": len(history),
                    "last_seen": history[-1]["timestamp"],
                })
        return result
