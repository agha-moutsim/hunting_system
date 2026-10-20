"""Phase I - user-declared sales, P&L summary, CSV import and C14 feedback.

Every figure this module returns is arithmetic over rows the user entered, or
over C14 scores the app already stored. It never reads a sold count and never
calls eBay. A sale row is labelled `user_declared` everywhere it appears,
because it is the user's record rather than an observation.

Missing money stays missing. A sale with an undeclared cost has no profit and
no margin, a month containing one has no monthly profit, and the response
carries a sentence saying why. The only honest zero is a measured one: no
sales in a period, or a real cost the user typed as 0.
"""

from __future__ import annotations

import calendar
import csv
import io
import logging
import math
import re
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, HTTPException, Query

from api.schemas import SaleCreate, SalesCsvImport
from engine.match import THRESHOLD_UNVERIFIED, THRESHOLD_VERIFIED
from engine.thresholds import replay_thresholds

router = APIRouter()
logger = logging.getLogger(__name__)

SALES_DECLARATION = (
    "These are your own sales records, entered by you. They are not eBay "
    "observations."
)

def _open_session():
    from db.database import SessionLocal

    return SessionLocal()


# --- serialisation ---------------------------------------------------------


def _sale_payload(sale) -> dict:
    from db.queries import sale_to_dict

    return sale_to_dict(sale)


def _parse_money(value: str, field: str, *, allow_zero: bool) -> float:
    cleaned = (value or "").strip().replace("£", "").replace(",", "")
    if cleaned == "":
        raise ValueError(f"{field} is missing")
    try:
        number = float(cleaned)
    except ValueError:
        raise ValueError(f"{field} is not a number: {value!r}")
    if not math.isfinite(number):
        raise ValueError(f"{field} is not a finite number")
    if number < 0:
        raise ValueError(f"{field} cannot be negative")
    if not allow_zero and number <= 0:
        raise ValueError(f"{field} must be greater than zero")
    return number


def _parse_quantity(value: str) -> int:
    cleaned = (value or "").strip()
    if cleaned == "":
        raise ValueError("quantity is missing")
    try:
        quantity = int(cleaned)
    except ValueError:
        raise ValueError(f"quantity is not a whole number: {value!r}")
    if quantity < 1:
        raise ValueError("quantity must be at least 1")
    return quantity


def _parse_date(value: str) -> date:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError("sale_date is missing")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f"sale_date must be YYYY-MM-DD (or DD/MM/YYYY), got {value!r}"
    )


# --- summary arithmetic ----------------------------------------------------


def _month_shift(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _period_bounds(today: date, days: int) -> tuple[datetime, datetime]:
    start_day = today - timedelta(days=days - 1)
    start = datetime.combine(start_day, time.min)
    end = datetime.combine(today + timedelta(days=1), time.min)
    return start, end


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    end_year, end_month = _month_shift(year, month, 1)
    return start, datetime(end_year, end_month, 1)


def _money_totals(sales: list) -> dict:
    revenue = round(
        sum(sale.sale_price * (sale.quantity or 0) for sale in sales),
        2,
    )
    units = sum(int(sale.quantity or 0) for sale in sales)
    missing = [sale for sale in sales if sale.profit is None]
    complete = not missing
    profit = (
        round(sum(sale.profit for sale in sales), 2)
        if complete and sales
        else (0.0 if not sales else None)
    )
    margin = (
        round(profit / revenue * 100, 2)
        if complete and profit is not None and revenue > 0
        else None
    )
    reason = (
        None
        if complete
        else (
            f"Profit and margin are not shown because {len(missing)} of "
            f"{len(sales)} sale{'s' if len(sales) != 1 else ''} in this period "
            "did not declare every cost."
        )
    )
    return {
        "revenue": revenue,
        "profit": profit,
        "margin": margin,
        "units": units,
        "missing": missing,
        "profit_is_complete": complete,
        "profit_missing_reason": reason,
    }


def _growth(current: float | None, previous: float | None, label: str) -> tuple[float | None, str | None]:
    if current is None or previous is None:
        return None, f"Percentage change is not shown because {label} is not known."
    if previous <= 0:
        return None, (
            f"Percentage change is not shown because there was no recorded "
            f"{label} in the previous period."
        )
    return round((current - previous) / previous * 100, 1), None


def _best(sales: list, attr: str, profit_values: dict[int, float]) -> str | None:
    totals: dict[str, float] = {}
    for sale in sales:
        label = getattr(sale, attr, None)
        if not label:
            continue
        totals[label] = totals.get(label, 0.0) + profit_values.get(sale.id, 0.0)
    if not totals:
        return None
    return max(totals, key=totals.get)


def _monthly_series(db, today: date, months: int) -> list[dict]:
    from db.models import Sale

    out: list[dict] = []
    for delta in range(-(months - 1), 1):
        year, month = _month_shift(today.year, today.month, delta)
        start, end = _month_bounds(year, month)
        sales = (
            db.query(Sale)
            .filter(Sale.sale_date >= start, Sale.sale_date < end)
            .all()
        )
        money = _money_totals(sales)
        out.append(
            {
                "month": f"{year}-{month:02d}",
                "label": f"{calendar.month_abbr[month]} {year}",
                "revenue": money["revenue"],
                "profit": money["profit"],
                "margin": money["margin"],
                "total_sales": len(sales),
                "total_units": money["units"],
                "profit_is_complete": money["profit_is_complete"],
                "profit_missing_reason": money["profit_missing_reason"],
            }
        )
    return out


def _build_summary(db, *, days: int, months: int, now: datetime | None = None) -> dict:
    from db.models import Sale

    now = now or datetime.utcnow()
    today = now.date()
    start, end = _period_bounds(today, days)
    previous_start = start - timedelta(days=days)

    current = (
        db.query(Sale)
        .filter(Sale.sale_date >= start, Sale.sale_date < end)
        .all()
    )
    previous = (
        db.query(Sale)
        .filter(Sale.sale_date >= previous_start, Sale.sale_date < start)
        .all()
    )

    money = _money_totals(current)
    previous_money = _money_totals(previous)

    if current and previous:
        growth_revenue, revenue_reason = _growth(
            money["revenue"], previous_money["revenue"], "revenue"
        )
        growth_profit, profit_reason = _growth(
            money["profit"], previous_money["profit"], "profit"
        )
    else:
        # A period with no rows is not a measured decline. Without records in
        # both windows there is no change to compute, so no percentage is
        # claimed in either direction.
        growth_revenue = None
        growth_profit = None
        reason = (
            "Percentage change is not shown unless both the current and "
            "previous periods have user-declared sales."
        )
        revenue_reason = reason
        profit_reason = reason

    profit_values = (
        {sale.id: sale.profit for sale in current}
        if money["profit_is_complete"]
        else {}
    )
    best_product = (
        _best(current, "product_name", profit_values)
        if money["profit_is_complete"]
        else None
    )
    best_category = (
        _best(current, "category", profit_values)
        if money["profit_is_complete"]
        else None
    )

    return {
        "user_declared": True,
        "declaration": SALES_DECLARATION,
        "currency": "GBP",
        "days": days,
        "period": {"start": start.date().isoformat(), "end": today.isoformat()},
        "previous_period": {
            "start": (start.date() - timedelta(days=days)).isoformat(),
            "end": (start.date() - timedelta(days=1)).isoformat(),
        },
        "total_revenue": money["revenue"],
        "total_profit": money["profit"],
        "avg_margin": money["margin"],
        "total_sales": len(current),
        "total_units": money["units"],
        "best_product": best_product,
        "best_category": best_category,
        "profit_is_complete": money["profit_is_complete"],
        "profit_missing_reason": money["profit_missing_reason"],
        "growth_revenue": growth_revenue,
        "growth_profit": growth_profit,
        "growth_revenue_reason": revenue_reason,
        "growth_profit_reason": profit_reason,
        "monthly": _monthly_series(db, today, months),
        "monthly_window_months": months,
    }


# --- routes ----------------------------------------------------------------


@router.get("/sales/summary")
def sales_summary(
    days: int = Query(30, ge=1, le=3650),
    months: int = Query(6, ge=1, le=24),
):
    """P&L over the user's own records, with the sample and window named."""
    db = _open_session()
    try:
        return _build_summary(db, days=days, months=months)
    finally:
        db.close()


@router.get("/sales/thresholds")
def sales_thresholds(
    verified: float = Query(THRESHOLD_VERIFIED, ge=0.0, le=1.0),
    unverified: float = Query(THRESHOLD_UNVERIFIED, ge=0.0, le=1.0),
    limit: int = Query(100, ge=1, le=500),
):
    """Replay stored C14 scores at a proposed pair of thresholds.

    Reads `supplier_matches`; writes nothing and changes no threshold. The
    rows the matcher dropped were never stored, and the response states that
    limit rather than presenting a one-sided result as complete.
    """
    from db.models import Product, SupplierMatch, Verdict

    if unverified > verified:
        raise HTTPException(
            status_code=422,
            detail="The shown threshold cannot be higher than the confirmed threshold.",
        )

    db = _open_session()
    try:
        joined = (
            db.query(SupplierMatch, Product, Verdict)
            .outerjoin(Product, SupplierMatch.product_id == Product.id)
            .outerjoin(Verdict, Verdict.product_id == SupplierMatch.product_id)
            .order_by(SupplierMatch.id)
            .all()
        )
        rows = [
            {
                "product_id": match.product_id,
                "product_title": product.title if product else None,
                "supplier_name": match.supplier_name,
                "supplier_title": match.supplier_title,
                "match_score": match.match_score,
                "verdict": verdict.verdict if verdict else None,
            }
            for match, product, verdict in joined
        ]
    finally:
        db.close()

    try:
        report = replay_thresholds(
            rows,
            current_verified=THRESHOLD_VERIFIED,
            current_unverified=THRESHOLD_UNVERIFIED,
            proposed_verified=verified,
            proposed_unverified=unverified,
            difference_limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    report["source"] = "stored_supplier_matches"
    report["label"] = "Stored C14 matcher outcomes"
    return report


_CSV_ALIASES = {
    "product name": "product_name",
    "product": "product_name",
    "product_name": "product_name",
    "category": "category",
    "sale price": "sale_price",
    "sale_price": "sale_price",
    "price": "sale_price",
    "supplier cost": "supplier_cost",
    "supplier_cost": "supplier_cost",
    "cost": "supplier_cost",
    "shipping cost": "shipping_cost",
    "shipping_cost": "shipping_cost",
    "shipping": "shipping_cost",
    "ebay fees": "ebay_fees",
    "ebay_fees": "ebay_fees",
    "fees": "ebay_fees",
    "quantity": "quantity",
    "qty": "quantity",
    "sale date": "sale_date",
    "sale_date": "sale_date",
    "date": "sale_date",
    "buyer location": "buyer_location",
    "buyer_location": "buyer_location",
    "notes": "notes",
}

_REQUIRED_CSV_FIELDS = (
    "product_name",
    "sale_price",
    "supplier_cost",
    "shipping_cost",
    "ebay_fees",
    "quantity",
    "sale_date",
)


def _header_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _csv_mapping(fieldnames: list[str] | None) -> tuple[dict[str, str], list[str]]:
    mapping: dict[str, str] = {}
    for raw in fieldnames or []:
        canonical = _CSV_ALIASES.get(_header_key(raw))
        if canonical and canonical not in mapping:
            mapping[canonical] = raw
    missing = [field for field in _REQUIRED_CSV_FIELDS if field not in mapping]
    return mapping, missing


@router.post("/sales/import")
def import_sales(req: SalesCsvImport):
    """Import declared sales from CSV text, one rejected row at a time.

    A row is imported only when every required value parses. Rejected rows do
    not stop the others; the response lists each rejection with its line
    number and a sentence. The service recomputes the affected months once,
    after the whole file has been validated.
    """
    from db.models import Sale
    from db.queries import recompute_monthly_stats, sale_money

    text = (req.csv or "").lstrip("\ufeff")
    if not text.strip():
        raise HTTPException(status_code=422, detail="The CSV file is empty.")

    reader = csv.DictReader(io.StringIO(text))
    mapping, missing = _csv_mapping(reader.fieldnames)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                "CSV is missing required column"
                f"{'s' if len(missing) != 1 else ''}: {', '.join(missing)}."
            ),
        )

    errors: list[dict] = []
    rejected = 0
    received = 0
    sales: list[Sale] = []
    months: set[tuple[int, int]] = set()

    for line_number, raw in enumerate(reader, start=2):
        values = {
            key: (raw.get(column) or "").strip()
            for key, column in mapping.items()
        }
        if not any(values.values()):
            continue
        received += 1
        try:
            product_name = values.get("product_name", "")
            if not product_name:
                raise ValueError("product_name is missing")
            sale_price = _parse_money(
                values.get("sale_price", ""), "sale_price", allow_zero=False
            )
            supplier_cost = _parse_money(
                values.get("supplier_cost", ""), "supplier_cost", allow_zero=True
            )
            shipping_cost = _parse_money(
                values.get("shipping_cost", ""), "shipping_cost", allow_zero=True
            )
            ebay_fees = _parse_money(
                values.get("ebay_fees", ""), "ebay_fees", allow_zero=True
            )
            quantity = _parse_quantity(values.get("quantity", ""))
            sale_date = _parse_date(values.get("sale_date", ""))
        except ValueError as exc:
            rejected += 1
            if len(errors) < 100:
                errors.append({"line": line_number, "reason": str(exc)})
            continue

        profit, margin = sale_money(
            sale_price=sale_price,
            supplier_cost=supplier_cost,
            shipping_cost=shipping_cost,
            ebay_fees=ebay_fees,
            quantity=quantity,
        )
        sale = Sale(
            product_name=product_name,
            category=values.get("category", ""),
            sale_price=sale_price,
            supplier_cost=supplier_cost,
            shipping_cost=shipping_cost,
            ebay_fees=ebay_fees,
            profit=profit,
            margin_percent=margin,
            quantity=quantity,
            sale_date=datetime.combine(sale_date, time.min),
            buyer_location=values.get("buyer_location", ""),
            notes=values.get("notes", ""),
        )
        sales.append(sale)
        months.add((sale_date.year, sale_date.month))

    if received == 0:
        raise HTTPException(
            status_code=422,
            detail="The CSV has a header but no data rows to import.",
        )

    db = _open_session()
    try:
        if sales:
            db.add_all(sales)
            db.flush()
            recompute_monthly_stats(db, months)
        ids = [sale.id for sale in sales]
    except Exception as exc:  # noqa: BLE001 - report a refusal, not a traceback
        db.rollback()
        logger.exception("sales CSV import failed")
        raise HTTPException(
            status_code=500,
            detail="The sales CSV could not be saved, so no rows were imported.",
        ) from exc
    finally:
        db.close()

    return {
        "user_declared": True,
        "declaration": SALES_DECLARATION,
        "filename": req.filename,
        "rows_received": received,
        "rows_imported": len(sales),
        "rows_rejected": rejected,
        "errors": errors,
        "errors_truncated": rejected > len(errors),
        "imported_ids": ids,
        "months_recomputed": len(months),
    }


@router.get("/sales")
def list_sales(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    from db.queries import count_sales, list_sales as _list_sales

    db = _open_session()
    try:
        rows = _list_sales(db, limit=limit, offset=offset)
        total = count_sales(db)
        return {
            "user_declared": True,
            "declaration": SALES_DECLARATION,
            "sales": [_sale_payload(sale) for sale in rows],
            "count": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        db.close()


@router.post("/sales")
def create_sale(req: SaleCreate):
    from db.queries import create_sale_record

    db = _open_session()
    try:
        sale = create_sale_record(
            db,
            product_name=req.product_name,
            category=req.category,
            sale_price=req.sale_price,
            supplier_cost=req.supplier_cost,
            shipping_cost=req.shipping_cost,
            ebay_fees=req.ebay_fees,
            quantity=req.quantity,
            sale_date=datetime.combine(req.sale_date, time.min),
            buyer_location=req.buyer_location,
            notes=req.notes,
        )
        return _sale_payload(sale)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("sale could not be created")
        raise HTTPException(
            status_code=500,
            detail="The sale was not saved because the database rejected it.",
        ) from exc
    finally:
        db.close()


@router.put("/sales/{sale_id}")
def update_sale(sale_id: int, req: SaleCreate):
    from db.queries import get_sale, update_sale_record

    db = _open_session()
    try:
        sale = get_sale(db, sale_id)
        if sale is None:
            raise HTTPException(status_code=404, detail="Sale not found.")
        sale = update_sale_record(
            db,
            sale,
            product_name=req.product_name,
            category=req.category,
            sale_price=req.sale_price,
            supplier_cost=req.supplier_cost,
            shipping_cost=req.shipping_cost,
            ebay_fees=req.ebay_fees,
            quantity=req.quantity,
            sale_date=datetime.combine(req.sale_date, time.min),
            buyer_location=req.buyer_location,
            notes=req.notes,
        )
        return _sale_payload(sale)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("sale could not be updated")
        raise HTTPException(
            status_code=500,
            detail="The sale was not updated because the database rejected it.",
        ) from exc
    finally:
        db.close()


@router.delete("/sales/{sale_id}")
def delete_sale(sale_id: int):
    from db.queries import delete_sale_record, get_sale

    db = _open_session()
    try:
        sale = get_sale(db, sale_id)
        if sale is None:
            raise HTTPException(status_code=404, detail="Sale not found.")
        delete_sale_record(db, sale)
        return {
            "deleted": True,
            "id": sale_id,
            "user_declared": True,
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("sale could not be deleted")
        raise HTTPException(
            status_code=500,
            detail="The sale was not deleted because the database rejected it.",
        ) from exc
    finally:
        db.close()
