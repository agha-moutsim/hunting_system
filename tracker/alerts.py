"""Price alert generation and management."""

from datetime import datetime
from typing import Optional

from db.database import SessionLocal
from db.models import PriceAlert, TrackedProduct


def generate_alert(
    product: TrackedProduct,
    alert_type: str,
    old_price: float,
    new_price: float,
) -> Optional[PriceAlert]:
    """Generate a price alert for a product."""
    db = SessionLocal()
    try:
        # Create message
        if alert_type == "price_drop":
            message = f"{product.product_name} dropped from £{old_price:.2f} to £{new_price:.2f}"
        elif alert_type == "price_increase":
            message = f"{product.product_name} increased from £{old_price:.2f} to £{new_price:.2f}"
        elif alert_type == "margin_alert":
            message = f"{product.product_name} margin alert"
        else:
            message = f"{product.product_name} price changed"

        alert = PriceAlert(
            tracked_product_id=product.id,
            alert_type=alert_type,
            message=message,
            old_price=old_price,
            new_price=new_price,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        return alert

    except Exception as e:
        print(f"[ERROR] Failed to generate alert: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def get_alerts(unread_only: bool = False, limit: int = 50) -> list[dict]:
    """Get price alerts."""
    db = SessionLocal()
    try:
        query = db.query(PriceAlert).join(TrackedProduct)

        if unread_only:
            query = query.filter(PriceAlert.is_read == False)

        alerts = query.order_by(PriceAlert.created_at.desc()).limit(limit).all()

        return [
            {
                "id": a.id,
                "product_id": a.tracked_product_id,
                "product_name": a.tracked_product.product_name if a.tracked_product else "",
                "alert_type": a.alert_type,
                "message": a.message,
                "old_price": a.old_price,
                "new_price": a.new_price,
                "is_read": a.is_read,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in alerts
        ]

    except Exception as e:
        print(f"[ERROR] Failed to get alerts: {e}")
        return []
    finally:
        db.close()


def mark_alert_read(alert_id: int) -> bool:
    """Mark an alert as read."""
    db = SessionLocal()
    try:
        alert = db.query(PriceAlert).filter(PriceAlert.id == alert_id).first()
        if alert:
            alert.is_read = True
            db.commit()
            return True
        return False
    except Exception as e:
        print(f"[ERROR] Failed to mark alert read: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def get_unread_count() -> int:
    """Get count of unread alerts."""
    db = SessionLocal()
    try:
        return db.query(PriceAlert).filter(PriceAlert.is_read == False).count()
    except Exception:
        return 0
    finally:
        db.close()


def clear_all_alerts() -> bool:
    """Clear all alerts."""
    db = SessionLocal()
    try:
        db.query(PriceAlert).delete()
        db.commit()
        return True
    except Exception as e:
        print(f"[ERROR] Failed to clear alerts: {e}")
        db.rollback()
        return False
    finally:
        db.close()
