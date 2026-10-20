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


# Phase J — a deals row now names its marketplace. The table already exists on
# every deployed database, so the column is ALTERed in place. The default is
# the historical truth: every row written before this change came from the UK
# deals page, and leaving those rows unset would make them disappear from a
# board that filters by market.
_DEAL_ITEM_ADDITIONS = (
    ("marketplace", "VARCHAR(16) NOT NULL DEFAULT 'EBAY_GB'"),
)


def ensure_deal_item_columns() -> list[str]:
    """Bring `deal_items` up to the columns the model declares."""
    inspector = inspect(engine)
    if not inspector.has_table("deal_items"):
        return []
    existing = {c["name"] for c in inspector.get_columns("deal_items")}
    added: list[str] = []
    for name, ddl in _DEAL_ITEM_ADDITIONS:
        if name in existing:
            continue
        with engine.begin() as conn:
            conn.execute(
                text(f"ALTER TABLE deal_items ADD COLUMN {name} {ddl}")
            )
        added.append(name)
    return added


def _deal_item_unique_sets() -> set[tuple[str, ...]]:
    """Every unique rule on `deal_items`, whether an index or a constraint."""
    inspector = inspect(engine)
    sets = {
        tuple(constraint.get("column_names") or ())
        for constraint in inspector.get_unique_constraints("deal_items")
    }
    sets.update(
        tuple(index.get("column_names") or ())
        for index in inspector.get_indexes("deal_items")
        if index.get("unique")
    )
    return sets


def ensure_deal_items_marketplace_unique() -> str:
    """Give `deal_items` uniqueness on `(marketplace, listing_id)`.

    The original table made `listing_id` unique on its own. That is wrong once
    two marketplaces are stored: the same eBay listing can be merchandised on
    both pages, and a global unique index either rejects the second row or
    forces `save_deals` to move the first market's row to the second. SQLite
    cannot drop a table-level UNIQUE, so this is the same idempotent
    rename/create/copy/drop rebuild used for `monthly_stats`.

    Returns ``"missing"`` (no table), ``"migrated"``, or ``"present"``.
    """
    inspector = inspect(engine)
    if not inspector.has_table("deal_items"):
        return "missing"

    unique_sets = _deal_item_unique_sets()
    desired = ("marketplace", "listing_id")
    if desired in unique_sets and ("listing_id",) not in unique_sets:
        return "present"

    old_name = "deal_items__pre_market_unique"
    with engine.begin() as conn:
        from db.models import DealItem  # deferred: db.models imports this

        conn.execute(text(f'DROP TABLE IF EXISTS "{old_name}"'))
        conn.execute(
            text(f'ALTER TABLE deal_items RENAME TO "{old_name}"')
        )

        # Index names are database-global in SQLite and survive a table
        # rename. Leaving the old `ix_deal_items_*` names behind makes
        # creating the new table fail on the first CREATE INDEX.
        for index in inspect(conn).get_indexes(old_name):
            index_name = index.get("name")
            if index_name:
                conn.execute(text(f'DROP INDEX IF EXISTS "{index_name}"'))

        old_columns = {
            column["name"]
            for column in inspect(conn).get_columns(old_name)
        }
        declared = [column.name for column in DealItem.__table__.columns]
        copy_columns = [name for name in declared if name in old_columns]
        quoted = ", ".join(f'"{name}"' for name in copy_columns)

        duplicate = conn.execute(
            text(
                f'SELECT marketplace, listing_id, COUNT(*) FROM "{old_name}" '
                "GROUP BY marketplace, listing_id HAVING COUNT(*) > 1"
            )
        ).fetchall()
        if duplicate:
            pairs = ", ".join(
                f"{market}/{listing_id}" for market, listing_id, _ in duplicate
            )
            raise RuntimeError(
                "deal_items cannot be migrated because these market/listing "
                f"pairs appear more than once: {pairs}. Delete the duplicates, "
                "then start the app again."
            )

        DealItem.__table__.create(bind=conn)
        conn.execute(
            text(
                f"INSERT INTO deal_items ({quoted}) "
                f'SELECT {quoted} FROM "{old_name}"'
            )
        )
        conn.execute(text(f'DROP TABLE "{old_name}"'))

    return "migrated"


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
    definition of the table and the two can never drift apart. An existing
    table still gets the Phase J `marketplace` column and the composite
    uniqueness the registry needs.
    """
    inspector = inspect(engine)
    if inspector.has_table("deal_items"):
        ensure_deal_item_columns()
        ensure_deal_items_marketplace_unique()
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


def _monthly_stats_unique_sets() -> list[tuple[str, ...]]:
    """The unique column sets currently enforced on `monthly_stats`."""
    inspector = inspect(engine)
    if not inspector.has_table("monthly_stats"):
        return []
    found: list[tuple[str, ...]] = []
    for constraint in inspector.get_unique_constraints("monthly_stats"):
        columns = tuple(constraint.get("column_names") or ())
        if columns:
            found.append(columns)
    for index in inspector.get_indexes("monthly_stats"):
        if not index.get("unique"):
            continue
        columns = tuple(index.get("column_names") or ())
        if columns and columns not in found:
            found.append(columns)
    return found


def ensure_monthly_stats_constraint() -> str:
    """Give `monthly_stats` ONE unique constraint on `(year, month)`.

    Returns ``"created"`` when the table did not exist, ``"migrated"`` when it
    was rebuilt, and ``"present"`` when it already had the right rule.

    The original model declared ``unique=True`` on `year` and on `month`
    separately. That is not merely redundant: it makes every October share one
    row, so a second year cannot be stored at all. SQLite has no
    `DROP CONSTRAINT`, and the offending rules are table-level UNIQUE
    constraints, so the only safe repair is a table rebuild:

        rename -> create from the model -> copy -> drop the old table

    Everything runs in one transaction, and duplicate `(year, month)` pairs
    are rejected with a sentence before any data is moved. The function is
    idempotent; `db/models.py` calls it on every import, and the second call
    is a no-op.
    """
    inspector = inspect(engine)
    if not inspector.has_table("monthly_stats"):
        from db.models import MonthlyStat  # deferred: db.models imports this

        MonthlyStat.__table__.create(bind=engine)
        return "created"

    unique_sets = _monthly_stats_unique_sets()
    desired = [("year", "month")]
    if unique_sets == desired:
        return "present"

    old_name = "monthly_stats__pre_composite"
    with engine.begin() as conn:
        from db.models import MonthlyStat  # deferred: db.models imports this

        conn.execute(text("DROP TABLE IF EXISTS monthly_stats__pre_composite"))
        conn.execute(
            text(f'ALTER TABLE monthly_stats RENAME TO "{old_name}"')
        )

        old_columns = {
            column["name"]
            for column in inspect(conn).get_columns(old_name)
        }
        declared = [column.name for column in MonthlyStat.__table__.columns]
        copy_columns = [name for name in declared if name in old_columns]
        quoted = ", ".join(f'"{name}"' for name in copy_columns)

        duplicate = conn.execute(
            text(
                f'SELECT year, month, COUNT(*) FROM "{old_name}" '
                "GROUP BY year, month HAVING COUNT(*) > 1"
            )
        ).fetchall()
        if duplicate:
            pairs = ", ".join(f"{year}-{month:02d}" for year, month, _ in duplicate)
            # Raising inside engine.begin() rolls the rename back, so the old
            # table is still the live table when the caller sees this sentence.
            raise RuntimeError(
                "monthly_stats cannot be migrated because these year-month "
                f"pairs appear more than once: {pairs}. Merge or delete the "
                "duplicates, then start the app again."
            )

        MonthlyStat.__table__.create(bind=conn)
        conn.execute(
            text(
                f'INSERT INTO monthly_stats ({quoted}) '
                f'SELECT {quoted} FROM "{old_name}"'
            )
        )
        conn.execute(text(f'DROP TABLE "{old_name}"'))

    return "migrated"


def get_db():
    """Dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
