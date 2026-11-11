"""A failed dashboard read is unknown, never zero revenue or profit (C1).

The legacy `/dashboard/*` helpers used to answer a database error with
``total: 0`` / ``total_revenue: 0.0``, which is indistinguishable from a
measured empty period. These tests keep the two apart: an empty read may
report zero, a failed one may not.
"""

from dashboard import analytics, charts


class _BrokenQuery:
    def filter(self, *args, **kwargs):
        raise RuntimeError("database is locked")

    def all(self):
        raise RuntimeError("database is locked")


class _BrokenSession:
    def query(self, *args, **kwargs):
        return _BrokenQuery()

    def close(self):
        pass


class _EmptyQuery:
    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return []


class _EmptySession:
    def query(self, *args, **kwargs):
        return _EmptyQuery()

    def close(self):
        pass


def test_a_failed_revenue_read_has_no_total_and_says_why(monkeypatch):
    monkeypatch.setattr(charts, "SessionLocal", lambda: _BrokenSession())

    trend = charts.get_revenue_trend(days=7)

    assert trend["total"] is None
    assert trend["revenue_is_complete"] is False
    assert "database is locked" in trend["reason"]
    assert trend["dates"] == []
    assert trend["values"] == []


def test_a_session_that_will_not_open_still_answers_honestly(monkeypatch):
    """The error branch must be reachable: a failed connect is not a crash."""

    def no_session():
        raise RuntimeError("cannot open database")

    monkeypatch.setattr(charts, "SessionLocal", no_session)
    trend = charts.get_revenue_trend(days=7)
    assert trend["total"] is None
    assert "cannot open database" in trend["reason"]

    monkeypatch.setattr(analytics, "SessionLocal", no_session)
    kpis = analytics.get_kpis(days=7)
    assert kpis["total_revenue"] is None
    assert kpis["total_sales"] is None
    assert "cannot open database" in kpis["error"]


def test_an_empty_revenue_read_is_still_a_measured_zero(monkeypatch):
    monkeypatch.setattr(charts, "SessionLocal", lambda: _EmptySession())

    trend = charts.get_revenue_trend(days=7)

    assert trend["total"] == 0
    assert trend["revenue_is_complete"] is True
    assert len(trend["dates"]) == 7
    assert trend["values"] == [0, 0, 0, 0, 0, 0, 0]


def test_a_failed_category_read_says_why_it_is_empty(monkeypatch):
    monkeypatch.setattr(charts, "SessionLocal", lambda: _BrokenSession())

    breakdown = charts.get_category_breakdown()

    assert breakdown["categories"] == []
    assert breakdown["values"] == []
    assert breakdown["revenue_is_complete"] is False
    assert "database is locked" in breakdown["reason"]


def test_an_empty_category_read_is_still_a_measured_zero(monkeypatch):
    monkeypatch.setattr(charts, "SessionLocal", lambda: _EmptySession())

    breakdown = charts.get_category_breakdown()

    assert breakdown["categories"] == []
    assert breakdown["values"] == []
    assert breakdown["revenue_is_complete"] is True


def test_a_failed_monthly_read_says_why_it_is_empty(monkeypatch):
    monkeypatch.setattr(charts, "SessionLocal", lambda: _BrokenSession())

    monthly = charts.get_monthly_comparison(months=3)

    assert monthly["labels"] == []
    assert monthly["revenue"] == []
    assert monthly["profit"] == []
    assert monthly["revenue_is_complete"] is False
    assert "database is locked" in monthly["reason"]


def test_an_empty_monthly_read_is_still_a_measured_zero(monkeypatch):
    monkeypatch.setattr(charts, "SessionLocal", lambda: _EmptySession())

    monthly = charts.get_monthly_comparison(months=3)

    assert monthly["labels"] == []
    assert monthly["revenue"] == []
    assert monthly["revenue_is_complete"] is True


def test_a_failed_top_products_read_is_not_an_empty_list(monkeypatch):
    monkeypatch.setattr(analytics, "SessionLocal", lambda: _BrokenSession())

    payload = analytics.get_top_products(limit=5)

    assert payload["products"] == []
    assert payload["read_complete"] is False
    assert "database is locked" in payload["reason"]


def test_a_failed_top_categories_read_is_not_an_empty_list(monkeypatch):
    monkeypatch.setattr(analytics, "SessionLocal", lambda: _BrokenSession())

    payload = analytics.get_top_categories(limit=5)

    assert payload["categories"] == []
    assert payload["read_complete"] is False
    assert "database is locked" in payload["reason"]


def test_an_empty_top_read_is_a_measured_empty_list(monkeypatch):
    monkeypatch.setattr(analytics, "SessionLocal", lambda: _EmptySession())

    products = analytics.get_top_products(limit=5)
    categories = analytics.get_top_categories(limit=5)

    assert products == {"products": [], "read_complete": True}
    assert categories == {"categories": [], "read_complete": True}


def test_a_failed_kpi_read_does_not_claim_zero_money_or_zero_sales(monkeypatch):
    monkeypatch.setattr(analytics, "SessionLocal", lambda: _BrokenSession())

    kpis = analytics.get_kpis(days=7)

    assert kpis["total_revenue"] is None
    assert kpis["total_profit"] is None
    assert kpis["total_sales"] is None
    assert kpis["total_units"] is None
    assert kpis["profit_is_complete"] is False
    assert "sales read failed" in kpis["profit_missing_reason"]
    assert kpis["growth_revenue"] is None
    assert kpis["growth_profit"] is None
    assert "database is locked" in kpis["error"]


def test_an_empty_kpi_read_is_still_a_measured_zero(monkeypatch):
    monkeypatch.setattr(analytics, "SessionLocal", lambda: _EmptySession())

    kpis = analytics.get_kpis(days=7)

    assert kpis["total_revenue"] == 0.0
    assert kpis["total_profit"] == 0.0
    assert kpis["total_sales"] == 0
    assert kpis["total_units"] == 0
    assert kpis["profit_is_complete"] is True
