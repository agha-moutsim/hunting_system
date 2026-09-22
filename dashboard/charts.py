"""Generate chart data for the dashboard."""

from datetime import datetime, timedelta, date
from collections import defaultdict

from db.database import SessionLocal
from db.models import Sale


def get_revenue_trend(days: int = 30) -> dict:
    """Get daily revenue trend for the last N days."""
    db = SessionLocal()
    try:
        start_date = datetime.utcnow() - timedelta(days=days)
        sales = db.query(Sale).filter(Sale.sale_date >= start_date).all()

        # Group by day
        daily_revenue = defaultdict(float)
        for s in sales:
            if s.sale_date:
                day = s.sale_date.date().isoformat()
                daily_revenue[day] += s.sale_price * s.quantity

        # Fill in missing days
        dates = []
        values = []
        for i in range(days):
            d = (datetime.utcnow() - timedelta(days=days - 1 - i)).date()
            dates.append(d.isoformat())
            values.append(round(daily_revenue.get(d.isoformat(), 0), 2))

        return {"dates": dates, "values": values, "total": round(sum(values), 2)}

    except Exception as e:
        print(f"[ERROR] Failed to get revenue trend: {e}")
        return {"dates": [], "values": [], "total": 0}
    finally:
        db.close()


def get_profit_trend(days: int = 30) -> dict:
    """Get daily profit trend for the last N days."""
    db = SessionLocal()
    try:
        start_date = datetime.utcnow() - timedelta(days=days)
        sales = db.query(Sale).filter(Sale.sale_date >= start_date).all()

        # Group by day
        daily_profit = defaultdict(float)
        for s in sales:
            if s.sale_date:
                day = s.sale_date.date().isoformat()
                daily_profit[day] += s.profit

        # Fill in missing days
        dates = []
        values = []
        for i in range(days):
            d = (datetime.utcnow() - timedelta(days=days - 1 - i)).date()
            dates.append(d.isoformat())
            values.append(round(daily_profit.get(d.isoformat(), 0), 2))

        return {"dates": dates, "values": values, "total": round(sum(values), 2)}

    except Exception as e:
        print(f"[ERROR] Failed to get profit trend: {e}")
        return {"dates": [], "values": [], "total": 0}
    finally:
        db.close()


def get_category_breakdown() -> dict:
    """Get category breakdown for pie chart."""
    db = SessionLocal()
    try:
        sales = db.query(Sale).filter(Sale.category != "").all()

        cat_revenue = defaultdict(float)
        for s in sales:
            if s.category:
                cat_revenue[s.category] += s.sale_price * s.quantity

        categories = list(cat_revenue.keys())
        values = [round(v, 2) for v in cat_revenue.values()]

        return {"categories": categories, "values": values}

    except Exception as e:
        print(f"[ERROR] Failed to get category breakdown: {e}")
        return {"categories": [], "values": []}
    finally:
        db.close()


def get_monthly_comparison(months: int = 6) -> dict:
    """Get monthly revenue/profit comparison for bar chart."""
    db = SessionLocal()
    try:
        start_date = datetime.utcnow() - timedelta(days=months * 30)
        sales = db.query(Sale).filter(Sale.sale_date >= start_date).all()

        # Group by month
        monthly = defaultdict(lambda: {"revenue": 0.0, "profit": 0.0})
        for s in sales:
            if s.sale_date:
                key = f"{s.sale_date.year}-{s.sale_date.month:02d}"
                monthly[key]["revenue"] += s.sale_price * s.quantity
                monthly[key]["profit"] += s.profit

        # Sort by month
        sorted_months = sorted(monthly.keys())

        labels = []
        revenue_values = []
        profit_values = []

        for m in sorted_months:
            labels.append(m)
            revenue_values.append(round(monthly[m]["revenue"], 2))
            profit_values.append(round(monthly[m]["profit"], 2))

        return {
            "labels": labels,
            "revenue": revenue_values,
            "profit": profit_values,
        }

    except Exception as e:
        print(f"[ERROR] Failed to get monthly comparison: {e}")
        return {"labels": [], "revenue": [], "profit": []}
    finally:
        db.close()
