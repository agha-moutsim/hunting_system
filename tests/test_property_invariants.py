"""Property-based invariants for the rules that decide money and truth.

The example tests elsewhere pin down specific numbers. These pin down the
rules: the properties that must hold for EVERY input, including the ones
nobody thought to write a test case for. A margin that drifts above 100%, a
profit that goes UP when the supplier gets more expensive, or a trend that
reports a slope from a single observation would each sail past a table of
hand-picked cases and fail a real product.

Hypothesis is already in the environment; these run offline and fast.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from engine.profit import calculate_profit
from hunter.demand_monitor import compute_trend

# Positive prices, sane magnitudes for a £5-£35 band product, but wide enough
# to cross every fee threshold and both sides of zero profit.
_money = st.floats(min_value=0.01, max_value=5000.0, allow_nan=False, allow_infinity=False)


class TestProfitProperties:
    @given(ebay=_money, supplier=_money, other=_money)
    @settings(max_examples=200, deadline=None)
    def test_a_dearer_supplier_never_raises_profit(self, ebay, supplier, other):
        """The invariant that matters: paying more can never make the profit
        go UP.

        Two precisions, because profit is a currency figure rounded to the
        penny. Within half a penny the two are simply the same displayed
        number - Hypothesis found a GBP0.0039 supplier difference rendering
        as -0.19 either way - so the strict decrease is asserted only once
        the gap is worth a penny. The non-increase holds at every scale.
        """
        cheap = calculate_profit(ebay, supplier)["profit"]
        dear = calculate_profit(ebay, other)["profit"]
        assume(other > supplier)

        assert dear <= cheap + 0.005, "a dearer supplier raised the profit"
        if round(other, 2) - round(supplier, 2) >= 0.01:
            assert dear < cheap, "a penny-dearer supplier did not lower the profit"

    @given(ebay=_money, supplier=_money, shipping=_money)
    @settings(max_examples=200, deadline=None)
    def test_postage_is_subtracted_exactly_once(self, ebay, supplier, shipping):
        """Postage is a real cost: it comes off by exactly its own amount, and
        it never gets counted twice.

        Compared to the penny, not to the last bit. Both profits are rounded
        to 2dp for display, and binary floats cannot represent 4.65 or 3.65
        exactly - `4.65 - 3.65` is 1.0000000000000004. Demanding bit-exact
        equality here would be testing IEEE 754, not the money rule. A
        discrepancy of more than a penny WOULD be a real double-count, which
        is what the Hypothesis search below is for: it found a £0.004 postage
        reading being subtracted, printed as £0.00, and still stamped
        shipping_known - a profit a penny below the sum of its printed parts.
        """
        without = calculate_profit(ebay, supplier)["profit"]
        with_shipping = calculate_profit(ebay, supplier, shipping_cost=shipping)["profit"]
        assert abs((without - with_shipping) - round(shipping, 2)) <= 0.01

    @given(ebay=_money, supplier=_money)
    @settings(max_examples=200, deadline=None)
    def test_a_penny_of_postage_never_moves_the_profit_by_more_than_a_penny(self, ebay, supplier):
        """The regression this file exists for: whatever postage is read, the
        printed profit and the printed postage must not disagree by more than
        the rounding penny. A figure that displays as £0.00 cannot have moved
        the profit at all."""
        base = calculate_profit(ebay, supplier)
        for postage in (0.004, 0.001, 0.0, 0.005):
            result = calculate_profit(ebay, supplier, shipping_cost=postage)
            moved = base["profit"] - result["profit"]
            assert abs(moved - result["shipping_cost"]) <= 0.01
            if result["shipping_cost"] == 0.0:
                assert moved == 0.0, "an unread postage reading moved the profit"

    @given(ebay=_money, supplier=_money)
    @settings(max_examples=200, deadline=None)
    def test_margin_never_exceeds_the_sale_price(self, ebay, supplier):
        """Costs are never negative, so the margin cannot exceed 100% - a
        margin above 100% is the classic sign of a double-counted fee."""
        assert calculate_profit(ebay, supplier)["margin"] <= 100.0

    @given(ebay=_money, supplier=_money)
    @settings(max_examples=100, deadline=None)
    def test_unread_postage_is_never_reported_as_complete(self, ebay, supplier):
        result = calculate_profit(ebay, supplier, shipping_cost=0.0)
        assert result["shipping_known"] is False
        assert result["profit_is_complete"] is False

    @given(ebay=_money, supplier=_money, shipping=_money)
    @settings(max_examples=200, deadline=None)
    def test_known_postage_makes_the_figure_complete(self, ebay, supplier, shipping):
        """A positive postage reading is real, so the profit is then whole."""
        result = calculate_profit(ebay, supplier, shipping_cost=shipping)
        assert result["shipping_known"] is True
        assert result["profit_is_complete"] is True

    @given(ebay=_money, supplier=_money)
    @settings(max_examples=200, deadline=None)
    def test_zero_and_negative_postage_are_both_unread(self, ebay, supplier):
        """0.0 is the 'we did not read one' sentinel; a negative figure is
        nonsense, and neither may be quietly turned into free postage."""
        for bad in (0.0, -1.0, -99.9):
            result = calculate_profit(ebay, supplier, shipping_cost=bad)
            assert result["shipping_known"] is False
            assert result["shipping_cost"] == 0.0


# A snapshot is (hours-after-base, sold_30d or None).
_points = st.lists(
    st.tuples(
        st.floats(min_value=0.0, max_value=24 * 60, allow_nan=False),
        st.one_of(st.none(), st.integers(min_value=0, max_value=100000)),
    ),
    min_size=0,
    max_size=12,
)


# Hypothesis builds timestamps as offsets from this base. `now` is pinned to
# well after the largest offset the strategy can generate (60 days), so these
# tests exercise the trend maths rather than tripping the staleness window -
# which has its own tests, because staleness is a rule and not an accident.
_BASE = datetime(2026, 1, 1)
_NOW = _BASE + timedelta(days=90)


def _snaps(points):
    base = _BASE
    rows = [
        SimpleNamespace(sold_30d=s30, captured_at=base + timedelta(hours=h))
        for h, s30 in points
    ]
    rows.sort(key=lambda r: r.captured_at)
    return rows


class TestTrendProperties:
    @given(points=_points)
    @settings(max_examples=300, deadline=None)
    def test_unverified_never_carries_a_number(self, points):
        """The whole point of the module: no data, no number. Whenever the
        trend is unverified there must be no pace to quote."""
        result = compute_trend(_snaps(points), now=_NOW, min_span_hours=24.0)
        if result["provenance"] == "unverified":
            assert result["pace_7d"] is None
            assert result["hot"] is False
            assert result["reason"]

    @given(points=_points)
    @settings(max_examples=300, deadline=None)
    def test_a_verified_trend_always_shows_its_endpoints(self, points):
        """A number the user cannot audit is a number they must not be given."""
        result = compute_trend(_snaps(points), now=_NOW, min_span_hours=24.0)
        if result["provenance"] == "verified":
            assert result["first"]["sold_30d"] is not None
            assert result["last"]["sold_30d"] is not None
            assert result["window_days"] and result["window_days"] > 0

    @given(points=st.lists(st.tuples(st.just(0.0), st.integers(min_value=0, max_value=1000)), min_size=1, max_size=8))
    @settings(max_examples=100, deadline=None)
    def test_points_at_the_same_instant_are_never_a_trend(self, points):
        """Every observation at one timestamp has a span of zero, so there is
        no slope to call - however many of them there are."""
        result = compute_trend(_snaps(points), now=_NOW, min_span_hours=24.0)
        assert result["provenance"] == "unverified"
        assert result["pace_7d"] is None

    @given(
        start=st.integers(min_value=0, max_value=1000),
        end=st.integers(min_value=1001, max_value=2000),
    )
    @settings(max_examples=150, deadline=None)
    def test_the_same_rise_over_a_longer_window_is_a_slower_pace(self, start, end):
        """Two observations 10 apart: spread over a week that is a slower
        weekly pace than over a day. Getting this backwards would turn one
        busy hour into a trend."""
        fast = compute_trend(
            _snaps([(0.0, start), (24.0, end)]), now=_NOW, min_span_hours=24.0
        )
        slow = compute_trend(
            _snaps([(0.0, start), (24.0 * 7, end)]), now=_NOW, min_span_hours=24.0
        )
        if fast["pace_7d"] is not None and slow["pace_7d"] is not None:
            assert slow["pace_7d"] < fast["pace_7d"]

    @given(
        start=st.integers(min_value=0, max_value=1000),
        end=st.integers(min_value=1001, max_value=2000),
        age_days=st.floats(min_value=8.0, max_value=3650.0, allow_nan=False),
    )
    @settings(max_examples=150, deadline=None)
    def test_any_series_older_than_the_window_is_stale(self, start, end, age_days):
        """Whatever the numbers say, a series last touched longer ago than the
        window cannot answer as a current trend."""
        result = compute_trend(
            _snaps([(0.0, start), (24.0, end)]),
            # days=1 + age_days, not hours=age_days: the newest snapshot sits
            # at +24h, so `now` has to clear it by age_days DAYS.
            now=_BASE + timedelta(days=1 + age_days),
            min_span_hours=24.0,
            max_age_days=7.0,
        )
        assert result["provenance"] == "unverified"
        assert result["pace_7d"] is None
        assert "stale" in result["reason"].lower()