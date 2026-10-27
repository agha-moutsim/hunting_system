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
