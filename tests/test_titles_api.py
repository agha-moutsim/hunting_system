"""GET /api/titles - the title helper's door, without a live eBay call.

The route spends one Browse search and hands the titles to engine/titles.py.
These tests pin what the page consumes: the query, the always-present sample
size, the two count tables, a refusal sentence instead of a fake zero, and the
absence of any search-volume-shaped field.
"""

from __future__ import annotations

import pytest

BANNED = {
    "search_volume",
    "monthly_searches",
    "volume",
    "popularity",
    "demand",
    "demand_index",
    "interest",
    "rank",
    "score",
    "trend",
    "competition",
    "keyword_difficulty",
    "cpc",
    "clicks",
    "watch_count",
    "watchers",
    "sold_count",
    "sales",
    "sales_count",
    "quantity_sold",
    "revenue",
}


class _Listing:
    def __init__(self, title: str):
        self.title = title


def _client():
    from fastapi.testclient import TestClient

    from main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def _fake_ebay_credentials(monkeypatch):
    """The route checks for keys before spending a call.

    Tests must not depend on the developer's .env, and a real key must never
    be used here. The values are obvious placeholders, not credentials.
    """
    import config

    monkeypatch.setattr(config, "EBAY_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(config, "EBAY_CLIENT_SECRET", "test-client-secret")


@pytest.fixture()
def search(monkeypatch):
    """Stub the scraper seam; the route itself is the unit under test."""
    calls = {"result": [], "error": None}

    def fake(self, query, limit=50):
        calls["query"] = query
        calls["limit"] = limit
        if calls["error"] is not None:
            raise calls["error"]
        return calls["result"]

    from scrapers.ebay import EbayScraper

    monkeypatch.setattr(EbayScraper, "search_titles", fake)
    return calls


class TestTheCounts:
    def test_counts_come_from_the_listings_the_query_returned(self, search):
        search["result"] = [
            _Listing("Garden Hose Anti-Kink 3-Pack"),
            _Listing("Expandable Garden Hose"),
            _Listing("Garden Hose Pipe"),
        ]

        with _client() as client:
            response = client.get("/api/titles", params={"q": "garden hose"})

        assert response.status_code == 200
        body = response.json()
        assert body["query"] == "garden hose"
        assert body["listings_analysed"] == 3
        assert body["unigrams"][0] == {"word": "garden", "count": 3}
        assert body["bigrams"][0] == {"phrase": "garden hose", "count": 3}
        assert body["reason"] is None

    def test_the_route_passes_the_trimmed_query_and_limit(self, search):
        with _client() as client:
            response = client.get(
                "/api/titles", params={"q": "  garden hose  ", "limit": 7}
            )

        assert response.status_code == 200
        assert search["query"] == "garden hose"
        assert search["limit"] == 7

    def test_a_zero_sample_is_reported_with_a_sentence(self, search):
        search["result"] = []

        with _client() as client:
            response = client.get("/api/titles", params={"q": "unfindable thing"})

        assert response.status_code == 200
        body = response.json()
        assert body["listings_analysed"] == 0
        assert body["unigrams"] == []
        assert body["bigrams"] == []
        assert isinstance(body["reason"], str)
        assert "no" in body["reason"].lower()


class TestTheRefusals:
    def test_a_failed_search_is_not_a_measured_zero(self, search):
        search["error"] = RuntimeError("eBay is down")

        with _client() as client:
            response = client.get("/api/titles", params={"q": "garden hose"})

        assert response.status_code == 502
        detail = response.json()["detail"]
        assert "did not answer" in detail
        assert "no counts" in detail

    def test_missing_credentials_are_refused_before_a_call(
        self, search, monkeypatch
    ):
        import config

        monkeypatch.setattr(config, "EBAY_CLIENT_ID", "")
        monkeypatch.setattr(config, "EBAY_CLIENT_SECRET", "")

        with _client() as client:
            response = client.get("/api/titles", params={"q": "garden hose"})

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert "credentials" in detail
        assert "no title counts" in detail
        assert "query" not in search, "no Browse call may be spent without keys"

    def test_a_blank_query_is_refused(self, search):
        with _client() as client:
            response = client.get("/api/titles", params={"q": "   "})

        assert response.status_code == 422
        assert "blank" in response.json()["detail"]

    @pytest.mark.parametrize("limit", [0, 51])
    def test_the_limit_is_bounded(self, search, limit):
        with _client() as client:
            response = client.get(
                "/api/titles", params={"q": "garden hose", "limit": limit}
            )

        assert response.status_code == 422


class TestNoSearchVolumeCanExist:
    def test_the_response_has_only_the_sample_and_two_count_tables(self, search):
        search["result"] = [_Listing("Garden Hose"), _Listing("Hose Pipe")]

        with _client() as client:
            body = client.get("/api/titles", params={"q": "garden hose"}).json()

        assert set(body) == {
            "query",
            "listings_analysed",
            "unigrams",
            "bigrams",
            "reason",
        }
        assert set(body["unigrams"][0]) == {"word", "count"}
        assert set(body["bigrams"][0]) == {"phrase", "count"}

    def test_no_key_can_be_mistaken_for_a_volume_claim(self, search):
        search["result"] = [_Listing("Garden Hose"), _Listing("Hose Pipe")]

        with _client() as client:
            body = client.get("/api/titles", params={"q": "garden hose"}).json()

        keys = set(body)
        keys |= {key for row in body["unigrams"] for key in row}
        keys |= {key for row in body["bigrams"] for key in row}
        assert keys.isdisjoint(BANNED), f"volume-shaped fields: {keys & BANNED}"

    def test_every_count_is_bounded_by_the_sample_size(self, search):
        search["result"] = [
            _Listing("hose hose"),
            _Listing("garden hose"),
            _Listing("expandable hose"),
        ]

        with _client() as client:
            body = client.get("/api/titles", params={"q": "hose"}).json()

        assert body["listings_analysed"] == 3
        for table in ("unigrams", "bigrams"):
            assert all(
                0 < row["count"] <= body["listings_analysed"]
                for row in body[table]
            )
