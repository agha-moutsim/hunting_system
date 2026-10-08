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


def get_db():
    """Dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
