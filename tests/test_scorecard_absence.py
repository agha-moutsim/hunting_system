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


class TestUnreadSupplierPriceIsNotFree:
    def _supplier(self, price):
        return _product(
            title="Greenhouse supplier",
            price=price,
            url="https://www.aliexpress.com/item/1",
        )

    def _card_with(self, price):
        return format_scorecard(
            _product(), [self._supplier(price)], DemandData(), Verdict(verdict="pending")
        )

    def test_a_zero_supplier_price_is_not_printed_as_money(self):
        card = self._card_with(0.0)

        assert "(price not read)" in _line(card, "Greenhouse supplier")
        assert "not read" in _line(card, "Supplier price:")
        assert "not computed" in _line(card, "Profit:")

    def test_a_negative_supplier_price_is_not_a_cost(self):
        card = self._card_with(-5.0)

        assert "not computed" in _line(card, "Profit:")

    def test_a_real_supplier_price_still_computes(self):
        card = format_scorecard(
            _product(),
            [self._supplier(6.0)],
            DemandData(),
            Verdict(verdict="pass", profit=4.0, margin=15.0, profit_computed=True),
        )

        assert "£6.00" in _line(card, "Supplier price:")
        # The card quotes the fee engine's own figures, not the verdict's
        # fields: this verdict carries stale placeholders from another sale.
        assert "£17.85" in _line(card, "Profit:")
        assert "59.5%" in _line(card, "Margin:")

    def test_a_verdict_without_figures_does_not_print_a_zero_profit(self):
        # A Verdict built without pricing the sale carries 0.0 placeholders.
        # With a real supplier price the engine does compute, and the card
        # must print that measurement rather than the placeholder zero.
        card = format_scorecard(
            _product(), [self._supplier(6.0)], DemandData(), Verdict(verdict="pending")
        )

        assert "£17.85" in _line(card, "Profit:")
        assert "£0.00" not in _line(card, "Profit:")


class TestAbsentFinalVerdict:
    def test_a_blank_verdict_reads_not_recorded(self):
        card = format_scorecard(_product(), [], None, Verdict(verdict=""))

        assert "VERDICT: NOT RECORDED" in card
        assert "VERDICT: \n" not in card


class TestAnUncheckedGatingRowIsNotADecision:
    """C13 — a rule nobody checked must not wear PASS or FAIL.

    With no demand data the engine leaves the "Demand (30d)" row unverified
    and holds the verdict at pending. The written card used to stamp the row
    [FAIL], so one run read as a failed rule in the stored scorecard and as
    "Unverified" in the live filter list.
    """

    @staticmethod
    def _card(product=None, demand=None, supplier_price=6.0):
        from engine.decisions import DecisionEngine

        product = product or _product()
        verdict = DecisionEngine().evaluate(product, demand, supplier_price)
        return format_scorecard(product, [], demand, verdict)

    def test_an_unread_demand_row_is_unverified_not_failed(self):
        line = _line(self._card(demand=None), "Demand (30d)")

        assert "[UNVERIFIED]" in line
        assert "[FAIL]" not in line
        assert "[PASS]" not in line

    def test_a_brand_we_never_checked_is_not_a_pass(self):
        # No brand name means the VeRO check never ran; the row is not a pass.
        line = _line(self._card(demand=DemandData()), "Brand")

        assert "[UNVERIFIED]" in line
        assert "[PASS]" not in line

    def test_verified_rows_keep_their_pass_and_fail(self):
        card = self._card(product=_product(price=35.01), demand=DemandData())

        assert "[FAIL]" in _line(card, "Price:")
        assert "[PASS]" in _line(card, "Condition")
