"""
Profit trend tracking — track profitability over time.

Usage:
    from utils.profit_trends import ProfitTrends
    trends = ProfitTrends()
    trends.record(product_id, profit=5.50, margin=34.2)
    summary = trends.get_summary()
"""

import json
from datetime import datetime, timedelta
from pathlib import Path


TRENDS_FILE = Path(__file__).parent.parent / "data" / "profit_trends.json"


class ProfitTrends:
    """Track profit trends over time."""

    def __init__(self, filepath: str = None):
        self.filepath = Path(filepath) if filepath else TRENDS_FILE
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file()

    def _ensure_file(self):
        if not self.filepath.exists():
            self.filepath.write_text("[]")

    def _load(self) -> list[dict]:
        try:
            return json.loads(self.filepath.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save(self, data: list[dict]):
        self.filepath.write_text(json.dumps(data, indent=2, default=str))

    def record(
        self,
        product_id: int,
        profit: float,
        margin: float,
        title: str = "",
        query: str = "",
    ):
        """Record a profit observation."""
        data = self._load()

        entry = {
            "product_id": product_id,
            "profit": profit,
            "margin": margin,
            "title": title[:100],
            "query": query[:100],
            "timestamp": datetime.now().isoformat(),
        }

        data.append(entry)

        # Keep last 500 entries
        if len(data) > 500:
            data = data[-500:]

        self._save(data)

    def get_recent(self, days: int = 30) -> list[dict]:
        """Get recent profit records."""
        data = self._load()
        cutoff = datetime.now() - timedelta(days=days)

        return [
            e for e in data
            if datetime.fromisoformat(e["timestamp"]) >= cutoff
        ]

    def get_summary(self, days: int = 30) -> dict:
        """Get profit summary for a period."""
        recent = self.get_recent(days)

        if not recent:
            return {
                "period_days": days,
                "total_products": 0,
                "avg_profit": 0,
                "avg_margin": 0,
                "total_profit": 0,
                "best_product": None,
                "worst_product": None,
            }

        profits = [e["profit"] for e in recent]
        margins = [e["margin"] for e in recent]

        return {
            "period_days": days,
            "total_products": len(recent),
            "avg_profit": round(sum(profits) / len(profits), 2),
            "avg_margin": round(sum(margins) / len(margins), 1),
            "total_profit": round(sum(profits), 2),
            "max_profit": round(max(profits), 2),
            "min_profit": round(min(profits), 2),
            "profitable_count": len([p for p in profits if p > 0]),
            "loss_count": len([p for p in profits if p <= 0]),
            "best_product": max(recent, key=lambda x: x["profit"])["title"] if recent else None,
            "worst_product": min(recent, key=lambda x: x["profit"])["title"] if recent else None,
        }

    def get_daily_trend(self, days: int = 7) -> list[dict]:
        """Get daily profit trend."""
        recent = self.get_recent(days)
        daily = {}

        for e in recent:
            date = e["timestamp"][:10]
            if date not in daily:
                daily[date] = {"date": date, "profits": [], "count": 0}
            daily[date]["profits"].append(e["profit"])
            daily[date]["count"] += 1

        result = []
        for date in sorted(daily.keys()):
            d = daily[date]
            result.append({
                "date": date,
                "avg_profit": round(sum(d["profits"]) / len(d["profits"]), 2),
                "total_profit": round(sum(d["profits"]), 2),
                "count": d["count"],
            })

        return result
