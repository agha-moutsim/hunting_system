"""
SQLAlchemy models — one class per PostgreSQL table.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, ForeignKey, JSON, DateTime
)
from sqlalchemy.orm import relationship
from db.database import Base, ensure_deal_items_table
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
    # OBSERVED SALE PRICES only — what a buyer actually paid. Nothing this app
    # can currently reach produces one, so these read NULL in practice, and
    # NULL means "no sale was read", never "the price was zero".
    avg_sold_price = Column(Float)
    lowest_sold_price = Column(Float)
    highest_sold_price = Column(Float)
    # SUPPLY-side evidence: the live in-band New listings a query returned and
    # their ASKING prices. Real numbers with a different meaning, kept in their
    # own columns so the two can never be read as one another. They shared the
    # sold columns until 2026-10-19.
    #
    # `active_listings_in_band` was computed from the start but never written
    # down, so a live Analyze run carried it and a replayed History run did not
    # — the same product giving two answers on two screens.
    active_listings_in_band = Column(Integer)
    avg_active_price = Column(Float)
    lowest_active_price = Column(Float)
    highest_active_price = Column(Float)
    # A3 - the individual observed sale prices behind the three figures
    # above, kept so History can redraw the chart for a run long past. A
    # row written before this column existed reads NULL, which loads as
    # "no observations held" and renders no chart rather than a zeroed one.
    sold_prices = Column(JSON)
    # The asking prices behind the `*_active_price` figures, same discipline.
    active_prices = Column(JSON)
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
    # C13 — provenance travels with the row into storage, or History replays
    # supplier rows with no label at all while the live screen shows one.
    # Added 2026-10-06 to a table that already existed, so db.database
    # ALTERs it on startup — create_all only makes MISSING TABLES.
    provenance = Column(String(32))
    provenance_label = Column(String(64))
    # C13 — "api" / "browser" / NULL. NULL means the row never stated it,
    # which is unknown rather than a claim that an API produced it.
    fetch_method = Column(String(16))
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


class DealItem(Base):
    """One listing eBay is currently merchandising on its own deals page.

    Refreshed wholesale. A row is here only because the page showed it, so an
    item eBay has stopped featuring leaves the board rather than lingering as a
    stale "deal". `fetched_at` is the refresh that produced the row, which is
    what lets the board report its own age instead of implying the prices are
    live.

    There is deliberately NO sold count and NO popularity column. eBay
    publishes neither to this app (see scrapers/ebay_deals.py for what was
    measured), and a column would only be an invitation to fill one in.
    """
    __tablename__ = "deal_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(String(32), nullable=False, unique=True, index=True)
    title = Column(Text, nullable=False)
    item_url = Column(Text, nullable=False)
    image_url = Column(Text, default="")
    # NULL is load-bearing: it means the price was not read. A real price of 0
    # is possible, so "unread" and "free" must not share a representation, and
    # the UI renders them differently.
    price = Column(Float)
    currency = Column(String(8), default="")
    seller = Column(String(64), default="")
    store_name = Column(String(128), default="")
    store_url = Column(Text, default="")
    # True only for a storefront link eBay itself rendered (engine.stores).
    store_verified = Column(Boolean, default=False)
    condition = Column(String(64), default="")
    # Position on eBay's page. A real observation about the page's own order,
    # never a rank by sales.
    position = Column(Integer, default=0)
    source = Column(String(32), default="ebay_deals")
    source_label = Column(String(128), default="")
    fetched_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )


# ---------------------------------------------------------------------------
# The board's table has to exist before anything can read it, and table
# creation otherwise only happens in the manual `python -m db.init_db` step.
# So a database created before this table existed would raise "no such table:
# deal_items" the first time the board was opened. Same self-healing stance as
# the column ALTERs in db/database.py.
#
# Called here, at the END of the module, because the helper creates the table
# from the model class above: running it earlier would find no such model.
# ---------------------------------------------------------------------------
ensure_deal_items_table()
