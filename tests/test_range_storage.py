"""Range-storage tests — amended PR-6/PR-7 range semantics.

Tracker/watchlist store any price; rows outside the active range are
flagged `outside_band` and list endpoints accept price_min/price_max
view-filter params (default = active range from utils.filters).
"""

from types import SimpleNamespace


class TestClientMixin:
    @staticmethod
    def _client():
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)


class TestWatchlistStoresAnyPrice(TestClientMixin):
    def test_create_at_40_succeeds_and_is_flagged_outside_band(self):
        with self._client() as client:
            resp = client.post("/api/watchlist", json={
                "product_name": "range-storage-watchlist-high",
                "ebay_price": 40.0,
                "ebay_url": "https://www.ebay.co.uk/itm/range-storage-high",
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body["outside_band"] is True

            wide = client.get("/api/watchlist", params={"price_min": 1, "price_max": 100})
            row = next(
                i for i in wide.json()["items"]
                if i["product_name"] == "range-storage-watchlist-high"
            )
            assert row["ebay_price"] == 40.0
            assert row["outside_band"] is True

            assert client.delete(f"/api/watchlist/{body['id']}").status_code == 200

    def test_create_at_12_succeeds_and_is_not_flagged(self):
        with self._client() as client:
            resp = client.post("/api/watchlist", json={
                "product_name": "range-storage-watchlist-mid",
                "ebay_price": 12.0,
                "ebay_url": "https://www.ebay.co.uk/itm/range-storage-mid",
            })
            assert resp.status_code == 200
            assert resp.json()["outside_band"] is False

            item_id = resp.json()["id"]
            assert client.delete(f"/api/watchlist/{item_id}").status_code == 200

    def test_default_view_hides_rows_outside_the_active_range(self):
        with self._client() as client:
            created = client.post("/api/watchlist", json={
                "product_name": "range-storage-watchlist-default",
                "ebay_price": 40.0,
                "ebay_url": "https://www.ebay.co.uk/itm/range-storage-default",
            }).json()

            default_view = client.get("/api/watchlist").json()
            assert "range_filter" in default_view
            names = [i["product_name"] for i in default_view["items"]]
            assert "range-storage-watchlist-default" not in names

            assert client.delete(f"/api/watchlist/{created['id']}").status_code == 200


class TestTrackerStoresAnyPrice(TestClientMixin):
    def test_create_at_40_succeeds_and_is_flagged_outside_band(self):
        with self._client() as client:
            resp = client.post("/api/tracker", json={
                "product_name": "range-storage-tracker-high",
                "ebay_price": 40.0,
                "ebay_url": "https://www.ebay.co.uk/itm/range-storage-tracker-high",
            })
            assert resp.status_code == 200
            assert resp.json()["outside_band"] is True

            wide = client.get("/api/tracker", params={"price_min": 1, "price_max": 100})
            row = next(
                p for p in wide.json()["products"]
                if p["product_name"] == "range-storage-tracker-high"
            )
            assert row["ebay_price"] == 40.0
            assert row["outside_band"] is True

            assert client.delete(f"/api/tracker/{resp.json()['id']}").status_code == 200

    def test_create_at_12_succeeds_and_is_not_flagged(self):
        with self._client() as client:
            resp = client.post("/api/tracker", json={
                "product_name": "range-storage-tracker-mid",
                "ebay_price": 12.0,
                "ebay_url": "https://www.ebay.co.uk/itm/range-storage-tracker-mid",
            })
            assert resp.status_code == 200
            assert resp.json()["outside_band"] is False

            assert client.delete(f"/api/tracker/{resp.json()['id']}").status_code == 200


class TestViewFilterParams(TestClientMixin):
    def test_watchlist_price_range_params_filter_rows(self):
        with self._client() as client:
            high = client.post("/api/watchlist", json={
                "product_name": "range-storage-filter-high",
                "ebay_price": 40.0,
                "ebay_url": "https://www.ebay.co.uk/itm/range-storage-filter-high",
            }).json()
            inside = client.post("/api/watchlist", json={
                "product_name": "range-storage-filter-in",
                "ebay_price": 8.0,
                "ebay_url": "https://www.ebay.co.uk/itm/range-storage-filter-in",
            }).json()

            resp = client.get("/api/watchlist", params={"price_min": 5, "price_max": 10})
            assert resp.status_code == 200
            payload = resp.json()
            assert payload["range_filter"] == {"min": 5, "max": 10}
            names = [i["product_name"] for i in payload["items"]]
            assert "range-storage-filter-high" not in names
            assert "range-storage-filter-in" in names

            assert client.delete(f"/api/watchlist/{high['id']}").status_code == 200
            assert client.delete(f"/api/watchlist/{inside['id']}").status_code == 200

    def test_tracker_price_range_params_filter_rows(self):
        with self._client() as client:
            high = client.post("/api/tracker", json={
                "product_name": "range-storage-filter-tracker-high",
                "ebay_price": 40.0,
                "ebay_url": "https://www.ebay.co.uk/itm/range-storage-filter-tracker-high",
            }).json()

            resp = client.get("/api/tracker", params={"price_min": 5, "price_max": 10})
            assert resp.status_code == 200
            payload = resp.json()
            assert payload["range_filter"] == {"min": 5, "max": 10}
            names = [p["product_name"] for p in payload["products"]]
            assert "range-storage-filter-tracker-high" not in names

            assert client.delete(f"/api/tracker/{high['id']}").status_code == 200


class TestRunnerSupplierPricesAreNeverGated:
    def test_out_of_band_supplier_price_still_stores_a_result(self, monkeypatch):
        import deep_search
        from watchlist import delete_search, get_new_results, run_search, save_search

        fake = SimpleNamespace(
            product_name="range-storage-runner",
            ebay_avg_price=8.0,
            best_supplier_price=50.0,
            margin=30.0,
            profit=5.0,
            verdict="pass",
            sources=["https://www.ebay.co.uk/itm/range-storage-runner"],
            suppliers=[{"name": "pricey supplier", "price": 50.0, "url": "https://supplier.example"}],
        )
        monkeypatch.setattr(deep_search, "deep_search_fast", lambda query: fake)

        search = save_search(
            search_name="range-storage-runner-search",
            query="generic widget",
            auto_run=False,
        )
        try:
            outcome = run_search(search.id)
            assert outcome["found"] == 1

            rows = get_new_results(unread_only=True)
            row = next(r for r in rows if r["search_name"] == "range-storage-runner-search")
            assert row["ebay_price"] == 8.0
            assert row["supplier_price"] == 50.0
            assert row["outside_band"] is False
        finally:
            delete_search(search.id)
