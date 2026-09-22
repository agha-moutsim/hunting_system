"""Watchlist items — add, remove, and manage watched products."""

from datetime import datetime
from typing import Optional

from db.database import SessionLocal
from db.models import WatchlistItem


def add_to_watchlist(
    product_name: str,
    ebay_url: str = "",
    ebay_price: float = 0.0,
    target_price: float = 0.0,
    supplier_price: float = 0.0,
    supplier_url: str = "",
    supplier_name: str = "",
    notes: str = "",
) -> Optional[WatchlistItem]:
    """Add a product to the watchlist."""
    db = SessionLocal()
    try:
        # Check if already watched (by URL or name)
        existing = None
        if ebay_url:
            existing = db.query(WatchlistItem).filter(WatchlistItem.ebay_url == ebay_url).first()
        if not existing:
            existing = db.query(WatchlistItem).filter(WatchlistItem.product_name == product_name).first()

        if existing:
            # Update existing
            existing.ebay_price = ebay_price
            existing.supplier_price = supplier_price
            existing.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(existing)
            return existing

        # Create new
        item = WatchlistItem(
            product_name=product_name,
            ebay_url=ebay_url,
            ebay_price=ebay_price,
            target_price=target_price,
            supplier_price=supplier_price,
            supplier_url=supplier_url,
            supplier_name=supplier_name,
            notes=notes,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    except Exception as e:
        print(f"[ERROR] Failed to add to watchlist: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def remove_from_watchlist(item_id: int) -> bool:
    """Remove a product from the watchlist."""
    db = SessionLocal()
    try:
        item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
        if item:
            db.delete(item)
            db.commit()
            return True
        return False
    except Exception as e:
        print(f"[ERROR] Failed to remove from watchlist: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def get_watchlist_items() -> list[dict]:
    """Get all watchlist items."""
    db = SessionLocal()
    try:
        items = db.query(WatchlistItem).order_by(WatchlistItem.added_at.desc()).all()
        return [
            {
                "id": item.id,
                "product_name": item.product_name,
                "ebay_url": item.ebay_url,
                "ebay_price": item.ebay_price,
                "target_price": item.target_price,
                "supplier_price": item.supplier_price,
                "supplier_url": item.supplier_url,
                "supplier_name": item.supplier_name,
                "notes": item.notes,
                "added_at": item.added_at.isoformat() if item.added_at else None,
            }
            for item in items
        ]
    except Exception as e:
        print(f"[ERROR] Failed to get watchlist items: {e}")
        return []
    finally:
        db.close()


def update_watchlist_item(item_id: int, **kwargs) -> bool:
    """Update a watchlist item."""
    db = SessionLocal()
    try:
        item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
        if not item:
            return False

        for key, value in kwargs.items():
            if hasattr(item, key):
                setattr(item, key, value)

        item.updated_at = datetime.utcnow()
        db.commit()
        return True
    except Exception as e:
        print(f"[ERROR] Failed to update watchlist item: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def is_watched(ebay_url: str = "", product_name: str = "") -> bool:
    """Check if a product is already in the watchlist."""
    db = SessionLocal()
    try:
        item = None
        if ebay_url:
            item = db.query(WatchlistItem).filter(WatchlistItem.ebay_url == ebay_url).first()
        if not item and product_name:
            item = db.query(WatchlistItem).filter(WatchlistItem.product_name == product_name).first()
        return item is not None
    except Exception:
        return False
    finally:
        db.close()
