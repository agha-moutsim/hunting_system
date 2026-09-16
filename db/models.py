"""
SQLAlchemy models — one class per PostgreSQL table.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, ForeignKey, JSON, DateTime
)
from sqlalchemy.orm import relationship
from db.database import Base


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
