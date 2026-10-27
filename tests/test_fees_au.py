"""Phase B - the eBay Australia rate card, tested against its sources.

Part 1 pins the card's provenance and reading rules before any number is
priced: the key, the version, the currency, the GST stance, the two seller
branches and the four capture IDs. The calculation tests arrive with the
sections they exercise.

Expected values are transcribed from eBay.com.au captures recorded in
docs/au-market/fee-research.md; no third-party calculator is a source.
"""

import pytest

from engine import fees

AU = fees.AU_RATE_CARD_TABLE


class TestTheAuCardIsRegisteredWithProvenance:
    def test_the_card_is_registered_under_its_page_date(self):
        table = fees.get_fee_table(AU)
        assert table["key"] == "au-rate-card-2026-10-09"
        assert fees.FEE_TABLES[AU] is table

    def test_the_table_states_a_version(self):
        table = fees.get_fee_table(AU)
        assert table["version"]
        assert "2026-10-09" in table["version"]

    def test_currency_and_tax_are_aud_and_gst(self):
        table = fees.get_fee_table(AU)
        assert table["currency"] == "AUD"
        assert table["tax_name"] == "GST"
        assert table["gst_rate"] == 10.0

    def test_the_au_domestic_region_and_defaults_are_stated(self):
        table = fees.get_fee_table(AU)
        assert table["domestic_region"] == "au"
        assert table["default_seller_type"] == "private"
        assert table["default_category_key"] == "tier-2"
        assert table["ambiguous_category_ids"] == [625, 293, 172176, 15032, 1249]

    def test_every_source_names_a_url_and_a_retrieval(self):
        """A rate without a source is a guess with a decimal point."""
        table = fees.get_fee_table(AU)
        assert len(table["sources"]) == 3
        for source in table["sources"]:
            assert source["url"] and source["url"].startswith(
                "https://www.ebay.com.au/"
            )
            assert source["retrieved"] and source["retrieved"].startswith(
                "Wayback capture 2026"
            )

    def test_the_label_source_states_why_it_has_no_page_date(self):
        label = fees.get_fee_table(AU)["sources"][2]
        assert label["page_updated"] is None
        assert "No date line" in label["date_note"]
        assert "20260908071955" in label["retrieved"]

    def test_the_card_records_its_reading_rules(self):
        notes = " ".join(fees.get_fee_table(AU)["notes"])
        assert "rowspan=4" in notes
        assert "GST at 10%" in notes
        assert "Tier 2" in notes
        assert "3.25%" in notes
        assert "label price is postage" in notes

    def test_the_uk_table_remains_the_active_one(self):
        assert fees.ACTIVE_TABLE == fees.RATE_CARD_TABLE
        assert fees.get_fee_table()["key"] == fees.RATE_CARD_TABLE


class TestTheBusinessTiersAreThePublishedOnes:
    """The tier table's numbers, including the merged Starter cell. The four
    worked examples depend on these values; a card that cannot reproduce them
    is not the published card."""

    PLANS = ("starter", "basic", "featured", "anchor")
    EXPECTED = {
        "tier-1": (13.4, 8.03, 7.26, 6.82),
        "tier-2": (13.4, 10.34, 9.68, 9.68),
        "tier-3": (13.4, 12.43, 11.22, 10.56),
        "tier-4": (13.4, 13.09, 11.77, 11.11),
    }

    @pytest.fixture()
    def categories(self):
        return fees.get_fee_table(AU)["business"]["categories"]

    @pytest.fixture()
    def by_key(self, categories):
        return {row["key"]: row for row in categories}

    def test_every_tier_carries_all_four_plans(self, by_key):
        for key in self.EXPECTED:
            assert set(by_key[key]["tiers_by_plan"]) == set(self.PLANS)

    def test_starter_is_13_4_in_every_tier(self, by_key):
        """The captured cell is rowspan=4; a plain-text scrape loses it."""
        for key in self.EXPECTED:
            assert by_key[key]["tiers_by_plan"]["starter"] == [
                (4000.0, 13.4),
                (None, 2.5),
            ], key

    def test_the_other_plans_keep_their_published_rates(self, by_key):
        for key, rates in self.EXPECTED.items():
            for plan, rate in zip(self.PLANS, rates):
                expected = [
                    (4000.0, rate),
                    (None, 2.5 if plan == "starter" else 2.75),
                ]
                assert by_key[key]["tiers_by_plan"][plan] == expected, (key, plan)

    def test_the_over_4000_portion_uses_the_published_plan_rates(self, by_key):
        for key in self.EXPECTED:
            for plan in self.PLANS:
                upper, percent = by_key[key]["tiers_by_plan"][plan][-1]
                assert upper is None
                assert percent == (2.5 if plan == "starter" else 2.75), (key, plan)

    def test_category_ids_are_unique_across_rows_and_are_real_ids(self, categories):
        seen = [cid for row in categories for cid in row["category_ids"]]
        assert len(seen) == len(set(seen))
        assert all(isinstance(cid, int) and cid > 0 for cid in seen)

    def test_the_ambiguous_parents_are_never_priced_by_a_tier(self, categories):
        """625/293/172176/15032/1249 head both Tier 1 and Tier 4; assigning
        one to either tier would be a guess."""
        table = fees.get_fee_table(AU)
        priced = {cid for row in categories for cid in row["category_ids"]}
        for parent in table["ambiguous_category_ids"]:
            assert parent not in priced

    def test_tier_1_pins_its_published_leaves(self, by_key):
        ids = set(by_key["tier-1"]["category_ids"])
        assert 20710 in ids  # Home Appliances
        assert 28179 in ids  # Camera > Binoculars & Telescopes
        assert 139971 in ids  # Video Game Consoles
        assert 625 not in ids and 293 not in ids and 1249 not in ids

    def test_tier_3_is_vehicle_parts_and_accessories(self, by_key):
        assert by_key["tier-3"]["category_ids"] == [131090]

    def test_tier_4_pins_its_published_leaves(self, by_key):
        ids = set(by_key["tier-4"]["category_ids"])
        assert 20081 in ids  # Antiques
        assert 11450 in ids  # Clothing, Shoes & Accessories
        assert 888 in ids  # Sporting Goods
        assert 15200 in ids  # Camera, Drone & Photo Accessories
        assert 58058 in ids  # Computers heading, named only by Tier 4
        assert 625 not in ids and 293 not in ids and 1249 not in ids

    def test_tier_2_is_the_stated_default_row(self, by_key):
        table = fees.get_fee_table(AU)
        assert by_key["tier-2"]["category_ids"] == []
        assert table["default_category_key"] == "tier-2"
        assert "stated default" in " ".join(by_key["tier-2"]["notes"])

    def test_nfts_are_a_flat_five_and_a_half_percent(self, by_key):
        nfts = by_key["nfts"]
        assert nfts["category_ids"] == []
        for plan in self.PLANS:
            assert nfts["tiers_by_plan"][plan] == [(None, 5.5)]
        assert any("category IDs" in note for note in nfts["notes"])

    def test_services_are_a_flat_forty_four_dollars(self, by_key):
        services = by_key["services"]
        assert services["category_ids"] == [316]
        assert services["flat_fee"] == 44.0
        assert "tiers_by_plan" not in services

    def test_every_tier_list_ends_open_ended(self, by_key):
        for key in self.EXPECTED:
            for plan in self.PLANS:
                tiers = by_key[key]["tiers_by_plan"][plan]
                assert tiers[-1][0] is None, (key, plan)
