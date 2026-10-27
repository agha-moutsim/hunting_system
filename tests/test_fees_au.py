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


class TestTheProPlansAndTheirCharges:
    @pytest.fixture()
    def business(self):
        return fees.get_fee_table(AU)["business"]

    def test_four_plans_with_the_published_monthly_fees(self, business):
        plans = business["plans"]
        assert set(plans) == {"starter", "basic", "featured", "anchor"}
        assert plans["starter"]["label"] == "Pro Starter"
        assert plans["starter"]["monthly_fee"] == 0.0
        assert plans["basic"]["monthly_fee"] == 27.45
        assert plans["featured"]["monthly_fee"] == 82.45
        assert plans["anchor"]["monthly_fee"] == 604.95

    def test_starter_is_the_default_plan(self, business):
        assert business["default_plan"] == "starter"

    def test_per_order_fee_is_thirty_cents_on_starter_and_thirty_three_above(
        self, business
    ):
        plans = business["plans"]
        assert plans["starter"]["per_order_fee"] == 0.30
        for plan in ("basic", "featured", "anchor"):
            assert plans[plan]["per_order_fee"] == 0.33, plan

    def test_plan_over_4000_metadata_matches_every_tier(self, business):
        for plan, meta in business["plans"].items():
            for row in business["categories"]:
                tiers = row.get("tiers_by_plan")
                if not tiers or row["key"] == "nfts":
                    # NFTs are a flat 5.5% row outside the tier table; the
                    # over-$4,000 step does not apply to them.
                    continue
                assert tiers[plan][-1] == (None, meta["over_4000_percent"]), (
                    row["key"],
                    plan,
                )

    def test_the_listing_allowance_and_excess_fees_are_published(self, business):
        guidance = business["listing_fee_guidance"]
        assert guidance["free_listings_per_month"] == 250000
        assert guidance["excess_listing_by_plan"] == {
            "starter": 1.00,
            "basic": 0.06,
            "featured": 0.06,
            "anchor": 0.06,
        }
        assert guidance["second_category_by_plan"] == {
            "starter": 1.00,
            "basic": 0.06,
            "featured": 0.06,
            "anchor": 0.06,
        }

    def test_the_subtitle_price_is_carried_but_its_plan_is_flagged(self, business):
        guidance = business["listing_fee_guidance"]
        assert guidance["subtitle"] == 2.20
        assert "unstated" in guidance["subtitle_plan_attribution"]

    def test_buy_it_now_and_scheduled_listing_steps_are_carried(self, business):
        guidance = business["listing_fee_guidance"]
        assert guidance["buy_it_now_auction"]["starter"] == {
            "most_categories": 0.0,
            "small_categories": 0.11,
        }
        assert guidance["buy_it_now_auction"]["basic"]["small_categories"] == 0.55
        assert guidance["scheduled_listing"] == {
            "most_categories": 0.0,
            "small_categories": 0.44,
        }
        assert 316 in guidance["small_categories"]
        assert 11759 in guidance["small_categories"]

    def test_the_pro_international_fee_is_one_point_one_percent(self, business):
        assert business["international_fee_percent"] == 1.1
        assert "outside Australia" in business["international_fee_note"]

    def test_performance_fees_are_a_percent_not_percentage_points(self):
        perf = fees.get_fee_table(AU)["performance_fees"]
        assert perf["below_standard_percent"] == 5.5
        assert perf["below_standard_percent_after_4_months"] == 6.6
        assert perf["very_high_inr_percent"] == 5.5
        assert perf["very_high_inr_percent_after_4_months"] == 6.6
        assert "not percentage points" in perf["shape"]
        assert perf["both_apply"] == "only the Below Standard fee is charged"

    def test_the_dispute_fee_and_currency_conversion_are_carried(self):
        table = fees.get_fee_table(AU)
        assert table["dispute_fee"] == 24.20
        conversion = table["currency_conversion"]
        assert conversion["percent_until_2026-10-31"] == 3.0
        assert conversion["percent_from_2026-11-01"] == 3.25
        assert conversion["effective_from"] == "2026-11-01"
        assert "domestic AUD sale" in conversion["note"]

    def test_the_pro_branch_names_what_it_does_not_price(self, business):
        assert "Motors" in business["excludes"]
        assert "eBay Live" in business["excludes"]
        notes = " ".join(business["notes"])
        assert "GST at 10%" in notes
        assert "per order" in notes
        assert "higher of the two" in notes


class TestTheFreeSellingBranch:
    @pytest.fixture()
    def private(self):
        return fees.get_fee_table(AU)["private"]

    def test_an_au_individual_pays_no_final_value_fee(self, private):
        assert private["au_resident"] is True
        assert private["fvf_percent"] == 0.0
        assert private["fees_include_gst"] is True

    def test_a_per_order_fee_is_absent_not_assumed_zero(self, private):
        assert private["per_order_fee"] is None
        notes = " ".join(private["notes"])
        assert "does not state a per-order fee" in notes
        assert "absent rather than assuming zero" in notes

    def test_the_listing_allowance_and_upgrade_prices_are_carried(self, private):
        assert private["free_listings_per_month"] == 250000
        assert private["listing_fee_after_allowance"] == 1.00
        assert private["second_category_fee"] == 1.00
        assert private["subtitle"] == 2.20
        guidance = private["listing_fee_guidance"]
        assert guidance["excess_listing"] == 1.00
        assert guidance["buy_it_now_auction"]["small_categories"] == 0.11
        assert guidance["scheduled_listing"]["small_categories"] == 0.44

    def test_the_free_selling_international_fee_is_three_percent(self, private):
        assert private["international_fee_percent"] == 3.0
        assert "outside Australia" in private["international_fee_note"]

    def test_eligibility_is_the_published_twenty_five_thousand_threshold(self, private):
        eligibility = private["free_selling_eligibility"]
        assert eligibility["max_annual_sales_aud"] == 25000.0
        assert "12 full calendar months" in eligibility["measurement"]
        assert len(eligibility["requirements"]) == 3
        assert "Pro Starter" in eligibility["over_threshold"]

    def test_the_label_mandate_carries_its_four_exceptions(self, private):
        rules = private["label_required"]
        assert rules["price_exception_below"] == 20.0
        assert rules["price_exception_above"] == 5000.0
        assert rules["local_pickup_exception"] is True
        assert rules["label_unavailable_examples"] == ["heavy or bulky items"]
        assert rules["envelope_eligible_types"] == [
            "trading cards",
            "comics",
            "magazines",
            "coins and banknotes",
            "jewellery",
            "CDs/DVDs/video games",
            "patches",
            "postcards",
            "greeting cards",
            "seeds",
            "stamps",
            "stickers",
            "decals",
        ]
        assert "exactly $20.00" in rules["boundary_reading"]
        assert "exactly $5,000.00" in rules["boundary_reading"]
        assert "postage, not an eBay fee" in rules["note"]

    def test_the_free_selling_branch_names_what_it_does_not_price(self, private):
        assert "Motors" in private["excludes"]
        assert "eBay Live" in private["excludes"]
        notes = " ".join(private["notes"])
        assert "GST at 10%" in notes
        assert "3 November 2026" in notes
        assert "11 November 2026" in notes


class TestTheLabelMandatePredicate:
    """The rule, not a fee: when it applies, the label's price is postage."""

    def _decide(self, price, **kw):
        kw.setdefault("envelope_eligible", False)
        kw.setdefault("label_available", True)
        kw.setdefault("local_pickup", False)
        return fees.label_required(price, fee_table=AU, **kw)

    @pytest.mark.parametrize(
        "price,expected",
        [(19.99, False), (20.00, True), (5000.00, True), (5000.01, False)],
    )
    def test_the_price_boundaries_are_inclusive_at_20_and_5000(self, price, expected):
        result = self._decide(price)
        assert result["required"] is expected
        assert result["price"] == price
        assert result["currency"] == "AUD"

    def test_an_envelope_eligible_item_is_excepted(self):
        result = self._decide(100.0, envelope_eligible=True)
        assert result["required"] is False
        assert "envelope" in result["reason"]

    def test_a_heavy_or_bulky_item_with_no_label_is_excepted(self):
        result = self._decide(100.0, label_available=False)
        assert result["required"] is False
        assert "heavy or bulky" in result["reason"]

    def test_local_pickup_is_excepted(self):
        result = self._decide(100.0, local_pickup=True)
        assert result["required"] is False
        assert "local pickup" in result["reason"]

    def test_a_normal_item_in_range_is_required(self):
        result = self._decide(100.0)
        assert result["required"] is True
        assert "none of the four exceptions" in result["reason"]

    def test_the_uk_table_has_no_label_mandate(self):
        result = fees.label_required(100.0)
        assert result["required"] is None
        assert "no label mandate" in result["reason"]
        assert result["currency"] == "GBP"

    def test_an_unread_price_is_not_decided(self):
        result = fees.label_required(None, fee_table=AU)
        assert result["required"] is None
        assert "unread" in result["reason"]
        assert result["price"] is None

    def test_nan_and_negative_prices_are_refused_not_decided(self):
        nan = fees.label_required(float("nan"), fee_table=AU)
        assert nan["required"] is None
        assert "NaN" in nan["reason"]
        negative = fees.label_required(-1.0, fee_table=AU)
        assert negative["required"] is None
        assert "greater than zero" in negative["reason"]

    def test_omitted_item_facts_are_stated_as_assumptions(self):
        result = fees.label_required(100.0, fee_table=AU)
        assert result["required"] is True
        assert len(result["assumptions"]) == 3
        joined = " ".join(result["assumptions"])
        assert "assumed not envelope-eligible" in joined
        assert "assumed available" in joined
        assert "assumed not selected" in joined

    def test_stated_item_facts_leave_no_assumptions(self):
        result = self._decide(100.0)
        assert result["assumptions"] == []


class TestGstIsIncludedNotAdded:
    """AU fees are displayed GST-inclusive; a GST-on-fees line would double
    count. The UK card's VAT behaviour must remain exactly as it was."""

    def test_au_private_fees_carry_gst_inside_the_quoted_total(self):
        result = fees.calculate_fees(100.0, seller_type="private", fee_table=AU)
        assert result["tax"] == {"name": "GST", "rate": 10.0, "included": True}
        assert result["vat_on_fees"] is None
        assert result["vat_recoverable"] is False
        assert result["fees_quoted_total"] == 0.0
        assert result["fees_gross_total"] == 0.0
        assert result["fees_cost_total"] == 0.0
        assert "inclusive of GST" in result["vat_note"]
        assert "no GST is added" in result["vat_note"]

    def test_postage_does_not_create_a_gst_line(self):
        result = fees.calculate_fees(
            100.0,
            postage_charged=10.0,
            seller_type="private",
            fee_table=AU,
        )
        assert result["total_amount_of_sale"] == 110.0
        assert result["fees_quoted_total"] == 0.0
        assert result["vat_on_fees"] is None

    def test_the_uk_business_card_still_adds_vat(self):
        result = fees.calculate_fees(100.0, seller_type="business")
        assert result["tax"] == {"name": "VAT", "rate": 20.0, "included": False}
        assert result["vat_on_fees"] > 0
        assert "20% VAT is added" in result["vat_note"]

    def test_the_uk_private_card_is_still_vat_inclusive(self):
        result = fees.calculate_fees(100.0, seller_type="private")
        assert result["tax"] == {"name": "VAT", "rate": 20.0, "included": True}
        assert result["vat_on_fees"] is None
        assert "inclusive of VAT" in result["vat_note"]
