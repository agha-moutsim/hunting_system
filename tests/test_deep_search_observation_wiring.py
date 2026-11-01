"""Deep Search runs save the observations they read."""


from __future__ import annotations

import types
from unittest.mock import patch

from backend.deep_search import deep_search_fast


class _SoldData:
    def __init__(self):
        self.items = [
            types.SimpleNamespace(
                title="Widget",
                price=12.5,
                url="https://www.ebay.co.uk/itm/123456789012",
                seller="seller1",
                condition="New",
            )
        ]
        self.total_sold_30d = 12
        self.total_sold_7d = 3
        self.price_min = 12.5
        self.price_max = 12.5
        self.price_avg = 12.5
        self.price_median = 12.5
        self.top_sellers = []
        self.sold_prices = [12.5]
        self.active_prices = []
        self.excluded_over_band = 0
        self._band_used = (0.99, 50.0)


def test_deep_search_fast_saves_observations(monkeypatch):
    monkeypatch.setattr(
        "backend.deep_search._sold_scraper",
        lambda market: types.SimpleNamespace(
            get_sold_data=lambda query, **kwargs: _SoldData()
        ),
    )
    monkeypatch.setattr(
        "backend.deep_search._discover_approved_suppliers",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "backend.deep_search._verify_supplier_candidates",
        lambda *args, **kwargs: [],
    )

    calls = []
    monkeypatch.setattr(
        "backend.deep_search._save_deep_search_observations",
        lambda market, query, sold_data: calls.append((market["id"], query)),
    )

    result = deep_search_fast("widget")

    assert result.marketplace == "EBAY_GB"
    assert calls == [("EBAY_GB", "widget")]