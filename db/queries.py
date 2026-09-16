"""
Common database queries.
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from db.models import Product, DemandData, SupplierMatch, Analysis, Verdict


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
