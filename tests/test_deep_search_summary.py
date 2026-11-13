"""C1 — the Deep Search text summary does not print unread money as zero.

`DeepSearchResult` defaults every price to 0.0. `summary()` formatted those
defaults as currency, so a run with no eBay average and no supplier price read
reported "$0.00" for both.
"""

from deep_search import DeepSearchResult


def _line(text, label):
    return next(line for line in text.splitlines() if label in line)


class TestSummaryKeepsUnreadPricesUnread:
    def test_an_unread_ebay_average_is_not_zero(self):
        result = DeepSearchResult(
            product_name="Widget", currency="AUD", currency_symbol="A$"
        )

        text = result.summary()

        assert "not read" in _line(text, "eBay avg price")
        assert "A$0.00" not in text

    def test_a_supplier_with_no_price_says_so(self):
        result = DeepSearchResult(
            currency="AUD",
            currency_symbol="A$",
            suppliers=[{"name": "CJ", "price": 0, "url": "x"}],
        )

        text = result.summary()

        assert "CJ | not read" in text
        assert "A$0.00" not in text

    def test_a_zero_best_cost_is_not_computed(self):
        result = DeepSearchResult(
            currency="AUD", currency_symbol="A$", best_supplier_price=0.0
        )

        assert "Best supplier cost: Not computed" in result.summary()

    def test_real_prices_still_print(self):
        result = DeepSearchResult(
            currency="AUD",
            currency_symbol="A$",
            ebay_avg_price=83.9,
            suppliers=[{"name": "CJ", "price": 41.2, "url": "x"}],
            best_supplier_price=41.2,
        )

        text = result.summary()

        assert "A$83.90" in _line(text, "eBay avg price")
        assert "CJ | A$41.20" in text
        assert "Best supplier cost: A$41.20" in text


class TestSummaryKeepsAnAbsentVerdictAbsent:
    def test_an_empty_verdict_is_not_a_blank_line(self):
        result = DeepSearchResult(product_name="Widget")

        assert "Verdict: NOT RECORDED" in result.summary()
        assert "Verdict: \n" not in result.summary()

    def test_a_stored_verdict_still_prints(self):
        result = DeepSearchResult(verdict="pass")

        assert "Verdict: PASS" in result.summary()
