"""Phase E - which price comparisons earn a `price_alerts` row.

The phase rule is a refusal, not a formula: an alert must name the two values
it compared, and a missing price never generates one. These tests pin the
refusals first, because they are what keeps the inbox trustworthy - an inbox
that reports a change nobody measured is worse than an empty one.
"""

from hunter.alerts import AlertDecision, decide_alerts

TRACKED = "Cafe Du Monde Coffee"


class TestNoComparisonNoRow:
    def test_an_unread_latest_reading_yields_nothing(self):
        assert decide_alerts(18.99, None, label=TRACKED) == []

    def test_an_unread_previous_reading_yields_no_change_row(self):
        assert decide_alerts(None, 15.49, label=TRACKED) == []

    def test_a_zero_reading_is_an_unread_reading(self):
        """The tracker writes 0.0 when the page could not be read.

        Treating it as a price would invent a drop to zero - a collapse
        nothing measured.
        """
        assert decide_alerts(18.99, 0.0, label=TRACKED) == []
        assert decide_alerts(0.0, 18.99, label=TRACKED) == []

    def test_a_negative_reading_is_not_a_price(self):
        assert decide_alerts(18.99, -5.0, label=TRACKED) == []

    def test_a_garbage_reading_is_not_a_price(self):
        assert decide_alerts(18.99, "eighteen", label=TRACKED) == []

    def test_an_unchanged_price_yields_nothing(self):
        assert decide_alerts(18.99, 18.99, label=TRACKED) == []

    def test_float_noise_within_the_penny_is_not_a_change(self):
        """Prices are compared at the precision the app shows and charges in."""
        assert decide_alerts(18.994, 18.993, label=TRACKED) == []

    def test_no_target_means_no_target_row(self):
        decisions = decide_alerts(18.99, 15.49, label=TRACKED)
        assert [d.alert_type for d in decisions] == ["price_drop"]


class TestAChangeNamesBothValues:
    def test_a_drop_names_the_previous_and_the_latest(self):
        (decision,) = decide_alerts(18.99, 15.49, label=TRACKED)

        assert isinstance(decision, AlertDecision)
        assert decision.alert_type == "price_drop"
        assert decision.old_price == 18.99
        assert decision.new_price == 15.49
        assert "£18.99" in decision.message
        assert "£15.49" in decision.message
        assert "dropped" in decision.message
        assert TRACKED in decision.message

    def test_a_rise_is_its_own_type_and_says_rose(self):
        (decision,) = decide_alerts(15.49, 18.99, label=TRACKED)

        assert decision.alert_type == "price_increase"
        assert decision.old_price == 15.49
        assert decision.new_price == 18.99
        assert "rose" in decision.message

    def test_the_message_says_what_kind_of_price_it_compared(self):
        """A query average and an item price are different facts, and the row
        has to say which one moved."""
        (decision,) = decide_alerts(
            21.40, 21.86, label="cordless drill", price_label="average asking price"
        )

        assert "average asking price" in decision.message
        assert "21.40" in decision.message and "21.86" in decision.message

    def test_prices_are_reported_at_the_penny(self):
        (decision,) = decide_alerts(18.994, 15.494, label=TRACKED)

        assert decision.old_price == 18.99
        assert decision.new_price == 15.49
        assert "£18.99" in decision.message
        assert "£15.49" in decision.message


class TestTheTargetIsAComparisonToo:
    def test_a_price_at_or_below_the_target_names_target_and_price(self):
        # The same reading also earned its change row; select the target one.
        decisions = decide_alerts(18.99, 15.49, label=TRACKED, target=16.00)
        (decision,) = [d for d in decisions if d.alert_type == "target_hit"]

        assert decision.alert_type == "target_hit"
        assert decision.old_price == 16.00  # the target
        assert decision.new_price == 15.49  # the reading
        assert "£15.49" in decision.message
        assert "£16.00" in decision.message
        assert "target" in decision.message

    def test_equalling_the_target_counts_as_hitting_it(self):
        decisions = decide_alerts(18.99, 16.00, label=TRACKED, target=16.00)

        assert [d.alert_type for d in decisions] == ["price_drop", "target_hit"]
        assert decisions[1].new_price == 16.00

    def test_a_price_above_the_target_is_not_a_target_row(self):
        decisions = decide_alerts(18.99, 17.50, label=TRACKED, target=16.00)

        assert [d.alert_type for d in decisions] == ["price_drop"]

    def test_an_unread_target_is_no_target(self):
        """A target that was never set is not a target of zero."""
        decisions = decide_alerts(18.99, 15.49, label=TRACKED, target=None)
        zero_target = decide_alerts(18.99, 15.49, label=TRACKED, target=0.0)

        assert [d.alert_type for d in decisions] == ["price_drop"]
        assert [d.alert_type for d in zero_target] == ["price_drop"]

    def test_the_target_comparison_does_not_need_a_previous_reading(self):
        """The first reading of an item can already be below the target: the
        comparison is price vs target, and both are real."""
        (decision,) = decide_alerts(None, 15.49, label=TRACKED, target=16.00)

        assert decision.alert_type == "target_hit"
        assert decision.new_price == 15.49

    def test_an_unread_latest_reading_kills_the_target_row_too(self):
        assert decide_alerts(18.99, None, label=TRACKED, target=16.00) == []
        assert decide_alerts(None, 0.0, label=TRACKED, target=16.00) == []

    def test_one_reading_can_earn_both_rows(self):
        decisions = decide_alerts(18.99, 15.49, label=TRACKED, target=16.00)

        assert [d.alert_type for d in decisions] == ["price_drop", "target_hit"]

    def test_the_target_label_can_say_what_it_is(self):
        (decision,) = decide_alerts(
            None, 15.49, label=TRACKED, target=16.00, target_label="buy-below price"
        )

        assert "buy-below price" in decision.message
