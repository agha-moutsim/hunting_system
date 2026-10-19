"""Saved-search runs: a stated Browse budget, and rows only for real numbers.

A run spends Browse quota, so the pass must be countable before it happens
(MAX_SEARCHES_PER_PASS, one Browse call per search) and the report must say
what it did not run. And a stored row names a specific listing at a real
eBay price with a real supplier price and a passing margin - anything less
is a reason, not a row. These tests pin both halves with a stubbed
analysis, so no quota is spent here.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import db.database as dbmod
from db.database import Base
from db.models import SavedSearch, SearchResult
from hunter.saved_searches import run_saved_search, run_saved_searches
from watchlist import runner as watchlist_runner


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    path = (tmp_path / "saved_searches.db").as_posix()
    engine = create_engine(f"sqlite:///{path}")
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "SessionLocal", factory)
    Base.metadata.create_all(engine)
    return factory


def _search(
    factory,
    name="drill",
    query="cordless drill",
    price_min=10.0,
    price_max=200.0,
    min_margin=15.0,
    auto_run=True,
):
    db = factory()
    try:
        row = SavedSearch(
            search_name=name,
            query=query,
            price_min=price_min,
            price_max=price_max,
            min_margin=min_margin,
            auto_run=auto_run,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _result(**overrides):
    base = dict(
        product_name="cordless drill",
        sources=["https://www.ebay.co.uk/itm/167000000009"],
        suppliers=[{"url": "https://supplier.example/drill", "name": "Example"}],
        ebay_avg_price=42.50,
        best_supplier_price=22.00,
        profit=8.10,
        margin=19.1,
        verdict="PASS",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _stub_analysis(monkeypatch, result=None, error=None):
    """Patch deep_search_fast (imported inside the runner) and count calls."""
    import deep_search

    calls = []

    def fake(query, budget_s=None, sink=None):
        calls.append({"query": query, "budget_s": budget_s})
        if error is not None:
            raise error
        return result if result is not None else _result()

    monkeypatch.setattr(deep_search, "deep_search_fast", fake)
    return calls


def _rows(factory):
    db = factory()
    try:
        return [
            {
                "id": r.id,
                "search_id": r.search_id,
                "product_name": r.product_name,
                "ebay_url": r.ebay_url,
                "ebay_price": r.ebay_price,
                "supplier_price": r.supplier_price,
                "supplier_url": r.supplier_url,
                "supplier_name": r.supplier_name,
                "profit": r.profit,
                "margin": r.margin,
                "verdict": r.verdict,
                "is_read": r.is_read,
            }
            for r in db.query(SearchResult).order_by(SearchResult.id).all()
        ]
    finally:
        db.close()


def _last_run(factory, search_id):
    db = factory()
    try:
        row = db.query(SavedSearch).filter(SavedSearch.id == search_id).first()
        return row.last_run
    finally:
        db.close()


class TestARunStoresOnlyRealNumbers:
    def test_a_qualified_result_is_stored_with_every_field(
        self, session_factory, monkeypatch
    ):
        search_id = _search(session_factory)
        _stub_analysis(monkeypatch)

        report = run_saved_search(search_id)

        assert report == {"found": 1, "error": None, "reason": None, "browse_calls": 1}
        (row,) = _rows(session_factory)
        assert row["search_id"] == search_id
        assert row["product_name"] == "cordless drill"
        assert row["ebay_url"] == "https://www.ebay.co.uk/itm/167000000009"
        assert row["ebay_price"] == 42.50
        assert row["supplier_price"] == 22.00
        assert row["supplier_name"] == "Example"
        assert row["profit"] == 8.10
        assert row["margin"] == 19.1
        assert row["verdict"] == "PASS"
        assert row["is_read"] is False
        assert _last_run(session_factory, search_id) is not None

    def test_no_supplier_price_stores_nothing_and_says_why(
        self, session_factory, monkeypatch
    ):
        search_id = _search(session_factory)
        _stub_analysis(monkeypatch, result=_result(best_supplier_price=0.0))

        report = run_saved_search(search_id)

        assert report["found"] == 0
        assert "no real supplier price" in report["reason"]
        assert _rows(session_factory) == []
        # The run still happened, so the page can say when it last did.
        assert _last_run(session_factory, search_id) is not None

    def test_no_named_listing_stores_nothing(self, session_factory, monkeypatch):
        search_id = _search(session_factory)
        _stub_analysis(monkeypatch, result=_result(sources=[]))

        report = run_saved_search(search_id)

        assert report["found"] == 0
        assert "named no specific listing" in report["reason"]
        assert _rows(session_factory) == []

    def test_a_margin_below_the_searches_own_minimum_names_both_numbers(
        self, session_factory, monkeypatch
    ):
        search_id = _search(session_factory, min_margin=25.0)
        _stub_analysis(monkeypatch, result=_result(margin=19.1))

        report = run_saved_search(search_id)

        assert report["found"] == 0
        assert "19.1%" in report["reason"]
        assert "25.0%" in report["reason"]
        assert _rows(session_factory) == []

    def test_a_price_outside_the_searches_band_names_price_and_band(
        self, session_factory, monkeypatch
    ):
        search_id = _search(session_factory, price_min=10.0, price_max=30.0)
        _stub_analysis(monkeypatch, result=_result(ebay_avg_price=42.50))

        report = run_saved_search(search_id)

        assert report["found"] == 0
        assert "42.50" in report["reason"]
        assert "30.00" in report["reason"]

    def test_a_negative_profit_is_not_a_find(self, session_factory, monkeypatch):
        search_id = _search(session_factory)
        _stub_analysis(monkeypatch, result=_result(profit=-2.00))

        report = run_saved_search(search_id)

        assert report["found"] == 0
        assert "not a find" in report["reason"]

    def test_an_empty_query_is_refused_without_spending_anything(
        self, session_factory, monkeypatch
    ):
        search_id = _search(session_factory, query="   ")
        calls = _stub_analysis(monkeypatch)

        report = run_saved_search(search_id)

        assert calls == [], "an empty query must not reach the analysis"
        assert report["browse_calls"] == 0
        assert "nothing to run" in report["reason"]

    def test_a_failed_analysis_is_reported_not_stored(
        self, session_factory, monkeypatch
    ):
        search_id = _search(session_factory)
        _stub_analysis(monkeypatch, error=RuntimeError("boom"))

        report = run_saved_search(search_id)

        assert report["found"] == 0
        assert "boom" in report["error"]
        assert report["browse_calls"] == 1
        assert _rows(session_factory) == []

    def test_the_same_listing_is_not_stored_twice(self, session_factory, monkeypatch):
        search_id = _search(session_factory)
        _stub_analysis(monkeypatch)
        run_saved_search(search_id)

        second = run_saved_search(search_id)

        assert second["found"] == 0
        assert "already in the results" in second["reason"]
        assert len(_rows(session_factory)) == 1

    def test_a_missing_search_is_an_error_not_a_run(self, session_factory, monkeypatch):
        calls = _stub_analysis(monkeypatch)

        report = run_saved_search(999999)

        assert report["error"] == "Search not found"
        assert report["browse_calls"] == 0
        assert calls == []

    def test_the_analysis_is_given_the_run_budget(self, session_factory, monkeypatch):
        search_id = _search(session_factory)
        calls = _stub_analysis(monkeypatch)

        run_saved_search(search_id, budget_s=12.5)

        assert calls == [{"query": "cordless drill", "budget_s": 12.5}]


class TestThePassBudgetIsStatedAndEnforced:
    def test_the_pass_stops_at_the_stated_budget(self, session_factory, monkeypatch):
        _search(session_factory, name="one")
        _search(session_factory, name="two")
        _search(session_factory, name="three")
        calls = _stub_analysis(monkeypatch)

        report = run_saved_searches(max_searches=2)

        assert len(calls) == 2
        assert report["searches_run"] == 2
        assert report["searches_stored"] == 3
        assert report["searches_not_run"] == 1
        assert report["browse_calls"] == 2
        assert report["total_found"] == 2

    def test_a_manual_search_is_left_alone(self, session_factory, monkeypatch):
        _search(session_factory, name="auto")
        _search(session_factory, name="manual", auto_run=False)
        calls = _stub_analysis(monkeypatch)

        report = run_saved_searches()

        assert len(calls) == 1
        assert report["searches_run"] == 1
        assert report["searches_stored"] == 1

    def test_the_report_names_why_each_empty_run_stored_nothing(
        self, session_factory, monkeypatch
    ):
        _search(session_factory, name="drill")
        _stub_analysis(monkeypatch, result=_result(best_supplier_price=0.0))

        report = run_saved_searches()

        assert report["total_found"] == 0
        assert report["reasons"] == [
            "drill: no real supplier price was found, so a margin would be a guess"
        ]

    def test_the_progress_callback_sees_each_search(self, session_factory, monkeypatch):
        _search(session_factory, name="one")
        _search(session_factory, name="two")
        _stub_analysis(monkeypatch)
        seen = []

        run_saved_searches(progress_callback=lambda i, n, name: seen.append((i, n, name)))

        assert seen == [(0, 2, "one"), (1, 2, "two")]


class TestOneImplementation:
    def test_the_watchlist_runner_delegates_to_the_budgeted_runner(
        self, session_factory, monkeypatch
    ):
        """No second implementation: patching the one runner must change what
        the Watchlist surface does."""
        _search(session_factory)
        _stub_analysis(monkeypatch)

        report = watchlist_runner.run_search(1)

        # Same keys the route has always returned, plus the stated cost.
        assert report["found"] == 1
        assert report["error"] is None
        assert report["browse_calls"] == 1

    def test_what_was_stored_is_readable_through_the_watchlist_surface(
        self, session_factory, monkeypatch
    ):
        # The legacy reader binds its session factory at import time, so the
        # throwaway database has to be wired in where it looks.
        monkeypatch.setattr(watchlist_runner, "SessionLocal", session_factory)
        _search(session_factory)
        _stub_analysis(monkeypatch)
        watchlist_runner.run_search(1)

        rows = watchlist_runner.get_new_results(
            unread_only=True, price_range={"min": 0.0, "max": 100000.0}
        )

        assert len(rows) == 1
        assert rows[0]["margin"] == 19.1
        assert rows[0]["search_name"] == "drill"
