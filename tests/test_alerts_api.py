"""GET/POST /api/alerts - the inbox door.

The routes are a pure read of price_alerts plus the read flag. These tests
pin what the inbox page consumes: the stored message verbatim (it is the
comparison the row earned), the unread count for the sidebar badge, the
type filter the tabs ask with, and refusals as 404/422 sentences.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import db.database as dbmod
from db.database import Base
from db.models import PriceAlert, TrackedProduct


def _client():
    from fastapi.testclient import TestClient

    from main import app

    return TestClient(app)


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    """A throwaway database, wired into the factory the routes open."""
    path = (tmp_path / "alerts_api.db").as_posix()
    engine = create_engine(f"sqlite:///{path}")
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "SessionLocal", factory)
    Base.metadata.create_all(engine)
    return factory


DROP_MESSAGE = (
    "cordless drill average asking price dropped from £25.00 to £22.50"
)
TARGET_MESSAGE = (
    "cordless drill item price is £15.49 - at or below your £16.00 target price"
)


def _seed(factory):
    """Two alerts on one product (one read), plus one orphaned row."""
    db = factory()
    try:
        product = TrackedProduct(
            product_name="cordless drill",
            ebay_url="https://www.ebay.co.uk/itm/167000000001",
        )
        db.add(product)
        db.commit()

        db.add_all(
            [
                PriceAlert(
                    tracked_product_id=product.id,
                    alert_type="price_drop",
                    message=DROP_MESSAGE,
                    old_price=25.00,
                    new_price=22.50,
                ),
                PriceAlert(
                    tracked_product_id=product.id,
                    alert_type="target_hit",
                    message=TARGET_MESSAGE,
                    old_price=16.00,
                    new_price=15.49,
                    is_read=True,
                ),
                PriceAlert(
                    tracked_product_id=None,  # no product - must still show
                    alert_type="price_increase",
                    message="an orphaned reading rose from £1.00 to £2.00",
                    old_price=1.00,
                    new_price=2.00,
                ),
            ]
        )
        db.commit()
        return product.id
    finally:
        db.close()


class TestTheInboxRead:
    def test_rows_come_newest_first_with_the_message_verbatim(self, session_factory):
        _seed(session_factory)

        with _client() as client:
            body = client.get("/api/alerts").json()

        assert body["count"] == 3
        assert body["unread"] == 2
        assert [row["alert_type"] for row in body["alerts"]] == [
            "price_increase",
            "target_hit",
            "price_drop",
        ]
        drop = body["alerts"][2]
        assert drop["message"] == DROP_MESSAGE
        assert drop["old_price"] == 25.00
        assert drop["new_price"] == 22.50
        assert drop["is_read"] is False
        assert drop["product_name"] == "cordless drill"

    def test_an_alert_without_a_product_still_shows(self, session_factory):
        _seed(session_factory)

        with _client() as client:
            body = client.get("/api/alerts").json()

        orphan = body["alerts"][0]
        assert orphan["alert_type"] == "price_increase"
        assert orphan["product_name"] == ""

    def test_unread_only_filters_to_the_unread_rows(self, session_factory):
        _seed(session_factory)

        with _client() as client:
            body = client.get("/api/alerts", params={"unread_only": True}).json()

        assert body["count"] == 2
        assert all(row["is_read"] is False for row in body["alerts"])

    def test_a_comma_separated_type_list_serves_the_tabs(self, session_factory):
        _seed(session_factory)

        with _client() as client:
            price = client.get(
                "/api/alerts", params={"alert_type": "price_drop,price_increase"}
            ).json()

        assert [row["alert_type"] for row in price["alerts"]] == [
            "price_increase",
            "price_drop",
        ]

    def test_an_unknown_type_is_refused_with_the_known_ones_listed(
        self, session_factory
    ):
        _seed(session_factory)

        with _client() as client:
            resp = client.get("/api/alerts", params={"alert_type": "margin"})

        assert resp.status_code == 422
        assert "unknown alert_type" in resp.json()["detail"]
        assert "target_hit" in resp.json()["detail"]

    def test_paging_never_loses_the_total(self, session_factory):
        _seed(session_factory)

        with _client() as client:
            body = client.get("/api/alerts", params={"limit": 1}).json()

        assert body["count"] == 1
        assert body["total"] == 3


class TestTheBadgeAndTheReadFlag:
    def test_count_is_just_the_unread_number(self, session_factory):
        _seed(session_factory)

        with _client() as client:
            body = client.get("/api/alerts/count").json()

        assert body == {"unread": 2}

    def test_marking_one_read_reports_the_new_count(self, session_factory):
        _seed(session_factory)

        with _client() as client:
            listing = client.get("/api/alerts").json()
            drop_id = next(
                row["id"] for row in listing["alerts"]
                if row["alert_type"] == "price_drop"
            )
            resp = client.post(f"/api/alerts/{drop_id}/read")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "unread": 1}

        with _client() as client:
            unread = client.get("/api/alerts", params={"unread_only": True}).json()

        assert [row["alert_type"] for row in unread["alerts"]] == ["price_increase"]

    def test_marking_a_missing_alert_is_a_404_not_a_lie(self, session_factory):
        _seed(session_factory)

        with _client() as client:
            resp = client.post("/api/alerts/999999/read")

        assert resp.status_code == 404
        assert "no alert with id 999999" in resp.json()["detail"]

    def test_read_all_marks_every_unread_row_once(self, session_factory):
        _seed(session_factory)

        with _client() as client:
            first = client.post("/api/alerts/read-all").json()
            second = client.post("/api/alerts/read-all").json()

        assert first == {"ok": True, "marked": 2, "unread": 0}
        assert second == {"ok": True, "marked": 0, "unread": 0}
