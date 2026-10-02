"""Profit must reflect shipping, and competition must be honest.

Two real defects motivated this file, both found by reading the code rather
than by a failing feature report:

  1. engine/decisions.py called calculate_profit(ebay_price, supplier_price)
     and DROPPED product.shipping_cost. Every caller - hunter's
     profit_calc.py, analysis_pipeline, deep_search - carefully reads the
     supplier's postage off the source and passes it in, and the decision
     engine then threw it away. The verdict and the headline profit were
     overstated by exactly the postage on every product that charges it.

  2. Competitor stores were counted (C11, STORE_COUNT=4) and displayed, but
     never reached the verdict at all. There is no user-set "maximum
     competitors" threshold anywhere in config, so inventing one and failing
     products on it would be a fabricated business rule. Instead the count
     becomes an ADVISORY row that never decides - and which reads zero
     competitors as a DEMAND WARNING, because "nobody else sells this" is
     what no-demand looks like, not an opportunity.

Expected values are derived from the rules themselves, not from constants
copied out of the implementation.
"""

import pytest

from engine.decisions import DecisionEngine
from engine.profit import calculate_profit
from scrapers.base import DemandData, ScrapedProduct


@pytest.fixture(autouse=True)
def _pristine_range(monkeypatch, tmp_path):
    """Run against the config defaults regardless of the repo's live state."""
    import json

    import utils.filters as uf

    target = tmp_path / "custom_filters.json"
    target.write_text(json.dumps({"active": {}, "presets": {}}))
    monkeypatch.setattr(uf, "FILTERS_FILE", target)
    uf._cache["mtime"] = None
    uf._cache["data"] = None
    yield
    uf._cache["mtime"] = None
    uf._cache["data"] = None


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


def _demand(**kw):
    base = dict(sold_count_30d=40, sold_count_7d=12, verified=True, verified_7d=True)
    base.update(kw)
    return DemandData(**base)


def _row(verdict, name):
    return next(r for r in verdict.filters if r.name == name)


class TestShippingReachesTheVerdict:
    def test_postage_reduces_profit_by_exactly_itself(self):
        """The dropped argument, stated as a property: shipping is subtracted."""
        unshipped = DecisionEngine().evaluate(_product(), _demand(), supplier_price=10.0)
        shipped = DecisionEngine().evaluate(
            _product(shipping_cost=4.75), _demand(), supplier_price=10.0
        )

        assert unshipped.profit == pytest.approx(shipped.profit + 4.75, abs=0.01)

    def test_postage_that_eats_the_whole_profit_flips_the_verdict_to_fail(self):
        """A product that only passed because postage was ignored must fail."""
        unshipped = DecisionEngine().evaluate(_product(), _demand(), supplier_price=10.0)
        # Postage just larger than the profit the verdict was relying on.
        killer = unshipped.profit + 1.00

        shipped = DecisionEngine().evaluate(
            _product(shipping_cost=killer), _demand(), supplier_price=10.0
        )

        assert unshipped.verdict != "fail", "precondition: it passes without postage"
        assert shipped.profit < 0
        assert shipped.verdict == "fail"

    def test_known_shipping_makes_the_profit_figure_complete(self):
        """engine.profit already reports completeness; the verdict must not
        contradict it by quoting an unknown postage as free."""
        shipped = DecisionEngine().evaluate(
            _product(shipping_cost=3.20), _demand(), supplier_price=10.0
        )
        direct = calculate_profit(30.00, 10.0, shipping_cost=3.20)

        assert shipped.profit == pytest.approx(direct["profit"], abs=0.01)
        assert direct["profit_is_complete"] is True

    def test_unread_postage_is_not_invented(self):
        """shipping_cost 0.0 means UNKNOWN (C1); it must not become a
        fabricated free-postage line that flatters the margin."""
        unknown = DecisionEngine().evaluate(_product(), _demand(), supplier_price=10.0)

        assert unknown.profit == pytest.approx(
            calculate_profit(30.00, 10.0)["profit"], abs=0.01
        )
        assert calculate_profit(30.00, 10.0)["profit_is_complete"] is False


class TestCompetitionIsHonestAndNeverDecides:
    def test_competition_is_advisory_so_the_count_cannot_change_the_verdict(self):
        none_found = DecisionEngine().evaluate(
            _product(), _demand(), supplier_price=10.0, competitor_store_count=0
        )
        four_found = DecisionEngine().evaluate(
            _product(), _demand(), supplier_price=10.0, competitor_store_count=4
        )

        assert _row(none_found, "Competition").advisory is True
        assert _row(four_found, "Competition").advisory is True
        assert none_found.verdict == four_found.verdict

    def test_zero_competitors_reads_as_a_demand_warning_not_an_opportunity(self):
        """The copy that matters: nobody else selling is what NO demand
        looks like. It must not be presented as a green light."""
        verdict = DecisionEngine().evaluate(
            _product(), _demand(), supplier_price=10.0, competitor_store_count=0
        )
        row = _row(verdict, "Competition")

        said = f"{row.actual} {row.expected}".lower()
        assert "no competitor stores" in said
        assert "demand" in said

    def test_a_real_count_is_reported_as_a_count(self):
        verdict = DecisionEngine().evaluate(
            _product(), _demand(), supplier_price=10.0, competitor_store_count=3
        )
        row = _row(verdict, "Competition")

        assert "3" in row.actual
        assert row.verified is True

    def test_no_competitor_data_adds_no_row_at_all(self):
        """Never invent a competition figure: absent count, absent row."""
        verdict = DecisionEngine().evaluate(_product(), _demand(), supplier_price=10.0)

        assert not [r for r in verdict.filters if r.name == "Competition"]

    def test_a_short_store_search_is_reported_as_unverified(self):
        """C11 ladder returns <4 stores on a broadened band; that is a
        partial search, not a market with no competitors."""
        verdict = DecisionEngine().evaluate(
            _product(),
            _demand(),
            supplier_price=10.0,
            competitor_store_count=2,
            competitor_stores_verified=False,
        )
        row = _row(verdict, "Competition")

        assert row.verified is False
        assert row.advisory is True


class TestScorecardNeverBrandsAnAdvisoryRowAsAFailure:
    """The verdict ladder excludes advisory rows from the decision, but the
    scorecard used to print every row with the same [PASS]/[FAIL] icon. So
    "no competitor stores found" rendered as a red FAIL and a healthy
    competition count rendered as a green PASS - reading an information
    channel as a rule, on the same rows that never decide anything."""

    def _scorecard(self, **kw):
        from engine.scorecard import format_scorecard

        verdict = DecisionEngine().evaluate(
            _product(),
            _demand(),
            supplier_price=10.0,
            competitor_store_count=kw.pop("competitor_store_count", 0),
            competitor_stores_verified=kw.pop("competitor_stores_verified", True),
            **kw,
        )
        return format_scorecard(_product(), [], _demand(), verdict)

    def test_an_advisory_row_is_never_shown_as_fail(self):
        card = self._scorecard(competitor_store_count=0)

        competition_line = next(
            line for line in card.splitlines() if "Competition" in line
        )
        assert "[FAIL]" not in competition_line
        assert "[PASS]" not in competition_line

    def test_an_advisory_row_is_marked_as_information(self):
        card = self._scorecard(competitor_store_count=0)
        competition_line = next(
            line for line in card.splitlines() if "Competition" in line
        )

        assert "INFO" in competition_line.upper()

    def test_an_unverified_advisory_row_says_so(self):
        card = self._scorecard(
            competitor_store_count=1, competitor_stores_verified=False
        )
        competition_line = next(
            line for line in card.splitlines() if "Competition" in line
        )

        assert "unverified" in competition_line.lower()

    def test_gating_rows_keep_their_pass_fail_verdicts(self):
        """The fix must not blunt the rules that actually decide."""
        card = self._scorecard()

        condition_line = next(
            line for line in card.splitlines() if "Condition" in line
        )
        assert "[PASS]" in condition_line