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


def test_an_empty_revenue_read_is_still_a_measured_zero(monkeypatch):
    monkeypatch.setattr(charts, "SessionLocal", lambda: _EmptySession())

    trend = charts.get_revenue_trend(days=7)

    assert trend["total"] == 0
    assert trend["revenue_is_complete"] is True
    assert len(trend["dates"]) == 7
    assert trend["values"] == [0, 0, 0, 0, 0, 0, 0]


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
