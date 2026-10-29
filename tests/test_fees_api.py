"""POST /api/fees/calculate + GET /api/fees/table - the calculator's API.

The routes are a thin door to engine/fees.py: these tests pin what the
calculator page consumes - the fee table version on every response, the
engine's own itemised lines, refusals as 422 sentences - and the Phase D
acceptance case through the HTTP door.
"""

import pytest


def _client():
    from fastapi.testclient import TestClient

    from main import app

    return TestClient(app)


ACCEPTANCE = {
    "sale_price": 24.99,
    "supplier_cost": 9.40,
    "postage_paid": 3.20,
    "promoted_rate": 2.0,
    "seller_type": "business",
}


class TestTheTableRoute:
    def test_returns_the_active_table_with_its_version_and_sources(self):
        with _client() as client:
            body = client.get("/api/fees/table").json()

        assert body["fee_table"]["key"] == "uk-rate-card-2026-09-30"
        assert body["fee_table"]["version"]
        assert body["fee_table"]["sources"][0]["url"].startswith("https://")

    def test_categories_are_ui_ready_and_include_the_stated_default(self):
        with _client() as client:
            body = client.get("/api/fees/table").json()

        row = next(r for r in body["categories"] if r["key"] == "everything-else")
        assert row["name"] == "Everything Else"
        assert row["category_ids"] == [99]
        assert row["rate_label"] == "12.9%"

    def test_the_profile_travels_so_the_page_can_prefill(self):
        with _client() as client:
            body = client.get("/api/fees/table").json()

        assert body["profile"]["seller_type"] == "business"
        assert body["profile"]["vat_registered"] is False
        assert body["market_defaults"]["seller_type"] == "business"
        assert body["market_defaults"]["buyer_region"] == "uk"

    def test_the_market_card_is_the_default_not_whatever_is_active(self):
        with _client() as client:
            body = client.get("/api/fees/table").json()

        assert body["fee_table"]["key"] == "uk-rate-card-2026-09-30"
        assert body["fee_table"]["currency"] == "GBP"

    def test_a_foreign_currency_card_is_refused_on_the_uk_market(self):
        with _client() as client:
            resp = client.get(
                "/api/fees/table",
                params={"key": "au-rate-card-2026-10-09"},
            )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "AUD" in detail
        assert "GBP" in detail
        assert "never applied across currencies" in detail

    def test_an_unknown_table_is_refused_with_the_known_ones_listed(self):
        with _client() as client:
            resp = client.get("/api/fees/table", params={"key": "made-up"})

        assert resp.status_code == 422
        assert "unknown fee table" in resp.json()["detail"]
        assert "uk-rate-card-2026-09-30" in resp.json()["detail"]

    def test_the_retired_v1_table_is_still_selectable(self):
        with _client() as client:
            body = client.get("/api/fees/table", params={"key": "v1-static"}).json()

        assert body["fee_table"]["key"] == "v1-static"
        assert "C3" in body["fee_table"]["version"]


class TestForwardMode:
    def test_the_acceptance_case_returns_the_engine_breakdown(self):
        with _client() as client:
            resp = client.post("/api/fees/calculate", json=ACCEPTANCE)

        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "forward"
        assert body["fee_table"]["key"] == "uk-rate-card-2026-09-30"

        calc = body["calculation"]
        by_label = {row["label"]: row for row in calc["fee_lines"]}
        assert by_label["Final value fee"]["amount"] == 3.22
        assert by_label["Final value fee"]["rate"] == "12.9%"
        assert by_label["Per-order fee"]["amount"] == 0.40
        assert by_label["Regulatory operating fee"]["amount"] == 0.09
        assert by_label["Promoted listings"]["amount"] == 0.50
        assert by_label["VAT on fees"]["amount"] == 0.84
        assert calc["fees"]["fees_cost_total"] == 5.05
        assert calc["net_after_fees"] == 19.94
        assert calc["profit"] == 6.59
        assert calc["margin"] == 26.4

    def test_the_missing_category_is_a_stated_default_not_a_silent_guess(self):
        with _client() as client:
            body = client.post("/api/fees/calculate", json=ACCEPTANCE).json()

        calc = body["calculation"]
        assert calc["fees"]["category"]["known"] is False
        assert calc["fees"]["category"]["key"] == "everything-else"
        assert any("stated default" in line for line in calc["fees"]["assumptions"])

    def test_an_unread_postage_is_a_ceiling_not_a_zero_cost(self):
        body = dict(ACCEPTANCE)
        body.pop("postage_paid")
        with _client() as client:
            calc = client.post("/api/fees/calculate", json=body).json()["calculation"]

        assert calc["postage_paid_known"] is False
        assert calc["profit_is_complete"] is False
        assert calc["profit"] == 9.79  # the same sale less the unexplained 3.20

    def test_no_supplier_price_leaves_profit_uncomputed_and_states_why(self):
        with _client() as client:
            calc = client.post(
                "/api/fees/calculate",
                json={"sale_price": 24.99, "promoted_rate": 2.0},
            ).json()["calculation"]

        assert calc["profit"] is None
        assert calc["margin"] is None
        assert calc["profit_is_complete"] is False
        assert calc["profit_missing_reason"]
        assert calc["fees"]["fvf"] == 3.22  # fees do not need a supplier

    def test_an_unknown_category_falls_back_to_the_stated_default(self):
        with _client() as client:
            calc = client.post(
                "/api/fees/calculate",
                json={"sale_price": 24.99, "category": "made-up-category"},
            ).json()["calculation"]

        assert calc["fees"]["category"]["known"] is False
        assert calc["fees"]["category"]["key"] == "everything-else"
        assert calc["fees"]["fvf_rate"] == "12.9%"

    def test_postage_charged_enters_the_fee_basis(self):
        with _client() as client:
            calc = client.post(
                "/api/fees/calculate",
                json={
                    "sale_price": 19.99,
                    "postage_charged": 5.00,
                    "supplier_cost": 8.00,
                },
            ).json()["calculation"]

        assert calc["fees"]["fee_basis"] == "total_amount_of_sale"
        assert calc["fees"]["total_amount_of_sale"] == 24.99
        assert calc["fees"]["fvf"] == 3.22  # 12.9% of 24.99
        assert calc["price"] == 19.99  # the sale itself is still the item

    def test_a_private_uk_sale_shows_documented_zeroes_and_no_vat_line(self):
        with _client() as client:
            calc = client.post(
                "/api/fees/calculate",
                json={
                    "sale_price": 30.0,
                    "supplier_cost": 10.0,
                    "seller_type": "private",
                },
            ).json()["calculation"]

        by_label = {row["label"]: row for row in calc["fee_lines"]}
        assert by_label["Final value fee"]["amount"] == 0.0
        assert "VAT on fees" not in by_label
        assert calc["fees"]["vat_on_fees"] is None

    def test_a_vat_registered_seller_recovers_the_vat_on_fees(self):
        with _client() as client:
            calc = client.post(
                "/api/fees/calculate",
                json={**ACCEPTANCE, "vat_registered": True},
            ).json()["calculation"]

        assert calc["fees"]["vat_recoverable"] is True
        assert calc["fees"]["fees_cost_total"] == 4.21  # quoted 4.21, VAT aside

    def test_a_foreign_currency_card_is_refused_before_pricing(self):
        with _client() as client:
            resp = client.post(
                "/api/fees/calculate",
                json={**ACCEPTANCE, "fee_table": "au-rate-card-2026-10-09"},
            )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "AUD" in detail
        assert "GBP" in detail
        assert "never applied across currencies" in detail

    def test_the_retired_v1_table_can_be_priced_explicitly(self):
        with _client() as client:
            body = client.post(
                "/api/fees/calculate",
                json={
                    "sale_price": 24.99,
                    "supplier_cost": 9.40,
                    "fee_table": "v1-static",
                },
            ).json()

        assert body["fee_table"]["key"] == "v1-static"
        calc = body["calculation"]
        assert calc["fees"]["fee_basis"] == "item_price"
        by_label = {row["label"]: row for row in calc["fee_lines"]}
        assert by_label["Final value fee"]["rate"] == "13.5%"
        assert calc["profit"] == 10.78


class TestReverseMode:
    def test_it_solves_the_price_and_ships_the_breakdown_at_it(self):
        with _client() as client:
            resp = client.post(
                "/api/fees/calculate",
                json={
                    "target_margin": 30.0,
                    "supplier_cost": 9.40,
                    "postage_paid": 3.20,
                    "promoted_rate": 2.0,
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "reverse"
        assert body["fee_table"]["key"] == "uk-rate-card-2026-09-30"
        assert body["achievable"] is True
        assert body["price"] == 26.86  # rounded UP to the penny, within 1p of 26.858
        assert body["target_margin"] == 30.0
        assert body["check"]["margin"] == 30.0
        assert body["check"]["profit"] == 8.06
        assert body["calculation"]["profit"] == 8.06
        assert body["calculation"]["margin"] == 30.0

    def test_the_round_trip_holds_through_the_forward_mode(self):
        with _client() as client:
            forward = client.post(
                "/api/fees/calculate",
                json={
                    "sale_price": 26.86,
                    "supplier_cost": 9.40,
                    "postage_paid": 3.20,
                    "promoted_rate": 2.0,
                },
            ).json()

        assert forward["calculation"]["margin"] == 30.0

    def test_it_refuses_a_target_outside_the_possible_range(self):
        with _client() as client:
            resp = client.post(
                "/api/fees/calculate",
                json={"target_margin": 150, "supplier_cost": 5},
            )

        assert resp.status_code == 422
        assert "target_margin" in resp.json()["detail"]

    def test_it_refuses_a_target_without_a_supplier_cost(self):
        with _client() as client:
            resp = client.post("/api/fees/calculate", json={"target_margin": 30})

        assert resp.status_code == 422
        assert "supplier_cost is required" in resp.json()["detail"]


class TestRefusals:
    @pytest.mark.parametrize(
        "body, expected",
        [
            ({"sale_price": 0, "supplier_cost": 1.0}, "greater than zero"),
            ({"sale_price": -5, "supplier_cost": 1.0}, "got -5"),
            (
                {"sale_price": 10, "promoted_rate": 150},
                "promoted_rate must be below 100",
            ),
            ({"sale_price": 10, "seller_type": "charity"}, "unknown seller_type"),
            ({"sale_price": 10, "buyer_region": "mars"}, "unknown buyer_region"),
            ({"sale_price": 10, "fee_table": "nope"}, "unknown fee table"),
        ],
    )
    def test_engine_refusals_are_422_with_the_engine_sentence(self, body, expected):
        with _client() as client:
            resp = client.post("/api/fees/calculate", json=body)

        assert resp.status_code == 422
        assert expected in resp.json()["detail"]

    def test_a_request_without_a_mode_is_refused(self):
        with _client() as client:
            resp = client.post("/api/fees/calculate", json={"supplier_cost": 2})

        assert resp.status_code == 422
        assert "sale_price (forward) or target_margin (reverse)" in resp.json()[
            "detail"
        ]

    def test_sending_both_modes_is_refused(self):
        with _client() as client:
            resp = client.post(
                "/api/fees/calculate",
                json={"sale_price": 20, "target_margin": 30, "supplier_cost": 5},
            )

        assert resp.status_code == 422
        assert "not both" in resp.json()["detail"]

    def test_a_null_price_is_unread_not_zero(self):
        with _client() as client:
            resp = client.post("/api/fees/calculate", json={"sale_price": None})

        # The endpoint asks for a mode; it never turns null into 0.
        assert resp.status_code == 422
        assert "required" in resp.json()["detail"]
