"""Legacy sales helpers, now backed by the Phase I sales rules.

The API owns the routes (`api/sales.py`); this module remains for exports and
any older internal caller. Every write goes through `db.queries`, so it also
recomputes `monthly_stats`. Costs default to None rather than 0.0: a caller
that does not know a cost must not be given invented profit.
"""

from datetime import date, datetime
from typing import Optional

from db.database import SessionLocal
from db.models import Sale


def log_sale(
    product_name: str,
    sale_price: float,
    supplier_cost: Optional[float] = None,
    shipping_cost: Optional[float] = None,
    ebay_fees: Optional[float] = None,
    quantity: int = 1,
    sale_date: Optional[date] = None,
    category: str = "",
    buyer_location: str = "",
    notes: str = "",
) -> Optional[Sale]:
    """Log a new sale and recompute the month it belongs to."""
    from db.queries import recompute_monthly_stats, sale_money

    db = SessionLocal()
    try:
        when = datetime.combine(sale_date, datetime.min.time()) if sale_date else datetime.utcnow()
        profit, margin = sale_money(
            sale_price=sale_price,
            supplier_cost=supplier_cost,
            shipping_cost=shipping_cost,
            ebay_fees=ebay_fees,
            quantity=quantity,
        )
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
            sale_date=when,
            buyer_location=buyer_location,
            notes=notes,
        )
        db.add(sale)
        db.flush()
        recompute_monthly_stats(db, [(when.year, when.month)])
        db.refresh(sale)
        return sale

    except Exception as exc:  # noqa: BLE001 - legacy helper returns None
        print(f"[ERROR] Failed to log sale: {exc}")
        db.rollback()
        return None
    finally:
        db.close()


def update_sale(sale_id: int, **kwargs) -> bool:
    """Update a sale, recalculating profit and both affected months."""
    from db.queries import recompute_monthly_stats, sale_money

    db = SessionLocal()
    try:
        sale = db.query(Sale).filter(Sale.id == sale_id).first()
        if not sale:
            return False

        old_pair = (sale.sale_date.year, sale.sale_date.month)
        for key, value in kwargs.items():
            if hasattr(sale, key):
                setattr(sale, key, value)
        sale.profit, sale.margin_percent = sale_money(
            sale_price=sale.sale_price,
            supplier_cost=sale.supplier_cost,
            shipping_cost=sale.shipping_cost,
            ebay_fees=sale.ebay_fees,
            quantity=sale.quantity,
        )
        db.flush()
        new_pair = (sale.sale_date.year, sale.sale_date.month)
        recompute_monthly_stats(db, {old_pair, new_pair})
        return True

    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Failed to update sale: {exc}")
        db.rollback()
        return False
    finally:
        db.close()


def delete_sale(sale_id: int) -> bool:
    """Delete a sale and remove or recompute its month."""
    from db.queries import recompute_monthly_stats

    db = SessionLocal()
    try:
        sale = db.query(Sale).filter(Sale.id == sale_id).first()
        if not sale:
            return False
        pair = (sale.sale_date.year, sale.sale_date.month)
        db.delete(sale)
        db.flush()
        recompute_monthly_stats(db, [pair])
        return True

    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Failed to delete sale: {exc}")
        db.rollback()
        return False
    finally:
        db.close()


def get_sales(limit: int = 100, offset: int = 0) -> list[dict]:
    """Get sales with pagination, labelled as user-declared."""
    from db.queries import list_sales, sale_to_dict

    db = SessionLocal()
    try:
        return [sale_to_dict(sale) for sale in list_sales(db, limit=limit, offset=offset)]
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Failed to get sales: {exc}")
        return []
    finally:
        db.close()


def get_sales_by_date_range(start_date: date, end_date: date) -> list[dict]:
    """Get sales within a date range."""
    from db.queries import sale_to_dict

    db = SessionLocal()
    try:
        sales = (
            db.query(Sale)
            .filter(Sale.sale_date >= start_date)
            .filter(Sale.sale_date <= end_date)
            .order_by(Sale.sale_date.desc())
            .all()
        )
        return [sale_to_dict(sale) for sale in sales]
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Failed to get sales by date range: {exc}")
        return []
    finally:
        db.close()


def get_sale_count() -> int:
    """Get total sale count."""
    from db.queries import count_sales

    db = SessionLocal()
    try:
        return count_sales(db)
    except Exception:  # noqa: BLE001
        return 0
    finally:
        db.close()
