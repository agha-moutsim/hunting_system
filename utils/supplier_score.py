"""
Supplier reliability scoring — track supplier performance over time.

Usage:
    from utils.supplier_score import SupplierScorer
    scorer = SupplierScorer()
    scorer.record("aliexpress", success=True, delivery_days=15)
    score = scorer.get_score("aliexpress")
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


SCORES_FILE = Path(__file__).parent.parent / "data" / "supplier_scores.json"


class SupplierScorer:
    """Track and score supplier reliability."""

    def __init__(self, filepath: str = None):
        self.filepath = Path(filepath) if filepath else SCORES_FILE
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

    def record(
        self,
        supplier: str,
        success: bool,
        delivery_days: int = None,
        price_accuracy: bool = None,
        notes: str = "",
    ):
        """Record a supplier interaction."""
        data = self._load()

        if supplier not in data:
            data[supplier] = {
                "total_orders": 0,
                "successful": 0,
                "failed": 0,
                "avg_delivery_days": [],
                "price_matches": 0,
                "price_mismatches": 0,
                "last_updated": None,
            }

        s = data[supplier]
        s["total_orders"] += 1

        if success:
            s["successful"] += 1
        else:
            s["failed"] += 1

        if delivery_days is not None:
            s["avg_delivery_days"].append(delivery_days)
            # Keep last 50 delivery times
            if len(s["avg_delivery_days"]) > 50:
                s["avg_delivery_days"] = s["avg_delivery_days"][-50:]

        if price_accuracy is not None:
            if price_accuracy:
                s["price_matches"] += 1
            else:
                s["price_mismatches"] += 1

        s["last_updated"] = datetime.now().isoformat()
        self._save(data)

    def get_score(self, supplier: str) -> dict:
        """Get supplier reliability score."""
        data = self._load()
        if supplier not in data:
            return {"supplier": supplier, "score": 0, "rating": "unknown"}

        s = data[supplier]
        total = s["total_orders"]
        if total == 0:
            return {"supplier": supplier, "score": 0, "rating": "unknown"}

        # Calculate score (0-100)
        success_rate = s["successful"] / total * 100

        # Average delivery days
        delivery = s.get("avg_delivery_days", [])
        avg_delivery = sum(delivery) / len(delivery) if delivery else 0

        # Price accuracy
        price_total = s["price_matches"] + s["price_mismatches"]
        price_accuracy = (s["price_matches"] / price_total * 100) if price_total > 0 else 50

        # Weighted score
        score = (success_rate * 0.5) + (price_accuracy * 0.3) + (min(100, max(0, 100 - avg_delivery * 2)) * 0.2)

        # Rating
        if score >= 80:
            rating = "excellent"
        elif score >= 60:
            rating = "good"
        elif score >= 40:
            rating = "fair"
        else:
            rating = "poor"

        return {
            "supplier": supplier,
            "score": round(score, 1),
            "rating": rating,
            "success_rate": round(success_rate, 1),
            "avg_delivery_days": round(avg_delivery, 1),
            "price_accuracy": round(price_accuracy, 1),
            "total_orders": total,
        }

    def get_all_scores(self) -> list[dict]:
        """Get scores for all suppliers."""
        data = self._load()
        return [self.get_score(s) for s in data.keys()]

    def get_rankings(self) -> list[dict]:
        """Get suppliers ranked by score."""
        scores = self.get_all_scores()
        return sorted(scores, key=lambda x: x["score"], reverse=True)
