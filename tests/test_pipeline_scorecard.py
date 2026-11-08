"""C1 — the pipeline's terminal scorecard does not print unread money as zero.

`calculate_profit` returns None for a figure it could not measure. The
scorecard filled those with `.get(key, 0)` and formatted them as GBP 0.00.
"""

from types import SimpleNamespace

from pipeline import Pipeline, PipelineResult


def _product(price=20.0):
    return SimpleNamespace(title="Greenhouse 6ft", price=price)


def _analysis():
    return SimpleNamespace(
        brand_verdict="unknown",
        brand_reasoning="",
        demand_assessment="",
        demand_reasoning="",
        recommended_action="",
        risk_flags=[],
    )


def _card(profit, price=20.0):
    result = PipelineResult()
    result.verdict = {"verdict": "pending", "filters": []}
    result.profit = profit
    return Pipeline.__new__(Pipeline)._build_scorecard(
        _product(price), None, _analysis(), result
    )


def _line(card, label):
    return next(line for line in card.splitlines() if line.strip().startswith(label))


class TestUnmeasuredProfitIsNotZero:
    def test_a_missing_supplier_cost_is_not_printed_as_zero(self):
        card = _card(
            {
                "supplier_price": None,
                "ebay_fee": 2.50,
                "returns_buffer": 1.00,
                "profit": None,
                "margin": None,
            }
        )

        assert "not computed" in _line(card, "Supplier:")
        assert "not computed" in _line(card, "Net profit:")
        assert "not computed" in _line(card, "Margin:")
        assert "GBP 0.00" not in card

    def test_measured_figures_still_print(self):
        card = _card(
            {
                "supplier_price": 8.00,
                "ebay_fee": 2.50,
                "returns_buffer": 1.00,
                "profit": 6.50,
                "margin": 32.5,
            }
        )

        assert "GBP 8.00" in _line(card, "Supplier:")
        assert "GBP 6.50" in _line(card, "Net profit:")
        assert "32.5%" in _line(card, "Margin:")

    def test_an_unread_product_price_is_not_zero(self):
        card = _card(None, price=0)

        assert "(not read)" in _line(card, "eBay Price:")
        assert "GBP 0.00" not in card
