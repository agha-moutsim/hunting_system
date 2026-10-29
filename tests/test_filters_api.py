"""GET/PUT /api/filters — the user-adjustable price range (PR-5/PR-7).

Validation lives in utils.filters._valid_range; the endpoint must reject
bad ranges with 422 and never poison the active gate.
"""

import json

import pytest


@pytest.fixture(autouse=True)
def _pristine_range(monkeypatch, tmp_path):
    import utils.filters as uf
    target = tmp_path / "custom_filters.json"
    target.write_text(json.dumps({"active": {}, "presets": {}}))
    monkeypatch.setattr(uf, "FILTERS_FILE", target)
    uf._cache["mtime"] = None
    uf._cache["data"] = None
    yield
    uf._cache["mtime"] = None
    uf._cache["data"] = None


def _client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


class TestGetFilters:
    def test_returns_active_range_and_config_defaults(self):
        with _client() as client:
            body = client.get("/api/filters").json()
            assert body["range"] == {"min": 5.0, "max": 35.0}
            assert body["defaults"] == {"price_min": 5.0, "price_max": 35.0}
            assert body["active"]["price_min"] == 5.0


class TestPutFilters:
    def test_valid_range_updates_and_persists(self):
        with _client() as client:
            resp = client.put("/api/filters", json={"price_min": 8, "price_max": 50})
            assert resp.status_code == 200
            assert resp.json()["range"] == {"min": 8.0, "max": 50.0}

            again = client.get("/api/filters").json()
            assert again["range"] == {"min": 8.0, "max": 50.0}
            # Defaults are untouched — only the active range moved.
            assert again["defaults"] == {"price_min": 5.0, "price_max": 35.0}

    def test_other_active_filters_are_preserved(self):
        with _client() as client:
            import utils.filters as uf
            uf.save_filters({"price_min": 5.0, "price_max": 35.0, "demand_min_30d": 42})

            client.put("/api/filters", json={"price_min": 6, "price_max": 20})
            body = client.get("/api/filters").json()
            assert body["range"] == {"min": 6.0, "max": 20.0}
            assert body["active"]["demand_min_30d"] == 42

    @pytest.mark.parametrize("payload", [
        {"price_min": 50, "price_max": 10},   # inverted
        {"price_min": 0, "price_max": 10},    # zero min
        {"price_min": -5, "price_max": 10},   # negative min
        {"price_min": 5, "price_max": 0},     # zero max
    ])
    def test_invalid_range_is_rejected_and_gate_unchanged(self, payload):
        with _client() as client:
            resp = client.put("/api/filters", json=payload)
            assert resp.status_code == 422
            assert client.get("/api/filters").json()["range"] == {"min": 5.0, "max": 35.0}


class TestConditionInFiltersApi:
    """C10 — condition is part of the contract, validated, never poisonable."""

    def test_condition_is_exposed_as_new_by_default(self):
        with _client() as client:
            body = client.get("/api/filters").json()
            assert body["active"]["condition"] == "New"

    def test_setting_condition_new_persists(self):
        with _client() as client:
            resp = client.put("/api/filters",
                              json={"price_min": 5, "price_max": 35, "condition": "New"})
            assert resp.status_code == 200
            assert resp.json()["condition"] == "New"
            assert client.get("/api/filters").json()["active"]["condition"] == "New"

    @pytest.mark.parametrize("bad", ["Used", "Refurbished", "Pre-owned", "", "new",
                                     "ANY", "New; Used"])
    def test_non_new_condition_is_422_and_gate_unchanged(self, bad):
        with _client() as client:
            resp = client.put("/api/filters",
                              json={"price_min": 5, "price_max": 35, "condition": bad})
            assert resp.status_code == 422
            assert client.get("/api/filters").json()["active"]["condition"] == "New"

    def test_condition_omitted_leaves_existing_value_alone(self):
        # Range-only clients (the PR-7 shape) must keep working.
        with _client() as client:
            resp = client.put("/api/filters", json={"price_min": 7, "price_max": 30})
            assert resp.status_code == 200
            assert client.get("/api/filters").json()["active"]["condition"] == "New"

    def test_poisoned_storage_file_cannot_relax_new_only(self, monkeypatch, tmp_path):
        import utils.filters as uf
        target = tmp_path / "poisoned.json"
        target.write_text(json.dumps({"active": {"condition": "Used"}, "presets": {}}))
        monkeypatch.setattr(uf, "FILTERS_FILE", target)
        uf._cache["mtime"] = None
        uf._cache["data"] = None
        try:
            assert uf.load_filters()["condition"] == "New"
        finally:
            uf._cache["mtime"] = None
            uf._cache["data"] = None


class _CapturedScan:
    """Fake category_scan + demand_check so /hunter/scan never scrapes."""

    def __init__(self):
        self.kwargs = None

    def install(self, monkeypatch):
        import hunter.category_scan as ccs
        import hunter.demand_check as dc

        def _scan(category, **kwargs):
            self.kwargs = kwargs
            return []

        monkeypatch.setattr(ccs, "scan_category", _scan)
        monkeypatch.setattr(dc, "batch_demand_check", lambda products: products)


class TestHunterScanRangeResolution:
    """Review fix: omitted/invalid client range must resolve to ACTIVE
    (the old `or`-fallback let a zero-ish value bypass the active band)."""

    def test_omitted_range_resolves_to_the_active_range(self, monkeypatch):
        capture = _CapturedScan()
        capture.install(monkeypatch)
        with _client() as client:
            client.put("/api/filters", json={"price_min": 8, "price_max": 50})
            resp = client.post("/api/hunter/scan", json={"category": "Garden"})
            assert resp.status_code == 200
        assert capture.kwargs["price_min"] == 8.0
        assert capture.kwargs["price_max"] == 50.0

    def test_invalid_client_range_falls_back_to_the_active_range(self, monkeypatch):
        capture = _CapturedScan()
        capture.install(monkeypatch)
        with _client() as client:
            client.put("/api/filters", json={"price_min": 8, "price_max": 50})
            resp = client.post(
                "/api/hunter/scan",
                json={"category": "Garden", "price_min": 50, "price_max": 10},
            )
            assert resp.status_code == 200
        assert capture.kwargs["price_min"] == 8.0
        assert capture.kwargs["price_max"] == 50.0

    def test_valid_client_range_is_honoured(self, monkeypatch):
        capture = _CapturedScan()
        capture.install(monkeypatch)
        with _client() as client:
            client.put("/api/filters", json={"price_min": 8, "price_max": 50})
            resp = client.post(
                "/api/hunter/scan",
                json={"category": "Garden", "price_min": 10, "price_max": 20},
            )
            assert resp.status_code == 200
        assert capture.kwargs["price_min"] == 10.0
        assert capture.kwargs["price_max"] == 20.0


class TestHunterLookupRangeForcing:
    """Review fix: the lookup's gate keys always resolve to the ACTIVE
    range — client echoes never move the selection gate (PR-7)."""

    def test_client_filters_cannot_move_the_gate(self, monkeypatch):
        import types

        captured = {}

        def _lookup(products, **kwargs):
            return products, 0

        def _calc(products, filters):
            captured.update(filters)
            return products

        def _report(products, **kwargs):
            return types.SimpleNamespace(to_dict=lambda: {"ok": True}, notes="")

        import hunter.supplier_lookup as sl
        import hunter.profit_calc as pc
        import hunter.report as rp
        monkeypatch.setattr(sl, "batch_supplier_lookup", _lookup)
        monkeypatch.setattr(pc, "batch_profit_calc", _calc)
        monkeypatch.setattr(rp, "generate_report", _report)

        product = {
            "title": "Generic widget",
            "price": 12.0,
            "url": "https://www.ebay.co.uk/itm/1",
            "sold_30d": 40,
            "sold_7d": 10,
            "supplier_price": 6.0,
            "supplier_name": "B&Q",
        }
        with _client() as client:
            client.put("/api/filters", json={"price_min": 8, "price_max": 50})
            resp = client.post(
                "/api/hunter/lookup",
                json={
                    "products": [product],
                    "filters": {"price_min": 1, "price_max": 9999},
                },
            )
            assert resp.status_code == 200
        assert captured["price_min"] == 8.0
        assert captured["price_max"] == 50.0


class TestSavedSearchRangeResolution:
    """Review fix: an omitted per-search range stores the ACTIVE range —
    config defaults are only the mirror when no active range exists."""

    def test_created_search_defaults_to_the_active_range(self):
        with _client() as client:
            client.put("/api/filters", json={"price_min": 8, "price_max": 50})
            created = client.post(
                "/api/searches",
                json={"search_name": "range-resolution-smoke", "query": "widget"},
            )
            assert created.status_code == 200
            sid = created.json()["id"]
            try:
                searches = client.get("/api/searches").json()["searches"]
                row = next(s for s in searches if s["id"] == sid)
                assert row["price_min"] == 8.0
                assert row["price_max"] == 50.0
            finally:
                client.delete(f"/api/searches/{sid}")

    def test_invalid_stored_range_is_replaced_by_the_active_range(self):
        with _client() as client:
            client.put("/api/filters", json={"price_min": 8, "price_max": 50})
            created = client.post(
                "/api/searches",
                json={
                    "search_name": "range-resolution-invalid",
                    "query": "widget",
                    "price_min": 50,
                    "price_max": 10,
                },
            )
            assert created.status_code == 200
            sid = created.json()["id"]
            try:
                searches = client.get("/api/searches").json()["searches"]
                row = next(s for s in searches if s["id"] == sid)
                assert row["price_min"] == 8.0
                assert row["price_max"] == 50.0
            finally:
                client.delete(f"/api/searches/{sid}")
