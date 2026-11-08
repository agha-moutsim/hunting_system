"""C1 — an unread competitor-store average is absent, not GBP 0.00.

`build_stores` used to coerce every average with `float(avg or 0.0)` and
round it, so a seller whose listings carried no readable price exported
`avg_price: 0.0` — a number that says their stock is free.
"""

from types import SimpleNamespace

from engine.stores import build_stores, stores_from_products


class TestUnreadAverageIsAbsent:
    def test_a_zero_average_is_absent(self):
        row = build_stores([("shop", 3, 0.0)])[0]

        assert row["avg_price"] is None

    def test_a_negative_average_is_absent(self):
        row = build_stores([("shop", 3, -5.0)])[0]

        assert row["avg_price"] is None

    def test_a_real_average_survives(self):
        row = build_stores([("shop", 3, 12.5)])[0]

        assert row["avg_price"] == 12.5

    def test_products_without_a_price_do_not_average_to_zero(self):
        rows = stores_from_products(
            [
                SimpleNamespace(seller="shop", price=0.0),
                SimpleNamespace(seller="shop", price=0.0),
            ]
        )

        assert rows[0]["avg_price"] is None

    def test_a_merge_keeps_the_one_reading_it_has(self):
        # First spelling carried no price; the second did. The merged row can
        # claim the reading that exists, and must not average it with zero.
        row = build_stores([("Store", 4, 0.0), ("store", 4, 20.0)])[0]

        assert row["avg_price"] == 20.0

    def test_two_readings_still_average(self):
        row = build_stores([("Store", 4, 10.0), ("store", 4, 20.0)])[0]

        assert row["avg_price"] == 15.0
