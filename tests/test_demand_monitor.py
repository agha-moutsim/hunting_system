"""The watchlist demand monitor, and its honest trend.

A 30d count is available on every search. A real 7-day trend can only be
derived from at least two observations of the same query over a window, so
this module manufactures nothing: it records what it fetched, and it says
"insufficient data" rather than a slope until the window is real.
"""

from datetime import datetime, timedelta

import pytest

from hunter.demand_monitor import compute_trend


class _Snap:
    def __init__(self, query, sold_30d, sold_7d, captured_at):
        self.query = query
        self.sold_30d = sold_30d
        self.sold_7d = sold_7d
        self.captured_at = captured_at


def _series(query, points):
    return [_Snap(query, s30, s7, t) for t, s30, s7 in points]


class TestComputeTrend:
    def test_one_observation_is_not_a_trend(self):
        snaps = _series("q", [(datetime(2026, 10, 1), 40, None)])
        r = compute_trend(snaps, now=datetime(2026, 10, 2))

        assert r["provenance"] == "unverified"
        assert "at least two" in r["reason"]
        assert r["pace_7d"] is None
        assert r["hot"] is False

    def test_two_points_a_short_window_apart_are_not_a_trend(self):
        snaps = _series("q", [
            (datetime(2026, 10, 1), 40, None),
            (datetime(2026, 10, 1, 6), 41, None),  # 6h later
        ])
        r = compute_trend(snaps, now=datetime(2026, 10, 2), min_span_hours=24)

        assert r["provenance"] == "unverified"
        assert "24h" in r["reason"] or "only" in r["reason"]
        assert r["pace_7d"] is None

    def test_a_real_positive_delta_is_hot_and_verified(self):
        snaps = _series("q", [
            (datetime(2026, 9, 23), 30, None),
            (datetime(2026, 10, 2), 44, None),   # +14 over ~9 days
        ])
        r = compute_trend(snaps, now=datetime(2026, 10, 2), min_span_hours=24)

        assert r["provenance"] == "verified"
        assert r["hot"] is True
        # +14 over ~9 days -> ~10.9/wk
        assert r["pace_7d"] == pytest.approx(14 * (7 / 9), abs=1.0)
        assert r["points"] == 2
        assert r["first"]["sold_30d"] == 30
        assert r["last"]["sold_30d"] == 44

    def test_a_decline_is_not_hot(self):
        snaps = _series("q", [
            (datetime(2026, 9, 23), 50, None),
            (datetime(2026, 10, 2), 30, None),
        ])
        r = compute_trend(snaps, now=datetime(2026, 10, 2))

        assert r["provenance"] == "verified"
        assert r["hot"] is False
        assert r["pace_7d"] < 0

    def test_a_missing_count_endpoint_is_not_a_trend(self):
        snaps = _series("q", [
            (datetime(2026, 9, 23), None, None),
            (datetime(2026, 10, 2), 40, None),
        ])
        r = compute_trend(snaps, now=datetime(2026, 10, 2))

        assert r["provenance"] == "unverified"
        assert "no real 30d" in r["reason"]

    def test_no_snapshots_at_all_is_unverified(self):
        r = compute_trend([], now=datetime(2026, 10, 2))

        assert r["provenance"] == "unverified"
        assert r["hot"] is False
        assert r["points"] == 0


class TestStaleness:
    """A slope from last March is not a trend today.

    The monitor only earns its keep by being run; a series that stopped
    being updated must not keep answering as if it were live. `now` is what
    makes that checkable, and it is the parameter the trend maths itself
    never needed.
    """

    def _fresh_pair(self):
        return _series("q", [
            (datetime(2026, 9, 23), 30, None),
            (datetime(2026, 10, 2), 44, None),
        ])

    def test_a_recent_series_is_verified(self):
        r = compute_trend(self._fresh_pair(), now=datetime(2026, 10, 3))

        assert r["provenance"] == "verified"

    def test_a_series_that_stopped_being_updated_is_unverified(self):
        """Same two points, same slope - but observed a month ago."""
        r = compute_trend(self._fresh_pair(), now=datetime(2026, 11, 20))

        assert r["provenance"] == "unverified"
        assert r["pace_7d"] is None
        assert r["hot"] is False
        assert "stale" in r["reason"].lower()

    def test_staleness_names_how_old_the_newest_point_is(self):
        r = compute_trend(self._fresh_pair(), now=datetime(2026, 11, 20))

        assert r["newest_age_days"] is not None
        assert r["newest_age_days"] > 40

    def test_the_staleness_window_is_adjustable(self):
        """A caller who samples weekly needs a weekly window, and must be
        able to say so rather than have the default declare it stale."""
        snaps = self._fresh_pair()
        strict = compute_trend(snaps, now=datetime(2026, 10, 12))
        lenient = compute_trend(
            snaps, now=datetime(2026, 10, 12), max_age_days=30
        )

        assert strict["provenance"] == "unverified"
        assert lenient["provenance"] == "verified"

    def test_a_single_recent_point_is_still_just_one_point(self):
        """Staleness must not become an excuse to invent a slope."""
        snaps = _series("q", [(datetime(2026, 10, 2), 40, None)])
        r = compute_trend(snaps, now=datetime(2026, 10, 3))

        assert r["provenance"] == "unverified"
        assert "at least two" in r["reason"]


class TestDbModel:
    def test_demand_snapshot_model_imports_and_has_the_columns(self):
        from db.models import DemandSnapshot

        for col in ("query", "sold_30d", "sold_7d", "avg_price", "source", "captured_at"):
            assert col in DemandSnapshot.__table__.columns.keys(), col
        assert DemandSnapshot.__tablename__ == "demand_snapshots"
