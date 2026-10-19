"""Phase C — a verified sold figure outranks everything derived from a search.

The one sold number this app can stand behind is `sold_count_7d`, and exactly one
thing produces it: the capture extension reading the user's own eBay purchase
history inside their own logged-in session (see extension/README.md). Everything
else eBay tells this app is a count of LIVE listings — supply — and it lives in
the `active_*` columns under names that say so.

That distinction is only worth anything if a stored figure can be traced back to
the source that produced it and the moment that source observed it. These tests
pin that: the value, its origin, and its read time travel together or not at all.

No network here. The only external fact is the extension's own HTML, and even
that is reduced to a stored row before the pipeline sees it. The rest runs
against a throwaway SQLite database.
"""

from datetime import datetime, timedelta

import pytest

from analysis_pipeline import SOLD_SOURCE_PURCHASE_HISTORY, apply_purchase_history
from scrapers.base import DemandData

ITEM_ID = "1234567890"
URL = f"https://www.ebay.co.uk/itm/{ITEM_ID}"


def _fresh_database(tmp_path):
    """A throwaway SQLite database carrying every table the app declares."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db.database import Base
    import db.models  # noqa: F401 - registers every table on Base.metadata

    engine = create_engine(f"sqlite:///{tmp_path / 'verified.db'}")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)


@pytest.fixture()
def sessions(tmp_path, monkeypatch):
    """One throwaway database, reached by the direct callers AND the API.

    `api.history` imports SessionLocal from db.database when the route runs, so
    patching it here points the endpoint and the tests at the same temp
    database. `engine` goes with it: anything that inspects or migrates would
    otherwise silently look at the real file.
    """
    import db.database as dbmod

    engine, factory = _fresh_database(tmp_path)
    monkeypatch.setattr(dbmod, "SessionLocal", factory)
    monkeypatch.setattr(dbmod, "engine", engine)
    return factory


def _store_capture(sessions, *, sold_7d=12, captured_at=None, item_id=ITEM_ID):
    """One capture row, as the extension would have posted it.

    Returns the moment it claims to have read the page, which is the value the
    rest of the chain has to carry rather than the time this test ran.
    """
    from db.models import PurchaseCapture

    read_at = captured_at or datetime.utcnow()
    session = sessions()
    try:
        session.add(
            PurchaseCapture(item_id=item_id, sold_7d=sold_7d, captured_at=read_at)
        )
        session.commit()
    finally:
        session.close()
    return read_at


# ---------------------------------------------------------------------------
# 1. The figure and its origin travel together
# ---------------------------------------------------------------------------

class TestTheSoldFigureCarriesItsOrigin:
    def test_a_capture_attaches_its_source_and_its_read_time(self, sessions):
        read_at = _store_capture(sessions, sold_7d=12)

        out = apply_purchase_history(DemandData(verified=False), URL, db=sessions())

        assert out.sold_count_7d == 12
        assert out.sold_source == SOLD_SOURCE_PURCHASE_HISTORY
        assert out.sold_captured_at == read_at
        assert out.verified_7d is True

    def test_the_read_time_is_when_the_browser_read_it_not_when_this_ran(
        self, sessions
    ):
        """The two can be a day apart, which is the whole reason the column
        exists. A screen saying "read just now" about a capture from yesterday
        would be the same defect as a live listing counted as a sale."""
        twenty_hours_ago = datetime.utcnow() - timedelta(hours=20)
        _store_capture(sessions, sold_7d=12, captured_at=twenty_hours_ago)

        out = apply_purchase_history(DemandData(verified=False), URL, db=sessions())

        assert out.sold_captured_at == twenty_hours_ago
        assert out.sold_captured_at < datetime.utcnow() - timedelta(hours=19)

    def test_the_sentence_names_the_source_that_produced_the_sold_figure(
        self, sessions
    ):
        _store_capture(sessions)
        query_sentence = (
            "ebay_browse_active_listings: in-band New ACTIVE listings the search "
            "returned. Supply, not sales."
        )

        out = apply_purchase_history(
            DemandData(verified=False, data_source=query_sentence),
            URL,
            db=sessions(),
        )

        # The query's own description survives — it still describes the supply
        # figures — and the sold figure's source is stated on top of it.
        assert out.data_source.startswith("ebay_browse_active_listings")
        assert "7-day sold figure: eBay purchase history" in out.data_source
        assert "Supply, not sales." in out.data_source

    def test_applying_it_twice_does_not_stack_the_sentence(self, sessions):
        """The override is reachable from two places (Analyze and the profit
        calculator), so a second application has to be a no-op, not a run-on."""
        _store_capture(sessions)

        once = apply_purchase_history(DemandData(verified=False), URL, db=sessions())
        twice = apply_purchase_history(once, URL, db=sessions())

        assert twice.data_source == once.data_source
        assert twice.data_source.count("7-day sold figure") == 1

    def test_a_stale_capture_attaches_nothing_at_all(self, sessions):
        """Past the window the capture is not evidence of the last 7 days, so
        there is no figure and therefore no source to attribute."""
        _store_capture(
            sessions, sold_7d=12, captured_at=datetime.utcnow() - timedelta(hours=25)
        )

        out = apply_purchase_history(DemandData(verified=False), URL, db=sessions())

        assert out.sold_count_7d is None
        assert out.sold_source is None
        assert out.sold_captured_at is None
        assert out.verified_7d is None
        assert out.data_source is None

    def test_no_capture_means_no_source_even_when_a_count_exists(self, sessions):
        """A Browse-derived count is supply. It must never pick up a sold
        source on its way through, however many listings it counted."""
        supply = DemandData(
            verified=False,
            sold_count_7d=None,
            active_listings_in_band=50,
            avg_active_price=21.99,
        )

        out = apply_purchase_history(supply, URL, db=sessions())

        assert out.sold_source is None
        assert out.sold_count_7d is None
        assert out.active_listings_in_band == 50  # untouched and still supply


# ---------------------------------------------------------------------------
# 2. What the stored row remembers
# ---------------------------------------------------------------------------

class TestWhatTheRowRemembers:
    def test_the_row_stores_the_source_and_the_read_time(self, sessions):
        from db.queries import save_demand_data

        read_at = _store_capture(sessions, sold_7d=12)
        demand = apply_purchase_history(
            DemandData(verified=False), URL, db=sessions()
        )

        session = sessions()
        try:
            row = save_demand_data(session, 1, demand)
            assert row.sold_count_7d == 12
            assert row.sold_source == "purchase_history"
            assert row.sold_captured_at == read_at
        finally:
            session.close()

    def test_a_rerun_without_a_capture_clears_the_previous_source(self, sessions):
        """All-or-nothing, like every other evidence set on this row: leaving a
        source behind next to a NULL count would read as a sold figure that came
        from somewhere when in fact nothing was read."""
        from db.queries import save_demand_data

        _store_capture(sessions, sold_7d=12)
        with_capture = apply_purchase_history(
            DemandData(verified=False), URL, db=sessions()
        )

        session = sessions()
        try:
            save_demand_data(session, 1, with_capture)
            row = save_demand_data(session, 1, DemandData(verified=False))
            assert row.sold_count_7d is None
            assert row.sold_source is None
            assert row.sold_captured_at is None
        finally:
            session.close()

    def test_a_source_is_never_stored_without_a_figure(self, sessions):
        from db.queries import save_demand_data

        session = sessions()
        try:
            # Hand-built contradiction: an origin for a figure that is not there.
            row = save_demand_data(
                session,
                1,
                DemandData(
                    verified=False,
                    sold_count_7d=None,
                    sold_source="purchase_history",
                    sold_captured_at=datetime(2026, 10, 19, 12, 0, 0),
                ),
            )
            assert row.sold_count_7d is None
            assert row.sold_source is None
            assert row.sold_captured_at is None
        finally:
            session.close()

    def test_a_source_and_its_figure_survive_a_re_analysis_of_a_different_query(
        self, sessions
    ):
        """The source belongs to the figure, not to the product: a run that
        re-reads eBay for the same product and finds no capture must not inherit
        the previous run's attribution."""
        from db.queries import save_demand_data

        _store_capture(sessions, sold_7d=9)
        attributed = apply_purchase_history(
            DemandData(verified=False), URL, db=sessions()
        )

        session = sessions()
        try:
            save_demand_data(session, 7, attributed)
            plain = save_demand_data(
                session,
                7,
                DemandData(verified=False, active_listings_in_band=50),
            )
            assert plain.sold_source is None
            assert plain.active_listings_in_band == 50
        finally:
            session.close()


# ---------------------------------------------------------------------------
# 3. What the API hands the screen
# ---------------------------------------------------------------------------

class TestWhatTheAPIHandsTheScreen:
    """The payload is where a stored figure becomes a rendered one.

    The rule this pins: a screen is told what produced each number and when it
    was read, and is told nothing at all where no number exists. A figure that
    was never measured arrives as null — not as a zero, and not as a badge over
    an absent value.
    """

    @staticmethod
    def _save(sessions, demand):
        from db.queries import save_demand_data, save_product
        from scrapers.base import ScrapedProduct

        session = sessions()
        try:
            product_id = save_product(
                session,
                ScrapedProduct(
                    source="ebay_uk",
                    title="Dyson ball animal 2",
                    price=99.0,
                    url=URL,
                    condition="New",
                ),
            )
            save_demand_data(session, product_id, demand)
            return product_id
        finally:
            session.close()

    def test_a_capture_backed_row_serves_the_figure_its_origin_and_its_time(
        self, sessions
    ):
        from api.history import product_detail

        read_at = _store_capture(sessions, sold_7d=12)
        demand = apply_purchase_history(DemandData(verified=False), URL, db=sessions())

        figure = product_detail(self._save(sessions, demand))["demand"]["figures"][
            "sold_count_7d"
        ]

        assert figure["value"] == 12
        assert figure["origin"] == SOLD_SOURCE_PURCHASE_HISTORY
        assert figure["observed_at"] == f"{read_at.isoformat()}Z"

    def test_the_read_time_says_which_instant_it_is(self, sessions):
        """A bare naive timestamp in a payload is an instant the reader has to
        guess at, and the guess is wrong for anyone not on UTC. The figure says
        which one it means."""
        from api.history import product_detail

        _store_capture(sessions, sold_7d=12)
        demand = apply_purchase_history(DemandData(verified=False), URL, db=sessions())

        served = product_detail(self._save(sessions, demand))["demand"]["figures"][
            "sold_count_7d"
        ]["observed_at"]

        assert served.endswith("Z")
        assert datetime.fromisoformat(served.replace("Z", "+00:00")).tzinfo is not None

    def test_a_row_with_no_capture_serves_no_sold_figure_at_all(self, sessions):
        from api.history import product_detail

        demand = DemandData(
            verified=False, active_listings_in_band=50, avg_active_price=21.99
        )
        detail = product_detail(self._save(sessions, demand))["demand"]

        assert detail["figures"]["sold_count_7d"] is None
        assert detail["figures"]["sold_count_30d"] is None
        # The supply figure is still served, under the name that says it is supply.
        assert detail["active_listings_in_band"] == 50

    def test_a_figure_with_no_recorded_origin_is_served_unattributed(self, sessions):
        """A legacy row holds a count and no idea where it came from. The
        payload says exactly that; filing it under a source would be inventing
        the citation."""
        from api.history import product_detail

        product_id = self._save(sessions, DemandData(verified=False, sold_count_7d=7))

        figure = product_detail(product_id)["demand"]["figures"]["sold_count_7d"]

        assert figure["value"] == 7
        assert figure["origin"] is None
        assert figure["observed_at"] is None

    def test_the_30d_slot_is_never_filed_under_the_7d_figures_source(self, sessions):
        """Two sold figures, one producer. Only the one it produced is
        attributed to it — the other says its origin is unknown rather than
        borrowing a badge that would make it look verified."""
        from api.history import product_detail

        _store_capture(sessions, sold_7d=12)
        demand = apply_purchase_history(DemandData(verified=False), URL, db=sessions())
        demand.sold_count_30d = 999  # no source this app can reach produces this

        figures = product_detail(self._save(sessions, demand))["demand"]["figures"]

        assert figures["sold_count_30d"]["value"] == 999
        assert figures["sold_count_30d"]["origin"] is None
        assert figures["sold_count_7d"]["origin"] == SOLD_SOURCE_PURCHASE_HISTORY

    def test_the_figures_block_is_additive(self, sessions):
        """History's existing readers keep working: Phase C adds the provenance
        block, it does not move the flat values other screens already read."""
        from api.history import product_detail

        product_id = self._save(
            sessions, DemandData(verified=False, active_listings_in_band=50)
        )
        detail = product_detail(product_id)["demand"]

        for key in (
            "sold_count_7d",
            "sold_count_30d",
            "active_listings_in_band",
            "active_prices",
            "data_source",
            "verified",
        ):
            assert key in detail, key


# ---------------------------------------------------------------------------
# 4. The columns reach a database that predates them
# ---------------------------------------------------------------------------

class TestTheMigration:
    def test_the_helper_is_idempotent(self):
        from db.database import ensure_demand_data_columns

        ensure_demand_data_columns()  # whatever state it was in, it is current now
        assert ensure_demand_data_columns() == []

    def test_the_table_that_exists_has_exactly_the_columns_the_model_declares(self):
        from sqlalchemy import inspect

        from db.database import engine, ensure_demand_data_columns
        from db.models import DemandData as DemandDataRow

        ensure_demand_data_columns()
        live = {c["name"] for c in inspect(engine).get_columns("demand_data")}
        declared = set(DemandDataRow.__table__.columns.keys())
        assert live == declared, f"model and database disagree: {live ^ declared}"

    def test_the_sentence_column_is_no_longer_width_limited(self):
        """The measured `data_source` value is a sentence well past 64
        characters, and Phase C appends the sold figure's origin to it. SQLite
        ignores VARCHAR lengths, so the narrow type never failed here — it would
        simply have truncated the sentence on an engine that honours it."""
        from db.models import DemandData as DemandDataRow

        column = DemandDataRow.__table__.columns["data_source"]
        assert not hasattr(column.type, "length") or column.type.length is None
