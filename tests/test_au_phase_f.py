"""Phase F - final AU UI/API acceptance checks."""


from __future__ import annotations

from fastapi.testclient import TestClient

from main import app
from marketplaces import get_marketplace, public_marketplace


def _client():
    return TestClient(app)


class TestAuPhaseFAcceptance:
    def test_the_public_au_market_is_fully_enabled(self):
        public = public_marketplace(get_marketplace("EBAY_AU"))

        assert public["analyze_ready"] is True
        assert public["fee_calculator_ready"] is True
        assert public["fee_table"] == "au-rate-card-2026-10-09"
        assert public["fee_warning"] is None
        assert public["supplier_bench"] == ["aliexpress", "cj_dropshipping"]

    def test_deals_are_served_in_aud_for_au(self):
        with _client() as client:
            body = client.get("/api/deals", params={"marketplace": "EBAY_AU"}).json()

        assert body["meta"]["marketplace"] == "EBAY_AU"
        assert body["meta"]["currency"] == "AUD"

    def test_titles_are_served_in_aud_for_au(self):
        with _client() as client:
            body = client.get(
                "/api/titles", params={"q": "drill", "marketplace": "EBAY_AU"}
            ).json()

        assert body["marketplace"] == "EBAY_AU"
        assert body["currency"] == "AUD"

    def test_fees_are_served_in_aud_for_au(self):
        with _client() as client:
            body = client.get("/api/fees/table", params={"marketplace": "EBAY_AU"}).json()

        assert body["marketplace"] == "EBAY_AU"
        assert body["currency"] == "AUD"
        assert body["fee_table"]["currency"] == "AUD"