"""C1 — the scorecard never turns an unread figure into a measured one.

Both defects here were found by reading the code: the demand block printed
`sold_count_7d or 0`, so an unread seven-day count became a measured zero,
and the block was gated on the 30-day count, so a real 7-day figure vanished
whenever the 30-day reading was missing.
"""

from engine.decisions import Verdict
from engine.scorecard import format_scorecard
from scrapers.base import DemandData, ScrapedProduct


def _product(**kw):
    base = dict(
        source="ebay_uk",
        title="Greenhouse 6ft",
        price=30.00,
        url="https://www.ebay.co.uk/itm/1",
        condition="New",
        verified=True,
    )
    base.update(kw)
    return ScrapedProduct(**base)


def _card(demand):
    return format_scorecard(_product(), [], demand, Verdict(verdict="pending"))


def _line(card, label):
    return next(line for line in card.splitlines() if label in line)


class TestSoldCountsStayAbsentWhenUnread:
    def test_an_unread_7d_count_is_not_a_zero(self):
        card = _card(DemandData(sold_count_30d=40, sold_count_7d=None))

        assert "not read" in _line(card, "Sold (7d)")
        assert "Sold (7d):  0" not in card

    def test_a_known_7d_count_survives_a_missing_30d_count(self):
        card = _card(DemandData(sold_count_30d=None, sold_count_7d=12))

        assert "12" in _line(card, "Sold (7d)")
        assert "not read" in _line(card, "Sold (30d)")

    def test_a_measured_zero_is_still_printed(self):
        card = _card(DemandData(sold_count_30d=0, sold_count_7d=0))

        assert _line(card, "Sold (30d)").endswith(" 0")
        assert _line(card, "Sold (7d)").endswith(" 0")

    def test_no_demand_row_still_says_there_is_no_data(self):
        card = _card(None)

        assert "No sold data available" in card
