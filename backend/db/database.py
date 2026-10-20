"""
Database connection and session management.
"""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config import DATABASE_URL


engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


# Columns added to an EXISTING table, with their DDL.
#
# Base.metadata.create_all only creates missing TABLES, so a column added to
# a model never reaches a database that was created before that change — and
# the failure it causes is a bare "no such column" surfacing in whatever the
# user happens to be looking at. This repo has no migration framework, so the
# gap is closed here instead: inspected first, ALTERed only when actually
# missing, so running it is a no-op on every run after the first.
_SUPPLIER_MATCH_ADDITIONS = (
    ("provenance", "VARCHAR(32)"),
    ("provenance_label", "VARCHAR(64)"),
    ("fetch_method", "VARCHAR(16)"),
)


def ensure_supplier_match_columns() -> list[str]:
    """Bring `supplier_matches` up to the columns the model declares.

    Returns the column names it added, so a caller can report the change
    rather than performing it in silence.
    """
    inspector = inspect(engine)
    if not inspector.has_table("supplier_matches"):
        return []
    existing = {c["name"] for c in inspector.get_columns("supplier_matches")}
    added: list[str] = []
    for name, ddl in _SUPPLIER_MATCH_ADDITIONS:
        if name in existing:
            continue
        with engine.begin() as conn:
            conn.execute(
                text(f"ALTER TABLE supplier_matches ADD COLUMN {name} {ddl}")
            )
        added.append(name)
    return added


# Every consumer imports this module before it can issue a query, so the
# ALTER runs before SQLAlchemy ever SELECTs one of these columns — including
# in the test suite, which talks to the same database.
ensure_supplier_match_columns()


# A3 — same treatment for the sold-price observations. SQLite cannot add a
# column that already exists, so this is inspected first and ALTERed only
# when genuinely missing: a no-op on every run after the first.
_DEMAND_DATA_ADDITIONS = (
    ("sold_prices", "JSON"),
    # 2026-10-19 - the SUPPLY-side evidence set. `active_listings_in_band` had
    # been computed since Phase 1 and never persisted, so a live Analyze run
    # carried it and a replayed History run did not: one product, two screens,
    # two different answers. The prices join it because they describe the same
    # rows and must survive or vanish together.
    ("active_listings_in_band", "INTEGER"),
    ("avg_active_price", "FLOAT"),
    ("lowest_active_price", "FLOAT"),
    ("highest_active_price", "FLOAT"),
    ("active_prices", "JSON"),
    # Phase C - the sold figure's provenance: which source produced it and when
    # that source observed it. Existing rows read NULL, which is the honest
    # answer for them: the row recorded a count without recording where from,
    # and inventing a source for it now would be a fabricated citation.
    ("sold_source", "VARCHAR(32)"),
    ("sold_captured_at", "DATETIME"),
)


def ensure_demand_data_columns() -> list[str]:
    """Bring `demand_data` up to the columns the model declares.

    Returns the column names it added, so a caller can report the change
    rather than performing it in silence.
    """
    inspector = inspect(engine)
    if not inspector.has_table("demand_data"):
        return []
    existing = {c["name"] for c in inspector.get_columns("demand_data")}
    added: list[str] = []
    for name, ddl in _DEMAND_DATA_ADDITIONS:
        if name in existing:
            continue
        with engine.begin() as conn:
            conn.execute(
                text(f"ALTER TABLE demand_data ADD COLUMN {name} {ddl}")
            )
        added.append(name)
    return added


ensure_demand_data_columns()


# The deals board reads a table nothing else creates on the way in, so it
# self-heals exactly the way the column ALTERs above do.
def ensure_deal_items_table() -> bool:
    """Create `deal_items` if it is missing. True when it had to be created.

    CALLED FROM THE BOTTOM OF db/models.py rather than from here, because the
    table is built from the model class and must not be created before that
    class exists. Doing it there also keeps both import orders safe: importing
    `db.models` first still finds this function defined, since database.py
    finishes loading before models.py reaches its last line.

    Built from Base.metadata rather than raw DDL so the model stays the single
    definition of the table and the two can never drift apart.
    """
    inspector = inspect(engine)
    if inspector.has_table("deal_items"):
        return False
    from db.models import DealItem  # deferred: db.models imports this module
    Base.metadata.create_all(bind=engine, tables=[DealItem.__table__])
    return True


def ensure_listing_observations_table() -> bool:
    """Create `listing_observations` if it is missing. True when it had to be.

    The same self-healing stance as `ensure_deal_items_table` above and for the
    same reason: this table is new, and a database created before it existed
    would otherwise raise "no such table: listing_observations" the first time
    History was opened.

    No column ALTERs accompany it. The `_*_ADDITIONS` helpers above exist to
    reach columns added to a table that already existed; a brand-new table is
    created whole, and adding empty tuples for it now would be code that never
    runs.
    """
    inspector = inspect(engine)
    if inspector.has_table("listing_observations"):
        return False
    from db.models import ListingObservation  # deferred: db.models imports this
    Base.metadata.create_all(
        bind=engine, tables=[ListingObservation.__table__]
    )
    return True


def ensure_query_observations_table() -> bool:
    """Create `query_observations` if it is missing. True when it had to be.

    The table stores one completed search result set per query. It is what
    makes churn answerable: `listing_observations` is change-only by design,
    so it cannot prove that a listing was absent from a later search. A
    database created before Phase G would otherwise raise "no such table"
    the first time the churn page was opened.
    """
    inspector = inspect(engine)
    if inspector.has_table("query_observations"):
        return False
    from db.models import QueryObservation  # deferred: db.models imports this
    Base.metadata.create_all(bind=engine, tables=[QueryObservation.__table__])
    return True


def get_db():
    """Dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
