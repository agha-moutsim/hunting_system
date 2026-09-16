"""
Local search history — stores recent searches in JSON file.

Usage:
    from utils.history import SearchHistory
    history = SearchHistory()
    history.add("wireless earbuds", results)
    recent = history.get_recent(10)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


HISTORY_FILE = Path(__file__).parent.parent / "data" / "search_history.json"


class SearchHistory:
    """Simple JSON-based search history."""

    def __init__(self, filepath: str = None):
        self.filepath = Path(filepath) if filepath else HISTORY_FILE
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

    def add(self, query: str, results: dict, verdict: str = None):
        """Add a search to history."""
        history = self._load()

        entry = {
            "id": len(history) + 1,
            "query": query,
            "timestamp": datetime.now().isoformat(),
            "verdict": verdict,
            "ebay_price": results.get("ebay_product", {}).get("price"),
            "product_title": results.get("ebay_product", {}).get("title", "")[:100],
            "supplier_count": len(results.get("supplier_matches", [])),
            "errors": results.get("errors", []),
        }

        history.insert(0, entry)  # Newest first

        # Keep only last 100 entries
        if len(history) > 100:
            history = history[:100]

        self._save(history)
        return entry["id"]

    def get_recent(self, limit: int = 20) -> list[dict]:
        """Get recent searches."""
        return self._load()[:limit]

    def get_by_id(self, entry_id: int) -> Optional[dict]:
        """Get a specific entry by ID."""
        for entry in self._load():
            if entry.get("id") == entry_id:
                return entry
        return None

    def search(self, query: str) -> list[dict]:
        """Search history by query text."""
        query_lower = query.lower()
        return [
            e for e in self._load()
            if query_lower in e.get("query", "").lower()
        ]

    def clear(self):
        """Clear all history."""
        self._save([])

    def get_stats(self) -> dict:
        """Get history statistics."""
        history = self._load()
        verdicts = {}
        for e in history:
            v = e.get("verdict", "pending")
            verdicts[v] = verdicts.get(v, 0) + 1

        return {
            "total_searches": len(history),
            "verdicts": verdicts,
            "last_search": history[0]["timestamp"] if history else None,
        }
