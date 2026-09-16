"""
Product bookmarks — save favorite products for later.

Usage:
    from utils.bookmarks import Bookmarks
    bm = Bookmarks()
    bm.add(product_id, title, price, url)
    favorites = bm.get_all()
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


BOOKMARKS_FILE = Path(__file__).parent.parent / "data" / "bookmarks.json"


class Bookmarks:
    """JSON-based product bookmarks."""

    def __init__(self, filepath: str = None):
        self.filepath = Path(filepath) if filepath else BOOKMARKS_FILE
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

    def add(
        self,
        product_id: int,
        title: str,
        price: float,
        url: str = "",
        notes: str = "",
    ) -> bool:
        """Bookmark a product."""
        bookmarks = self._load()

        # Check if already bookmarked
        if any(b.get("product_id") == product_id for b in bookmarks):
            return False

        bookmark = {
            "product_id": product_id,
            "title": title[:200],
            "price": price,
            "url": url,
            "notes": notes,
            "bookmarked_at": datetime.now().isoformat(),
        }

        bookmarks.insert(0, bookmark)
        self._save(bookmarks)
        return True

    def remove(self, product_id: int) -> bool:
        """Remove a bookmark."""
        bookmarks = self._load()
        new_bookmarks = [b for b in bookmarks if b.get("product_id") != product_id]
        if len(new_bookmarks) < len(bookmarks):
            self._save(new_bookmarks)
            return True
        return False

    def get_all(self) -> list[dict]:
        """Get all bookmarks."""
        return self._load()

    def is_bookmarked(self, product_id: int) -> bool:
        """Check if a product is bookmarked."""
        return any(b.get("product_id") == product_id for b in self._load())

    def count(self) -> int:
        return len(self._load())

    def clear(self):
        self._save([])
