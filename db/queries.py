"""
Common database queries.
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from db.models import Product, DemandData, SupplierMatch, Analysis, Verdict
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
