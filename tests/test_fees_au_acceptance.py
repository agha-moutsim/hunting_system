"""Phase B acceptance - the AU rate card end to end.

These tests do not re-derive the table. They pin the four worked examples
eBay publishes, the refusals that keep the card from guessing, and the
agreement between the calculator, the money layer and the reverse solver.
A card that passes these is selectable; Phase C decides when it is active.
"""

import pytest

from engine import fees

AU = fees.AU_RATE_CARD_TABLE


class TestTheFourPublishedExamples:
    @pytest.mark.parametrize(
        "sale_price,category,plan,expected_total",
        [
            (20.0, "tier-2", "starter", 2.98),
            (300.0, 20710, "basic", 24.42),
            (150.0, 131090, "featured", 17.16),
            (5200.0, 888, "anchor", 477.73),
        ],
    )
    def test_the_engine_reproduces_the_pages_own_totals(
        self, sale_price, category, plan, expected_total
    ):
        result = fees.calculate_fees(
            sale_price,
            seller_type="business",
            seller_plan=plan,
            category=category,
            fee_table=AU,
        )
        assert result["fees_quoted_total"] == pytest.approx(
            expected_total, abs=0.005
        )
        assert result["fees_cost_total"] == pytest.approx(
            expected_total, abs=0.005
        )
        assert result["tax"] == {"name": "GST", "rate": 10.0, "included": True}
        assert result["vat_on_fees"] is None
        assert result["seller"]["plan"] == plan
        assert result["category"]["known"] is True


class TestTheCardRefusesToGuess:
    def test_an_unresolved_category_is_the_stated_tier_2_default(self):
        result = fees.calculate_fees(
            20.0, seller_type="business", fee_table=AU
        )
        assert result["category"]["key"] == "tier-2"
        assert result["category"]["known"] is False
        assert any("No category identified" in a for a in result["assumptions"])

    def test_an_ambiguous_parent_is_never_assigned_to_one_tier(self):
        result = fees.calculate_fees(
            20.0, seller_type="business", category=625, fee_table=AU
        )
        assert result["category"]["key"] == "tier-2"
        assert result["category"]["known"] is False
        assert result["category"]["ambiguous_parent"] is True

    def test_an_unknown_plan_is_refused(self):
        with pytest.raises(ValueError) as err:
            fees.calculate_fees(
                20.0,
                seller_type="business",
                seller_plan="platinum",
                fee_table=AU,
            )
        assert "expected one of" in str(err.value)

    def test_an_unknown_delivery_region_is_refused(self):
        with pytest.raises(ValueError) as err:
            fees.calculate_fees(20.0, buyer_region="mars", fee_table=AU)
        assert "unknown buyer_region" in str(err.value)

    def test_an_unread_price_is_refused(self):
        with pytest.raises(ValueError) as err:
            fees.calculate_fees(None, fee_table=AU)
        assert "sale_price is required" in str(err.value)

    def test_the_label_predicate_does_not_decide_an_unread_price(self):
        result = fees.label_required(None, fee_table=AU)
        assert result["required"] is None
        assert "unread" in result["reason"]

    def test_the_uk_card_carries_no_label_mandate(self):
        result = fees.label_required(100.0)
        assert result["required"] is None
        assert "no label mandate" in result["reason"]

    def test_the_au_card_does_not_price_a_non_resident_private_seller(self):
        with pytest.raises(ValueError) as err:
            fees.calculate_fees(
                100.0,
                seller_type="private",
                uk_resident=False,
                fee_table=AU,
            )
        assert "non-resident" in str(err.value)


class TestTheLayersAgree:
    def test_forward_and_reverse_paths_agree_on_an_au_sale(self):
        solved = fees.solve_for_margin(
            25.0,
            supplier_cost=8.0,
            seller_type="business",
            seller_plan="basic",
            category=131090,
            fee_table=AU,
        )
        assert solved["achievable"] is True
        outcome = fees.sale_outcome(
            solved["price"],
            supplier_cost=8.0,
            seller_type="business",
            seller_plan="basic",
            category=131090,
            fee_table=AU,
        )
        assert outcome["fees"]["fees_cost_total"] == pytest.approx(
            solved["check"]["fees_cost_total"], abs=0.02
        )
        assert outcome["margin"] == pytest.approx(25.0, abs=0.2)

    def test_the_money_layer_uses_the_same_fee_total(self):
        direct = fees.calculate_fees(
            300.0,
            seller_type="business",
            seller_plan="basic",
            category=20710,
            fee_table=AU,
        )
        outcome = fees.sale_outcome(
            300.0,
            supplier_cost=10.0,
            seller_type="business",
            seller_plan="basic",
            category=20710,
            fee_table=AU,
        )
        assert outcome["fees"]["fees_cost_total"] == pytest.approx(
            direct["fees_cost_total"], abs=0.005
        )

    def test_an_au_business_sale_has_no_gst_on_fees_line(self):
        outcome = fees.sale_outcome(
            20.0,
            supplier_cost=5.0,
            seller_type="business",
            seller_plan="starter",
            category="tier-2",
            fee_table=AU,
        )
        labels = [line["label"] for line in outcome["fee_lines"]]
        assert "Final value fee" in labels
        assert "Per-order fee" in labels
        assert "VAT on fees" not in labels
        assert "GST on fees" not in labels

    def test_an_au_private_sale_is_a_stated_zero_not_a_missing_fee(self):
        outcome = fees.sale_outcome(
            100.0,
            supplier_cost=20.0,
            seller_type="private",
            fee_table=AU,
        )
        assert outcome["fees"]["fvf"] == 0.0
        assert outcome["fees"]["per_order_fee"] is None
        assert outcome["fees"]["fees_quoted_total"] == 0.0
        assert outcome["fees"]["tax"]["included"] is True
        labels = [line["label"] for line in outcome["fee_lines"]]
        assert "Final value fee" in labels
        assert "Per-order fee" not in labels
        assert "VAT on fees" not in labels

    def test_the_label_rule_never_adds_a_fee_line(self):
        outcome = fees.sale_outcome(
            100.0,
            supplier_cost=20.0,
            seller_type="private",
            fee_table=AU,
        )
        labels = [line["label"].lower() for line in outcome["fee_lines"]]
        assert all("label" not in label for label in labels)
        decision = fees.label_required(
            100.0,
            envelope_eligible=False,
            label_available=True,
            local_pickup=False,
            fee_table=AU,
        )
        assert decision["required"] is True
        assert "postage, not an eBay fee" in fees.get_fee_table(AU)[
            "private"
        ]["label_required"]["note"]


class TestTheCardIsSelectableButNotActiveYet:
    def test_the_uk_card_is_still_the_default(self):
        assert fees.ACTIVE_TABLE == fees.RATE_CARD_TABLE
        assert fees.get_fee_table()["key"] == fees.RATE_CARD_TABLE

    def test_the_au_card_is_registered_and_selectable(self):
        assert fees.get_fee_table(AU)["key"] == AU
        assert AU in fees.FEE_TABLES

    def test_list_categories_and_resolve_category_agree(self):
        table = fees.get_fee_table(AU)
        rows = fees.list_categories(table)
        assert {row["key"] for row in rows} == {
            "tier-1",
            "tier-2",
            "tier-3",
            "tier-4",
            "nfts",
            "services",
        }
        for row in rows:
            resolved, known = fees.resolve_category(row["key"], table)
            assert known is True
            assert resolved["key"] == row["key"]

    def test_the_card_keeps_both_currency_conversion_dates(self):
        conversion = fees.get_fee_table(AU)["currency_conversion"]
        assert conversion["percent_until_2026-10-31"] == 3.0
        assert conversion["percent_from_2026-11-01"] == 3.25
        assert conversion["effective_from"] == "2026-11-01"
