"""Phase H - the seller footprint engine and its one read route.

The tests use stored-shaped dictionaries for the engine and a temporary
SQLite database for the route. They pin three things:

* a seller's feedback and account type are eBay's values, not a computed
  score, and an absent value stays absent;
* the distributions count listings, use one latest reading per listing, and
  refuse to mix currencies;
* a query filter uses the listings actually stored for that query, while the
  response still reports the query sample size.

There is deliberately no revenue, sales, sold or turnover field to test for;
the final test asserts that no such key appears in the JSON.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def _fresh_session_factory(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db.database import Base
    from db import models  # noqa: F401 - register every table

    engine = create_engine(f"sqlite:///{tmp_path / 'phase-h-api.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def session_factory(tmp_path):
    return _fresh_session_factory(tmp_path)


@pytest.fixture()
def client(session_factory, monkeypatch):
    monkeypatch.setattr("db.database.SessionLocal", session_factory)
    from fastapi.testclient import TestClient
    from main import app

    return TestClient(app)


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        found = set(value)
        for item in value.values():
            found |= _keys(item)
        return found
    if isinstance(value, list):
        found = set()
        for item in value:
            found |= _keys(item)
        return found
    return set()


def _reading(
    listing_id: str,
    observed_at: datetime,
    *,
    seller: str = "agprefect_09",
    feedback_percentage: float | None = 99.8,
    feedback_score: int | None = 12431,
    account_type: str | None = "BUSINESS",
    country: str | None = "GB",
    postal_code: str | None = "WR4",
    condition: str | None = "New",
    price: float | None = 16.99,
    currency: str | None = "GBP",
    creation: datetime | None = None,
    row_id: int | None = None,
) -> dict:
    row = {
        "listing_id": listing_id,
        "observed_at": observed_at,
        "seller_username": seller,
        "seller_feedback_percentage": feedback_percentage,
        "seller_feedback_score": feedback_score,
        "seller_account_type": account_type,
        "item_country": country,
        "item_postal_code": postal_code,
        "condition_text": condition,
        "price": price,
        "currency": currency,
        "item_creation_date": creation,
    }
    if row_id is not None:
        row["id"] = row_id
    return row


def _listing(
    listing_id: str,
    title: str = "Garden Hose 30m",
    *,
    price: float = 19.99,
    currency: str = "GBP",
    creation: datetime | None = None,
) -> dict:
    return {
        "listing_id": listing_id,
        "title": title,
        "item_url": f"https://www.ebay.co.uk/itm/{listing_id}",
        "price": price,
        "currency": currency,
        "item_creation_date": (
            creation.isoformat() if creation is not None else None
        ),
    }


def _run(
    observed_at: datetime,
    listings: list[dict],
    *,
    query: str = "garden hose",
    price_filter: str = "conditions:{NEW},price:[10..100]",
    limit: int = 5,
) -> dict:
    return {
        "query": query,
        "observed_at": observed_at,
        "source": "browse_search",
        "filter": price_filter,
        "limit": limit,
        "listings": listings,
    }


def _save_runs(session_factory, runs):
    from db.queries import save_query_observations

    session = session_factory()
    try:
        save_query_observations(session, runs)
    finally:
        session.close()


def _save_readings(session_factory, readings):
    from db.models import ListingObservation

    session = session_factory()
    try:
        session.add_all(
            [
                ListingObservation(
                    listing_id=row["listing_id"],
                    observed_at=row["observed_at"],
                    seller_username=row["seller_username"],
                    seller_feedback_percentage=row["seller_feedback_percentage"],
                    seller_feedback_score=row["seller_feedback_score"],
                    seller_account_type=row["seller_account_type"],
                    item_country=row["item_country"],
                    item_postal_code=row["item_postal_code"],
                    condition_text=row["condition_text"],
                    price=row["price"],
                    currency=row["currency"],
                    item_creation_date=row["item_creation_date"],
                )
                for row in readings
            ]
        )
        session.commit()
    finally:
        session.close()


def _client_factory(client):
    from db.database import SessionLocal

    return SessionLocal


class TestSellerEngine:
    def test_one_listing_contributes_one_price_and_the_latest_feedback(self):
        from engine.sellers import build_seller_footprint

        now = datetime(2026, 10, 20, 12, 0, 0)
        rows = [
            _reading(
                "1",
                now - timedelta(days=2),
                feedback_percentage=99.8,
                feedback_score=100,
                price=10.0,
                creation=now - timedelta(days=10),
                row_id=1,
            ),
            _reading(
                "1",
                now - timedelta(days=1),
                feedback_percentage=99.9,
                feedback_score=101,
                price=12.0,
                row_id=2,
            ),
        ]

        body = build_seller_footprint(rows, "AGPREFECT_09", now=now)

        assert body["username"] == "agprefect_09"
        assert body["observed_listings"] == 1
        assert body["readings"] == 2
        assert body["feedback"]["percentage"] == 99.9
        assert body["feedback"]["score"] == 101
        assert body["condition_mix"] == {
            "known": 1,
            "unknown": 0,
            "values": [{"condition": "New", "count": 1, "share": 1.0}],
        }
        assert body["asking_prices"] == {
            "currency": "GBP",
            "min": 12.0,
            "max": 12.0,
            "median": 12.0,
            "sample": 1,
        }
        assert body["listed_age"]["min_days"] == 10
        assert body["listed_age"]["max_days"] == 10
        assert body["listed_age"]["sample"] == 1

    def test_absent_readings_are_null_with_a_sentence(self):
        from engine.sellers import build_seller_footprint

        now = datetime(2026, 10, 20, 12, 0, 0)
        rows = [
            _reading(
                "1",
                now - timedelta(days=1),
                feedback_percentage=None,
                feedback_score=None,
                account_type=None,
                country=None,
                postal_code=None,
                condition=None,
                price=None,
                currency=None,
                creation=None,
            )
        ]

        body = build_seller_footprint(rows, "agprefect_09", now=now)

        assert body["observed_listings"] == 1
        assert body["feedback"] is None
        assert body["account_type"] is None
        assert body["region"] is None
        assert body["condition_mix"] == {"known": 0, "unknown": 1, "values": []}
        assert body["asking_prices"] is None
        assert "No asking price" in body["asking_prices_reason"]
        assert body["listed_age"] is None
        assert "creation date" in body["listed_age_reason"]

    def test_mixed_currencies_refuse_a_single_range(self):
        from engine.sellers import build_seller_footprint

        now = datetime(2026, 10, 20, 12, 0, 0)
        rows = [
            _reading("1", now, price=10.0, currency="GBP", creation=now),
            _reading("2", now, price=20.0, currency="USD", creation=now),
        ]

        body = build_seller_footprint(rows, "agprefect_09", now=now)

        assert body["asking_prices"] is None
        assert "GBP" in body["asking_prices_reason"]
        assert "USD" in body["asking_prices_reason"]

    def test_a_future_creation_date_is_not_rendered_as_zero_age(self):
        from engine.sellers import build_seller_footprint

        now = datetime(2026, 10, 20, 12, 0, 0)
        body = build_seller_footprint(
            [_reading("1", now, creation=now + timedelta(days=3))],
            "agprefect_09",
            now=now,
        )

        assert body["listed_age"] is None
        assert "creation date" in body["listed_age_reason"]

    def test_readings_named_for_another_seller_do_not_leak_into_the_footprint(self):
        from engine.sellers import build_seller_footprint

        now = datetime(2026, 10, 20, 12, 0, 0)
        rows = [
            _reading("1", now - timedelta(days=2), seller="other", price=1.0),
            _reading(
                "1",
                now - timedelta(days=1),
                seller="agprefect_09",
                price=10.0,
            ),
        ]

        body = build_seller_footprint(rows, "agprefect_09", now=now)

        assert body["observed_listings"] == 1
        assert body["readings"] == 1
        assert body["asking_prices"]["min"] == 10.0

    def test_a_blank_username_returns_no_sample(self):
        from engine.sellers import build_seller_footprint

        body = build_seller_footprint([_reading("1", datetime.now())], "   ")

        assert body["observed_listings"] == 0
        assert body["asking_prices"] is None
        assert body["listed_age"] is None
        assert "username" in body["asking_prices_reason"]


class TestSellerDoor:
    def test_an_unknown_seller_is_an_empty_state_not_a_fabricated_panel(self, client):
        response = client.get("/api/sellers/nobody")

        assert response.status_code == 200
        body = response.json()
        assert body["username"] == "nobody"
        assert body["observed_listings"] == 0
        assert body["feedback"] is None
        assert body["account_type"] is None
        assert body["condition_mix"] == {"known": 0, "unknown": 0, "values": []}
        assert body["asking_prices"] is None
        assert body["listed_age"] is None
        assert "No stored Browse reading" in body["reason"]

    def test_the_footprint_uses_one_latest_reading_per_listing(self, client):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        creation_long = now - timedelta(days=10, hours=1)
        creation_short = now - timedelta(days=3, hours=1)
        _save_readings(
            _client_factory(client),
            [
                _reading(
                    "1",
                    datetime(2026, 10, 18, 10, 0, 0),
                    feedback_percentage=99.8,
                    feedback_score=100,
                    price=10.0,
                    creation=creation_long,
                    row_id=1,
                ),
                _reading(
                    "1",
                    datetime(2026, 10, 19, 10, 0, 0),
                    feedback_percentage=99.9,
                    feedback_score=101,
                    price=16.99,
                    row_id=2,
                ),
                _reading(
                    "2",
                    datetime(2026, 10, 18, 9, 0, 0),
                    condition="New",
                    price=8.99,
                    creation=creation_short,
                    row_id=3,
                ),
            ],
        )

        body = client.get("/api/sellers/agprefect_09").json()

        assert body["observed_listings"] == 2
        assert body["readings"] == 3
        assert body["username"] == "agprefect_09"
        assert body["feedback"]["percentage"] == 99.9
        assert body["feedback"]["score"] == 101
        assert body["account_type"] == "BUSINESS"
        assert body["region"] == {"country": "GB", "postal_code": "WR4"}
        assert body["condition_mix"]["known"] == 2
        assert body["condition_mix"]["unknown"] == 0
        assert body["condition_mix"]["values"] == [
            {"condition": "New", "count": 2, "share": 1.0}
        ]
        assert body["asking_prices"]["currency"] == "GBP"
        assert body["asking_prices"]["min"] == 8.99
        assert body["asking_prices"]["max"] == 16.99
        assert body["asking_prices"]["median"] == pytest.approx(12.99)
        assert body["asking_prices"]["sample"] == 2
        assert body["listed_age"]["min_days"] == 3
        assert body["listed_age"]["max_days"] == 10
        assert body["listed_age"]["sample"] == 2
        assert body["query"] is None
        assert body["query_context"] is None
        assert body["reason"] is None

    def test_account_type_is_kept_verbatim_and_region_stays_item_location(self, client):
        _save_readings(
            _client_factory(client),
            [
                _reading(
                    "1",
                    datetime(2026, 10, 20, 10, 0, 0),
                    seller="PrivateSeller",
                    account_type="INDIVIDUAL",
                    country="GB",
                    postal_code="M8***",
                )
            ],
        )

        body = client.get("/api/sellers/privateseller").json()

        assert body["username"] == "PrivateSeller"
        assert body["account_type"] == "INDIVIDUAL"
        assert body["region"] == {"country": "GB", "postal_code": "M8***"}

    def test_the_query_filter_uses_the_latest_stored_sample(self, client):
        _save_readings(
            _client_factory(client),
            [
                _reading("1", datetime(2026, 10, 18, 10, 0, 0), price=10.0),
                _reading("2", datetime(2026, 10, 19, 10, 0, 0), price=20.0),
                _reading("3", datetime(2026, 10, 19, 10, 0, 0), price=30.0),
            ],
        )
        _save_runs(
            _client_factory(client),
            [
                _run(datetime(2026, 10, 20, 10, 0, 0), [_listing("2")]),
                _run(
                    datetime(2026, 10, 19, 10, 0, 0),
                    [_listing("1"), _listing("2")],
                ),
            ],
        )

        body = client.get(
            "/api/sellers/agprefect_09", params={"query": "Garden  Hose"}
        ).json()

        assert body["query"] == "garden hose"
        # Listing 1 was only in the earlier sample; listing 3 was never in
        # this query. The latest set contains only listing 2.
        assert body["observed_listings"] == 1
        assert body["asking_prices"]["sample"] == 1
        assert body["asking_prices"]["min"] == 20.0
        assert body["asking_prices"]["max"] == 20.0
        assert body["query_context"] == {
            "observations": 2,
            "latest_listing_count": 1,
            "latest_observed_at": "2026-10-20T10:00:00Z",
        }

    def test_a_query_with_no_stored_observations_is_a_refusal(self, client):
        body = client.get(
            "/api/sellers/agprefect_09", params={"query": "never observed"}
        ).json()

        assert body["observed_listings"] == 0
        assert body["query"] == "never observed"
        assert body["query_context"] == {
            "observations": 0,
            "latest_listing_count": 0,
            "latest_observed_at": None,
        }
        assert "No search observation" in body["reason"]

    def test_a_query_with_no_reading_for_the_seller_is_a_refusal(self, client):
        _save_readings(
            _client_factory(client),
            [_reading("1", datetime(2026, 10, 18, 10, 0, 0))],
        )
        _save_runs(
            _client_factory(client),
            [_run(datetime(2026, 10, 20, 10, 0, 0), [_listing("9")])],
        )

        body = client.get(
            "/api/sellers/agprefect_09", params={"query": "garden hose"}
        ).json()

        assert body["observed_listings"] == 0
        assert body["query_context"]["latest_listing_count"] == 1
        assert "agprefect_09" in body["reason"]
        assert "latest" in body["reason"]
        assert "query" in body["reason"]

    def test_a_blank_query_is_rejected(self, client):
        response = client.get(
            "/api/sellers/agprefect_09", params={"query": "   "}
        )
        assert response.status_code == 422

    def test_a_blank_username_is_rejected(self, client):
        response = client.get("/api/sellers/%20")
        assert response.status_code == 422

    def test_the_response_never_carries_a_revenue_or_sale_field(self, client):
        _save_readings(
            _client_factory(client),
            [_reading("1", datetime(2026, 10, 20, 10, 0, 0))],
        )

        body = client.get("/api/sellers/agprefect_09").json()

        banned = {
            "sold",
            "sold_count",
            "sales",
            "revenue",
            "turnover",
            "feedback_score_computed",
            "seller_rating",
        }
        assert _keys(body).isdisjoint(banned)
