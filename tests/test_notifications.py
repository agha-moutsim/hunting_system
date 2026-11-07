"""C1 — a price-drop alert needs two real readings.

`check_price_drop` used to divide by `old_price` after only checking that it
was positive, and never checked `new_price` at all. An unread new price
(`None`) raised a TypeError; a zero new price produced a fabricated 100% drop.
"""

import pytest

from utils.notifications import Notifier


@pytest.fixture()
def notifier(tmp_path):
    return Notifier(filepath=str(tmp_path / "notifications.json"))


class TestPriceDropNeedsTwoReadings:
    def test_an_unread_new_price_raises_nothing(self, notifier):
        assert notifier.check_price_drop(1, "Drill", 20.0, None) is None
        assert notifier.get_all() == []

    def test_a_zero_new_price_is_not_a_100_percent_drop(self, notifier):
        assert notifier.check_price_drop(1, "Drill", 20.0, 0) is None
        assert notifier.get_all() == []

    def test_an_unread_old_price_is_not_a_baseline(self, notifier):
        assert notifier.check_price_drop(1, "Drill", None, 15.0) is None
        assert notifier.get_all() == []

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), "20.0", True])
    def test_a_non_price_is_ignored(self, notifier, bad):
        assert notifier.check_price_drop(1, "Drill", bad, 15.0) is None
        assert notifier.check_price_drop(1, "Drill", 20.0, bad) is None

    def test_a_real_drop_is_still_reported(self, notifier):
        notif_id = notifier.check_price_drop(1, "Drill", 20.0, 15.0)

        assert notif_id is not None
        (row,) = notifier.get_all()
        assert "£20.00" in row["message"]
        assert "£15.00" in row["message"]
        assert "25%" in row["message"]

    def test_a_small_change_is_not_an_alert(self, notifier):
        assert notifier.check_price_drop(1, "Drill", 20.0, 19.50) is None
