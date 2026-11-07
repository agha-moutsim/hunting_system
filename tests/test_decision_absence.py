"""C1 — the decision engine does not price a zero supplier cost.

Supplier scrapers use 0 for "price not read". `evaluate` passed that straight
into the fee engine, which treats it as a real cost of nothing: the margin row
was marked verified and the verdict quoted a profit for a free item.
"""

import pytest

from engine.decisions import DecisionEngine
from scrapers.base import DemandData, ScrapedProduct


@pytest.fixture(autouse=True)
def _pristine_range(monkeypatch, tmp_path):
    """Run against the config defaults regardless of the repo's live state."""
    import json

    import utils.filters as uf

    target = tmp_path / "custom_filters.json"
    target.write_text(json.dumps({"active": {}, "presets": {}}))
    monkeypatch.setattr(uf, "FILTERS_FILE", target)
    uf._cache["mtime"] = None
    uf._cache["data"] = None
    yield
    uf._cache["mtime"] = None
    uf._cache["data"] = None


def _product():
    return ScrapedProduct(
        source="ebay_uk",
        title="Greenhouse 6ft",
        price=20.00,
        url="https://www.ebay.co.uk/itm/1",
        condition="New",
        verified=True,
    )


def _demand():
    return DemandData(sold_count_30d=40, sold_count_7d=12, verified=True)


def _margin(verdict):
    return next(row for row in verdict.filters if row.name == "Margin")


class TestASupplierPriceOfZeroIsUnread:
    @pytest.mark.parametrize("placeholder", [0, 0.0, -5.0, float("nan")])
    def test_a_placeholder_is_treated_as_absent(self, placeholder):
        verdict = DecisionEngine().evaluate(_product(), _demand(), placeholder)

        assert _margin(verdict).verified is False
        assert verdict.profit_computed is False

    def test_a_real_price_still_computes(self):
        verdict = DecisionEngine().evaluate(_product(), _demand(), 8.0)

        assert _margin(verdict).verified is True
        assert verdict.profit_computed is True
        assert verdict.profit > 0
