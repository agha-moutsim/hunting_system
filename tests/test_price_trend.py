"""C1 — a price trend needs two real readings.

With fewer than two points, or with an unread endpoint, `get_price_trend`
used to answer "stable, 0.0%": a measured flat market invented from no
evidence. The unread points are now skipped, and a comparison that cannot be
made says `unknown` with a null change.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import tracker.history as history_module
from db.database import Base
from db.models import PriceHistory, TrackedProduct


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    path = (tmp_path / "trend.db").as_posix()
    engine = create_engine(f"sqlite:///{path}")
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(history_module, "SessionLocal", factory)
    Base.metadata.create_all(engine)
    return factory


def _product(factory):
    db = factory()
    try:
        row = TrackedProduct(
            product_name="Drill",
            ebay_url="https://www.ebay.co.uk/itm/167000000002",
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _point(factory, product_id, price, minutes_ago):
    db = factory()
    try:
        db.add(
            PriceHistory(
                tracked_product_id=product_id,
                ebay_price=price,
                checked_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
            )
        )
        db.commit()
    finally:
        db.close()


class TestATrendNeedsTwoReadings:
    def test_no_points_is_unknown_not_stable(self, session_factory):
        product_id = _product(session_factory)

        assert history_module.get_price_trend(product_id) == {
            "trend": "unknown",
            "change": None,
            "change_percent": None,
        }

    def test_one_point_is_unknown_not_stable(self, session_factory):
        product_id = _product(session_factory)
        _point(session_factory, product_id, 18.99, minutes_ago=5)

        assert history_module.get_price_trend(product_id)["trend"] == "unknown"

    @pytest.mark.parametrize("placeholder", [0.0, 0, None, float("nan")])
    def test_unread_points_cannot_make_a_stable_trend(
        self, session_factory, placeholder
    ):
        product_id = _product(session_factory)
        _point(session_factory, product_id, placeholder, minutes_ago=10)
        _point(session_factory, product_id, placeholder, minutes_ago=5)

        assert history_module.get_price_trend(product_id)["trend"] == "unknown"

    def test_unread_points_are_skipped_between_real_readings(self, session_factory):
        product_id = _product(session_factory)
        _point(session_factory, product_id, 0.0, minutes_ago=20)
        _point(session_factory, product_id, 18.99, minutes_ago=10)
        _point(session_factory, product_id, None, minutes_ago=8)
        _point(session_factory, product_id, 15.49, minutes_ago=5)
        _point(session_factory, product_id, 0.0, minutes_ago=1)

        trend = history_module.get_price_trend(product_id)

        assert trend["trend"] == "down"
        assert trend["change"] == -3.5

    def test_a_real_rise_is_up(self, session_factory):
        product_id = _product(session_factory)
        _point(session_factory, product_id, 15.49, minutes_ago=10)
        _point(session_factory, product_id, 18.99, minutes_ago=5)

        assert history_module.get_price_trend(product_id)["trend"] == "up"

    def test_a_change_within_fifty_pence_is_stable(self, session_factory):
        product_id = _product(session_factory)
        _point(session_factory, product_id, 20.00, minutes_ago=10)
        _point(session_factory, product_id, 19.80, minutes_ago=5)

        trend = history_module.get_price_trend(product_id)

        assert trend["trend"] == "stable"
        assert trend["change"] == -0.2
