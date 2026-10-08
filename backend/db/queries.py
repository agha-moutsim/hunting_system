"""
Common database queries.
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from db.models import Product, DemandData, SupplierMatch, Analysis, Verdict, PurchaseCapture
from scrapers.base import ScrapedProduct, DemandData as DemandDataDTO


def get_product_by_listing_id(db: Session, listing_id: str) -> Product | None:
    """Get product by eBay listing ID."""
    return db.query(Product).filter(Product.ebay_listing_id == listing_id).first()


def create_product(db: Session, **kwargs) -> Product:
    """Create a new product record."""
    product = Product(**kwargs)
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def save_demand(db: Session, product_id: int, **kwargs) -> DemandData:
    """Save or update demand data for a product."""
    existing = db.query(DemandData).filter(DemandData.product_id == product_id).first()
    if existing:
        for k, v in kwargs.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing

    demand = DemandData(product_id=product_id, **kwargs)
    db.add(demand)
    db.commit()
    db.refresh(demand)
    return demand


def save_supplier_match(db: Session, product_id: int, **kwargs) -> SupplierMatch:
    """Save a supplier match for a product."""
    match = SupplierMatch(product_id=product_id, **kwargs)
    db.add(match)
    db.commit()
    db.refresh(match)
    return match


def save_analysis(db: Session, product_id: int, **kwargs) -> Analysis:
    """Save or update LLM analysis for a product."""
    existing = db.query(Analysis).filter(Analysis.product_id == product_id).first()
    if existing:
        for k, v in kwargs.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing

    analysis = Analysis(product_id=product_id, **kwargs)
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def save_verdict(db: Session, product_id: int, **kwargs) -> Verdict:
    """Save or update verdict for a product."""
    existing = db.query(Verdict).filter(Verdict.product_id == product_id).first()
    if existing:
        for k, v in kwargs.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing

    verdict = Verdict(product_id=product_id, **kwargs)
    db.add(verdict)
    db.commit()
    db.refresh(verdict)
    return verdict


def get_recent_analyses(db: Session, limit: int = 20) -> list[dict]:
    """Get recent product analyses with verdicts."""
    results = (
        db.query(Product, Verdict)
        .join(Verdict, Verdict.product_id == Product.id)
        .order_by(Verdict.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": p.id,
            "title": p.title,
            "price": p.price,
            "verdict": v.verdict,
            "profit": v.profit_amount,
            "margin": v.profit_margin,
            "created_at": v.created_at.isoformat(),
        }
        for p, v in results
    ]


def is_data_fresh(db: Session, product_id: int, max_age_hours: int = 24) -> bool:
    """Check if product data is still fresh (reconcile pattern)."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return False

    age = datetime.utcnow() - product.updated_at
    return age < timedelta(hours=max_age_hours)


def save_product(db: Session, product: ScrapedProduct) -> int:
    """Save a scraped product and return its ID."""
    existing = db.query(Product).filter(Product.ebay_url == product.url).first()
    if existing:
        existing.title = product.title
        existing.price = product.price
        existing.image_url = product.image_url
        existing.seller = product.seller
        existing.condition = product.condition
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing.id

    new_product = Product(
        ebay_url=product.url,
        title=product.title,
        price=product.price,
        image_url=product.image_url,
        seller=product.seller,
        condition=product.condition,
    )
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    return new_product.id


def save_demand_data(db: Session, product_id: int, demand: DemandDataDTO) -> DemandData:
    """Save demand evidence from a scraped DemandData dataclass."""
    existing = db.query(DemandData).filter(DemandData.product_id == product_id).first()
    data = {
        "sold_count_30d": demand.sold_count_30d,
        "sold_count_7d": demand.sold_count_7d,
        "last_sale_date": demand.last_sale_date,
        "avg_sold_price": demand.avg_sold_price,
        "lowest_sold_price": demand.lowest_sold_price,
        "highest_sold_price": demand.highest_sold_price,
        "verified": demand.verified,
    }
    # A3 — the per-sale observations behind min/avg/max. Written whenever the
    # DTO carries the field (it now always does), including as [], because a
    # re-run that observed no sales must clear the previous run's chart
    # rather than keep redrawing it.
    if hasattr(demand, "sold_prices"):
        data["sold_prices"] = list(demand.sold_prices or [])
    # P5: only written when the DTO carries a source string (e.g. the
    # "...+purchase_history" suffix set by analysis_pipeline) so the column
    # default keeps applying everywhere else.
    data_source = getattr(demand, "data_source", None)
    if data_source:
        data["data_source"] = data_source
    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing

    demand_row = DemandData(product_id=product_id, **data)
    db.add(demand_row)
    db.commit()
    db.refresh(demand_row)
    return demand_row


def save_supplier_match_data(db: Session, product_id: int, supplier_data: dict) -> SupplierMatch:
    """Save a supplier match from a dict."""
    match = SupplierMatch(product_id=product_id, **supplier_data)
    db.add(match)
    db.commit()
    db.refresh(match)
    return match


def save_analysis_data(db: Session, product_id: int, analysis: dict) -> Analysis:
    """Save or update LLM analysis from a dict."""
    existing = db.query(Analysis).filter(Analysis.product_id == product_id).first()
    if existing:
        for k, v in analysis.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing

    row = Analysis(product_id=product_id, **analysis)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def clear_analysis_data(db: Session, product_id: int) -> bool:
    """Remove the AI verdict stored for a product.

    Called when an analysis ran with NO AI behind it. `save_product` reuses
    the Product row for the same eBay URL and `save_analysis_data` only
    writes when it is called, so the row an earlier run left would be read
    by History as this run's verdict — an AI output for an analysis that
    produced none (C13). Returns True when a row was actually removed.
    """
    existing = db.query(Analysis).filter(Analysis.product_id == product_id).first()
    if existing is None:
        return False
    db.delete(existing)
    db.commit()
    return True


def save_verdict_data(db: Session, product_id: int, verdict: dict) -> Verdict:
    """Save or update verdict from a dict."""
    existing = db.query(Verdict).filter(Verdict.product_id == product_id).first()
    if existing:
        for k, v in verdict.items():
            setattr(existing, k, v)
        db.commit()
        db.refresh(existing)
        return existing

    row = Verdict(product_id=product_id, **verdict)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_recent_products(db: Session, limit: int = 20) -> list[dict]:
    """Get recent products with their verdicts."""
    results = (
        db.query(Product, Verdict)
        .outerjoin(Verdict, Verdict.product_id == Product.id)
        .order_by(Product.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": p.id,
            "title": p.title,
            "price": p.price,
            "url": p.ebay_url,
            "image_url": p.image_url,
            "verdict": v.verdict if v else None,
            "profit": v.profit_amount if v else None,
            "margin": v.profit_margin if v else None,
            "created_at": p.created_at.isoformat(),
        }
        for p, v in results
    ]


def get_product_by_url(db: Session, url: str) -> Product | None:
    """Check if a product URL has already been scraped."""
    return db.query(Product).filter(Product.ebay_url == url).first()


def is_data_fresh_by_product(db: Session, product_id: int, max_age_hours: int = 24) -> bool:
    """Check if product data is fresh enough to skip re-scraping."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return False
    age = datetime.utcnow() - product.updated_at
    return age < timedelta(hours=max_age_hours)


def get_latest_purchase_capture(db: Session, item_id: str) -> PurchaseCapture | None:
    """Most recent browser purchase-history capture for an eBay item (P5)."""
    return (
        db.query(PurchaseCapture)
        .filter(PurchaseCapture.item_id == str(item_id))
        .order_by(PurchaseCapture.captured_at.desc(), PurchaseCapture.id.desc())
        .first()
    )


def upsert_purchase_capture(
    db: Session,
    *,
    item_id: str,
    url: str | None,
    sold_7d: int,
    sold_30d: int | None,
    sales_json: str,
    captured_at: datetime,
    source: str = "extension",
) -> PurchaseCapture:
    """Insert or update the capture for `item_id` — latest capture wins.

    One row per item: the existing row's counts/sales/captured_at are
    replaced and any duplicate rows for the same item_id are removed.
    """
    item_id = str(item_id)
    existing = (
        db.query(PurchaseCapture)
        .filter(PurchaseCapture.item_id == item_id)
        .order_by(PurchaseCapture.captured_at.desc(), PurchaseCapture.id.desc())
        .all()
    )
    if existing:
        row = existing[0]
        for duplicate in existing[1:]:
            db.delete(duplicate)
        row.url = url
        row.sold_7d = sold_7d
        row.sold_30d = sold_30d
        row.sales_json = sales_json
        row.captured_at = captured_at
        row.source = source
    else:
        row = PurchaseCapture(
            item_id=item_id,
            url=url,
            sold_7d=sold_7d,
            sold_30d=sold_30d,
            sales_json=sales_json,
            captured_at=captured_at,
            source=source,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row
