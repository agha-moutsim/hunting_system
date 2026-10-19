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

from engine import fees


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
