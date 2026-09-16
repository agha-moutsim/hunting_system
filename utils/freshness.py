"""
Data freshness checker — validate data currency across the system.

Usage:
    from utils.freshness import FreshnessChecker
    checker = FreshnessChecker()
    status = checker.check_all()
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class FreshnessChecker:
    """Check data freshness across the system."""

    def __init__(self, max_age_hours: int = 24):
        self.max_age_hours = max_age_hours
        self.data_dir = Path(__file__).parent.parent / "data"

    def check_file(self, filepath: str) -> dict:
        """Check freshness of a JSON data file."""
        path = Path(filepath) if not filepath.startswith("/") else Path(filepath)

        if not path.exists():
            return {
                "file": str(path.name),
                "exists": False,
                "fresh": False,
                "age_hours": None,
                "message": "File not found",
            }

        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        age = datetime.now() - mtime
        age_hours = age.total_seconds() / 3600

        return {
            "file": str(path.name),
            "exists": True,
            "fresh": age_hours <= self.max_age_hours,
            "age_hours": round(age_hours, 1),
            "last_modified": mtime.isoformat(),
            "message": f"{'Fresh' if age_hours <= self.max_age_hours else 'Stale'} ({age_hours:.1f}h old)",
        }

    def check_all(self) -> list[dict]:
        """Check freshness of all data files."""
        files = [
            self.data_dir / "search_history.json",
            self.data_dir / "bookmarks.json",
            self.data_dir / "notifications.json",
            self.data_dir / "price_history.json",
        ]

        results = []
        for f in files:
            results.append(self.check_file(str(f)))

        return results

    def get_stale_items(self) -> list[dict]:
        """Get all stale data items."""
        return [r for r in self.check_all() if not r.get("fresh", True)]

    def get_summary(self) -> dict:
        """Get freshness summary."""
        all_items = self.check_all()
        fresh = [i for i in all_items if i.get("fresh")]
        stale = [i for i in all_items if not i.get("fresh")]

        return {
            "total_files": len(all_items),
            "fresh": len(fresh),
            "stale": len(stale),
            "all_fresh": len(stale) == 0,
        }

    def format_report(self) -> str:
        """Format freshness report for display."""
        items = self.check_all()
        lines = ["\nData Freshness Report:\n"]

        for item in items:
            status = "✓" if item.get("fresh") else "✗"
            age = f"{item['age_hours']}h" if item.get("age_hours") else "N/A"
            lines.append(f"  {status} {item['file']:<25} {item['message']}")

        lines.append("")
        return "\n".join(lines)
