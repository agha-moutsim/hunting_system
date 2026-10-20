"""The two Phase G read routes, without a live database or eBay call.

The churn door is tested for the difference between "no observation", "one
observation" and a measured comparison. The listing door is tested for the
two dates it must keep apart: the first time this app saw the listing and the
latest stored reading, which is not the same as a last-seen time.

Every response is also checked for the sale word and for rates the app has no
basis to compute. The word is excluded from listing titles, which are eBay's
content and may legitimately contain anything.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest


def _fresh_session_factory(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db.database import Base
    from db import models  # noqa: F401 - register every table

    engine = create_engine(f"sqlite:///{tmp_path / 'phase-g-api.db'}")
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


def _listing(
    listing_id: str,
    title: str = "Garden Hose 30m",
    *,
    creation: datetime | None = None,
) -> dict:
    return {
        "listing_id": listing_id,
        "title": title,
        "item_url": f"https://www.ebay.co.uk/itm/{listing_id}",
        "price": 19.99,
        "currency": "GBP",
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


class TestChurnDoor:
    def test_no_observation_is_a_refusal_not_a_zero(self, client):
        response = client.get(
            "/api/observations/churn", params={"query": "never observed"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["query"] == "never observed"
        assert body["observations"] == 0
        assert body["comparable"] is False
        assert body["churned"] is None
        assert "No search observation" in body["reason"]
        assert body["latest"] == []

    def test_one_observation_keeps_the_latest_sample_but_claims_no_churn(self, client):
        creation = datetime.utcnow() - timedelta(days=74, hours=1)
        _save_runs(
            client_factory(client),
            [_run(datetime(2026, 10, 20, 10, 0, 0), [_listing("1", creation=creation)])],
        )

        body = client.get(
            "/api/observations/churn", params={"query": "garden hose"}
        ).json()

        assert body["observations"] == 1
        assert body["comparable"] is False
        assert body["churned"] is None
        assert "second" in body["reason"]
        assert body["latest_listing_count"] == 1
        assert body["latest"][0]["age"]["days"] == 74

    def test_two_matching_observations_report_the_missing_listing(self, client):
        first = datetime(2026, 10, 19, 10, 0, 0)
        latest = datetime(2026, 10, 20, 10, 0, 0)
        _save_runs(
            client_factory(client),
            [
                _run(latest, [_listing("2", "Still here"), _listing("3", "New")]),
                _run(first, [_listing("1", "Gone"), _listing("2", "Still here")]),
            ],
        )

        body = client.get(
            "/api/observations/churn", params={"query": "garden hose"}
        ).json()

        assert body["observations"] == 2
        assert body["comparable"] is True
        assert body["latest_listing_count"] == 2
        assert body["earlier_listing_count"] == 2
        assert body["limit"] == 5
        assert body["filter"] == "conditions:{NEW},price:[10..100]"
        assert [row["listing_id"] for row in body["churned"]] == ["1"]
        assert body["churned"][0]["status"] == "no_longer_listed"
        assert body["churned"][0]["last_seen_at"] == "2026-10-19T10:00:00Z"
        assert body["latest_observed_at"] == "2026-10-20T10:00:00Z"
        assert body["previous_observed_at"] == "2026-10-19T10:00:00Z"
        assert body["reason"] is None

    def test_a_latest_sample_that_is_empty_reports_every_earlier_listing(self, client):
        _save_runs(
            client_factory(client),
            [
                _run(datetime(2026, 10, 20, 10, 0, 0), []),
                _run(
                    datetime(2026, 10, 19, 10, 0, 0),
                    [_listing("1", "Gone one"), _listing("2", "Gone two")],
                ),
            ],
        )

        body = client.get(
            "/api/observations/churn", params={"query": "garden hose"}
        ).json()

        assert body["latest_listing_count"] == 0
        assert body["comparable"] is True
        assert [row["listing_id"] for row in body["churned"]] == ["1", "2"]

    def test_different_filters_refuse_the_comparison(self, client):
        _save_runs(
            client_factory(client),
            [
                _run(
                    datetime(2026, 10, 20, 10, 0, 0),
                    [_listing("2")],
                    price_filter="price:[10..100]",
                ),
                _run(
                    datetime(2026, 10, 19, 10, 0, 0),
                    [_listing("1")],
                    price_filter="price:[10..200]",
                ),
            ],
        )

        body = client.get(
            "/api/observations/churn", params={"query": "garden hose"}
        ).json()

        assert body["comparable"] is False
        assert body["churned"] is None
        assert "different price filters" in body["reason"]

    def test_the_query_lane_is_case_and_spacing_insensitive(self, client):
        _save_runs(
            client_factory(client),
            [
                _run(datetime(2026, 10, 20, 10, 0, 0), [_listing("2")]),
                _run(
                    datetime(2026, 10, 19, 10, 0, 0),
                    [_listing("1"), _listing("2")],
                    query="Garden  Hose",
                ),
            ],
        )

        body = client.get(
            "/api/observations/churn", params={"query": "GARDEN HOSE"}
        ).json()

        assert body["query"] == "garden hose"
        assert body["observations"] == 2

    def test_a_blank_query_is_rejected(self, client):
        response = client.get("/api/observations/churn", params={"query": "   "})
        assert response.status_code == 422

    def test_the_static_route_is_not_captured_as_a_listing_id(self, client):
        body = client.get(
            "/api/observations/churn", params={"query": "nothing"}
        ).json()
        assert "observations" in body
        assert "observed" not in body

    def test_the_response_never_carries_the_sale_word_or_a_rate(self, client):
        _save_runs(
            client_factory(client),
            [
                _run(datetime(2026, 10, 20, 10, 0, 0), [_listing("2")]),
                _run(
                    datetime(2026, 10, 19, 10, 0, 0),
                    [_listing("1"), _listing("2")],
                ),
            ],
        )

        body = client.get(
            "/api/observations/churn", params={"query": "garden hose"}
        ).json()

        banned = {
            "sold",
            "sold_count",
            "sales",
            "revenue",
            "churn_rate",
            "churn_percent",
            "percentage",
            "percent",
            "trend",
            "score",
        }
        assert _keys(body).isdisjoint(banned)
        assert "sold" not in (body.get("reason") or "").lower()
        for row in body["churned"]:
            assert "sold" not in (row.get("status") or "").lower()


class TestListingDoor:
    def test_an_unobserved_listing_is_reported_as_not_observed(self, client):
        response = client.get("/api/observations/123")

        assert response.status_code == 200
        body = response.json()
        assert body["listing_id"] == "123"
        assert body["observed"] is False
        assert body["readings"] == 0
        assert body["age"] is None
        assert "No Browse reading" in body["reason"]

    def test_age_comes_from_eBay_and_the_two_dates_stay_separate(self, client):
        from db.models import ListingObservation

        creation = datetime.utcnow() - timedelta(days=74, hours=1)
        session = client_factory(client)()
        try:
            session.add(
                ListingObservation(
                    listing_id="123",
                    observed_at=datetime(2026, 10, 18, 10, 0, 0),
                    item_creation_date=creation,
                )
            )
            session.commit()
        finally:
            session.close()

        body = client.get("/api/observations/123").json()

        assert body["observed"] is True
        assert body["readings"] == 1
        assert body["first_seen_at"] == "2026-10-18T10:00:00Z"
        assert body["latest_reading_at"] == "2026-10-18T10:00:00Z"
        assert body["age"]["days"] == 74
        assert body["age"]["basis"] == "ebay_item_creation_date"
        assert body["age"]["tone"] == "neutral"
        assert body["reason"] is None
        # The first-sighting date is not presented as the age.
        assert body["first_seen_at"] != body["item_creation_date"]

    def test_a_later_reading_without_a_creation_date_does_not_erase_age(self, client):
        from db.models import ListingObservation

        creation = datetime.utcnow() - timedelta(days=74, hours=1)
        session = client_factory(client)()
        try:
            session.add_all(
                [
                    ListingObservation(
                        listing_id="123",
                        observed_at=datetime(2026, 10, 18, 10, 0, 0),
                        item_creation_date=creation,
                    ),
                    ListingObservation(
                        listing_id="123",
                        observed_at=datetime(2026, 10, 19, 10, 0, 0),
                        item_creation_date=None,
                    ),
                ]
            )
            session.commit()
        finally:
            session.close()

        body = client.get("/api/observations/123").json()

        assert body["readings"] == 2
        assert body["latest_reading_at"] == "2026-10-19T10:00:00Z"
        assert body["age"]["days"] == 74

    def test_a_listing_without_a_creation_date_gets_no_age_claim(self, client):
        from db.models import ListingObservation

        session = client_factory(client)()
        try:
            session.add(
                ListingObservation(
                    listing_id="123",
                    observed_at=datetime(2026, 10, 18, 10, 0, 0),
                    item_creation_date=None,
                )
            )
            session.commit()
        finally:
            session.close()

        body = client.get("/api/observations/123").json()

        assert body["observed"] is True
        assert body["age"] is None
        assert "creation date" in body["reason"]

    def test_a_future_creation_date_is_refused_not_rendered_as_zero(self, client):
        from db.models import ListingObservation

        session = client_factory(client)()
        try:
            session.add(
                ListingObservation(
                    listing_id="123",
                    observed_at=datetime(2026, 10, 18, 10, 0, 0),
                    item_creation_date=datetime.utcnow() + timedelta(days=1),
                )
            )
            session.commit()
        finally:
            session.close()

        body = client.get("/api/observations/123").json()

        assert body["age"] is None
        assert "future" in body["reason"]


def client_factory(client):
    """The session factory the route fixture patched in.

    A small helper because the tests need to seed rows through the same
    database the route reads, and `client` itself does not expose the factory.
    """
    from db.database import SessionLocal

    return SessionLocal
