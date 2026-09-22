"""Log and manage sales."""

from datetime import datetime, date
from typing import Optional

from db.database import SessionLocal
from db.models import Sale


def log_sale(
    product_name: str,
    sale_price: float,
    supplier_cost: float = 0.0,
    shipping_cost: float = 0.0,
    ebay_fees: float = 0.0,
    quantity: int = 1,
    sale_date: Optional[date] = None,
    category: str = "",
    buyer_location: str = "",
    notes: str = "",
) -> Optional[Sale]:
    """Log a new sale."""
    db = SessionLocal()
    try:
        # Calculate profit
        revenue = sale_price * quantity
        costs = (supplier_cost + shipping_cost + ebay_fees) * quantity
        profit = revenue - costs

        # Calculate margin
        margin = (profit / revenue * 100) if revenue > 0 else 0

        sale = Sale(
            product_name=product_name,
            category=category,
            sale_price=sale_price,
            supplier_cost=supplier_cost,
            shipping_cost=shipping_cost,
            ebay_fees=ebay_fees,
            profit=profit,
            margin_percent=margin,
            quantity=quantity,
            sale_date=sale_date or datetime.utcnow(),
            buyer_location=buyer_location,
            notes=notes,
        )
        db.add(sale)
        db.commit()
        db.refresh(sale)
        return sale

    except Exception as e:
        print(f"[ERROR] Failed to log sale: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def update_sale(sale_id: int, **kwargs) -> bool:
    """Update a sale."""
    db = SessionLocal()
    try:
        sale = db.query(Sale).filter(Sale.id == sale_id).first()
        if not sale:
            return False

        for key, value in kwargs.items():
            if hasattr(sale, key):
                setattr(sale, key, value)

        # Recalculate profit and margin
        revenue = sale.sale_price * sale.quantity
        costs = (sale.supplier_cost + sale.shipping_cost + sale.ebay_fees) * sale.quantity
        sale.profit = revenue - costs
        sale.margin_percent = (sale.profit / revenue * 100) if revenue > 0 else 0

        db.commit()
        return True

    except Exception as e:
        print(f"[ERROR] Failed to update sale: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def delete_sale(sale_id: int) -> bool:
    """Delete a sale."""
    db = SessionLocal()
    try:
        sale = db.query(Sale).filter(Sale.id == sale_id).first()
        if sale:
            db.delete(sale)
            db.commit()
            return True
        return False

    except Exception as e:
        print(f"[ERROR] Failed to delete sale: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def get_sales(limit: int = 100, offset: int = 0) -> list[dict]:
    """Get sales with pagination."""
    db = SessionLocal()
    try:
        sales = (
            db.query(Sale)
            .order_by(Sale.sale_date.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            {
                "id": s.id,
                "product_name": s.product_name,
                "category": s.category,
                "sale_price": s.sale_price,
                "supplier_cost": s.supplier_cost,
                "shipping_cost": s.shipping_cost,
                "ebay_fees": s.ebay_fees,
                "profit": s.profit,
                "margin_percent": s.margin_percent,
                "quantity": s.quantity,
                "sale_date": s.sale_date.isoformat() if s.sale_date else None,
                "buyer_location": s.buyer_location,
                "notes": s.notes,
            }
            for s in sales
        ]

    except Exception as e:
        print(f"[ERROR] Failed to get sales: {e}")
        return []
    finally:
        db.close()


def get_sales_by_date_range(start_date: date, end_date: date) -> list[dict]:
    """Get sales within a date range."""
    db = SessionLocal()
    try:
        sales = (
            db.query(Sale)
            .filter(Sale.sale_date >= start_date)
            .filter(Sale.sale_date <= end_date)
            .order_by(Sale.sale_date.desc())
            .all()
        )
        return [
            {
                "id": s.id,
                "product_name": s.product_name,
                "category": s.category,
                "sale_price": s.sale_price,
                "profit": s.profit,
                "margin_percent": s.margin_percent,
                "quantity": s.quantity,
                "sale_date": s.sale_date.isoformat() if s.sale_date else None,
            }
            for s in sales
        ]

    except Exception as e:
        print(f"[ERROR] Failed to get sales by date range: {e}")
        return []
    finally:
        db.close()


def get_sale_count() -> int:
    """Get total sale count."""
    db = SessionLocal()
    try:
        return db.query(Sale).count()
    except Exception:
        return 0
    finally:
        db.close()
