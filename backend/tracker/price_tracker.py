"""Add, remove, and manage tracked products."""

from datetime import datetime
from typing import Optional

from db.database import SessionLocal
from db.models import TrackedProduct


def add_to_tracker(
    product_name: str,
    ebay_url: str,
    ebay_price: float,
    target_price: float = 0.0,
    supplier_price: float = 0.0,
    supplier_url: str = "",
    supplier_name: str = "",
) -> Optional[TrackedProduct]:
    """Add a product to the price tracker."""
    db = SessionLocal()
    try:
        # Check if already tracked
        existing = db.query(TrackedProduct).filter(
            TrackedProduct.ebay_url == ebay_url
        ).first()
        if existing:
            return existing

        tracked = TrackedProduct(
            product_name=product_name,
            ebay_url=ebay_url,
            ebay_price=ebay_price,
            target_price=target_price,
            supplier_price=supplier_price,
            supplier_url=supplier_url,
            supplier_name=supplier_name,
            last_checked=datetime.utcnow(),
        )
        db.add(tracked)
        db.commit()
        db.refresh(tracked)
        return tracked
    except Exception as e:
        print(f"[ERROR] Failed to add to tracker: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def remove_from_tracker(tracked_id: int) -> bool:
    """Remove a product from the price tracker."""
    db = SessionLocal()
    try:
        tracked = db.query(TrackedProduct).filter(TrackedProduct.id == tracked_id).first()
        if tracked:
            db.delete(tracked)
            db.commit()
            return True
        return False
    except Exception as e:
        print(f"[ERROR] Failed to remove from tracker: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def get_tracked_products() -> list[dict]:
    """Get all tracked products."""
    db = SessionLocal()
    try:
        products = db.query(TrackedProduct).order_by(TrackedProduct.created_at.desc()).all()
        return [
            {
                "id": p.id,
                "product_name": p.product_name,
                "ebay_url": p.ebay_url,
                "ebay_price": p.ebay_price,
                "target_price": p.target_price,
                "supplier_price": p.supplier_price,
                "supplier_url": p.supplier_url,
                "supplier_name": p.supplier_name,
                "last_checked": p.last_checked.isoformat() if p.last_checked else None,
                "alert_enabled": p.alert_enabled,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in products
        ]
    except Exception as e:
        print(f"[ERROR] Failed to get tracked products: {e}")
        return []
    finally:
        db.close()


def update_tracked_product(tracked_id: int, **kwargs) -> bool:
    """Update a tracked product's fields."""
    db = SessionLocal()
    try:
        tracked = db.query(TrackedProduct).filter(TrackedProduct.id == tracked_id).first()
        if not tracked:
            return False

        for key, value in kwargs.items():
            if hasattr(tracked, key):
                setattr(tracked, key, value)

        tracked.updated_at = datetime.utcnow()
        db.commit()
        return True
    except Exception as e:
        print(f"[ERROR] Failed to update tracked product: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def toggle_alert(tracked_id: int) -> bool:
    """Toggle alert enabled for a tracked product."""
    db = SessionLocal()
    try:
        tracked = db.query(TrackedProduct).filter(TrackedProduct.id == tracked_id).first()
        if not tracked:
            return False
        tracked.alert_enabled = not tracked.alert_enabled
        db.commit()
        return tracked.alert_enabled
    except Exception as e:
        print(f"[ERROR] Failed to toggle alert: {e}")
        db.rollback()
        return False
    finally:
        db.close()
