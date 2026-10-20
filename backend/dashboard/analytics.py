"""KPIs and top lists over user-declared sales.

The Phase I dashboard reads `/api/sales/summary`, which owns the same rules in
one place. These helpers remain for the legacy `/dashboard/*` read routes and
must obey the same honesty rule: if any sale in a total has an undeclared cost,
the profit is unknown, not zero.
"""

from datetime import datetime, time, timedelta

from db.database import SessionLocal
from db.models import Sale, MonthlyStat

_DECLARATION = (
    "These are your own sales records, entered by you. They are not eBay "
    "observations."
)


def _period(days: int) -> tuple[datetime, datetime]:
    today = datetime.utcnow().date()
    start_day = today - timedelta(days=days - 1)
    return (
        datetime.combine(start_day, time.min),
        datetime.combine(today + timedelta(days=1), time.min),
    )


def _profit(sales: list[Sale]) -> tuple[float | None, bool, str | None]:
    missing = [sale for sale in sales if sale.profit is None]
    if missing:
        return (
            None,
            False,
            f"Profit is not shown because {len(missing)} of {len(sales)} "
            "sale(s) did not declare every cost.",
        )
    return round(sum(sale.profit for sale in sales), 2), True, None


def _empty_kpis(days: int, reason: str | None = None) -> dict:
    return {
        "total_revenue": 0.0,
        "total_profit": 0.0,
        "avg_margin": None,
        "total_sales": 0,
        "total_units": 0,
        "best_product": None,
        "best_category": None,
        "growth_revenue": None,
        "growth_profit": None,
        "growth_revenue_reason": reason,
        "growth_profit_reason": reason,
        "profit_is_complete": True,
        "profit_missing_reason": None,
        "user_declared": True,
        "declaration": _DECLARATION,
        "days": days,
    }


def get_kpis(days: int = 30) -> dict:
    """KPIs for the last N calendar days, with missing money left absent."""
    db = SessionLocal()
    try:
        start, end = _period(days)
        previous_start = start - timedelta(days=days)
        sales = (
            db.query(Sale)
            .filter(Sale.sale_date >= start, Sale.sale_date < end)
            .all()
        )
        if not sales:
            return _empty_kpis(
                days,
                "No user-declared sales in either period, so no percentage "
                "change is claimed.",
            )

        total_revenue = round(
            sum(sale.sale_price * sale.quantity for sale in sales), 2
        )
        total_profit, complete, missing_reason = _profit(sales)
        total_units = sum(sale.quantity for sale in sales)
        avg_margin = (
            round(total_profit / total_revenue * 100, 1)
            if complete and total_profit is not None and total_revenue > 0
            else None
        )

        previous = (
            db.query(Sale)
            .filter(Sale.sale_date >= previous_start, Sale.sale_date < start)
            .all()
        )
        previous_revenue = (
            round(sum(sale.sale_price * sale.quantity for sale in previous), 2)
            if previous
            else 0.0
        )
        previous_profit, previous_complete, _ = _profit(previous)
        growth_revenue = (
            round((total_revenue - previous_revenue) / previous_revenue * 100, 1)
            if previous_revenue > 0
            else None
        )
        growth_profit = (
            round((total_profit - previous_profit) / previous_profit * 100, 1)
            if complete
            and previous_complete
            and total_profit is not None
            and previous_profit is not None
            and previous_profit > 0
            else None
        )

        best_product = None
        best_category = None
        if complete:
            product_profits: dict[str, float] = {}
            category_profits: dict[str, float] = {}
            for sale in sales:
                product_profits[sale.product_name] = (
                    product_profits.get(sale.product_name, 0.0) + sale.profit
                )
                if sale.category:
                    category_profits[sale.category] = (
                        category_profits.get(sale.category, 0.0) + sale.profit
                    )
            if product_profits:
                best_product = max(product_profits, key=product_profits.get)
            if category_profits:
                best_category = max(category_profits, key=category_profits.get)

        return {
            "total_revenue": total_revenue,
            "total_profit": total_profit,
            "avg_margin": avg_margin,
            "total_sales": len(sales),
            "total_units": total_units,
            "best_product": best_product,
            "best_category": best_category,
            "growth_revenue": growth_revenue,
            "growth_profit": growth_profit,
            "growth_revenue_reason": (
                None
                if growth_revenue is not None
                else "No recorded revenue in the previous period, so no "
                "percentage change is claimed."
            ),
            "growth_profit_reason": (
                None
                if growth_profit is not None
                else "Profit change is not shown because one period has no "
                "known positive profit."
            ),
            "profit_is_complete": complete,
            "profit_missing_reason": missing_reason,
            "user_declared": True,
            "declaration": _DECLARATION,
            "days": days,
        }

    except Exception as exc:  # noqa: BLE001 - a read must not kill the page
        print(f"[ERROR] Failed to get KPIs: {exc}")
        return {**_empty_kpis(days), "error": str(exc)}
    finally:
        db.close()


def get_monthly_stats(year: int) -> list[dict]:
    """Monthly rows for a year, preserving unknown profit as None."""
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
                "month": stat.month,
                "year": stat.year,
                "total_revenue": stat.total_revenue,
                "total_profit": stat.total_profit,
                "total_sales": stat.total_sales,
                "avg_margin": stat.avg_margin,
                "user_declared": True,
            }
            for stat in stats
        ]
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Failed to get monthly stats: {exc}")
        return []
    finally:
        db.close()


def get_top_products(limit: int = 10) -> list[dict]:
    """Top products by profit when every cost is known, else by revenue."""
    db = SessionLocal()
    try:
        product_data: dict[str, dict] = {}
        for sale in db.query(Sale).all():
            row = product_data.setdefault(
                sale.product_name,
                {
                    "product_name": sale.product_name,
                    "total_revenue": 0.0,
                    "total_profit": 0.0,
                    "total_units": 0,
                    "profit_is_complete": True,
                },
            )
            row["total_revenue"] += sale.sale_price * sale.quantity
            row["total_units"] += sale.quantity
            if sale.profit is None:
                row["profit_is_complete"] = False
            else:
                row["total_profit"] += sale.profit

        rows = list(product_data.values())
        for row in rows:
            row["total_revenue"] = round(row["total_revenue"], 2)
            if row["profit_is_complete"]:
                row["total_profit"] = round(row["total_profit"], 2)
            else:
                row["total_profit"] = None
        sort_by_revenue = any(not row["profit_is_complete"] for row in rows)
        rows.sort(
            key=lambda row: (
                row["total_revenue"] if sort_by_revenue else row["total_profit"]
            ),
            reverse=True,
        )
        return rows[:limit]
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Failed to get top products: {exc}")
        return []
    finally:
        db.close()


def get_top_categories(limit: int = 10) -> list[dict]:
    """Top categories by profit when every cost is known, else by revenue."""
    db = SessionLocal()
    try:
        category_data: dict[str, dict] = {}
        for sale in db.query(Sale).filter(Sale.category != "").all():
            row = category_data.setdefault(
                sale.category,
                {
                    "category": sale.category,
                    "total_revenue": 0.0,
                    "total_profit": 0.0,
                    "total_units": 0,
                    "profit_is_complete": True,
                },
            )
            row["total_revenue"] += sale.sale_price * sale.quantity
            row["total_units"] += sale.quantity
            if sale.profit is None:
                row["profit_is_complete"] = False
            else:
                row["total_profit"] += sale.profit

        rows = list(category_data.values())
        for row in rows:
            row["total_revenue"] = round(row["total_revenue"], 2)
            if row["profit_is_complete"]:
                row["total_profit"] = round(row["total_profit"], 2)
            else:
                row["total_profit"] = None
        sort_by_revenue = any(not row["profit_is_complete"] for row in rows)
        rows.sort(
            key=lambda row: (
                row["total_revenue"] if sort_by_revenue else row["total_profit"]
            ),
            reverse=True,
        )
        return rows[:limit]
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Failed to get top categories: {exc}")
        return []
    finally:
        db.close()
