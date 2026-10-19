"""Price alert reading and management for the tracker surfaces.

Writing alerts lives in `hunter.alerts` (one comparison rule, one writer -
Phase E): an earlier `generate_alert` here had its own 50p threshold and its
own message format, which is exactly how two inboxes start disagreeing about
one price. This module only reads and updates the rows.
"""

from db.database import SessionLocal
from db.models import PriceAlert, TrackedProduct


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
