"""Phase D - the fee engine, tested against the rules it must keep.

Part 1: the fee table itself. These tests pin the things that make the
table trustworthy - its provenance, its internal consistency, its refusal
to price an unknown category as if it had been read, and the difference
between the active published rate card and the retained v1-static model.

Expected values are derived from the table's own stated rules (a rate
stated on the card, a default that must announce itself), not copied out
of fetched pages.
"""

import pytest

from config import PROFIT_CONFIG
from engine import fees
from engine.profit import calculate_profit


class TestTheActiveTableIsThePublishedRateCard:
    def test_the_active_table_is_the_rate_card(self):
        assert fees.ACTIVE_TABLE == fees.RATE_CARD_TABLE
        assert fees.get_fee_table()["key"] == fees.RATE_CARD_TABLE

    def test_the_table_states_a_version(self):
        table = fees.get_fee_table()
        assert table["version"]
        assert "2026-09-30" in table["version"]

    def test_every_source_names_a_url_and_a_retrieval(self):
        """A rate without a source is a guess with a decimal point."""
        for source in fees.get_fee_table()["sources"]:
            assert source["url"] and source["url"].startswith("https://")
            assert source["retrieved"]
            assert source["page_updated"]

    def test_an_unknown_table_is_refused_not_guessed(self):
        with pytest.raises(KeyError) as err:
            fees.get_fee_table("some-other-marketplace")

        assert fees.RATE_CARD_TABLE in str(err.value)


class TestCategoryRowsAreWellFormed:
    @pytest.fixture()
    def categories(self):
        return fees.get_fee_table()["business"]["categories"]

    def test_every_row_has_a_key_name_ids_and_tiers(self, categories):
        for row in categories:
            assert row["key"] and row["key"] == row["key"].lower()
            assert row["name"]
            assert row["category_ids"] and all(
                isinstance(cid, int) for cid in row["category_ids"]
            )
            assert row["tiers"]

    def test_keys_are_unique(self, categories):
        keys = [row["key"] for row in categories]
        assert len(keys) == len(set(keys))

    def test_category_ids_are_unique_across_rows(self, categories):
        seen: list[int] = []
        for row in categories:
            seen.extend(row["category_ids"])
        assert len(seen) == len(set(seen))

    def test_tiers_end_open_ended_and_ascend(self, categories):
        for row in categories:
            tiers = row["tiers"]
            assert tiers[-1][0] is None, row["key"]
            limits = [upper for upper, _ in tiers if upper is not None]
            assert limits == sorted(limits), row["key"]
            assert len(limits) == len(set(limits)), row["key"]

    def test_every_rate_is_a_real_percentage(self, categories):
        for row in categories:
            for _, percent in row["tiers"]:
                assert 0 < percent < 100, row["key"]
            switch = row.get("rate_switch")
            if switch:
                assert 0 < switch["percent"] < 100

    def test_base_rates_stay_inside_the_documented_band(self, categories):
        """The rate card documents a 5% floor and a 14.9% ceiling. A number
        outside that band would mean a transcription error, not a fee."""
        for row in categories:
            first_percent = row["tiers"][0][1]
            assert 5.0 <= first_percent <= 14.9, row["key"]

    def test_tiered_rows_lower_the_rate_above_the_limit(self, categories):
        """Tiered rows are volume-deliberate: the above-limit rate is lower."""
        for row in categories:
            if len(row["tiers"]) > 1:
                rates = [percent for _, percent in row["tiers"]]
                assert rates == sorted(rates, reverse=True), row["key"]


class TestCategoryResolution:
    def test_a_key_resolves_to_its_row(self):
        row, known = fees.resolve_category("jewellery-watches")
        assert known is True
        assert row["name"] == "Jewellery & Watches"
        assert row["tiers"] == [(1000.0, 14.9), (None, 4.0)]

    def test_a_category_id_resolves_to_the_same_row(self):
        by_key, _ = fees.resolve_category("jewellery-watches")
        by_id, known = fees.resolve_category(281)
        by_str, _ = fees.resolve_category("281")
        assert known is True
        assert by_id is by_key
        assert by_str is by_key

    def test_a_missing_category_defaults_loudly(self):
        for cat in (None, "", "not-a-category", 999999999):
            row, known = fees.resolve_category(cat)
            assert known is False
            assert row["key"] == fees.DEFAULT_CATEGORY_KEY

    def test_the_default_row_is_a_real_published_row(self):
        """The default is Everything Else from the card - a stated rate, not
        an invented average."""
        row, _ = fees.resolve_category(None)
        assert row["category_ids"] == [99]
        assert row["tiers"] == [(None, 12.9)]


class TestTheCardNumbersAreTheDocumentedOnes:
    """Spot-checks against the rate card, including the lanes in it that are
    easy to flatten by accident."""

    @pytest.fixture()
    def business(self):
        return fees.get_fee_table()["business"]

    def test_per_order_fee_steps_at_ten_pounds(self, business):
        pof = business["per_order_fee"]
        assert pof["at_or_below"] == 10.0
        assert pof["fee_at_or_below"] == 0.30
        assert pof["fee_above"] == 0.40

    def test_regulatory_fee_is_the_documented_fraction(self, business):
        assert business["regulatory_fee_percent"] == 0.35

    def test_common_categories_carry_their_documented_rates(self):
        expected = {
            "books-comics-magazines": [(None, 9.9)],
            "business-office-industrial": [(None, 12.5)],
            "crafts": [(None, 12.9)],
            "pet-supplies": [(None, 12.9)],
            "everything-else": [(None, 12.9)],
            "vehicle-parts-accessories": [(750.0, 9.5), (None, 3.0)],
            "video-games-consoles-hardware": [(400.0, 6.9), (None, 2.0)],
            "home-furniture-diy-furniture": [(500.0, 10.9), (1000.0, 7.9), (None, 3.0)],
        }
        for key, tiers in expected.items():
            row, known = fees.resolve_category(key)
            assert known is True, key
            assert row["tiers"] == tiers, key

    def test_trainers_switch_uses_the_item_price_not_the_total(self):
        row, _ = fees.resolve_category("clothes-trainers")
        assert row["rate_switch"] == {"item_price_at_least": 100.0, "percent": 7.0}

    def test_vat_is_twenty_and_currency_is_gbp(self):
        table = fees.get_fee_table()
        assert table["vat_rate"] == 20.0
        assert table["currency"] == "GBP"

    def test_business_fees_are_quoted_excluding_vat(self, business):
        assert business["fees_include_vat"] is False

    def test_below_standard_and_top_rated_modifiers_are_carried(self, business):
        mods = business["modifiers"]
        assert mods["below_standard_extra_pp"] == 6.0
        assert mods["top_rated_premium_service_discount_percent"] == 10.0


class TestPrivateSellersHaveTheirOwnStructure:
    def test_uk_private_sellers_pay_no_final_value_fee(self):
        table = fees.get_fee_table()
        private = table["private"]
        assert private["fvf_percent"] == 0.0
        assert private["regulatory_fee_percent"] == 0.0

    def test_private_fees_are_quoted_including_vat(self):
        assert fees.get_fee_table()["private"]["fees_include_vat"] is True

    def test_private_listing_allowance_is_carried(self):
        private = fees.get_fee_table()["private"]
        assert private["free_listings_per_month"] == 300
        assert private["listing_fee_after_allowance"] == 0.35

    def test_non_uk_resident_private_sellers_get_the_documented_schedule(self):
        side = fees.seller_side(fees.get_fee_table(), "private", uk_resident=False)
        assert side["fvf_tiers"] == [(5000.0, 12.8), (None, 3.0)]
        assert side["per_order_fee"] == 0.30
        assert side["regulatory_fee_percent"] == 0.42

    def test_the_uk_side_does_not_inherit_the_non_uk_schedule(self):
        side = fees.seller_side(fees.get_fee_table(), "private")
        assert side["fvf_percent"] == 0.0
        assert "fvf_tiers" not in side

    def test_an_unknown_seller_type_is_refused(self):
        with pytest.raises(ValueError):
            fees.seller_side(fees.get_fee_table(), "sometime-seller")


class TestTheV1ModelIsKeptButNamesItself:
    def test_v1_static_carries_the_c3_numbers(self):
        table = fees.get_fee_table(fees.V1_STATIC_TABLE)
        assert table["business"]["fvf_percent"] == 13.5
        assert table["business"]["listing_fee_percent"] == 0.03
        assert table["vat_rate"] == 20.0

    def test_v1_static_does_not_pretend_to_have_the_newer_fees(self):
        business = fees.get_fee_table(fees.V1_STATIC_TABLE)["business"]
        assert business["per_order_fee"] is None
        assert business["regulatory_fee_percent"] is None
        assert business["categories"] is None

    def test_v1_static_says_where_it_came_from(self):
        table = fees.get_fee_table(fees.V1_STATIC_TABLE)
        assert "CONSTRAINTS.md C3" in table["sources"][0]["label"]
        assert any("Superseded" in note for note in table["notes"])


class TestRateLabelsNeverFlattenATieredRate:
    def test_a_flat_rate_reads_as_one_rate(self):
        row, _ = fees.resolve_category("books-comics-magazines")
        assert fees.rate_label(row) == "9.9%"

    def test_a_tiered_rate_names_both_limits(self):
        row, _ = fees.resolve_category("jewellery-watches")
        label = fees.rate_label(row)
        assert "14.9%" in label
        assert "GBP 1,000" in label
        assert "4%" in label
        assert "above" in label

    def test_a_three_step_rate_names_all_three(self):
        row, _ = fees.resolve_category("home-furniture-diy-furniture")
        label = fees.rate_label(row)
        assert label.count("%") == 3

    def test_the_trainers_label_names_the_switch(self):
        row, _ = fees.resolve_category("clothes-trainers")
        label = fees.rate_label(row)
        assert "7%" in label
        assert "GBP 100" in label

    def test_list_categories_covers_every_row(self):
        rows = fees.list_categories()
        categories = fees.get_fee_table()["business"]["categories"]
        assert len(rows) == len(categories)
        for entry in rows:
            assert entry["key"] and entry["name"] and entry["rate_label"]
            assert entry["category_ids"]


# ---------------------------------------------------------------------------
# The forward calculation
# ---------------------------------------------------------------------------


def _business(sale_price, **kw):
    kw.setdefault("seller_type", "business")
    return fees.calculate_fees(sale_price, **kw)


class TestTheAcceptanceCaseIsArithmeticallyConsistent:
    """Phase D's acceptance example: a business seller at GBP 24.99 with 2%
    promoted and GBP 3.20 postage paid, no category given (so the stated
    default rate applies). Every expected value is recomputed from the
    published rule, not copied from the implementation."""

    @pytest.fixture()
    def result(self):
        return fees.calculate_fees(
            24.99,
            postage_charged=0.0,
            promoted_rate=2.0,
            seller_type="business",
            listing_fee=0.0,
        )

    def test_every_line_follows_the_published_rule(self, result):
        total = 24.99
        assert result["fvf"] == pytest.approx(round(total * 0.129, 2), abs=0.01)
        assert result["per_order_fee"] == 0.40
        assert result["regulatory_fee"] == pytest.approx(
            round(total * 0.0035, 2), abs=0.01
        )
        assert result["promoted_fee"] == pytest.approx(round(total * 0.02, 2), abs=0.01)

    def test_the_quoted_total_is_the_sum_of_its_lines(self, result):
        lines = [
            result["fvf"],
            result["per_order_fee"],
            result["regulatory_fee"],
            result["promoted_fee"],
        ]
        assert sum(lines) == pytest.approx(result["fees_quoted_total"], abs=0.01)

    def test_vat_is_added_to_the_fee_lines_and_the_gross_is_consistent(self, result):
        assert result["vat_on_fees"] == pytest.approx(
            result["fees_quoted_total"] * 0.20, abs=0.01
        )
        assert result["fees_gross_total"] == pytest.approx(
            result["fees_quoted_total"] + result["vat_on_fees"], abs=0.01
        )

    def test_a_default_category_announces_itself(self, result):
        assert result["category"]["known"] is False
        assert result["category"]["key"] == fees.DEFAULT_CATEGORY_KEY
        assert any("stated default" in line for line in result["assumptions"])

    def test_the_response_states_the_table_it_used(self, result):
        assert result["fee_table"]["key"] == fees.RATE_CARD_TABLE
        assert result["fee_table"]["version"]
        assert result["fee_table"]["currency"] == "GBP"

    def test_the_worked_breakdown_holds_together(self, result):
        """One hand-computable statement of the whole thing: 24.99 item,
        Everything Else 12.9% + 40p + 0.35% + 2% promoted, +20% VAT."""
        assert result["fvf"] == 3.22
        assert result["per_order_fee"] == 0.40
        assert result["regulatory_fee"] == 0.09
        assert result["promoted_fee"] == 0.50
        assert result["fees_quoted_total"] == 4.21
        assert result["vat_on_fees"] == 0.84
        assert result["fees_gross_total"] == 5.05
        assert result["fees_cost_total"] == 5.05


class TestThePerOrderFeeSteps:
    def test_at_ten_pounds_the_lower_fee_applies(self):
        assert _business(10.00)["per_order_fee"] == 0.30

    def test_above_ten_pounds_the_higher_fee_applies(self):
        assert _business(10.01)["per_order_fee"] == 0.40

    def test_the_step_is_measured_on_the_total_including_postage(self):
        """The rate card defines an order as everything checked out together:
        postage pushes an order across the step like anything else."""
        under = _business(9.50, postage_charged=0.50)
        over = _business(9.50, postage_charged=0.51)
        assert under["per_order_fee"] == 0.30
        assert over["per_order_fee"] == 0.40


class TestTieredCategoryRates:
    def test_at_the_tier_limit_the_lower_rate_has_not_started(self):
        result = _business(1000.0, category="jewellery-watches")
        assert result["fvf"] == pytest.approx(149.00, abs=0.01)

    def test_above_the_limit_only_the_portion_above_is_reduced(self):
        result = _business(1200.0, category="jewellery-watches")
        assert result["fvf"] == pytest.approx(149.00 + 8.00, abs=0.01)

    def test_a_second_tiered_shape_behaves_the_same_way(self):
        at_limit = _business(450.0, category="coins")
        above = _business(500.0, category="coins")
        assert at_limit["fvf"] == pytest.approx(49.05, abs=0.01)
        assert above["fvf"] == pytest.approx(49.05 + 1.50, abs=0.01)

    def test_the_label_names_the_rate_actually_applied(self):
        result = _business(100.0, category="jewellery-watches")
        assert "14.9%" in result["fvf_rate"]
        assert result["category"]["rate_label"] == result["fvf_rate"]


class TestTheTrainersSwitch:
    def test_below_the_threshold_the_normal_rate_applies(self):
        result = _business(99.99, category="clothes-trainers")
        assert result["fvf"] == pytest.approx(99.99 * 0.119, abs=0.01)

    def test_at_the_threshold_the_switched_rate_applies(self):
        result = _business(100.00, category="clothes-trainers")
        assert result["fvf"] == pytest.approx(100.00 * 0.07, abs=0.01)
        assert "7%" in result["fvf_rate"]

    def test_the_threshold_uses_the_item_price_not_the_total(self):
        """The card says the selling price excludes postage - so postage
        must not push a listing across the switch."""
        result = _business(99.99, postage_charged=10.00, category="clothes-trainers")
        expected = (99.99 + 10.00) * 0.119
        assert result["fvf"] == pytest.approx(expected, abs=0.01)


class TestVatTreatment:
    def test_an_unregistered_business_seller_bears_the_vat(self):
        result = _business(100.0, vat_registered=False)
        assert result["vat_recoverable"] is False
        assert result["fees_cost_total"] == pytest.approx(
            result["fees_gross_total"], abs=0.01
        )

    def test_a_registered_business_seller_recovers_the_vat(self):
        result = _business(100.0, vat_registered=True)
        assert result["vat_recoverable"] is True
        assert result["fees_cost_total"] == pytest.approx(
            result["fees_quoted_total"], abs=0.01
        )
        # eBay still invoices the gross; only the cost view changes.
        assert result["fees_gross_total"] > result["fees_cost_total"]
        assert "recoverable" in result["vat_note"]

    def test_a_private_seller_gets_no_vat_line_and_is_told_why(self):
        result = fees.calculate_fees(100.0, seller_type="private")
        assert result["vat_on_fees"] is None
        assert "inclusive" in result["vat_note"]


class TestBusinessVersusPrivate:
    def test_a_uk_private_seller_pays_no_final_value_fee(self):
        result = fees.calculate_fees(100.0, seller_type="private")
        assert result["fvf"] == 0.0
        assert result["fvf_rate"] == "0%"

    def test_a_uk_private_seller_pays_no_regulatory_fee_and_that_is_a_zero(self):
        """The private page states the fee is not charged. That is a
        documented zero, not the absence of a fee - the two must not look
        alike (v1-static has no regulatory fee at all; see the other test)."""
        result = fees.calculate_fees(100.0, seller_type="private")
        assert result["regulatory_fee"] == 0.0

    def test_nothing_the_private_card_does_not_charge_appears_as_a_fee(self):
        result = fees.calculate_fees(100.0, seller_type="private")
        assert result["fees_quoted_total"] == 0.0
        assert result["fees_gross_total"] == 0.0
        assert result["fees_cost_total"] == 0.0

    def test_promoted_applies_to_private_sellers_too(self):
        result = fees.calculate_fees(50.0, seller_type="private", promoted_rate=4.0)
        assert result["promoted_fee"] == pytest.approx(2.00, abs=0.01)

    def test_a_non_uk_private_seller_gets_the_documented_schedule(self):
        result = fees.calculate_fees(
            6000.0, seller_type="private", uk_resident=False
        )
        expected_fvf = 5000 * 0.128 + 1000 * 0.03
        assert result["fvf"] == pytest.approx(expected_fvf, abs=0.02)
        assert result["per_order_fee"] == 0.30
        assert result["regulatory_fee"] == pytest.approx(6000 * 0.0042, abs=0.01)

    def test_the_uk_schedule_is_not_applied_to_a_non_uk_seller(self):
        """The two schedules must not share a code path by accident: a UK
        private seller pays 0, the non-UK schedule pays 12.8%."""
        uk = fees.calculate_fees(100.0, seller_type="private")
        abroad = fees.calculate_fees(100.0, seller_type="private", uk_resident=False)
        assert uk["fvf"] == 0.0
        assert abroad["fvf"] == pytest.approx(12.80, abs=0.01)


class TestTheV1TableComputesOnTheItemPriceOnly:
    def test_postage_does_not_enter_the_old_basis(self):
        result = _business(
            100.0, postage_charged=10.0, fee_table=fees.V1_STATIC_TABLE
        )
        assert result["fvf"] == pytest.approx(13.50, abs=0.01)
        # the v1 listing component is a percent of the item price:
        assert result["listing_fee"] == pytest.approx(0.03, abs=0.005)
        assert result["fee_basis"] == "item_price"

    def test_the_old_listing_percent_appears_in_the_quoted_total(self):
        result = _business(100.0, fee_table=fees.V1_STATIC_TABLE)
        # 13.5% + 0.03% of the item price
        assert result["fees_quoted_total"] == pytest.approx(13.53, abs=0.01)

    def test_fees_the_old_model_never_had_stay_absent(self):
        result = _business(100.0, fee_table=fees.V1_STATIC_TABLE)
        assert result["per_order_fee"] is None
        assert result["regulatory_fee"] is None


class TestInternationalFee:
    def test_a_uk_buyer_incurs_no_international_fee(self):
        result = _business(100.0, buyer_region="uk")
        assert result["international_fee"] is None

    def test_each_documented_region_gets_its_documented_rate(self):
        rates = {"eu_northern_europe": 1.05, "us_canada": 1.8, "rest_of_world": 2.0}
        for region, rate in rates.items():
            result = _business(200.0, buyer_region=region)
            assert result["international_fee"] == pytest.approx(200.0 * rate / 100, abs=0.01), region

    def test_a_private_seller_ships_abroad_at_three_percent(self):
        result = fees.calculate_fees(
            100.0, seller_type="private", buyer_region="rest_of_world"
        )
        assert result["international_fee"] == pytest.approx(3.00, abs=0.01)

    def test_international_fees_carry_vat_for_a_business_seller(self):
        result = _business(100.0, buyer_region="us_canada")
        gross = result["fees_quoted_total"] * 1.2
        assert result["fees_gross_total"] == pytest.approx(gross, abs=0.02)


class TestPromotedIsOnlyShownWhenStated:
    def test_zero_promoted_is_no_line_at_all(self):
        assert _business(100.0)["promoted_fee"] is None

    def test_a_stated_rate_charges_on_the_total_including_postage(self):
        result = _business(20.0, postage_charged=5.0, promoted_rate=2.0)
        assert result["promoted_fee"] == pytest.approx(0.50, abs=0.005)


class TestRefusalsAreErrorsNotZeros:
    def test_an_unread_price_is_refused_with_the_reason(self):
        with pytest.raises(ValueError) as err:
            fees.calculate_fees(None)
        assert "unread" in str(err.value).lower()

    def test_a_zero_price_is_refused(self):
        with pytest.raises(ValueError):
            fees.calculate_fees(0)

    def test_a_negative_price_is_refused(self):
        with pytest.raises(ValueError):
            fees.calculate_fees(-5.0)

    def test_nan_is_refused(self):
        with pytest.raises(ValueError):
            fees.calculate_fees(float("nan"))

    def test_a_ludicrous_promoted_rate_is_refused(self):
        with pytest.raises(ValueError):
            fees.calculate_fees(10.0, promoted_rate=100.0)

    def test_a_negative_promoted_rate_is_refused(self):
        with pytest.raises(ValueError):
            fees.calculate_fees(10.0, promoted_rate=-1.0)

    def test_a_negative_postage_charged_is_refused(self):
        with pytest.raises(ValueError):
            fees.calculate_fees(10.0, postage_charged=-0.01)

    def test_a_negative_listing_fee_is_refused(self):
        with pytest.raises(ValueError):
            fees.calculate_fees(10.0, listing_fee=-0.30)

    def test_an_unknown_buyer_region_is_refused(self):
        with pytest.raises(ValueError):
            fees.calculate_fees(10.0, buyer_region="mars")

    def test_an_unknown_seller_type_is_refused(self):
        with pytest.raises(ValueError):
            fees.calculate_fees(10.0, seller_type="robot")


class TestListingFeeIsShownWhenSupplied:
    def test_zero_assumes_and_says_what_a_listing_costs(self):
        result = _business(100.0)
        assert result["listing_fee"] is None
        assert any("30p" in line or "35p" in line for line in result["assumptions"])

    def test_a_supplied_listing_fee_reaches_every_total(self):
        result = _business(100.0, listing_fee=0.30)
        assert result["listing_fee"] == 0.30
        assert result["fees_quoted_total"] == pytest.approx(
            result["fvf"] + result["per_order_fee"] + result["regulatory_fee"] + 0.30,
            abs=0.01,
        )


class TestAssumptionsAreStated:
    def test_the_fee_basis_is_stated_as_a_sentence(self):
        result = _business(24.99, postage_charged=3.99)
        assert any("total amount of the sale" in a for a in result["assumptions"])
        assert any("3.99" in a for a in result["assumptions"])

    def test_the_domestic_default_is_stated(self):
        result = _business(10.0)
        assert any("UK delivery address" in a for a in result["assumptions"])

    def test_the_gross_and_cost_views_never_disagree_silently(self):
        """Every combination of the flag must be explained by a sentence."""
        for registered in (True, False):
            result = _business(50.0, vat_registered=registered)
            assert result["vat_note"]
            if registered:
                assert "recoverable" in result["vat_note"]
            else:
                assert "not VAT registered" in result["vat_note"]


# ---------------------------------------------------------------------------
# The money layer: one sale all the way to profit, and the reverse solver
# ---------------------------------------------------------------------------


class TestTheAcceptanceMoneyView:
    """The Phase D acceptance example, taken all the way: business seller,
    GBP 24.99, 2% promoted, GBP 3.20 postage paid, GBP 9.40 supplier."""

    @pytest.fixture()
    def outcome(self):
        return fees.sale_outcome(
            24.99,
            supplier_cost=9.40,
            postage_paid=3.20,
            promoted_rate=2.0,
            seller_type="business",
        )

    def test_the_money_view_holds_together(self, outcome):
        # fees: 3.22 + 0.40 + 0.09 + 0.50 = 4.21, +20% VAT = 5.05
        assert outcome["fees"]["fees_cost_total"] == 5.05
        assert outcome["net_after_fees"] == 19.94
        assert outcome["risk_buffer"] == 0.75
        assert outcome["profit"] == 6.59
        assert outcome["margin"] == 26.4

    def test_the_profit_and_its_parts_never_disagree_by_more_than_a_penny(
        self, outcome
    ):
        parts = (
            outcome["profit"]
            + outcome["postage_paid"]
            + outcome["supplier_cost"]
            + outcome["risk_buffer"]
            + outcome["fees"]["fees_cost_total"]
        )
        assert parts == pytest.approx(outcome["proceeds"], abs=0.01)

    def test_a_missing_supplier_is_not_a_zero(self):
        outcome = fees.sale_outcome(24.99, seller_type="business")
        assert outcome["supplier_cost"] is None
        assert outcome["profit"] is None
        assert outcome["margin"] is None
        assert outcome["profit_is_complete"] is False
        assert "not given" in outcome["profit_missing_reason"]
        # the fee figures never needed the supplier and still compute
        assert outcome["fees"]["fees_cost_total"] > 0
        assert outcome["net_after_fees"] > 0

    def test_unread_postage_is_unknown_not_free(self):
        outcome = fees.sale_outcome(24.99, supplier_cost=9.40)
        assert outcome["postage_paid"] == 0.0
        assert outcome["postage_paid_known"] is False
        assert outcome["profit_is_complete"] is False

    def test_a_reading_below_a_penny_is_still_not_free(self):
        outcome = fees.sale_outcome(24.99, supplier_cost=9.40, postage_paid=0.001)
        assert outcome["postage_paid"] == 0.0
        assert outcome["postage_paid_known"] is False

    def test_a_penny_of_postage_moves_the_profit_by_a_penny(self):
        base = fees.sale_outcome(24.99, supplier_cost=9.40, postage_paid=3.20)
        dearer = fees.sale_outcome(24.99, supplier_cost=9.40, postage_paid=3.21)
        assert base["profit"] - dearer["profit"] == pytest.approx(0.01, abs=0.001)

    def test_the_risk_buffer_is_named_and_is_not_a_fee(self, outcome):
        assert outcome["risk_buffer_percent"] == 3.0
        assert outcome["risk_buffer"] == 0.75
        assert "risk_buffer" not in outcome["fees"]

    def test_a_different_buffer_moves_the_profit_by_the_same_rule(self):
        without = fees.sale_outcome(24.99, supplier_cost=9.40, risk_buffer_percent=0.0)
        base = fees.sale_outcome(24.99, supplier_cost=9.40)
        assert without["profit"] - base["profit"] == pytest.approx(0.75, abs=0.01)

    def test_vat_registration_lifts_the_profit_by_the_recoverable_vat(self):
        registered = fees.sale_outcome(100.0, supplier_cost=50.0, vat_registered=True)
        unregistered = fees.sale_outcome(100.0, supplier_cost=50.0, vat_registered=False)
        assert registered["profit"] - unregistered["profit"] == pytest.approx(
            unregistered["fees"]["vat_on_fees"], abs=0.01
        )

    def test_proceeds_include_postage_charged(self):
        outcome = fees.sale_outcome(20.0, supplier_cost=5.0, postage_charged=3.0)
        assert outcome["proceeds"] == 23.00
        assert outcome["net_after_fees"] == pytest.approx(
            23.00 - outcome["fees"]["fees_cost_total"], abs=0.01
        )


class TestSolveForMargin:
    def _outcome_kwargs(self):
        return dict(
            supplier_cost=9.40,
            postage_paid=3.20,
            promoted_rate=2.0,
            seller_type="business",
        )

    def test_the_acceptance_reverse_case_lands_where_the_math_says(self):
        solved = fees.solve_for_margin(30.0, **self._outcome_kwargs())
        assert solved["achievable"] is True
        # profit = 0.787 * price - 13.08 must equal 0.30 * price -> 26.86
        assert solved["price"] == pytest.approx(26.86, abs=0.02)

    def test_the_solver_proves_its_own_answer(self):
        solved = fees.solve_for_margin(30.0, **self._outcome_kwargs())
        assert solved["check"]["margin"] == pytest.approx(30.0, abs=0.1)
        assert solved["check"]["profit"] >= 0

    def test_solving_a_margin_then_recomputing_returns_the_same_margin(self):
        for target in (10.0, 25.0, 30.0, 50.0):
            solved = fees.solve_for_margin(target, **self._outcome_kwargs())
            assert solved["achievable"] is True, target
            recomputed = fees.sale_outcome(solved["price"], **self._outcome_kwargs())
            assert recomputed["margin"] == pytest.approx(target, abs=0.15), target
            assert recomputed["profit"] == pytest.approx(
                solved["check"]["profit"], abs=0.01
            ), target

    def test_the_solver_steps_over_the_per_order_fee(self):
        """A root above the GBP 10 step must charge the higher per-order fee."""
        solved = fees.solve_for_margin(30.0, supplier_cost=8.0, seller_type="business")
        assert solved["achievable"] is True
        # profit = 0.811 * price - 0.48 - 8 = 0.30 * price -> 16.60
        assert solved["price"] == pytest.approx(16.60, abs=0.02)

    def test_the_solver_steps_under_the_per_order_fee(self):
        solved = fees.solve_for_margin(10.0, supplier_cost=2.0, seller_type="business")
        assert solved["achievable"] is True
        # profit = 0.811 * price - 0.36 - 2 = 0.10 * price -> 3.32
        assert solved["price"] == pytest.approx(3.32, abs=0.02)

    def test_the_solver_crosses_a_tier_boundary(self):
        solved = fees.solve_for_margin(
            5.0, supplier_cost=900.0, category="jewellery-watches", seller_type="business"
        )
        assert solved["achievable"] is True
        # above GBP 1,000 the rate is 4% and the quoted side is
        # 0.0435 * price + 109.40 (fvf + 0.35% regulatory + 0.40 per order):
        # profit = 0.9178 * price - 1031.28 = 0.05 * price -> 1188.39
        assert solved["price"] == pytest.approx(1188.39, abs=0.02)
        assert solved["check"]["margin"] == pytest.approx(5.0, abs=0.1)

    def test_break_even_means_zero_margin(self):
        solved = fees.solve_for_margin(0.0, supplier_cost=10.0, seller_type="business")
        assert solved["achievable"] is True
        assert -0.01 <= solved["check"]["profit"] <= 0.02
        assert solved["check"]["margin"] == pytest.approx(0.0, abs=0.1)

    def test_a_fee_free_seller_breaks_even_at_the_supplier_price(self):
        solved = fees.solve_for_margin(
            0.0, supplier_cost=25.0, seller_type="private", risk_buffer_percent=0.0
        )
        assert solved["price"] == 25.0
        assert solved["check"]["profit"] == 0.0

    def test_the_default_buffer_moves_private_break_even_the_same_way(self):
        solved = fees.solve_for_margin(0.0, supplier_cost=25.0, seller_type="private")
        # 0.97 * price = 25 -> 25.78
        assert solved["price"] == pytest.approx(25.78, abs=0.02)

    def test_the_old_table_solves_by_its_own_rules(self):
        solved = fees.solve_for_margin(
            25.0,
            supplier_cost=10.0,
            seller_type="business",
            fee_table=fees.V1_STATIC_TABLE,
        )
        # v1: 0.80764 * price - 10 = 0.25 * price -> 17.94
        assert solved["price"] == pytest.approx(17.94, abs=0.05)

    def test_an_unreachable_target_says_so_and_returns_no_price(self):
        solved = fees.solve_for_margin(95.0, supplier_cost=10.0, seller_type="business")
        assert solved["achievable"] is False
        assert solved["price"] is None
        assert solved["check"] is None
        assert "No sale price" in solved["reason"]

    def test_a_missing_supplier_cannot_be_solved_around(self):
        with pytest.raises(ValueError):
            fees.solve_for_margin(30.0, supplier_cost=None)

    def test_a_non_numeric_target_is_refused(self):
        with pytest.raises(ValueError):
            fees.solve_for_margin(None, supplier_cost=10.0)

    def test_impossible_targets_are_refused(self):
        for bad in (-1.0, 100.0, 120.0):
            with pytest.raises(ValueError):
                fees.solve_for_margin(bad, supplier_cost=10.0)


# ---------------------------------------------------------------------------
# engine/profit.py - the C3 rule every verdict path calls
# ---------------------------------------------------------------------------


class TestThePipelineMoneyRuleDelegatesWithTheSameNumbers:
    """engine/profit.py keeps the shape and the numbers every caller reads.
    This class recomputes the pre-Phase-D formula here, independently of the
    implementation, and pins the two against each other on the v1-static
    selection - so the retired model stays exactly reproducible. The default
    is now the published card, pinned in the classes below."""

    def _legacy_expected(self, price, supplier, shipping=0.0):
        cfg = PROFIT_CONFIG
        ebay_fee = price * cfg["ebay_fee_percent"] / 100
        listing_fee = price * cfg["listing_fee_percent"] / 100
        vat_on_fees = (ebay_fee + listing_fee) * cfg["vat_on_fees_percent"] / 100
        returns_buffer = price * cfg["returns_buffer_percent"] / 100
        packaging = cfg["packaging_cost"]
        total_fees = ebay_fee + listing_fee + vat_on_fees + returns_buffer + packaging
        displayed = round(shipping, 2) if round(shipping, 2) > 0 else 0.0
        profit = price - supplier - total_fees - displayed
        margin = profit / price * 100 if price > 0 else 0.0
        return {
            "ebay_fee": round(ebay_fee, 2),
            "listing_fee": round(listing_fee, 2),
            "vat_on_fees": round(vat_on_fees, 2),
            "returns_buffer": round(returns_buffer, 2),
            "packaging_cost": round(packaging, 2),
            "shipping_cost": round(displayed, 2),
            "shipping_known": displayed > 0,
            "total_fees": round(total_fees + displayed, 2),
            "profit": round(profit, 2),
            "margin": round(margin, 1),
        }

    @pytest.mark.parametrize(
        "price,supplier,shipping",
        [
            (24.99, 9.40, 0.0),
            (24.99, 9.40, 3.20),
            (10.0, 5.0, 0.0),
            (5.5, 2.0, 1.5),
            (33.33, 12.12, 7.77),
            (100.0, 40.0, 0.004),
        ],
    )
    def test_every_figure_matches_the_pre_phase_d_formula(
        self, price, supplier, shipping
    ):
        # The v1 model is explicit here: this test is about the retired
        # formula being exactly reproducible, not about what runs today.
        got = calculate_profit(
            price, supplier, shipping_cost=shipping, fee_table=fees.V1_STATIC_TABLE
        )
        expected = self._legacy_expected(price, supplier, shipping)
        for key, value in expected.items():
            assert got[key] == value, key
        assert got["profit_is_complete"] == expected["shipping_known"]

    def test_the_old_key_set_is_intact(self):
        got = calculate_profit(24.99, 9.40, shipping_cost=3.20)
        for key in (
            "ebay_price",
            "supplier_price",
            "ebay_fee",
            "listing_fee",
            "vat_on_fees",
            "returns_buffer",
            "packaging_cost",
            "shipping_cost",
            "shipping_known",
            "profit_is_complete",
            "total_fees",
            "profit",
            "margin",
        ):
            assert key in got, key

    def test_the_result_states_the_fee_table_that_made_it(self):
        got = calculate_profit(24.99, 9.40)
        assert got["fee_table"]["key"] == fees.RATE_CARD_TABLE
        assert got["fee_table"]["version"]

    def test_the_default_is_the_published_card_and_v1_stays_selectable(self):
        """The switch, pinned: the default computes from the published card,
        the retired v1 model is one explicit argument away, and each result
        says which table made it, so the two can never be confused."""
        card = calculate_profit(24.99, 9.40)
        v1 = calculate_profit(24.99, 9.40, fee_table=fees.V1_STATIC_TABLE)
        assert card["fee_table"]["key"] == fees.RATE_CARD_TABLE
        assert v1["fee_table"]["key"] == fees.V1_STATIC_TABLE
        assert card["profit"] != v1["profit"]

    def test_a_below_a_penny_postage_reading_is_still_unknown(self):
        got = calculate_profit(24.99, 9.40, shipping_cost=0.004)
        assert got["shipping_known"] is False
        assert got["shipping_cost"] == 0.0

    def test_a_zero_price_is_refused_not_given_a_zero_margin(self):
        with pytest.raises(ValueError):
            calculate_profit(0.0, 10.0)


# ---------------------------------------------------------------------------
# The engine states its own lines - one source for CLI/scorecard/API/UI
# ---------------------------------------------------------------------------


class TestTheEngineStatesItsOwnLines:
    """The itemised rows every display surface renders - CLI, scorecard and
    the calculator UI to come - come from the engine, not from constants
    retyped per surface."""

    def test_the_card_lines_are_labelled_and_priced(self):
        outcome = fees.sale_outcome(24.99, supplier_cost=9.40, promoted_rate=2.0)
        by_label = {row["label"]: row for row in outcome["fee_lines"]}
        assert by_label["Final value fee"]["amount"] == outcome["fees"]["fvf"] == 3.22
        assert by_label["Final value fee"]["rate"] == "12.9%"
        assert by_label["Per-order fee"]["amount"] == 0.40
        assert by_label["Regulatory operating fee"]["amount"] == 0.09
        assert by_label["Promoted listings"]["amount"] == 0.50
        assert by_label["VAT on fees"]["amount"] == 0.84
        assert by_label["VAT on fees"]["rate"] == "20%"

    def test_a_fee_the_card_does_not_carry_has_no_line_and_no_zero(self):
        outcome = fees.sale_outcome(24.99, supplier_cost=9.40)
        labels = [row["label"] for row in outcome["fee_lines"]]
        # the card charges per listing, not a percent of the sale
        assert "Listing fee" not in labels
        assert outcome["fees"]["listing_fee"] is None

    def test_the_buffer_is_not_a_fee_line(self):
        outcome = fees.sale_outcome(24.99, supplier_cost=9.40)
        labels = [row["label"] for row in outcome["fee_lines"]]
        assert "Returns buffer" not in labels
        assert outcome["risk_buffer"] == 0.75
        assert outcome["risk_buffer_percent"] == 3.0

    def test_a_private_uk_sale_shows_its_documented_zeroes(self):
        outcome = fees.sale_outcome(30.0, supplier_cost=10.0, seller_type="private")
        by_label = {row["label"]: row for row in outcome["fee_lines"]}
        assert by_label["Final value fee"]["amount"] == 0.0
        assert by_label["Final value fee"]["rate"] == "0%"
        assert by_label["Regulatory operating fee"]["amount"] == 0.0
        # fees are VAT-inclusive on the private page: no VAT line to add
        assert "VAT on fees" not in by_label

    def test_the_v1_table_speaks_its_own_lines(self):
        outcome = fees.sale_outcome(
            100.0, supplier_cost=40.0, fee_table=fees.V1_STATIC_TABLE
        )
        by_label = {row["label"]: row for row in outcome["fee_lines"]}
        assert by_label["Final value fee"]["rate"] == "13.5%"
        assert by_label["Listing fee"]["rate"] == "0.03%"
        assert "Per-order fee" not in by_label


# ---------------------------------------------------------------------------
# Phase D acceptance: the verdict and the calculator answer as one
# ---------------------------------------------------------------------------


def _acceptance_product():
    from scrapers.base import ScrapedProduct

    return ScrapedProduct(
        source="ebay_uk",
        title="Test listing",
        price=24.99,
        url="https://www.ebay.co.uk/itm/123",
        condition="New",
        shipping_cost=3.20,
        verified=True,
    )


def _acceptance_demand():
    from scrapers.base import DemandData

    return DemandData(
        sold_count_30d=40, sold_count_7d=12, verified=True, verified_7d=True
    )


class TestTheVerdictAndTheCalculatorCannotDisagree:
    """Phase D acceptance, end to end: a business seller at GBP 24.99 with 2%
    promoted and GBP 3.20 postage paid. The same inputs through the pipeline
    verdict and through the calculator must give the same profit."""

    def test_the_acceptance_case_through_the_pipeline_verdict(self, monkeypatch):
        from config import SELLER_PROFILE
        from engine.decisions import DecisionEngine

        monkeypatch.setitem(SELLER_PROFILE, "promoted_rate", 2.0)

        verdict = DecisionEngine().evaluate(
            _acceptance_product(), _acceptance_demand(), supplier_price=9.40
        )
        calculator = fees.sale_outcome(
            24.99,
            supplier_cost=9.40,
            postage_paid=3.20,
            promoted_rate=2.0,
            seller_type="business",
        )

        assert calculator["profit"] == 6.59
        assert calculator["margin"] == 26.4
        assert verdict.profit == calculator["profit"]
        assert verdict.margin == calculator["margin"]

    def test_the_pipeline_money_entry_point_carries_the_profile_too(self, monkeypatch):
        from config import SELLER_PROFILE

        monkeypatch.setitem(SELLER_PROFILE, "promoted_rate", 2.0)
        via_pipeline = calculate_profit(24.99, 9.40, shipping_cost=3.20)
        assert via_pipeline["profit"] == 6.59
        assert via_pipeline["margin"] == 26.4
        assert via_pipeline["fee_table"]["key"] == fees.RATE_CARD_TABLE

    def test_the_scorecard_renders_the_engine_lines_and_the_table(self, monkeypatch):
        from types import SimpleNamespace

        from config import SELLER_PROFILE
        from engine.decisions import DecisionEngine
        from engine.scorecard import format_scorecard

        # The scorecard is the third surface of the same sale; it must show
        # the table, the engine's lines and the verdict's own figures.
        monkeypatch.setitem(SELLER_PROFILE, "promoted_rate", 2.0)

        product = _acceptance_product()
        demand = _acceptance_demand()
        verdict = DecisionEngine().evaluate(product, demand, supplier_price=9.40)
        card = format_scorecard(
            product, [SimpleNamespace(price=9.40, title="Supplier A")], demand, verdict
        )

        assert fees.RATE_CARD_TABLE in card
        assert "Final value fee:" in card
        assert "Per-order fee:" in card
        assert "\u00a36.59" in card
        assert "26.4%" in card

    def test_the_calculator_and_the_pipeline_agree_on_the_default_profile_too(self):
        calculator = fees.sale_outcome(
            24.99, supplier_cost=9.40, postage_paid=3.20, seller_type="business"
        )
        via_pipeline = calculate_profit(24.99, 9.40, shipping_cost=3.20)
        assert via_pipeline["profit"] == calculator["profit"]
        assert via_pipeline["margin"] == calculator["margin"]

    def test_the_shipped_profile_is_the_business_card_by_default(self):
        from config import SELLER_PROFILE

        assert SELLER_PROFILE["seller_type"] == "business"
        assert SELLER_PROFILE["vat_registered"] is False
        assert SELLER_PROFILE["promoted_rate"] == 0.0
        assert SELLER_PROFILE["fee_table"] is None  # None -> the engine's ACTIVE table
