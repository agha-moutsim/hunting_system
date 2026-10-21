"""
SQLAlchemy models — one class per PostgreSQL table.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, ForeignKey, JSON, DateTime,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from db.database import (
    Base,
    ensure_deal_items_table,
    ensure_listing_observations_table,
    ensure_monthly_stats_constraint,
    ensure_query_observations_table,
)
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
    # PHASE C - WHERE THE SOLD FIGURE CAME FROM, AND WHEN IT WAS READ.
    #
    # `sold_count_7d` is the only sold number this app can verify, and exactly
    # one thing can produce it: the capture extension reading the user's own
    # eBay purchase history inside their own logged-in session (see
    # extension/README.md). These two columns are NOT a second copy of
    # `verified` - they say WHICH source produced the number and WHEN it
    # observed it, which is what lets a screen read "12 sold in 7 days, eBay
    # purchase history, read 2h ago" instead of a bare 12 that could have come
    # from anywhere.
    #
    # NULL means no capture-backed sold figure is held. That is the normal case,
    # and it is not a gap to be filled: every Browse-derived count is SUPPLY, and
    # it lives in the `active_*` columns under names that say so.
    sold_source = Column(String(32))
    sold_captured_at = Column(DateTime)
    # A SENTENCE, not a token. The measured value names the query that produced
    # the figures and states what it can and cannot mean - well past 64
    # characters. SQLite ignores VARCHAR lengths, so the narrow type never
    # failed here, but the same sentence would have been silently truncated on
    # any engine that honours it.
    data_source = Column(Text, default="ebay_sold_listings")
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
    # C13 — “api” / “browser” / NULL. NULL means the row never stated it,
    # which is unknown rather than a claim that an API produced it.
    fetch_method = Column(String(16))
    # Sourcing standard — real review, stock, shipping and ranking evidence.
    # NULL/False/empty means “not read”; never a default or a guess.
    review_rating = Column(Float)
    review_count = Column(Integer)
    review_verified = Column(Boolean)
    review_source = Column(String(32))
    stock_status = Column(String(32))
    stock_verified = Column(Boolean)
    shipping_known = Column(Boolean)
    shipping_methods = Column(JSON)
    standard_shipping_available = Column(Boolean)
    standard_shipping_cost = Column(Float)
    standard_shipping_days_min = Column(Integer)
    standard_shipping_days_max = Column(Integer)
    standard_shipping_raw = Column(Text)
    total_landed_cost = Column(Float)
    sourcing_preferred = Column(Boolean)
    sourcing_eligible = Column(Boolean)
    sourcing_reasons = Column(JSON)
    sourcing_score = Column(Float)
    sourcing_policy_version = Column(String(32))
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
    # No defaults on costs or profit: an undeclared cost must stay NULL, and
    # NULL profit means unknown. A default of 0.0 would turn both into a real
    # zero the user never stated (C1).
    supplier_cost = Column(Float)
    shipping_cost = Column(Float)
    ebay_fees = Column(Float)
    profit = Column(Float)
    margin_percent = Column(Float)
    quantity = Column(Integer, default=1)
    sale_date = Column(DateTime, nullable=False)
    buyer_location = Column(String(128))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class MonthlyStat(Base):
    """One calendar month of user-declared sales.

    `year` and `month` are unique TOGETHER, never separately. Separate
    `unique=True` flags made October 2025 and October 2026 collide, so the
    table could only ever hold twelve months in total. The old database is
    rebuilt by `db.database.ensure_monthly_stats_constraint()` because SQLite
    cannot drop the single-column UNIQUE constraints in place.
    """

    __tablename__ = "monthly_stats"
    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_monthly_stats_year_month"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    total_revenue = Column(Float)
    # NULL means at least one sale in the month did not declare every cost,
    # so profit is unknown rather than zero (C1).
    total_profit = Column(Float)
    total_sales = Column(Integer, default=0)
    avg_margin = Column(Float)
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
    #: Unique per market, not globally: the same eBay listing can be
    #: merchandised on two marketplaces, and one market's refresh must never
    #: steal or delete the other market's row.
    listing_id = Column(String(32), nullable=False, index=True)
    #: Phase J — which marketplace's deals page produced this row. Existing
    #: rows predate the column and are eBay UK observations; the ALTER in
    #: db/database.py gives them that default rather than leaving them
    #: unassigned. The board reads one market at a time and never mixes them.
    marketplace = Column(String(16), nullable=False, default="EBAY_GB", index=True)
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

    __table_args__ = (
        UniqueConstraint(
            "marketplace", "listing_id",
            name="uq_deal_items_marketplace_listing",
        ),
    )


class ListingObservation(Base):
    """One Browse reading of one listing, kept as evidence.

    APPEND-ONLY. `deal_items` is upsert-by-listing-id because a board row means
    "eBay is featuring this now"; this table means "this is what the Browse API
    said at this moment", and a reading that can be overwritten cannot show that
    anything changed. Nothing here is derived, ranked or inferred - every value
    is a field eBay returned (see scrapers/browse_fields.py for the shapes,
    which were measured against a live payload before being written down).

    A reading is stored only when it DIFFERS from the last one for that listing,
    so `observed_at` means "the listing became different here" and an hourly
    refresh of an unchanged board adds no rows.

    NULL is load-bearing throughout: it means the Browse API did not return that
    field - measured on a real payload, `itemOriginDate`, `itemGroupType`,
    `itemLocation.postalCode` and `seller.storeName` were all absent. None of
    them is defaulted to 0, "" or False, because "not read" and "read as zero"
    are different facts and only one of them is evidence.
    """
    __tablename__ = "listing_observations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(String(32), nullable=False, index=True)
    observed_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    item_creation_date = Column(DateTime)
    item_origin_date = Column(DateTime)

    seller_username = Column(String(64))
    # eBay sends this as the string "99.1" (measured); stored as a number so it
    # can be compared without every reader re-parsing it.
    seller_feedback_percentage = Column(Float)
    seller_feedback_score = Column(Integer)
    # BUSINESS or INDIVIDUAL - eBay's own word, kept verbatim.
    seller_account_type = Column(String(16))
    seller_store_name = Column(String(128))

    item_country = Column(String(8))
    item_city = Column(String(64))
    item_postal_code = Column(String(16))

    condition_id = Column(String(16))
    condition_text = Column(String(64))
    category_id = Column(String(32))
    category_name = Column(String(128))

    # Nullable booleans on purpose: absent is not False.
    top_rated = Column(Boolean)
    priority_listing = Column(Boolean)
    item_group_type = Column(String(32))
    buying_options = Column(JSON)

    price = Column(Float)
    currency = Column(String(8))
    # 0.00 is a real measured value (free postage); None means not read.
    shipping_cost = Column(Float)
    shipping_currency = Column(String(8))
    shipping_type = Column(String(64))

    #: Which Browse surface produced this reading - scrapers/browse_fields.py
    #: holds the two values. A search-summary reading is less complete than an
    #: item reading, so a NULL is only interpretable alongside this.
    source = Column(String(32), default="browse_api_item")


class QueryObservation(Base):
    """One completed Browse search result set for one query.

    `listing_observations` answers "what changed about this listing" and
    deliberately stores nothing when a reading repeats the last one. That is
    the right table for field history, but it cannot answer "was this listing
    present in the latest search": an unchanged listing leaves no row, so its
    absence from that table is not absence from eBay.

    This table stores the SET a search returned, once per search, including a
    search that returned zero listings. Churn is a comparison of two of these
    sets, which is why a zero-result search must still leave a row - otherwise
    "we searched and saw nothing" would be indistinguishable from "we never
    searched."

    `listings` is a JSON list of the display fields read from the summaries:
    listing_id, title, item_url, price, currency and item_creation_date.
    Everything in it came from eBay in the response being recorded; no field
    is derived. `price_filter` and `sample_limit` are the exact request knobs,
    kept so two observations are only compared when they describe the same
    population.
    """

    __tablename__ = "query_observations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(Text, nullable=False, index=True)
    observed_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    source = Column(String(32), default="browse_search")
    #: The exact Browse filter string (condition + price band) sent for this
    #: search. Churn refuses to compare runs whose filters differ.
    price_filter = Column(Text)
    #: The sample ceiling actually sent (min(requested, eBay's 50)).
    sample_limit = Column(Integer)
    #: len(listings), stored so a reader does not have to trust or parse JSON
    #: just to report the sample size.
    listing_count = Column(Integer, nullable=False, default=0)
    listings = Column(JSON, nullable=False, default=list)


# ---------------------------------------------------------------------------
# These tables have to exist before anything can read them, and table creation
# otherwise only happens in the manual `python -m db.init_db` step. So a
# database created before a table existed would raise "no such table" the first
# time the surface that reads it was opened. Same self-healing stance as the
# column ALTERs in db/database.py.
#
# Called here, at the END of the module, because the helpers create the tables
# from the model classes above: running them earlier would find no such models.
# ---------------------------------------------------------------------------
ensure_deal_items_table()
ensure_listing_observations_table()
ensure_query_observations_table()
ensure_monthly_stats_constraint()
