r"""Provenance has to survive into storage, or History is a second story.

The live screen labels every supplier row (C13: the label is data), but the
`supplier_matches` table had no provenance columns, so replaying a saved
analysis showed none — a row that was marked on the way in lost its mark on
the way back out.

Two things are under test:

  * the SCHEMA. These columns were added to a table that already existed,
    and this repo has no migration framework — `create_all` only creates
    MISSING TABLES, never missing columns. `ensure_supplier_match_columns`
    closes that gap and must be idempotent, must not touch a table that is
    absent, and must leave existing rows where they are.
  * the ROUND TRIP. What `save_analysis_to_db` writes is what
    `/history/{id}` hands back, and a row that never stated a provenance
    comes back as null rather than as a invented "verified".
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import db.database as dbmod
from db.database import Base


OLD_SUPPLIER_MATCHES = """
CREATE TABLE supplier_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    supplier_name VARCHAR(64) NOT NULL,
    supplier_url TEXT,
    supplier_title TEXT,
    supplier_price FLOAT,
    delivery_days_min INTEGER,
    delivery_days_max INTEGER,
    supplier_type VARCHAR(32),
    confidence VARCHAR(16),
    match_score FLOAT,
    verified BOOLEAN,
    created_at DATETIME
)
"""

NEW = (
    "provenance",
    "provenance_label",
    "fetch_method",
    "review_rating",
    "review_count",
    "review_verified",
    "review_source",
    "stock_status",
    "stock_verified",
    "shipping_known",
    "shipping_methods",
    "standard_shipping_available",
    "standard_shipping_cost",
    "standard_shipping_days_min",
    "standard_shipping_days_max",
    "standard_shipping_raw",
    "total_landed_cost",
    "sourcing_preferred",
    "sourcing_eligible",
    "sourcing_reasons",
    "sourcing_score",
    "sourcing_policy_version",
)


@pytest.fixture()
def old_db(tmp_path, monkeypatch):
    """A database whose supplier_matches predates the three columns."""
    engine = create_engine(f"sqlite:///{tmp_path/'old.db'}")
    with engine.begin() as conn:
        conn.execute(text(OLD_SUPPLIER_MATCHES))
        conn.execute(
            text(
                "INSERT INTO supplier_matches (supplier_name, supplier_price,"
                " verified) VALUES ('AliExpress', 9.99, 1)"
            )
        )
    monkeypatch.setattr(dbmod, "engine", engine)
    return engine


def _cols(engine):
    with engine.connect() as conn:
        rows = conn.execute(
            text("PRAGMA table_info(supplier_matches)")
        ).fetchall()
    return {r[1] for r in rows}


class TestTheSchemaMigration:
    def test_missing_columns_are_added(self, old_db):
        from db.database import ensure_supplier_match_columns

        added = ensure_supplier_match_columns()

        assert set(added) == set(NEW)
        assert set(NEW) <= _cols(old_db)

    def test_a_second_run_adds_nothing(self, old_db):
        from db.database import ensure_supplier_match_columns

        ensure_supplier_match_columns()
        assert ensure_supplier_match_columns() == []

    def test_existing_rows_survive_the_alter(self, old_db):
        from db.database import ensure_supplier_match_columns

        ensure_supplier_match_columns()

        with old_db.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT supplier_name, supplier_price, provenance,"
                    " fetch_method FROM supplier_matches"
                )
            ).fetchone()

        assert row[0] == "AliExpress"
        assert row[1] == 9.99
        # Backfilled with nothing: this row was saved before the column
        # existed and nobody has said what it was. NULL, never "verified".
        assert row[2] is None
        assert row[3] is None

    def test_a_database_without_the_table_is_left_alone(self, tmp_path, monkeypatch):
        engine = create_engine(f"sqlite:///{tmp_path/'empty.db'}")
        monkeypatch.setattr(dbmod, "engine", engine)

        from db.database import ensure_supplier_match_columns

        assert ensure_supplier_match_columns() == []


class TestTheRoundTrip:
    """save_supplier_match_data -> /history/{id}."""

    @pytest.fixture()
    def session_factory(self, tmp_path, monkeypatch):
        # Models register themselves with Base on import; without this
        # create_all has nothing to create and every query hits an empty
        # database.
        import db.models  # noqa: F401

        engine = create_engine(f"sqlite:///{tmp_path/'fresh.db'}")
        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine)
        # Every consumer reads SessionLocal from here, including the
        # history endpoint, so this points all of them at the temp database.
        monkeypatch.setattr(dbmod, "SessionLocal", factory)
        monkeypatch.setattr(dbmod, "engine", engine)
        return factory

    @staticmethod
    def _save(factory, **supplier_overrides):
        from db.queries import save_product, save_supplier_match_data
        from scrapers.base import ScrapedProduct

        db = factory()
        try:
            product_id = save_product(db, ScrapedProduct(
                source="ebay_uk", title="Generic widget", price=12.0,
                url="https://www.ebay.co.uk/itm/1", condition="New",
            ))
            row = save_supplier_match_data(db, product_id, {
                "supplier_name": "AliExpress",
                "supplier_url": "https://www.aliexpress.com/item/1.html",
                "supplier_title": "Generic widget",
                "supplier_price": 9.99,
                "verified": True,
                "provenance": "verified",
                "provenance_label": "Verified",
                "fetch_method": "browser",
                **supplier_overrides,
            })
            return row.product_id, row.id
        finally:
            db.close()

    def test_a_labelled_row_is_persisted_and_replayed(self, session_factory):
        from api.history import product_detail

        product_id, _ = self._save(session_factory)

        detail = product_detail(product_id)
        sup = detail["suppliers"][0]

        assert sup["provenance"] == "verified"
        assert sup["provenance_label"] == "Verified"
        assert sup["fetch_method"] == "browser"

    def test_a_browser_row_keeps_its_method_through_the_round_trip(
        self, session_factory
    ):
        from api.history import product_detail

        product_id, _ = self._save(
            session_factory, provenance="verified",
            provenance_label="Verified", fetch_method="browser",
        )

        sup = product_detail(product_id)["suppliers"][0]
        assert sup["fetch_method"] == "browser"

    def test_a_row_that_never_stated_one_comes_back_as_null(
        self, session_factory
    ):
        """Not "verified", not "api" — the row never said, so null says so."""
        from api.history import product_detail

        product_id, _ = self._save(
            session_factory, provenance=None,
            provenance_label=None, fetch_method=None,
        )

        sup = product_detail(product_id)["suppliers"][0]

        assert sup["provenance"] is None
        assert sup["provenance_label"] is None
        assert sup["fetch_method"] is None


class TestSaveAnalysisToDbCarriesTheStamp:
    """The dict built at the call site, not the row the mapper writes.

    The two are separate failure points: a correct `save_supplier_match_data`
    still persists nothing if `save_analysis_to_db` never puts the fields in
    the dict. Captured here the same way test_match_score_persistence.py
    captures `match_score`.
    """

    @pytest.fixture()
    def saved(self, monkeypatch):
        import analysis_pipeline as ap

        captured: list[dict] = []
        monkeypatch.setattr(
            ap, "save_supplier_match_data",
            lambda db, product_id, data: captured.append(data),
        )
        return captured

    @staticmethod
    def _results(*suppliers):
        from scrapers.base import ScrapedProduct

        return {
            "ebay_product": ScrapedProduct(
                source="ebay_uk", title="Generic widget", price=12.0,
                url="https://www.ebay.co.uk/itm/1", condition="New",
                verified=True,
            ),
            "demand": None,
            "supplier_matches": list(suppliers),
            "llm_analysis": None,
            "verdict": None,
        }

    @staticmethod
    def _supplier(**marks):
        from scrapers.base import ScrapedProduct

        s = ScrapedProduct(
            source="AliExpress", title="Generic widget", price=9.99,
            url="https://www.aliexpress.com/item/1.html", condition="",
            verified=True,
        )
        for k, v in marks.items():
            setattr(s, k, v)
        return s

    def test_a_stamped_row_reaches_the_persistence_layer(self, saved):
        import analysis_pipeline as ap

        ap.save_analysis_to_db(self._results(self._supplier(
            provenance="verified", provenance_label="Verified",
            fetch_method="browser",
        )))

        assert saved[0]["provenance"] == "verified"
        assert saved[0]["provenance_label"] == "Verified"
        assert saved[0]["fetch_method"] == "browser"

    def test_an_unstamped_row_becomes_null_not_an_empty_string(self, saved):
        """An empty string would be a claim the row said something."""
        import analysis_pipeline as ap

        ap.save_analysis_to_db(self._results(self._supplier(
            provenance="", provenance_label="", fetch_method="",
        )))

        assert saved[0]["provenance"] is None
        assert saved[0]["provenance_label"] is None
        assert saved[0]["fetch_method"] is None

    def test_every_supplied_row_is_captured(self, saved):
        import analysis_pipeline as ap

        ap.save_analysis_to_db(self._results(
            self._supplier(provenance="verified", fetch_method="browser"),
            self._supplier(provenance="verified", fetch_method="api"),
        ))

        assert [r["fetch_method"] for r in saved] == ["browser", "api"]
