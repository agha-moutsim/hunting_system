"""Phase E - which price comparisons earn a `price_alerts` row.

The phase rule is a refusal, not a formula: an alert must name the two values
it compared, and a missing price never generates one. These tests pin the
refusals first, because they are what keeps the inbox trustworthy - an inbox
that reports a change nobody measured is worse than an empty one.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import db.database as dbmod
from db.database import Base
from db.models import DemandSnapshot, PriceAlert, PriceHistory, TrackedProduct
from hunter.alerts import (
    AlertDecision,
    decide_alerts,
    generate_alerts,
    generate_for_monitored_queries,
    generate_for_product,
    generate_for_tracked_items,
)

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


# ---------------------------------------------------------------------------
# The generator: stored observations in, rows out
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    """A throwaway database wired into the factory the module opens for itself."""
    path = (tmp_path / "alerts.db").as_posix()
    engine = create_engine(f"sqlite:///{path}")
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "SessionLocal", factory)
    Base.metadata.create_all(engine)
    return factory


def _product(factory, name=TRACKED, target=0.0, alert_enabled=True):
    db = factory()
    try:
        row = TrackedProduct(
            product_name=name,
            ebay_url="https://www.ebay.co.uk/itm/167000000001",
            target_price=target,
            alert_enabled=alert_enabled,
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _reading(factory, product_id, price, minutes_ago):
    db = factory()
    try:
        db.add(
            PriceHistory(
                tracked_product_id=product_id,
                ebay_price=price,
                checked_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
            )
        )
        db.commit()
    finally:
        db.close()


def _snapshot(factory, query, avg_price, hours_ago):
    db = factory()
    try:
        db.add(
            DemandSnapshot(
                query=query,
                avg_price=avg_price,
                captured_at=datetime.utcnow() - timedelta(hours=hours_ago),
            )
        )
        db.commit()
    finally:
        db.close()


def _alerts(factory):
    db = factory()
    try:
        return [
            {
                "id": row.id,
                "alert_type": row.alert_type,
                "message": row.message,
                "old_price": row.old_price,
                "new_price": row.new_price,
                "is_read": row.is_read,
                "tracked_product_id": row.tracked_product_id,
            }
            for row in db.query(PriceAlert).order_by(PriceAlert.id).all()
        ]
    finally:
        db.close()


class TestTheTrackedItemLane:
    def test_two_real_readings_that_differ_write_one_row(self, session_factory):
        product_id = _product(session_factory)
        _reading(session_factory, product_id, 18.99, minutes_ago=10)
        _reading(session_factory, product_id, 15.49, minutes_ago=1)

        report = generate_for_tracked_items()

        assert report["products"] == 1
        assert report["comparisons"] == 1
        assert report["written"] == 1
        (row,) = _alerts(session_factory)
        assert row["alert_type"] == "price_drop"
        assert row["old_price"] == 18.99
        assert row["new_price"] == 15.49
        assert "£18.99" in row["message"] and "£15.49" in row["message"]
        assert row["is_read"] is False
        assert row["tracked_product_id"] == product_id

    def test_a_second_pass_writes_nothing(self, session_factory):
        """The tracker's inline check and the scheduled pass must not double up."""
        product_id = _product(session_factory)
        _reading(session_factory, product_id, 18.99, minutes_ago=10)
        _reading(session_factory, product_id, 15.49, minutes_ago=1)

        first = generate_for_tracked_items()
        second = generate_for_tracked_items()

        assert first["written"] == 1
        assert second["written"] == 0
        assert second["skipped"] == 1
        assert len(_alerts(session_factory)) == 1

    def test_a_new_reading_at_a_new_price_earns_a_new_row(self, session_factory):
        product_id = _product(session_factory)
        _reading(session_factory, product_id, 18.99, minutes_ago=10)
        _reading(session_factory, product_id, 15.49, minutes_ago=5)
        generate_for_tracked_items()

        _reading(session_factory, product_id, 12.00, minutes_ago=0)
        report = generate_for_tracked_items()

        assert report["written"] == 1
        rows = _alerts(session_factory)
        assert (rows[1]["old_price"], rows[1]["new_price"]) == (15.49, 12.00)

    def test_unread_readings_never_write_an_alert(self, session_factory):
        """0.0 is the tracker's 'could not read' - not a collapse to zero."""
        product_id = _product(session_factory)
        _reading(session_factory, product_id, 0.0, minutes_ago=10)
        _reading(session_factory, product_id, 0.0, minutes_ago=1)

        report = generate_for_tracked_items()

        assert report["written"] == 0
        assert report["comparisons"] == 0
        assert _alerts(session_factory) == []

    def test_a_single_reading_is_not_a_change(self, session_factory):
        product_id = _product(session_factory)
        _reading(session_factory, product_id, 18.99, minutes_ago=1)

        report = generate_for_tracked_items()

        assert report["written"] == 0
        assert report["comparisons"] == 0
        assert _alerts(session_factory) == []

    def test_a_target_hit_names_the_target_and_the_price(self, session_factory):
        product_id = _product(session_factory, target=16.00)
        _reading(session_factory, product_id, 15.49, minutes_ago=1)

        report = generate_for_tracked_items()

        assert report["written"] == 1
        (row,) = _alerts(session_factory)
        assert row["alert_type"] == "target_hit"
        assert row["old_price"] == 16.00  # the target
        assert row["new_price"] == 15.49  # the reading
        assert "£16.00" in row["message"] and "£15.49" in row["message"]

    def test_a_disabled_product_is_not_compared(self, session_factory):
        product_id = _product(session_factory, alert_enabled=False)
        _reading(session_factory, product_id, 18.99, minutes_ago=10)
        _reading(session_factory, product_id, 15.49, minutes_ago=1)

        report = generate_for_tracked_items()

        assert report["products"] == 0
        assert _alerts(session_factory) == []

    def test_a_disabled_product_is_left_alone_even_when_checked_by_hand(
        self, session_factory
    ):
        product_id = _product(session_factory, alert_enabled=False)
        _reading(session_factory, product_id, 18.99, minutes_ago=10)
        _reading(session_factory, product_id, 15.49, minutes_ago=1)

        report = generate_for_product(product_id)

        assert report["products"] == 1
        assert report["written"] == 0
        assert _alerts(session_factory) == []

    def test_a_missing_product_is_an_empty_report(self, session_factory):
        assert generate_for_product(999999) == {
            "products": 0,
            "comparisons": 0,
            "written": 0,
            "skipped": 0,
            "messages": [],
        }


class TestTheQueryLane:
    def test_two_real_average_readings_that_differ_write_one_row(self, session_factory):
        product_id = _product(session_factory, name="cordless drill")
        _snapshot(session_factory, "cordless drill", 25.00, hours_ago=5)
        _snapshot(session_factory, "cordless drill", 22.50, hours_ago=1)

        report = generate_for_monitored_queries()

        assert report["written"] == 1
        (row,) = _alerts(session_factory)
        assert row["alert_type"] == "price_drop"
        assert row["old_price"] == 25.00
        assert row["new_price"] == 22.50
        assert "average asking price" in row["message"]
        assert "£25.00" in row["message"] and "£22.50" in row["message"]
        assert row["tracked_product_id"] == product_id

    def test_the_target_is_not_applied_to_the_average(self, session_factory):
        """A target set for one listing cannot be compared to a market average."""
        _product(session_factory, name="cordless drill", target=30.00)
        _snapshot(session_factory, "cordless drill", 20.00, hours_ago=5)
        _snapshot(session_factory, "cordless drill", 20.00, hours_ago=1)

        assert generate_for_monitored_queries()["comparisons"] == 0

        _snapshot(session_factory, "cordless drill", 18.00, hours_ago=0)
        generate_for_monitored_queries()

        assert [row["alert_type"] for row in _alerts(session_factory)] == ["price_drop"]

    def test_unpriced_snapshots_are_not_readings(self, session_factory):
        _product(session_factory, name="cordless drill")
        _snapshot(session_factory, "cordless drill", None, hours_ago=5)
        _snapshot(session_factory, "cordless drill", 22.50, hours_ago=1)

        report = generate_for_monitored_queries()

        assert report["written"] == 0
        assert report["comparisons"] == 0
        assert _alerts(session_factory) == []

    def test_a_second_pass_writes_nothing(self, session_factory):
        _product(session_factory, name="cordless drill")
        _snapshot(session_factory, "cordless drill", 25.00, hours_ago=5)
        _snapshot(session_factory, "cordless drill", 22.50, hours_ago=1)

        generate_for_monitored_queries()
        second = generate_for_monitored_queries()

        assert second["written"] == 0
        assert second["skipped"] == 1
        assert len(_alerts(session_factory)) == 1


class TestTheWholePass:
    def test_generate_alerts_runs_both_lanes_and_reports_each(self, session_factory):
        product_id = _product(session_factory, name="cordless drill")
        _reading(session_factory, product_id, 18.99, minutes_ago=10)
        _reading(session_factory, product_id, 15.49, minutes_ago=1)
        _snapshot(session_factory, "cordless drill", 25.00, hours_ago=5)
        _snapshot(session_factory, "cordless drill", 22.50, hours_ago=1)

        report = generate_alerts()

        assert set(report) == {"tracked_items", "monitored_queries"}
        assert report["tracked_items"]["written"] == 1
        assert report["monitored_queries"]["written"] == 1
        assert len(_alerts(session_factory)) == 2


class TestTheTrackerCheckUsesTheSameRule:
    """The inline check and the scheduled pass write the same rows, or none.

    An earlier inline writer compared against a 50p threshold and built its
    own message; these tests pin that the check now goes through the one
    rule, so the inbox cannot contain two kinds of sentence about one price.
    """

    @staticmethod
    def _wire(monkeypatch, session_factory, price):
        from tracker import price_checker

        monkeypatch.setattr(price_checker, "SessionLocal", session_factory)
        monkeypatch.setattr(price_checker, "_fetch_ebay_price", lambda url: price)
        return price_checker

    def test_a_check_that_reads_a_new_price_writes_one_alert(
        self, session_factory, monkeypatch
    ):
        product_id = _product(session_factory)
        _reading(session_factory, product_id, 18.99, minutes_ago=10)
        price_checker = self._wire(monkeypatch, session_factory, 15.49)

        price = price_checker.check_single_price(product_id)

        assert price == 15.49
        (row,) = _alerts(session_factory)
        assert row["alert_type"] == "price_drop"
        assert (row["old_price"], row["new_price"]) == (18.99, 15.49)
        assert "item price" in row["message"]

    def test_a_check_that_could_not_read_a_price_keeps_the_inbox_silent(
        self, session_factory, monkeypatch
    ):
        product_id = _product(session_factory)
        _reading(session_factory, product_id, 18.99, minutes_ago=10)
        price_checker = self._wire(monkeypatch, session_factory, 0.0)

        assert price_checker.check_single_price(product_id) is None
        assert _alerts(session_factory) == []

    def test_a_small_move_is_still_a_move(self, session_factory, monkeypatch):
        """20p is a comparison with two real values; the old 50p threshold is gone."""
        product_id = _product(session_factory)
        _reading(session_factory, product_id, 15.49, minutes_ago=10)
        price_checker = self._wire(monkeypatch, session_factory, 15.29)

        price_checker.check_single_price(product_id)

        (row,) = _alerts(session_factory)
        assert (row["old_price"], row["new_price"]) == (15.49, 15.29)

    def test_a_second_check_at_the_same_price_writes_nothing(
        self, session_factory, monkeypatch
    ):
        product_id = _product(session_factory)
        _reading(session_factory, product_id, 18.99, minutes_ago=10)
        price_checker = self._wire(monkeypatch, session_factory, 15.49)
        price_checker.check_single_price(product_id)

        price_checker.check_single_price(product_id)

        assert len(_alerts(session_factory)) == 1

    def test_a_batch_check_reports_the_alert_it_wrote(
        self, session_factory, monkeypatch
    ):
        product_id = _product(session_factory)
        _reading(session_factory, product_id, 18.99, minutes_ago=10)
        price_checker = self._wire(monkeypatch, session_factory, 15.49)

        result = price_checker.check_all_prices()

        assert result == {"checked": 1, "alerts": 1, "errors": 0}
        assert len(_alerts(session_factory)) == 1
