"""Phase G - age and churn, pinned without a database or a network.

The age tests use a fixed clock so "74 days" cannot depend on the day the
suite runs. The churn tests pin the cases that would otherwise become a
fabricated claim: one observation, unlike samples, a listing that reappears,
and a listing that vanished several observations ago.

The last class scans the engine's own source for the word the copy must never
use. That is deliberately a source test: a future edit that puts the word in
a label, a reason or a docstring fails here even if no current test calls it.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from engine.listing_age import (
    AGE_INFO_MAX_DAYS,
    NO_LONGER_LISTED,
    age_days,
    build_churn_report,
    describe_age,
    normalise_query,
)

NOW = datetime(2026, 10, 20, 12, 0, 0)


def _listing(
    listing_id: str,
    title: str = "A listing",
    *,
    creation: str | None = "2025-01-01T00:00:00",
    price: float | None = 19.99,
    currency: str | None = "GBP",
    item_url: str | None = None,
) -> dict:
    return {
        "listing_id": listing_id,
        "title": title,
        "item_url": item_url or f"https://www.ebay.co.uk/itm/{listing_id}",
        "price": price,
        "currency": currency,
        "item_creation_date": creation,
    }


def _run(
    observed_at: datetime,
    listings: list[dict],
    *,
    price_filter: str = "conditions:{NEW},price:[10..100]",
    limit: int = 5,
) -> dict:
    return {
        "observed_at": observed_at,
        "filter": price_filter,
        "limit": limit,
        "listings": listings,
    }


class TestAge:
    def test_age_is_whole_days_since_eBay_created_the_listing(self):
        assert age_days(NOW - timedelta(days=74), NOW) == 74

    def test_a_fresh_listing_is_informational_and_an_old_one_is_neutral(self):
        fresh = describe_age(NOW - timedelta(days=2), NOW)
        old = describe_age(NOW - timedelta(days=74), NOW)

        assert fresh["age"] == {
            "days": 2,
            "tone": "info",
            "basis": "ebay_item_creation_date",
        }
        assert old["age"] == {
            "days": 74,
            "tone": "neutral",
            "basis": "ebay_item_creation_date",
        }
        assert fresh["reason"] is None
        assert old["reason"] is None

    def test_the_tone_boundary_is_the_documented_six_days(self):
        assert AGE_INFO_MAX_DAYS == 6
        assert describe_age(NOW - timedelta(days=6), NOW)["age"]["tone"] == "info"
        assert describe_age(NOW - timedelta(days=7), NOW)["age"]["tone"] == "neutral"

    def test_today_and_yesterday_have_real_ages_not_placeholder_labels(self):
        assert age_days(NOW - timedelta(hours=2), NOW) == 0
        assert age_days(NOW - timedelta(days=1, hours=2), NOW) == 1

    def test_a_missing_creation_date_is_refused_with_a_sentence(self):
        result = describe_age(None, NOW)

        assert result["age"] is None
        assert "creation date" in result["reason"]
        assert "not claimed" in result["reason"]

    def test_a_future_creation_date_is_not_an_age_of_zero(self):
        result = describe_age(NOW + timedelta(days=1), NOW)

        assert result["age"] is None
        assert "future" in result["reason"]

    def test_an_unreadable_date_is_refused_rather_than_parsed_as_today(self):
        result = describe_age("not-a-date", NOW)

        assert result["age"] is None
        assert "creation date" in result["reason"]

    def test_an_aware_datetime_is_normalised_to_the_same_instant(self):
        aware = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)
        assert age_days(aware, NOW) == 74

    def test_the_clock_does_not_default_to_a_different_day_in_tests(self):
        """A fixed clock is what makes the examples stable; this also proves
        the helper accepts a datetime rather than reading the wall clock."""
        assert age_days(datetime(2026, 10, 18, 12, 0, 0), NOW) == 2


class TestChurnSuppression:
    def test_no_observations_means_no_claim_and_no_latest_list(self):
        report = build_churn_report([], now=NOW)

        assert report["observations"] == 0
        assert report["comparable"] is False
        assert report["churned"] is None
        assert report["latest"] == []
        assert "No search observation" in report["reason"]

    def test_one_observation_suppresses_churn_instead_of_zero_filling(self):
        report = build_churn_report(
            [_run(NOW, [_listing("1")])],
            now=NOW,
        )

        assert report["observations"] == 1
        assert report["comparable"] is False
        assert report["churned"] is None
        assert "second" in report["reason"]
        # The one sample is still shown, including its measured age.
        assert report["latest"][0]["listing_id"] == "1"
        assert report["latest"][0]["age"]["days"] > 0

    def test_different_price_filters_are_not_compared(self):
        report = build_churn_report(
            [
                _run(NOW, [_listing("2")], price_filter="price:[10..100]"),
                _run(
                    NOW - timedelta(days=1),
                    [_listing("1")],
                    price_filter="price:[10..200]",
                ),
            ],
            now=NOW,
        )

        assert report["observations"] == 2
        assert report["comparable"] is False
        assert report["churned"] is None
        assert "different price filters" in report["reason"]

    def test_different_sample_sizes_are_not_compared(self):
        report = build_churn_report(
            [
                _run(NOW, [_listing("2")], limit=5),
                _run(NOW - timedelta(days=1), [_listing("1")], limit=50),
            ],
            now=NOW,
        )

        assert report["comparable"] is False
        assert report["churned"] is None
        assert "different sample sizes" in report["reason"]

    def test_one_unlike_observation_anywhere_in_the_history_refuses_the_claim(self):
        """A listing from the differently-filtered early run cannot be
        compared with the latest one, so the whole history is not like-for-
        like rather than silently dropping that run."""
        report = build_churn_report(
            [
                _run(NOW, [_listing("3")], price_filter="price:[10..100]"),
                _run(
                    NOW - timedelta(days=1),
                    [_listing("2")],
                    price_filter="price:[10..100]",
                ),
                _run(
                    NOW - timedelta(days=2),
                    [_listing("1")],
                    price_filter="price:[10..200]",
                ),
            ],
            now=NOW,
        )

        assert report["comparable"] is False
        assert report["churned"] is None
        assert "different price filters" in report["reason"]


class TestChurn:
    def test_a_listing_missing_from_the_latest_sample_is_reported(self):
        first = NOW - timedelta(days=1)
        report = build_churn_report(
            [
                _run(NOW, [_listing("2", "Still here"), _listing("3", "New")]),
                _run(first, [_listing("1", "Gone"), _listing("2", "Still here")]),
            ],
            now=NOW,
        )

        assert report["comparable"] is True
        assert report["observations"] == 2
        assert report["latest_listing_count"] == 2
        assert report["earlier_listing_count"] == 2
        assert report["limit"] == 5
        assert report["filter"] == "conditions:{NEW},price:[10..100]"
        assert [row["listing_id"] for row in report["churned"]] == ["1"]
        gone = report["churned"][0]
        assert gone["title"] == "Gone"
        assert gone["status"] == NO_LONGER_LISTED
        assert gone["last_seen_at"] == f"{first.isoformat()}Z"
        assert gone["first_seen_at"] == f"{first.isoformat()}Z"
        assert report["reason"] is None

    def test_a_listing_that_reappears_is_not_churned(self):
        report = build_churn_report(
            [
                _run(NOW, [_listing("1", "Back again")]),
                _run(NOW - timedelta(days=1), []),
                _run(NOW - timedelta(days=2), [_listing("1", "Back again")]),
            ],
            now=NOW,
        )

        assert report["comparable"] is True
        assert report["churned"] == []
        assert "No listing observed earlier" in report["reason"]

    def test_a_listing_absent_for_several_observations_keeps_its_last_seen_date(self):
        first = NOW - timedelta(days=3)
        report = build_churn_report(
            [
                _run(NOW, [_listing("2", "Still here")]),
                _run(NOW - timedelta(days=1), [_listing("2", "Still here")]),
                _run(first, [_listing("1", "Long gone"), _listing("2", "Still here")]),
            ],
            now=NOW,
        )

        assert [row["listing_id"] for row in report["churned"]] == ["1"]
        assert report["churned"][0]["last_seen_at"] == f"{first.isoformat()}Z"

    def test_a_measured_empty_churn_list_is_not_the_same_as_a_refusal(self):
        report = build_churn_report(
            [
                _run(NOW, [_listing("1", "Stable")]),
                _run(NOW - timedelta(days=1), [_listing("1", "Stable")]),
            ],
            now=NOW,
        )

        assert report["comparable"] is True
        assert report["churned"] == []
        assert report["reason"] is not None
        assert "No listing observed earlier" in report["reason"]

    def test_age_uses_eBay_creation_date_not_the_first_sighting(self):
        old_listing = _listing(
            "1",
            "Old stock",
            creation="2025-01-01T00:00:00",
        )
        first_seen = NOW - timedelta(days=1)
        report = build_churn_report(
            [
                _run(NOW, [old_listing]),
                _run(first_seen, [old_listing]),
            ],
            now=NOW,
        )

        row = report["latest"][0]
        assert row["first_seen_at"] == f"{first_seen.isoformat()}Z"
        assert row["age"]["days"] > 600
        assert row["age"]["basis"] == "ebay_item_creation_date"
        assert row["age_reason"] is None

    def test_a_latest_listing_without_a_creation_date_gets_no_age_claim(self):
        report = build_churn_report(
            [
                _run(NOW, [_listing("1", "No date", creation=None)]),
                _run(NOW - timedelta(days=1), [_listing("1", "No date", creation=None)]),
            ],
            now=NOW,
        )

        row = report["latest"][0]
        assert row["age"] is None
        assert "creation date" in row["age_reason"]

    def test_duplicate_listing_ids_in_one_run_are_one_listing(self):
        duplicate = _listing("1", "Same listing")
        report = build_churn_report(
            [
                _run(NOW, [duplicate, dict(duplicate), _listing("2")]),
                _run(NOW - timedelta(days=1), [duplicate]),
            ],
            now=NOW,
        )

        assert report["latest_listing_count"] == 2
        assert report["earlier_listing_count"] == 1
        assert [row["listing_id"] for row in report["latest"]] == ["1", "2"]

    def test_a_listing_with_no_id_is_skipped_rather_than_filed_under_blank(self):
        report = build_churn_report(
            [
                _run(NOW, [{"title": "No id"}, _listing("2")]),
                _run(NOW - timedelta(days=1), [_listing("1")]),
            ],
            now=NOW,
        )

        assert report["latest_listing_count"] == 1
        assert [row["listing_id"] for row in report["churned"]] == ["1"]

    def test_churned_rows_are_newest_last_seen_first(self):
        older = NOW - timedelta(days=3)
        newer = NOW - timedelta(days=1)
        report = build_churn_report(
            [
                _run(NOW, [_listing("3")]),
                _run(newer, [_listing("2", "B")]),
                _run(older, [_listing("1", "A")]),
            ],
            now=NOW,
        )

        assert [row["listing_id"] for row in report["churned"]] == ["2", "1"]

    def test_no_rate_or_other_unmeasured_figure_is_reported(self):
        report = build_churn_report(
            [
                _run(NOW, [_listing("2")]),
                _run(NOW - timedelta(days=1), [_listing("1")]),
            ],
            now=NOW,
        )

        def keys(value):
            if isinstance(value, dict):
                found = set(value)
                for item in value.values():
                    found |= keys(item)
                return found
            if isinstance(value, list):
                found = set()
                for item in value:
                    found |= keys(item)
                return found
            return set()

        banned = {
            "sold",
            "sold_count",
            "sales",
            "revenue",
            "churn_rate",
            "churn_percent",
            "percentage",
            "percent",
            "trend",
            "score",
        }
        assert keys(report).isdisjoint(banned)


class TestQueryLanes:
    @pytest.mark.parametrize(
        "value",
        ["Garden Hose", "  garden   hose  ", "GARDEN HOSE"],
    )
    def test_case_and_spacing_do_not_split_one_query_lane(self, value):
        assert normalise_query(value) == "garden hose"

    def test_a_blank_query_has_no_lane(self):
        assert normalise_query("   ") == ""
        assert normalise_query(None) == ""


class TestTheModuleNeverUsesTheSaleWord:
    def test_the_source_does_not_contain_the_word(self):
        source = inspect.getsource(
            __import__("engine.listing_age", fromlist=["listing_age"])
        ).lower()
        assert "sold" not in source
