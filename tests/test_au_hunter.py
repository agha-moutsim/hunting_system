"""Phase E4 - AU Category Hunter in AUD."""

from __future__ import annotations

import types

from fastapi.testclient import TestClient

from main import app
from marketplaces import get_marketplace


def _product():
    return {
        "title": "Generic widget",
        "price": 12.0,
        "url": "https://www.ebay.com.au/itm/1",
        "sold_30d": 40,
        "sold_7d": 10,
        "supplier_price": 6.0,
        "supplier_name": "AliExpress",
    }


class TestApiCarriesTheMarket:
    def _client(self):
        return TestClient(app)

    def test_au_scan_route_is_unlocked_and_labelled_aud(self, monkeypatch):
        import hunter.category_scan as ccs
        import hunter.demand_check as dc

        monkeypatch.setattr(ccs, "scan_category", lambda *a, **k: [])
        monkeypatch.setattr(dc, "batch_demand_check", lambda products, **k: products)

        with self._client() as client:
            resp = client.post(
                "/api/hunter/scan",
                json={"category": "Garden"},
                headers={"X-Ebay-Marketplace": "EBAY_AU"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["marketplace"] == "EBAY_AU"
        assert body["currency"] == "AUD"
        assert body["currency_symbol"] == "A$"

    def test_au_lookup_route_is_unlocked_and_labelled_aud(self, monkeypatch):
        import hunter.supplier_lookup as sl
        import hunter.profit_calc as pc
        import hunter.report as rp

        monkeypatch.setattr(
            sl, "batch_supplier_lookup", lambda products, **k: (products, 0)
        )
        monkeypatch.setattr(
            pc, "batch_profit_calc",
            lambda products, filters=None, **k: products,
        )
        monkeypatch.setattr(
            rp, "generate_report",
            lambda *a, **k: types.SimpleNamespace(
                to_dict=lambda: {"ok": True}, notes=""
            ),
        )

        with self._client() as client:
            resp = client.post(
                "/api/hunter/lookup",
                json={"products": [_product()]},
                headers={"X-Ebay-Marketplace": "EBAY_AU"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["marketplace"] == "EBAY_AU"
        assert body["currency"] == "AUD"
        assert body["currency_symbol"] == "A$"

    def test_a_market_without_a_card_or_bench_is_still_refused(self):
        with self._client() as client:
            scan_resp = client.post(
                "/api/hunter/scan",
                json={"category": "Garden"},
                headers={"X-Ebay-Marketplace": "EBAY_US"},
            )
            lookup_resp = client.post(
                "/api/hunter/lookup",
                json={"products": [_product()]},
                headers={"X-Ebay-Marketplace": "EBAY_US"},
            )
        assert scan_resp.status_code == 422
        assert "not enabled" in scan_resp.json()["detail"]
        assert "USD" in scan_resp.json()["detail"]
        assert lookup_resp.status_code == 422
        assert "not enabled" in lookup_resp.json()["detail"]


class TestMarketPropagation:
    def test_scan_passes_marketplace_only_for_non_uk(self, monkeypatch):
        import hunter.category_scan as ccs
        import hunter.demand_check as dc

        seen = []

        def fake_scan(category, **kwargs):
            seen.append(kwargs)
            return []

        monkeypatch.setattr(ccs, "scan_category", fake_scan)
        monkeypatch.setattr(dc, "batch_demand_check", lambda products, **k: products)

        with TestClient(app) as client:
            client.post("/api/hunter/scan", json={"category": "Garden"})
            client.post(
                "/api/hunter/scan",
                json={"category": "Garden"},
                headers={"X-Ebay-Marketplace": "EBAY_AU"},
            )

        assert "marketplace" not in seen[0]
        assert seen[1].get("marketplace") == "EBAY_AU"

    def test_lookup_passes_marketplace_to_supplier_and_profit_for_au(
        self, monkeypatch
    ):
        import hunter.supplier_lookup as sl
        import hunter.profit_calc as pc
        import hunter.report as rp

        supplier_seen = []
        profit_seen = []

        def fake_lookup(products, **kwargs):
            supplier_seen.append(kwargs)
            return products, 0

        def fake_profit(products, filters=None, **kwargs):
            profit_seen.append(kwargs)
            return products

        monkeypatch.setattr(sl, "batch_supplier_lookup", fake_lookup)
        monkeypatch.setattr(pc, "batch_profit_calc", fake_profit)
        monkeypatch.setattr(
            rp, "generate_report",
            lambda *a, **k: types.SimpleNamespace(
                to_dict=lambda: {"ok": True}, notes=""
            ),
        )

        with TestClient(app) as client:
            client.post(
                "/api/hunter/lookup",
                json={"products": [_product()]},
            )
            client.post(
                "/api/hunter/lookup",
                json={"products": [_product()]},
                headers={"X-Ebay-Marketplace": "EBAY_AU"},
            )

        assert all("marketplace" in call for call in supplier_seen)
        assert "marketplace" not in profit_seen[0]
        assert profit_seen[1].get("marketplace") == "EBAY_AU"

    def test_functions_accept_an_au_market(self):
        import hunter.category_scan as ccs
        import hunter.demand_check as dc
        import hunter.profit_calc as pc

        assert ccs.scan_category("", marketplace="EBAY_AU") == []
        assert dc.batch_demand_check([], marketplace="EBAY_AU") == []
        assert pc.batch_profit_calc([], marketplace="EBAY_AU") == []
