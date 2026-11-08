"""C1 — a comma in an imported price is a thousands separator, not noise.

`_parse_money` stripped every comma, so "1,23" became 123: a price ten times
the one in the file. Only a correctly grouped number may carry a comma now.
"""

import pytest

from api.sales import _parse_money


class TestGroupedThousands:
    def test_a_grouped_number_is_accepted(self):
        assert _parse_money("1,234.56", "sale_price", allow_zero=False) == 1234.56

    def test_a_grouped_number_without_pence_is_accepted(self):
        assert _parse_money("1,234", "sale_price", allow_zero=False) == 1234.0

    def test_a_pound_sign_and_groups_are_accepted(self):
        assert _parse_money("£1,234.50", "sale_price", allow_zero=False) == 1234.50

    def test_an_ungrouped_number_is_still_accepted(self):
        assert _parse_money("1234.56", "sale_price", allow_zero=False) == 1234.56

    @pytest.mark.parametrize("bad", ["1,23", "12,34", "1,2345", "1,23.45"])
    def test_an_ambiguous_comma_is_refused_not_reinterpreted(self, bad):
        with pytest.raises(ValueError, match="ambiguous thousands separator"):
            _parse_money(bad, "sale_price", allow_zero=False)

    def test_a_negative_grouped_number_still_says_it_is_negative(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            _parse_money("-1,234.50", "sale_price", allow_zero=True)
