"""Phase G - storing search result sets and draining them from a scrape.

The churn engine can only be as honest as its input. `listing_observations`
keeps a row only when a listing changed, so it cannot prove that a stable
listing was present in a later search. These tests pin the second store: one
row per completed search, including a search that returned zero listings.

The scraper tests use a stubbed Browse response and no network. The store
tests use a temporary SQLite database, not the live one.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

import pytest

PAYLOAD_NEW = {
    "legacyItemId": "111111111111",
    "title": "Garden Hose 30m",
    "itemCreationDate": "2025-03-21T15:44:11.000Z",
    "conditionId": "1000",
    "condition": "New",
    "price": {"value": "19.99", "currency": "GBP"},
    "itemWebUrl": "https://www.ebay.co.uk/itm/111111111111",
    "seller": {
        "username": "seller-one",
        "feedbackPercentage": "99.5",
        "feedbackScore": 1200,
    },
    "buyingOptions": ["FIXED_PRICE"],
}

PAYLOAD_REFURBISHED = {
    "legacyItemId": "222222222222",
    "title": "Garden Hose 30m - Refurbished",
    "itemCreationDate": "2024-01-02T03:04:05.000Z",
    "conditionId": "2020",
    "condition": "Very Good - Refurbished",
    "price": {"value": "12.50", "currency": "GBP"},
    "itemWebUrl": "https://www.ebay.co.uk/itm/222222222222",
    "seller": {"username": "seller-two"},
    "buyingOptions": ["FIXED_PRICE"],
}


def _fresh_session_factory(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db.database import Base
    from db import models  # noqa: F401 - register every table on Base.metadata

    engine = create_engine(f"sqlite:///{tmp_path / 'phase-g.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _run(
    *,
    query: str = "garden hose",
    observed_at: datetime | None = None,
    listings: list[dict] | None = None,
    price_filter: str = "conditions:{NEW},price:[10..100]",
    limit: int = 5,
) -> dict:
    return {
        "query": query,
        "observed_at": observed_at or datetime(2026, 10, 20, 10, 0, 0),
        "source": "browse_search",
        "filter": price_filter,
        "limit": limit,
        "listings": listings or [],
    }


def _listing(listing_id: str, title: str = "A listing") -> dict:
    return {
        "listing_id": listing_id,
        "title": title,
        "item_url": f"https://www.ebay.co.uk/itm/{listing_id}",
        "price": 19.99,
        "currency": "GBP",
        "item_creation_date": "2025-03-21T15:44:11",
    }


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _stub_get(monkeypatch, payload):
    monkeypatch.setattr(
        "scrapers.ebay.requests.get", lambda *a, **k: _FakeResponse(payload)
    )


def _authed_scraper():
    from scrapers.ebay import EbayScraper

    scraper = EbayScraper()
    scraper._token = "test-token"
    scraper._token_expiry = time.time() + 3600
    return scraper


class TestTheTable:
    def test_the_model_declares_every_field_the_store_writes(self):
        from db.models import QueryObservation

        assert set(QueryObservation.__table__.columns.keys()) == {
            "id",
            "query",
            "observed_at",
            "source",
            "price_filter",
            "sample_limit",
            "listing_count",
            "listings",
        }

    def test_the_table_helper_is_idempotent(self):
        from db.database import ensure_query_observations_table

        assert ensure_query_observations_table() is False
        assert ensure_query_observations_table() is False


class TestTheSnapshotFields:
    def test_a_summary_becomes_the_fields_the_churn_page_shows(self):
        from scrapers.browse_fields import query_listing

        row = query_listing(PAYLOAD_NEW)

        assert row == {
            "listing_id": "111111111111",
            "title": "Garden Hose 30m",
            "item_url": "https://www.ebay.co.uk/itm/111111111111",
            "price": 19.99,
            "currency": "GBP",
            "item_creation_date": "2025-03-21T15:44:11",
        }

    def test_a_payload_without_a_listing_id_is_not_given_one(self):
        from scrapers.browse_fields import query_listing

        assert query_listing({**PAYLOAD_NEW, "legacyItemId": None, "itemId": None}) is None

    def test_a_missing_creation_date_stays_none(self):
        from scrapers.browse_fields import query_listing

        payload = {**PAYLOAD_NEW, "itemCreationDate": None}
        assert query_listing(payload)["item_creation_date"] is None

    def test_a_missing_title_stays_none_rather_than_an_empty_string(self):
        from scrapers.browse_fields import query_listing

        payload = {**PAYLOAD_NEW, "title": "   "}
        assert query_listing(payload)["title"] is None


class TestTheStore:
    def test_one_search_result_set_is_one_row(self, tmp_path):
        from db.models import QueryObservation
        from db.queries import save_query_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            stored = save_query_observations(
                session,
                [_run(listings=[_listing("1"), _listing("2")])],
            )
            assert stored == {"recorded": 1, "skipped": 0}

            row = session.query(QueryObservation).one()
            assert row.query == "garden hose"
            assert row.listing_count == 2
            assert [item["listing_id"] for item in row.listings] == ["1", "2"]
            assert row.price_filter == "conditions:{NEW},price:[10..100]"
            assert row.sample_limit == 5
        finally:
            session.close()

    def test_a_zero_result_search_is_stored_as_a_zero(self, tmp_path):
        from db.models import QueryObservation
        from db.queries import save_query_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            save_query_observations(session, [_run(listings=[])])
            row = session.query(QueryObservation).one()
            assert row.listing_count == 0
            assert row.listings == []
        finally:
            session.close()

    def test_a_blank_query_is_skipped_rather_than_filed_under_nothing(self, tmp_path):
        from db.models import QueryObservation
        from db.queries import save_query_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            stored = save_query_observations(session, [_run(query="   ")])
            assert stored == {"recorded": 0, "skipped": 1}
            assert session.query(QueryObservation).count() == 0
        finally:
            session.close()

    def test_case_and_spacing_reach_the_same_lane(self, tmp_path):
        from db.queries import get_query_observations, save_query_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            save_query_observations(session, [_run(query="Garden  Hose")])
            rows = get_query_observations(session, "garden hose")
            assert len(rows) == 1
            assert rows[0].query == "garden hose"
        finally:
            session.close()

    def test_newest_observation_comes_first(self, tmp_path):
        from db.queries import get_query_observations, save_query_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            save_query_observations(
                session,
                [
                    _run(observed_at=datetime(2026, 10, 19, 10, 0, 0)),
                    _run(observed_at=datetime(2026, 10, 20, 10, 0, 0)),
                ],
            )
            rows = get_query_observations(session, "garden hose")
            assert [row.observed_at for row in rows] == [
                datetime(2026, 10, 20, 10, 0, 0),
                datetime(2026, 10, 19, 10, 0, 0),
            ]
        finally:
            session.close()

    def test_a_listing_summary_names_the_first_and_latest_readings(self, tmp_path):
        from db.models import ListingObservation
        from db.queries import get_listing_observation_summary

        session = _fresh_session_factory(tmp_path)()
        try:
            session.add_all(
                [
                    ListingObservation(
                        listing_id="1",
                        observed_at=datetime(2026, 10, 18, 10, 0, 0),
                        item_creation_date=datetime(2025, 1, 1, 0, 0, 0),
                    ),
                    ListingObservation(
                        listing_id="1",
                        observed_at=datetime(2026, 10, 19, 10, 0, 0),
                        item_creation_date=None,
                    ),
                ]
            )
            session.commit()

            summary = get_listing_observation_summary(session, "1")
            assert summary["readings"] == 2
            assert summary["first_seen_at"] == datetime(2026, 10, 18, 10, 0, 0)
            assert summary["latest_reading_at"] == datetime(2026, 10, 19, 10, 0, 0)
            # The later summary omitted the field; the earlier real value stays.
            assert summary["item_creation_date"] == datetime(2025, 1, 1, 0, 0, 0)
        finally:
            session.close()

    def test_an_unknown_listing_has_no_summary(self, tmp_path):
        from db.queries import get_listing_observation_summary

        session = _fresh_session_factory(tmp_path)()
        try:
            assert get_listing_observation_summary(session, "missing") == {
                "readings": 0,
                "first_seen_at": None,
                "latest_reading_at": None,
                "item_creation_date": None,
            }
        finally:
            session.close()


class TestTheScraperRecordsTheSet:
    def test_a_search_keeps_every_listing_it_was_handed_before_the_gates(
        self, monkeypatch
    ):
        scraper = _authed_scraper()
        _stub_get(
            monkeypatch,
            {"itemSummaries": [PAYLOAD_NEW, PAYLOAD_REFURBISHED]},
        )

        scraper._search_api("garden hose", limit=7, price_band=None)

        assert len(scraper.query_observations) == 1
        run = scraper.query_observations[0]
        assert run["query"] == "garden hose"
        assert run["limit"] == 7
        assert "conditions:{NEW}" in run["filter"]
        assert [row["listing_id"] for row in run["listings"]] == [
            "111111111111",
            "222222222222",
        ]

    def test_a_zero_result_search_is_a_measured_zero(self, monkeypatch):
        scraper = _authed_scraper()
        _stub_get(monkeypatch, {"total": 0, "itemSummaries": []})

        scraper._search_api("nothing here", limit=5, price_band=None)

        assert len(scraper.query_observations) == 1
        assert scraper.query_observations[0]["listings"] == []

    def test_an_error_body_is_not_recorded_as_a_zero(self, monkeypatch):
        scraper = _authed_scraper()
        _stub_get(monkeypatch, {"errors": [{"message": "bad request"}]})

        scraper._search_api("bad", limit=5, price_band=None)

        assert scraper.query_observations == []

    def test_duplicate_listing_ids_in_one_response_are_one_row(self, monkeypatch):
        scraper = _authed_scraper()
        _stub_get(
            monkeypatch,
            {"itemSummaries": [PAYLOAD_NEW, dict(PAYLOAD_NEW)]},
        )

        scraper._search_api("garden hose", limit=5, price_band=None)

        assert len(scraper.query_observations[0]["listings"]) == 1

    def test_the_demand_search_is_not_a_query_observation(self, monkeypatch):
        scraper = _authed_scraper()
        _stub_get(monkeypatch, {"itemSummaries": [PAYLOAD_NEW]})

        scraper._get_sold_api("garden hose")

        assert scraper.query_observations == []


class TestThePipelineDrainsTheSet:
    def test_both_kinds_of_evidence_are_stored(self, tmp_path):
        from db.models import ListingObservation, QueryObservation
        from analysis_pipeline import _save_observations
        from db.queries import save_query_observations

        factory = _fresh_session_factory(tmp_path)
        session = factory()
        try:
            _save_observations(
                session,
                {
                    "observations": [("1", PAYLOAD_NEW, "browse_api_summary")],
                    "query_observations": [_run(listings=[_listing("1")])],
                },
            )
            assert session.query(ListingObservation).count() == 1
            assert session.query(QueryObservation).count() == 1
        finally:
            session.close()

    def test_a_query_observation_failure_does_not_discard_the_listing_reading(
        self, tmp_path, monkeypatch
    ):
        from db.models import ListingObservation, QueryObservation
        import analysis_pipeline as ap

        factory = _fresh_session_factory(tmp_path)
        session = factory()

        def boom(*args, **kwargs):
            raise RuntimeError("query store unavailable")

        monkeypatch.setattr(ap, "save_query_observations", boom)
        try:
            ap._save_observations(
                session,
                {
                    "observations": [("1", PAYLOAD_NEW, "browse_api_summary")],
                    "query_observations": [_run(listings=[_listing("1")])],
                },
            )
            assert session.query(ListingObservation).count() == 1
            assert session.query(QueryObservation).count() == 0
        finally:
            session.close()

    def test_a_no_product_run_still_saves_its_search_set(
        self, tmp_path, monkeypatch
    ):
        from db.models import QueryObservation
        import analysis_pipeline as ap

        factory = _fresh_session_factory(tmp_path)
        monkeypatch.setattr(ap, "SessionLocal", factory)

        ap.save_analysis_to_db(
            {
                "ebay_product": None,
                "query_observations": [_run(listings=[_listing("1")])],
            }
        )

        session = factory()
        try:
            assert session.query(QueryObservation).count() == 1
        finally:
            session.close()

    def test_a_no_product_run_with_no_observation_writes_nothing(
        self, tmp_path, monkeypatch
    ):
        from db.models import QueryObservation
        import analysis_pipeline as ap

        factory = _fresh_session_factory(tmp_path)
        monkeypatch.setattr(ap, "SessionLocal", factory)

        ap.save_analysis_to_db({"ebay_product": None, "query_observations": []})

        session = factory()
        try:
            assert session.query(QueryObservation).count() == 0
        finally:
            session.close()

    def test_a_timeout_still_saves_the_search_that_completed(
        self, monkeypatch
    ):
        """A slow supplier must not erase a search that already succeeded.

        The pipeline's `finally` copies the list into the caller's sink before
        cancellation unwinds. The route then saves it. This is the one path
        where the ordinary post-pipeline save cannot run.
        """
        import api.analyze as analyze_api
        from fastapi.testclient import TestClient
        from main import app

        saved: list[dict] = []

        async def _slow(
            query,
            is_url=False,
            filters=None,
            progress=None,
            timing_sink=None,
        ):
            if timing_sink is not None:
                timing_sink["query_observations"] = [
                    _run(listings=[_listing("1")])
                ]
            await asyncio.Event().wait()

        monkeypatch.setattr(analyze_api, "run_analysis_pipeline", _slow)
        monkeypatch.setattr(analyze_api, "PIPELINE_TIMEOUT_S", 0.2)
        monkeypatch.setattr(
            analyze_api,
            "save_analysis_to_db",
            lambda raw: saved.append(raw),
        )

        response = TestClient(app).post(
            "/api/analyze", json={"query": "garden hose"}
        )

        assert response.status_code == 200
        assert len(saved) == 1
        assert saved[0]["ebay_product"] is None
        assert saved[0]["query_observations"][0]["listings"][0]["listing_id"] == "1"

    def test_a_timeout_with_no_completed_search_writes_nothing(self, monkeypatch):
        import api.analyze as analyze_api
        from fastapi.testclient import TestClient
        from main import app

        saved: list[dict] = []

        async def _slow(
            query,
            is_url=False,
            filters=None,
            progress=None,
            timing_sink=None,
        ):
            await asyncio.Event().wait()

        monkeypatch.setattr(analyze_api, "run_analysis_pipeline", _slow)
        monkeypatch.setattr(analyze_api, "PIPELINE_TIMEOUT_S", 0.2)
        monkeypatch.setattr(
            analyze_api,
            "save_analysis_to_db",
            lambda raw: saved.append(raw),
        )

        response = TestClient(app).post(
            "/api/analyze", json={"query": "garden hose"}
        )

        assert response.status_code == 200
        assert saved == []
