"""Phase E5 - AU fee calculator in AUD."""


from __future__ import annotations

import pytest

from fastapi.testclient import TestClient
from main import app
from marketplaces import get_marketplace, public_marketplace


def _client():
    return TestClient(app)


AU_HEADERS = {"X-EBay-Marketplace": "EBAY_AU"}
US_HEADERS = {"X-EBay-Marketplace": "EBAY_US"}


class TestTheAuCalculatorIsEnabled:
    def test_the_public_market_exposes_the_aud_card(self):
        public = public_marketplace(get_marketplace("EBAY_AU"))

        assert public["fee_table"] == "au-rate-card-2026-10-09"
        assert public["fee_table_registered"] == "au-rate-card-2026-10-09"
        assert public["fee_calculator_ready"] is True
        assert public["fee_warning"] is None

    def test_the_fee_table_route_returns_aud_metadata_and_plans(self):
        with _client() as client:
            body = client.get("/api/fees/table", headers=AU_HEADERS).json()

        assert body["marketplace"] == "EBAY_AU"
        assert body["currency"] == "AUD"
        assert body["currency_symbol"] == "A$"
        assert body["fee_table"]["key"] == "au-rate-card-2026-10-09"
        assert body["fee_table"]["currency"] == "AUD"
        assert body["default_seller_type"] == "private"
        assert body["default_plan"] == "starter"
        assert [plan["key"] for plan in body["plans"]] == [
            "starter",
            "basic",
            "featured",
            "anchor",
        ]
        assert body["tax"] == {"name": "GST", "rate": 10.0, "included": True}
        assert body["domestic_region"] == "au"
        default = next(row for row in body["categories"] if row["is_default"])
        assert default["key"] == "tier-2"
        assert "starter" in (default.get("rates_by_plan") or {})

    def test_the_calculator_defaults_to_individual_aud(self):
        with _client() as client:
            body = client.post(
                "/api/fees/calculate",
                json={"sale_price": 100.0},
                headers=AU_HEADERS,
            ).json()

        assert body["marketplace"] == "EBAY_AU"
        assert body["currency"] == "AUD"
        calc = body["calculation"]
        assert calc["fees"]["seller"]["type"] == "private"
        assert calc["fees"]["fvf"] == 0.0
        assert calc["fees"]["fees_quoted_total"] == 0.0
        assert calc["fees"]["tax"]["name"] == "GST"
        assert "GST on fees" not in [
            line["label"] for line in calc["fee_lines"]
        ]

    def test_a_business_sale_reproduces_the_published_total(self):
        with _client() as client:
            body = client.post(
                "/api/fees/calculate",
                json={
                    "sale_price": 20.0,
                    "seller_type": "business",
                    "category": "tier-2",
                },
                headers=AU_HEADERS,
            ).json()

        calc = body["calculation"]
        assert calc["fees"]["seller"]["type"] == "business"
        assert calc["fees"]["seller"]["plan"] == "starter"
        assert calc["fees"]["fees_quoted_total"] == pytest.approx(2.98, abs=0.005)
        assert calc["fees"]["fees_cost_total"] == pytest.approx(2.98, abs=0.005)

    def test_a_selected_plan_is_honoured(self):
        with _client() as client:
            body = client.post(
                "/api/fees/calculate",
                json={
                    "sale_price": 300.0,
                    "seller_type": "business",
                    "seller_plan": "basic",
                    "category": "tier-1",
                },
                headers=AU_HEADERS,
            ).json()

        calc = body["calculation"]
        assert calc["fees"]["seller"]["plan"] == "basic"
        assert calc["fees"]["fees_quoted_total"] == pytest.approx(24.42, abs=0.005)

    def test_an_international_buyer_pays_the_international_fee(self):
        with _client() as client:
            business = client.post(
                "/api/fees/calculate",
                json={
                    "sale_price": 20.0,
                    "seller_type": "business",
                    "buyer_region": "rest_of_world",
                },
                headers=AU_HEADERS,
            ).json()["calculation"]
            private = client.post(
                "/api/fees/calculate",
                json={
                    "sale_price": 20.0,
                    "seller_type": "private",
                    "buyer_region": "rest_of_world",
                },
                headers=AU_HEADERS,
            ).json()["calculation"]

        assert business["fees"]["international_fee"] == pytest.approx(0.22, abs=0.005)
        assert private["fees"]["international_fee"] == pytest.approx(0.60, abs=0.005)

    def test_a_market_without_a_card_is_still_refused(self):
        with _client() as client:
            table_resp = client.get("/api/fees/table", headers=US_HEADERS)
            calc_resp = client.post(
                "/api/fees/calculate",
                json={"sale_price": 24.99},
                headers=US_HEADERS,
            )

        assert table_resp.status_code == 422
        assert "No USD fee table" in table_resp.json()["detail"]
        assert calc_resp.status_code == 422
        assert "No USD fee table" in calc_resp.json()["detail"]
