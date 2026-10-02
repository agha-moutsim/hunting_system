"""
SQLAlchemy models — one class per PostgreSQL table.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, ForeignKey, JSON, DateTime
)
from sqlalchemy.orm import relationship
from db.database import Base
from config import FILTERS


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ebay_url = Column(Text, nullable=False)
    ebay_listing_id = Column(String(64), unique=True)
    title = Column(Text)
    price = Column(Float)
    condition = Column(String(32), default="New")
    format = Column(String(32), default="Buy It Now")
    seller = Column(String(128))
    image_url = Column(Text)
    category = Column(String(128))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    demand = relationship("DemandData", back_populates="product", uselist=False)
    supplier_matches = relationship("SupplierMatch", back_populates="product")
    analysis = relationship("Analysis", back_populates="product", uselist=False)
    verdict = relationship("Verdict", back_populates="product", uselist=False)


class DemandData(Base):
    __tablename__ = "demand_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), unique=True)
    sold_count_30d = Column(Integer)
    sold_count_7d = Column(Integer)
    last_sale_date = Column(String(64))
    avg_sold_price = Column(Float)
    lowest_sold_price = Column(Float)
    highest_sold_price = Column(Float)
    data_source = Column(String(64), default="ebay_sold_listings")
    verified = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="demand")


class SupplierMatch(Base):
    __tablename__ = "supplier_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"))
    supplier_name = Column(String(64), nullable=False)
    supplier_url = Column(Text)
    supplier_title = Column(Text)
    supplier_price = Column(Float)
    delivery_days_min = Column(Integer)
    delivery_days_max = Column(Integer)
    supplier_type = Column(String(32))   # wholesaler, dropship, retailer
    confidence = Column(String(16))      # high, medium, low
    match_score = Column(Float)          # 0.0 to 1.0
    verified = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="supplier_matches")


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), unique=True)
    brand_verdict = Column(String(16))      # generic, branded, ambiguous
    brand_reasoning = Column(Text)
    demand_assessment = Column(String(16))  # strong, moderate, weak, spike
    demand_reasoning = Column(Text)
    supplier_match_notes = Column(Text)
    llm_raw_response = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="analysis")


class Verdict(Base):
    __tablename__ = "verdicts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), unique=True)
    verdict = Column(String(16))    # pass, fail, pending
    profit_amount = Column(Float)
    profit_margin = Column(Float)
    filter_results = Column(JSON)   # which filters passed/failed
    scorecard = Column(Text)        # full formatted scorecard
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="verdict")


class DemandSnapshot(Base):
    """One timestamped sold-count observation for a monitored query.

    The watchlist monitor (hunter.demand_monitor) appends one row per query
    per run. Two snapshots of the same query over a window give the only
    honest 7-day trend; a single point cannot have a slope, and one that is
    fabricated is the C13 violation this table exists to prevent.
    """
    __tablename__ = "demand_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(Text, nullable=False, index=True)
    sold_30d = Column(Integer)
    sold_7d = Column(Integer)
    avg_price = Column(Float)
    source = Column(String(64), default="watchlist_monitor")
    captured_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PurchaseCapture(Base):
    """One verified purchase-history capture posted by the browser extension (P5).

    Upserted by item_id — the latest capture wins.
    """
    __tablename__ = "purchase_captures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(64), nullable=False, index=True)
    url = Column(Text)
    sold_7d = Column(Integer)
    sold_30d = Column(Integer)
    sales_json = Column(Text, nullable=False, default="[]")
    captured_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    source = Column(String(32), default="extension")


class TrackedProduct(Base):
    __tablename__ = "tracked_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(Text, nullable=False)
    ebay_url = Column(Text, nullable=False)
    ebay_price = Column(Float, default=0.0)
    target_price = Column(Float, default=0.0)
    supplier_price = Column(Float, default=0.0)
    supplier_url = Column(Text)
    supplier_name = Column(String(128))
    last_checked = Column(DateTime)
    alert_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    price_history = relationship("PriceHistory", back_populates="tracked_product")
    alerts = relationship("PriceAlert", back_populates="tracked_product")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracked_product_id = Column(Integer, ForeignKey("tracked_products.id", ondelete="CASCADE"))
    ebay_price = Column(Float, default=0.0)
    supplier_price = Column(Float, default=0.0)
    checked_at = Column(DateTime, default=datetime.utcnow)

    tracked_product = relationship("TrackedProduct", back_populates="price_history")


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracked_product_id = Column(Integer, ForeignKey("tracked_products.id", ondelete="CASCADE"))
    alert_type = Column(String(32))  # price_drop, price_increase, margin_alert
    message = Column(Text)
    old_price = Column(Float, default=0.0)
    new_price = Column(Float, default=0.0)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    tracked_product = relationship("TrackedProduct", back_populates="alerts")


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(Text, nullable=False)
    ebay_url = Column(Text)
    ebay_price = Column(Float, default=0.0)
    target_price = Column(Float, default=0.0)
    supplier_price = Column(Float, default=0.0)
    supplier_url = Column(Text)
    supplier_name = Column(String(128))
    notes = Column(Text)
    added_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    search_name = Column(Text, nullable=False)
    query = Column(Text, nullable=False)
    category = Column(String(128))
    price_min = Column(Float, default=FILTERS["price_min"])
    price_max = Column(Float, default=FILTERS["price_max"])
    min_margin = Column(Float, default=25.0)
    auto_run = Column(Boolean, default=True)
    last_run = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    results = relationship("SearchResult", back_populates="saved_search", cascade="all, delete-orphan")


class SearchResult(Base):
    __tablename__ = "search_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    search_id = Column(Integer, ForeignKey("saved_searches.id", ondelete="CASCADE"))
    product_name = Column(Text)
    ebay_url = Column(Text)
    ebay_price = Column(Float, default=0.0)
    supplier_price = Column(Float, default=0.0)
    supplier_url = Column(Text)
    supplier_name = Column(String(128))
    profit = Column(Float, default=0.0)
    margin = Column(Float, default=0.0)
    verdict = Column(String(16))
    is_read = Column(Boolean, default=False)
    found_at = Column(DateTime, default=datetime.utcnow)

    saved_search = relationship("SavedSearch", back_populates="results")


class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(Text, nullable=False)
    category = Column(String(128))
    sale_price = Column(Float, nullable=False)
    supplier_cost = Column(Float, default=0.0)
    shipping_cost = Column(Float, default=0.0)
    ebay_fees = Column(Float, default=0.0)
    profit = Column(Float, default=0.0)
    margin_percent = Column(Float, default=0.0)
    quantity = Column(Integer, default=1)
    sale_date = Column(DateTime, nullable=False)
    buyer_location = Column(String(128))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class MonthlyStat(Base):
    __tablename__ = "monthly_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer, nullable=False, unique=True)
    month = Column(Integer, nullable=False, unique=True)
    total_revenue = Column(Float, default=0.0)
    total_profit = Column(Float, default=0.0)
    total_sales = Column(Integer, default=0)
    avg_margin = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
