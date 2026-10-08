r"""Goal 4 — Deep Search must carry the observations its own price tiles summarise.

Analyze has plotted the sold-price distribution since A3: `sold_prices` is
built by EbaySoldScraper._calculate_stats (ebay_sold.py:417) from the SAME
list that produced price_min/max/avg/median (ebay_sold.py:430ff), so the
chart and the tiles can never disagree. The Deep Search paths copied the
summary numbers across (deep_search.py:810-814 and 1092-1096) and dropped
the list itself — the run had the evidence and threw it away, leaving the
page able to assert a market shape it could not show.

Two things must therefore hold:

  1. both the full and the fast path transfer the list, and it survives
     to_dict(), which is asdict() and so only carries what the dataclass
     declares;
  2. the caption that will be drawn over it gets its OWN stamp. The count
     of observations is NOT `ebay_total_sold_30d`: that is len(items)
     (ebay_sold.py:430) while the list drops non-positive prices
     (ebay_sold.py:417), so the two quantities can differ. Labeling one
     with the other's provenance is exactly the C13 failure B3 removed.

SEAM: `_stub_deep_search` / `_stub_fast_path` are reused from
test_store_wiring, so both paths are exercised end-to-end offline rather
than by calling a private helper.
"""

import deep_search as ds
from engine.provenance import Provenance
from tests.test_store_wiring import (
    _sold_data,
    _stub_deep_search,
    _stub_fast_path,
)

# Matches the fixture's own price_min / price_max so the list and the
# summary numbers it is transferred beside describe the same run.
PRICES = [8.0, 9.99, 15.0]


def _priced_sold_data():
    data = _sold_data(top=True)
    data.sold_prices = list(PRICES)
    return data


class TestTheListIsCarriedNotJustTheSummary:
    def test_the_result_declares_it_and_serialises_it(self):
        result = ds.DeepSearchResult(product_name="widget")

        assert result.sold_prices == []
        # to_dict() is asdict(): a field that is not declared never reaches
        # the frontend, no matter what a caller sets on the instance.
        assert result.to_dict()["sold_prices"] == []

    def test_the_full_path_transfers_the_list(self, monkeypatch):
        _stub_deep_search(monkeypatch, _priced_sold_data())

        result = ds.deep_search_product("widget")

        assert result.sold_prices == PRICES
        assert result.to_dict()["sold_prices"] == PRICES
        # and it is the same evidence the summary numbers came from
        assert result.ebay_price_min == min(PRICES)
        assert result.ebay_price_max == max(PRICES)

    def test_the_fast_path_transfers_the_list_too(self, monkeypatch):
        """Fast is the Bulk path; it runs the same sold query and would
        drop the same evidence."""
        _stub_fast_path(monkeypatch, _priced_sold_data())

        result = ds.deep_search_fast("widget")

        assert result.sold_prices == PRICES

    def test_a_run_with_no_sold_data_carries_an_empty_list(self, monkeypatch):
        """Nothing observed means nothing to plot — never a synthetic
        distribution standing in for the one we failed to fetch."""
        _stub_deep_search(monkeypatch, _sold_data(top=False))

        result = ds.deep_search_product("widget")

        assert result.sold_prices == []


class TestTheCaptionCarriesItsOwnStamp:
    """C13 — the count on the chart is a different quantity from the
    30-day count, so it cannot borrow that field's stamp."""

    def test_observations_are_stamped_when_the_run_has_any(self, monkeypatch):
        from api.provenance_block import build_provenance_block

        _stub_deep_search(monkeypatch, _priced_sold_data())
        result = ds.deep_search_product("widget")

        fields = build_provenance_block(result.to_dict())["fields"]

        assert "sold_prices" in fields
        assert fields["sold_prices"]["provenance"] == Provenance.VERIFIED.value

    def test_a_run_holding_no_observations_is_stamped_unverified(
            self, monkeypatch):
        from api.provenance_block import build_provenance_block

        _stub_deep_search(monkeypatch, _sold_data(top=False))
        result = ds.deep_search_product("widget")

        fields = build_provenance_block(result.to_dict())["fields"]

        assert fields["sold_prices"]["provenance"] == Provenance.UNVERIFIED.value
        # an unverified stamp must always say why (C13)
        assert fields["sold_prices"].get("reason")

    def test_the_two_counts_are_stamped_independently(self, monkeypatch):
        """The case that would expose a borrowed stamp: real sold items
        with no positive price recorded, so the 30-day count is verified
        while the list the chart plots is empty. One entry must not drag
        the other's tier along with it."""
        from api.provenance_block import build_provenance_block

        data = _sold_data(top=True)
        data.sold_prices = []
        _stub_deep_search(monkeypatch, data)

        result = ds.deep_search_product("widget")
        fields = build_provenance_block(result.to_dict())["fields"]

        assert result.ebay_total_sold_30d > 0
        assert fields["ebay_total_sold_30d"]["provenance"] == (
            Provenance.VERIFIED.value
        )
        assert fields["sold_prices"]["provenance"] == (
            Provenance.UNVERIFIED.value
        )
