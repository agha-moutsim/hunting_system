"""Calculate KPIs and analytics."""

from datetime import datetime, timedelta, date
from typing import Optional

from db.database import SessionLocal
from db.models import Sale, MonthlyStat


def get_kpis(days: int = 30) -> dict:
    """Get KPIs for the last N days."""
    db = SessionLocal()
    try:
        start_date = datetime.utcnow() - timedelta(days=days)

        sales = db.query(Sale).filter(Sale.sale_date >= start_date).all()

        if not sales:
            return {
                "total_revenue": 0.0,
                "total_profit": 0.0,
                "avg_margin": 0.0,
                "total_sales": 0,
                "total_units": 0,
                "best_product": "",
                "best_category": "",
                "growth_revenue": 0.0,
                "growth_profit": 0.0,
                "days": days,
            }

        total_revenue = sum(s.sale_price * s.quantity for s in sales)
        total_profit = sum(s.profit for s in sales)
        total_units = sum(s.quantity for s in sales)
        avg_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0

        # Best product (by total profit)
        product_profits = {}
        for s in sales:
            product_profits[s.product_name] = product_profits.get(s.product_name, 0) + s.profit
        best_product = max(product_profits, key=product_profits.get) if product_profits else ""

        # Best category
        cat_profits = {}
        for s in sales:
            if s.category:
                cat_profits[s.category] = cat_profits.get(s.category, 0) + s.profit
        best_category = max(cat_profits, key=cat_profits.get) if cat_profits else ""

        # Growth (compare to previous period)
        prev_start = start_date - timedelta(days=days)
        prev_sales = db.query(Sale).filter(Sale.sale_date >= prev_start).filter(Sale.sale_date < start_date).all()

        prev_revenue = sum(s.sale_price * s.quantity for s in prev_sales) if prev_sales else 0
        prev_profit = sum(s.profit for s in prev_sales) if prev_sales else 0

        growth_revenue = ((total_revenue - prev_revenue) / prev_revenue * 100) if prev_revenue > 0 else 0
        growth_profit = ((total_profit - prev_profit) / prev_profit * 100) if prev_profit > 0 else 0

        return {
            "total_revenue": round(total_revenue, 2),
            "total_profit": round(total_profit, 2),
            "avg_margin": round(avg_margin, 1),
            "total_sales": len(sales),
            "total_units": total_units,
            "best_product": best_product,
            "best_category": best_category,
            "growth_revenue": round(growth_revenue, 1),
            "growth_profit": round(growth_profit, 1),
            "days": days,
        }

    except Exception as e:
        print(f"[ERROR] Failed to get KPIs: {e}")
        return {
            "total_revenue": 0.0,
            "total_profit": 0.0,
            "avg_margin": 0.0,
            "total_sales": 0,
            "total_units": 0,
            "best_product": "",
            "best_category": "",
            "growth_revenue": 0.0,
            "growth_profit": 0.0,
            "days": days,
            "error": str(e),
        }
    finally:
        db.close()


def get_monthly_stats(year: int) -> list[dict]:
    """Get monthly stats for a year."""
    db = SessionLocal()
    try:
        stats = (
            db.query(MonthlyStat)
            .filter(MonthlyStat.year == year)
            .order_by(MonthlyStat.month)
            .all()
        )
        return [
            {
                "month": s.month,
                "year": s.year,
                "total_revenue": s.total_revenue,
                "total_profit": s.total_profit,
                "total_sales": s.total_sales,
                "avg_margin": s.avg_margin,
            }
            for s in stats
        ]
    except Exception as e:
        print(f"[ERROR] Failed to get monthly stats: {e}")
        return []
    finally:
        db.close()


def get_top_products(limit: int = 10) -> list[dict]:
    """Get top products by profit."""
    db = SessionLocal()
    try:
        sales = db.query(Sale).all()

        product_data = {}
        for s in sales:
            if s.product_name not in product_data:
                product_data[s.product_name] = {
                    "product_name": s.product_name,
                    "total_revenue": 0.0,
                    "total_profit": 0.0,
                    "total_units": 0,
                }
            product_data[s.product_name]["total_revenue"] += s.sale_price * s.quantity
            product_data[s.product_name]["total_profit"] += s.profit
            product_data[s.product_name]["total_units"] += s.quantity

        sorted_products = sorted(
            product_data.values(),
            key=lambda x: x["total_profit"],
            reverse=True,
        )

        for p in sorted_products:
            p["total_revenue"] = round(p["total_revenue"], 2)
            p["total_profit"] = round(p["total_profit"], 2)

        return sorted_products[:limit]

    except Exception as e:
        print(f"[ERROR] Failed to get top products: {e}")
        return []
    finally:
        db.close()


def get_top_categories(limit: int = 10) -> list[dict]:
    """Get top categories by profit."""
    db = SessionLocal()
    try:
        sales = db.query(Sale).filter(Sale.category != "").all()

        cat_data = {}
        for s in sales:
            if s.category not in cat_data:
                cat_data[s.category] = {
                    "category": s.category,
                    "total_revenue": 0.0,
                    "total_profit": 0.0,
                    "total_units": 0,
                }
            cat_data[s.category]["total_revenue"] += s.sale_price * s.quantity
            cat_data[s.category]["total_profit"] += s.profit
            cat_data[s.category]["total_units"] += s.quantity

        sorted_cats = sorted(
            cat_data.values(),
            key=lambda x: x["total_profit"],
            reverse=True,
        )

        for c in sorted_cats:
            c["total_revenue"] = round(c["total_revenue"], 2)
            c["total_profit"] = round(c["total_profit"], 2)

        return sorted_cats[:limit]

    except Exception as e:
        print(f"[ERROR] Failed to get top categories: {e}")
        return []
    finally:
        db.close()
