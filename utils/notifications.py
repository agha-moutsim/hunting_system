"""
Notification system — alerts for price drops and opportunities.

Usage:
    from utils.notifications import Notifier
    notifier = Notifier()
    notifier.add("price_drop", "Wireless Earbuds dropped to £8.99")
    alerts = notifier.get_unread()
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


NOTIFICATIONS_FILE = Path(__file__).parent.parent / "data" / "notifications.json"


class Notifier:
    """Simple notification system."""

    def __init__(self, filepath: str = None):
        self.filepath = Path(filepath) if filepath else NOTIFICATIONS_FILE
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
        notification_type: str,
        message: str,
        product_id: int = None,
        priority: str = "normal",
    ) -> int:
        """Add a notification."""
        notifications = self._load()

        notif = {
            "id": len(notifications) + 1,
            "type": notification_type,
            "message": message,
            "product_id": product_id,
            "priority": priority,
            "read": False,
            "created_at": datetime.now().isoformat(),
        }

        notifications.insert(0, notif)
        self._save(notifications)
        return notif["id"]

    def get_all(self, unread_only: bool = False) -> list[dict]:
        """Get notifications."""
        notifications = self._load()
        if unread_only:
            return [n for n in notifications if not n.get("read")]
        return notifications

    def get_unread(self) -> list[dict]:
        return self.get_all(unread_only=True)

    def mark_read(self, notif_id: int):
        """Mark a notification as read."""
        notifications = self._load()
        for n in notifications:
            if n.get("id") == notif_id:
                n["read"] = True
                break
        self._save(notifications)

    def mark_all_read(self):
        """Mark all as read."""
        notifications = self._load()
        for n in notifications:
            n["read"] = True
        self._save(notifications)

    def clear(self):
        self._save([])

    def unread_count(self) -> int:
        return len(self.get_unread())

    def check_price_drop(
        self,
        product_id: int,
        title: str,
        old_price: float,
        new_price: float,
        threshold: float = 0.1,
    ) -> Optional[int]:
        """Check if price dropped and create notification."""
        if old_price <= 0:
            return None

        drop_pct = (old_price - new_price) / old_price
        if drop_pct >= threshold:
            return self.add(
                notification_type="price_drop",
                message=f"{title[:60]} dropped £{old_price:.2f} → £{new_price:.2f} ({drop_pct:.0%} off)",
                product_id=product_id,
                priority="high",
            )
        return None
