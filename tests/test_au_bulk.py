"""Phase E3 - AU Bulk in AUD.

Bulk runs the fast deep-search path for many queries at once. It follows the
same `analyze_ready` gate as Deep Search, so AU (which has a sourced card and
an AUD bench) is unlocked while markets without a card or bench stay locked.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from deep_search import DeepSearchResult
from main import app
from marketplaces import get_marketplace


def _result(market_id: str = "EBAY_GB") -> DeepSearchResult:
    market = get_marketplace(market_id)
    result = DeepSearchResult(
        product_name="widget",
        marketplace=market["id"],
        currency=market["currency"],
        currency_symbol=market["currency_symbol"],
    )
    result.verdict = "PASS"
    return result


class TestApiCarriesTheMarket:
    def _client(self):
        return TestClient(app)

    def test_au_bulk_route_is_unlocked_and_labelled_aud(self, monkeypatch):
        import deep_search as ds

        monkeypatch.setattr(
            ds, "deep_search_fast",
            lambda query, *args, **kwargs: _result(
                kwargs.get("marketplace", "EBAY_GB")
            ),
        )
        with self._client() as client:
            created = client.post(
                "/api/bulk",
                json={"queries": ["widget"]},
                headers={"X-Ebay-Marketplace": "EBAY_AU"},
            )
        assert created.status_code == 200
        body = created.json()
        assert body["marketplace"] == "EBAY_AU"
        assert body["currency"] == "AUD"
        assert body["currency_symbol"] == "A$"
        assert body["succeeded"] == 1
        assert body["results"][0]["currency"] == "AUD"

    def test_a_market_without_a_card_or_bench_is_still_refused(self):
        with self._client() as client:
            resp = client.post(
                "/api/bulk",
                json={"queries": ["widget"]},
                headers={"X-Ebay-Marketplace": "EBAY_US"},
            )
        assert resp.status_code == 422
        assert "not enabled" in resp.json()["detail"]
        assert "USD" in resp.json()["detail"]


class TestMarketPropagation:
    def test_uk_keeps_the_one_argument_call_and_au_states_its_market(
        self, monkeypatch
    ):
        import deep_search as ds

        seen: list[tuple[tuple, dict]] = []

        def fake(query, *args, **kwargs):
            seen.append((args, kwargs))
            return _result(kwargs.get("marketplace", "EBAY_GB"))

        monkeypatch.setattr(ds, "deep_search_fast", fake)

        with TestClient(app) as client:
            client.post("/api/bulk", json={"queries": ["widget"]})
            client.post(
                "/api/bulk",
                json={"queries": ["widget"]},
                headers={"X-Ebay-Marketplace": "EBAY_AU"},
            )

        assert "marketplace" not in seen[0][1]
        assert seen[1][1].get("marketplace") == "EBAY_AU"
