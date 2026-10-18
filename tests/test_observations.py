"""Phase B - rich field persistence: the extractor, the table, the wiring.

No network anywhere. The extractor is pinned against a payload whose shape was
copied from a live Browse response (not imagined), the store runs against a
throwaway SQLite database, the scraper's sink is exercised with a stubbed
`_api_get`, and the History replay goes through the real FastAPI app with the
session factory swapped out.

The point of the phase is that these fields were already in hand and were being
discarded, so the tests are mostly about what a NULL means: every one of them
asserts that "eBay did not return this" never turns into 0, False or an epoch.
"""

import json
import time
from datetime import datetime

import pytest

from scrapers.base import ScrapedProduct
from scrapers.browse_fields import (
    COMPARED,
    FIELDS,
    SOURCE_ITEM,
    SOURCE_SUMMARY,
    extract_observation,
    is_change,
    listing_id_of,
)
from scrapers.ebay_deals import DealItem, EbayDealsScraper

# ---------------------------------------------------------------------------
# The measured payload.
#
# Trimmed to the fields this phase keeps, but not invented: every key and every
# VALUE (including the ones that are absent) was read off a live
# `get_item_by_legacy_id` response for deals listing 116529177245 on 2026-10-19.
# Two of these values are the reason the extractor looks the way it does -
# `feedbackPercentage` is a STRING, and `itemLocation` has no postalCode.
# ---------------------------------------------------------------------------
LIVE_PAYLOAD = {
    "legacyItemId": "116529177245",
    "title": "Dyson Ball Animal - Refurbished",
    "itemCreationDate": "2025-03-21T15:44:11.000Z",
    "conditionId": "2020",
    "condition": "Very Good - Refurbished",
    "topRatedBuyingExperience": False,
    "priorityListing": True,
    "buyingOptions": ["FIXED_PRICE"],
    "categoryId": "177017",
    "categoryPath": "Home, Furniture & DIY|Appliances|Vacuum Cleaners",
    "price": {"value": "169.00", "currency": "GBP"},
    "seller": {
        "username": "dyson_outlet",
        "feedbackPercentage": "99.1",
        "feedbackScore": 152255,
        "sellerAccountType": "BUSINESS",
    },
    "itemLocation": {"city": "UK", "country": "GB"},
    "shippingOptions": [
        {
            "type": "Standard Delivery",
            "shippingCost": {"value": "0.00", "currency": "GBP"},
            "shippingCostType": "FIXED",
        }
    ],
}

NO_PRICE_PAYLOAD = {k: v for k, v in LIVE_PAYLOAD.items() if k != "price"}


def _fresh_session_factory(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db.database import Base
    import db.models  # noqa: F401 - registers every table on Base.metadata

    engine = create_engine(f"sqlite:///{tmp_path / 'observations.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


# ---------------------------------------------------------------------------
# 1. The extractor
# ---------------------------------------------------------------------------

class TestExtractObservation:
    def test_it_reads_the_values_that_were_actually_there(self):
        reading = extract_observation(LIVE_PAYLOAD)
        assert reading["seller_username"] == "dyson_outlet"
        assert reading["seller_account_type"] == "BUSINESS"
        assert reading["item_city"] == "UK"
        assert reading["item_country"] == "GB"
        assert reading["condition_id"] == "2020"
        assert reading["condition_text"] == "Very Good - Refurbished"
        assert reading["shipping_type"] == "Standard Delivery"
        assert reading["buying_options"] == ["FIXED_PRICE"]
        assert reading["price"] == 169.0
        assert reading["currency"] == "GBP"

    def test_the_creation_date_is_normalised_to_naive_utc(self):
        assert extract_observation(LIVE_PAYLOAD)["item_creation_date"] == datetime(
            2025, 3, 21, 15, 44, 11
        )

    def test_feedback_percentage_is_read_from_the_string_eBay_actually_sends(self):
        """MEASURED: `feedbackPercentage` is the string "99.1" while
        `feedbackScore` is the integer 152255. Assuming one type would have
        stored NULL for half the sellers and never raised."""
        reading = extract_observation(LIVE_PAYLOAD)
        assert reading["seller_feedback_percentage"] == 99.1
        assert isinstance(reading["seller_feedback_percentage"], float)
        assert reading["seller_feedback_score"] == 152255

    def test_a_field_eBay_did_not_return_is_null_and_never_a_default(self):
        """itemOriginDate, itemGroupType, seller.storeName and
        itemLocation.postalCode were all ABSENT on the measured payload."""
        reading = extract_observation(LIVE_PAYLOAD)
        assert reading["item_origin_date"] is None
        assert reading["item_group_type"] is None
        assert reading["seller_store_name"] is None
        assert reading["item_postal_code"] is None

    def test_an_entirely_empty_payload_is_a_row_of_nulls_not_an_error(self):
        for payload in ({}, None, "not a payload", []):
            reading = extract_observation(payload)
            assert set(reading) == set(FIELDS)
            assert all(value is None for value in reading.values())

    def test_absent_is_not_false_for_the_flags(self):
        """A missing flag must not read as a denial: "eBay did not say" and
        "eBay says no" are different facts."""
        assert extract_observation({})["top_rated"] is None
        assert extract_observation(LIVE_PAYLOAD)["top_rated"] is False
        assert extract_observation(LIVE_PAYLOAD)["priority_listing"] is True

    def test_a_real_zero_is_not_the_same_as_a_missing_value(self):
        assert extract_observation(LIVE_PAYLOAD)["shipping_cost"] == 0.0
        assert extract_observation(LIVE_PAYLOAD)["shipping_currency"] == "GBP"
        assert extract_observation({})["shipping_cost"] is None

        free = {"price": {"value": "0.00", "currency": "GBP"}}
        assert extract_observation(free)["price"] == 0.0

    def test_an_empty_string_is_treated_as_not_returned(self):
        """eBay sends "" for a field it did not fill in. Recording that
        separately from absent would make a reading look changed when nothing
        was."""
        blank = {"seller": {"username": "", "sellerAccountType": "   "}}
        reading = extract_observation(blank)
        assert reading["seller_username"] is None
        assert reading["seller_account_type"] is None

    def test_unparseable_values_become_null_rather_than_defaults(self):
        junk = {
            "itemCreationDate": "not-a-date",
            "itemOriginDate": "31/02/2025",
            "seller": {"feedbackPercentage": "n/a", "feedbackScore": "many"},
            "price": {"value": "free", "currency": "GBP"},
        }
        reading = extract_observation(junk)
        assert reading["item_creation_date"] is None
        assert reading["item_origin_date"] is None
        assert reading["seller_feedback_percentage"] is None
        assert reading["seller_feedback_score"] is None
        assert reading["price"] is None
        # The currency was still returned, so it is still kept.
        assert reading["currency"] == "GBP"

    def test_the_category_comes_from_the_shape_that_actually_fires(self):
        """On the measured payload BOTH `categories` and `leafCategoryIds` were
        absent, so the top-level `categoryId` is the path that produced a value.
        The other two shapes are still honoured when eBay sends them."""
        measured = extract_observation(LIVE_PAYLOAD)
        assert measured["category_id"] == "177017"
        assert measured["category_name"] == (
            "Home, Furniture & DIY|Appliances|Vacuum Cleaners"
        )

        with_categories = extract_observation(
            {"categories": [{"categoryId": "9", "categoryName": "Vacuum Parts"}]}
        )
        assert with_categories["category_id"] == "9"
        assert with_categories["category_name"] == "Vacuum Parts"

        leaves_only = extract_observation({"leafCategoryIds": ["11", "12"]})
        assert leaves_only["category_id"] == "11"
        assert leaves_only["category_name"] is None

    def test_a_bare_formatted_price_string_is_still_a_price(self):
        """The two item endpoints are not consistent about the price shape."""
        reading = extract_observation({"price": "£12.99"})
        assert reading["price"] == 12.99
        assert reading["currency"] == "GBP"

    def test_the_extractor_needs_no_session_and_no_clock(self):
        """Purity is the reason this is testable at all: same input, same
        output, nothing attached."""
        assert extract_observation(json.loads(json.dumps(LIVE_PAYLOAD))) == (
            extract_observation(LIVE_PAYLOAD)
        )


class TestIsChange:
    def test_a_first_reading_is_always_a_change(self):
        assert is_change(None, extract_observation(LIVE_PAYLOAD)) is True

    def test_an_identical_reading_is_not_a_change(self):
        reading = extract_observation(LIVE_PAYLOAD)
        stored = dict(reading, source=SOURCE_ITEM)
        assert is_change(stored, dict(stored)) is False

    def test_a_moved_price_is_a_change(self):
        previous = extract_observation(LIVE_PAYLOAD)
        moved = extract_observation({**LIVE_PAYLOAD, "price": {"value": "149.00"}})
        assert is_change(dict(previous, source=SOURCE_ITEM), dict(moved)) is True

    def test_a_field_going_missing_is_also_a_change(self):
        """eBay withdrawing a field is information: the reading now says less."""
        previous = extract_observation(LIVE_PAYLOAD)
        without = extract_observation(NO_PRICE_PAYLOAD)
        assert is_change(dict(previous, source=SOURCE_ITEM), dict(without)) is True

    def test_the_compared_set_covers_every_field_plus_provenance(self):
        assert set(COMPARED) == set(FIELDS) | {"source"}

    def test_a_different_source_alone_counts_as_a_change(self):
        """A search-summary reading carries different NULLs from an item
        reading, and a row's provenance should be true of that row."""
        reading = extract_observation(LIVE_PAYLOAD)
        assert is_change(
            dict(reading, source=SOURCE_SUMMARY), dict(reading, source=SOURCE_ITEM)
        ) is True


# ---------------------------------------------------------------------------
# 2. The store
# ---------------------------------------------------------------------------

class TestTheStore:
    def test_a_new_listing_records_one_reading(self, tmp_path):
        from db.queries import get_listing_observations, save_listing_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            counts = save_listing_observations(
                session,
                [("116529177245", LIVE_PAYLOAD, SOURCE_ITEM)],
                observed_at=datetime(2026, 10, 19, 12, 0, 0),
            )
            assert counts == {
                "readings": 1,
                "recorded": 1,
                "unchanged": 0,
                "empty": 0,
                "duplicate": 0,
            }

            rows = get_listing_observations(session, "116529177245")
            assert len(rows) == 1
            assert rows[0].seller_account_type == "BUSINESS"
            assert rows[0].seller_feedback_percentage == 99.1
            assert rows[0].shipping_cost == 0.0
            assert rows[0].item_creation_date == datetime(2025, 3, 21, 15, 44, 11)
            assert rows[0].observed_at == datetime(2026, 10, 19, 12, 0, 0)
        finally:
            session.close()

    def test_the_columns_that_eBay_left_empty_are_still_null_in_storage(
        self, tmp_path
    ):
        from db.queries import get_listing_observations, save_listing_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            save_listing_observations(
                session, [("116529177245", LIVE_PAYLOAD, SOURCE_ITEM)]
            )
            row = get_listing_observations(session, "116529177245")[0]
            assert row.item_origin_date is None
            assert row.item_group_type is None
            assert row.seller_store_name is None
            assert row.item_postal_code is None
        finally:
            session.close()

    def test_an_unchanged_listing_is_not_stored_again(self, tmp_path):
        """An hourly refresh of a stable board must not write 1,752 identical
        rows a day, and every stored row should mean something happened."""
        from db.models import ListingObservation
        from db.queries import save_listing_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            save_listing_observations(
                session, [("116529177245", LIVE_PAYLOAD, SOURCE_ITEM)]
            )
            for _ in range(5):
                counts = save_listing_observations(
                    session, [("116529177245", LIVE_PAYLOAD, SOURCE_ITEM)]
                )
                assert counts["recorded"] == 0
                assert counts["unchanged"] == 1

            assert session.query(ListingObservation).count() == 1
        finally:
            session.close()

    def test_a_changed_price_becomes_its_own_row_and_history_keeps_order(
        self, tmp_path
    ):
        from db.queries import get_listing_observations, save_listing_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            save_listing_observations(
                session,
                [("116529177245", LIVE_PAYLOAD, SOURCE_ITEM)],
                observed_at=datetime(2026, 10, 19, 12, 0, 0),
            )
            cheaper = {**LIVE_PAYLOAD, "price": {"value": "149.00", "currency": "GBP"}}
            save_listing_observations(
                session,
                [("116529177245", cheaper, SOURCE_ITEM)],
                observed_at=datetime(2026, 10, 19, 13, 0, 0),
            )

            rows = get_listing_observations(session, "116529177245")
            assert [r.price for r in rows] == [149.0, 169.0]  # newest first
        finally:
            session.close()

    def test_nothing_is_ever_updated_or_deleted(self, tmp_path):
        """Append-only is the whole value of the table: a reading that can be
        overwritten cannot show that anything changed."""
        from db.models import ListingObservation
        from db.queries import save_listing_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            for price in ("169.00", "159.00", "149.00"):
                payload = {**LIVE_PAYLOAD, "price": {"value": price}}
                save_listing_observations(
                    session, [("116529177245", payload, SOURCE_ITEM)]
                )
            assert session.query(ListingObservation).count() == 3
        finally:
            session.close()

    def test_an_unreadable_payload_is_counted_as_empty_and_never_stored(
        self, tmp_path
    ):
        """Storing it would claim eBay reported nothing, when in fact nothing
        was read (C1)."""
        from db.models import ListingObservation
        from db.queries import save_listing_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            counts = save_listing_observations(
                session,
                [
                    ("116529177245", {"errors": [{"errorId": 11006}]}, SOURCE_ITEM),
                    ("116529177246", None, SOURCE_SUMMARY),
                ],
            )
            assert counts["empty"] == 2
            assert counts["recorded"] == 0
            assert session.query(ListingObservation).count() == 0
        finally:
            session.close()

    def test_one_listing_is_read_once_per_batch(self, tmp_path):
        """MEASURED on live data, and the reason this rule exists.

        The same listing came back from two different Browse queries in one
        refresh, reporting `priorityListing` True in one and False in the other.
        Both were stored with the same `observed_at` - a change that never
        happened, because no time passed - and each then differed from the
        latest row, so every later refresh wrote two more rows, forever.
        """
        from db.models import ListingObservation
        from db.queries import get_listing_observations, save_listing_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            reported_promoted = {**LIVE_PAYLOAD, "priorityListing": True}
            reported_organic = {**LIVE_PAYLOAD, "priorityListing": False}
            batch = [
                ("116529177245", reported_promoted, SOURCE_SUMMARY),
                ("116529177245", reported_organic, SOURCE_SUMMARY),
            ]

            first = save_listing_observations(
                session, batch, observed_at=datetime(2026, 10, 19, 12, 0, 0)
            )
            assert first["recorded"] == 1
            assert first["duplicate"] == 1

            rows = get_listing_observations(session, "116529177245")
            assert len(rows) == 1
            # The first reading of the listing is the one kept.
            assert rows[0].priority_listing is True

            # The same refresh again changes nothing - which is the whole point,
            # because this listing is on the board every hour.
            again = save_listing_observations(
                session, batch, observed_at=datetime(2026, 10, 19, 13, 0, 0)
            )
            assert again == {
                "readings": 2,
                "recorded": 0,
                "unchanged": 1,
                "empty": 0,
                "duplicate": 1,
            }
            assert session.query(ListingObservation).count() == 1
        finally:
            session.close()

    def test_an_unreadable_report_cannot_shadow_a_readable_one(self, tmp_path):
        """The duplicate rule only claims a listing once something readable has
        been extracted for it, so a junk payload cannot block the real one."""
        from db.queries import get_listing_observations, save_listing_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            counts = save_listing_observations(
                session,
                [
                    ("116529177245", {"errors": []}, SOURCE_SUMMARY),
                    ("116529177245", LIVE_PAYLOAD, SOURCE_ITEM),
                ],
            )
            assert counts["empty"] == 1
            assert counts["recorded"] == 1
            assert counts["duplicate"] == 0

            rows = get_listing_observations(session, "116529177245")
            assert len(rows) == 1
            assert rows[0].source == SOURCE_ITEM
        finally:
            session.close()

    def test_readings_for_different_listings_are_kept_apart(self, tmp_path):
        from db.queries import get_listing_observations, save_listing_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            save_listing_observations(
                session,
                [
                    ("116529177245", LIVE_PAYLOAD, SOURCE_ITEM),
                    ("204925572731", {**LIVE_PAYLOAD, "price": {"value": "42.00"}},
                     SOURCE_SUMMARY),
                ],
            )
            first = get_listing_observations(session, "116529177245")
            second = get_listing_observations(session, "204925572731")
            assert [r.price for r in first] == [169.0]
            assert [r.price for r in second] == [42.0]
            assert second[0].source == SOURCE_SUMMARY
        finally:
            session.close()

    def test_a_listing_with_no_readings_returns_an_empty_list(self, tmp_path):
        from db.queries import get_listing_observations

        session = _fresh_session_factory(tmp_path)()
        try:
            assert get_listing_observations(session, "999999999999") == []
            assert get_listing_observations(session, "") == []
        finally:
            session.close()


# ---------------------------------------------------------------------------
# 3. The migration
# ---------------------------------------------------------------------------

class TestTheMigration:
    def test_the_helper_is_idempotent(self):
        from db.database import ensure_listing_observations_table

        # Whatever state the database was in, it exists after the first call...
        ensure_listing_observations_table()
        # ...and the second call is a no-op, which is what makes it safe to run
        # on every import.
        assert ensure_listing_observations_table() is False

    def test_the_table_that_exists_has_exactly_the_columns_the_model_declares(self):
        from sqlalchemy import inspect

        from db.database import engine, ensure_listing_observations_table
        from db.models import ListingObservation

        ensure_listing_observations_table()
        live = {c["name"] for c in inspect(engine).get_columns("listing_observations")}
        declared = set(ListingObservation.__table__.columns.keys())
        assert live == declared, f"model and database disagree: {live ^ declared}"

    def test_every_extracted_field_has_somewhere_to_go(self):
        """Add a field to the extractor without a column and this fails, instead
        of the field silently never being stored."""
        from db.models import ListingObservation

        declared = set(ListingObservation.__table__.columns.keys())
        assert set(FIELDS) <= declared, f"no column for: {set(FIELDS) - declared}"


class TestTheTableCannotHoldAPopularityClaim:
    """The same discipline the deals board carries, on the new table."""

    BANNED = {
        "sold_count", "sold_7d", "sold_30d", "sales", "sales_count",
        "quantity_sold", "units_sold", "watch_count", "watchers", "popularity",
        "best_seller", "hotness", "hot", "rank", "score", "trend",
        "sell_through", "search_volume", "revenue", "estimated_revenue",
    }

    def test_there_is_no_column_for_a_claim_nobody_measured(self):
        from db.models import ListingObservation

        names = set(ListingObservation.__table__.columns.keys())
        assert not (names & self.BANNED), f"unmeasurable columns: {names & self.BANNED}"

    def test_a_reading_cannot_carry_one_either(self):
        assert set(extract_observation(LIVE_PAYLOAD)).isdisjoint(self.BANNED)


# ---------------------------------------------------------------------------
# 4. The scraper's sink - the seam that spends no extra API call
# ---------------------------------------------------------------------------

def _stub_api(monkeypatch, scraper, *, item=None, search=None):
    """Answer the two Browse endpoints without a network.

    `_by_id` sends `legacy_item_id`; `_by_title` sends `q`. Dispatching on that
    is what lets a test drive one path or the other.
    """

    def fake(path, params):
        return item if "legacy_item_id" in params else search

    monkeypatch.setattr(scraper, "_api_get", fake)


def _card(listing_id="116529177245"):
    return DealItem(
        listing_id=listing_id,
        title="Dyson Ball Animal - Refurbished",
        item_url=f"https://www.ebay.co.uk/itm/{listing_id}",
    )


class TestTheScraperOffersEveryReading:
    def test_a_payload_from_the_item_endpoint_is_offered_as_an_item_reading(
        self, monkeypatch
    ):
        seen = []
        scraper = EbayDealsScraper(
            on_observation=lambda lid, payload, source: seen.append((lid, payload, source))
        )
        _stub_api(monkeypatch, scraper, item=LIVE_PAYLOAD)

        assert scraper.enrich(_card()) is True
        assert seen == [("116529177245", LIVE_PAYLOAD, SOURCE_ITEM)]

    def test_a_payload_from_the_search_fallback_says_so(self, monkeypatch):
        """Half the cards on a measured page resolve this way, and a summary
        carries fewer fields - which is what makes its NULLs interpretable."""
        summary = {**LIVE_PAYLOAD, "legacyItemId": "116529177245"}
        seen = []
        scraper = EbayDealsScraper(
            on_observation=lambda lid, payload, source: seen.append((lid, payload, source))
        )
        _stub_api(monkeypatch, scraper, item=None, search={"itemSummaries": [summary]})

        assert scraper.enrich(_card()) is True
        assert len(seen) == 1
        assert seen[0][2] == SOURCE_SUMMARY

    def test_a_card_with_no_readable_price_is_still_observed(self, monkeypatch):
        """The unpriceable card is exactly the one whose other fields are worth
        keeping, so observing must not be conditional on the price."""
        seen = []
        scraper = EbayDealsScraper(
            on_observation=lambda lid, payload, source: seen.append((lid, payload, source))
        )
        _stub_api(monkeypatch, scraper, item=NO_PRICE_PAYLOAD)

        assert scraper.enrich(_card()) is False
        assert scraper.price_failures == 1
        assert len(seen) == 1

    def test_nothing_is_offered_when_eBay_returned_nothing(self, monkeypatch):
        seen = []
        scraper = EbayDealsScraper(
            on_observation=lambda lid, payload, source: seen.append((lid, payload, source))
        )
        _stub_api(monkeypatch, scraper, item=None, search=None)

        assert scraper.enrich(_card()) is False
        assert seen == []

    def test_a_failing_sink_never_costs_the_card_its_price(self, monkeypatch):
        """Observing is a side effect. It must not be able to break the board."""

        def boom(listing_id, payload, source):
            raise RuntimeError("database is on fire")

        scraper = EbayDealsScraper(on_observation=boom)
        _stub_api(monkeypatch, scraper, item=LIVE_PAYLOAD)

        card = _card()
        assert scraper.enrich(card) is True
        assert card.price == 169.0
        assert card.seller == "dyson_outlet"

    def test_no_sink_at_all_is_fine(self, monkeypatch):
        scraper = EbayDealsScraper()
        _stub_api(monkeypatch, scraper, item=LIVE_PAYLOAD)
        assert scraper.enrich(_card()) is True


# ---------------------------------------------------------------------------
# 5. The refresh wiring
# ---------------------------------------------------------------------------

class _FakeScraper:
    """The smallest thing `refresh` can be handed: it reports its spend, returns
    its cards, and offers a reading to whatever sink was attached."""

    def __init__(self, cards, payload=None, source=SOURCE_ITEM):
        self.cards = cards
        self.payload = payload if payload is not None else LIVE_PAYLOAD
        self.source = source
        self.api_calls = 1
        self.price_failures = 0
        self.on_observation = None

    def fetch_deals(self, limit=None, enrich=True):
        for card in self.cards:
            if self.on_observation is not None:
                self.on_observation(card.listing_id, self.payload, self.source)
        return self.cards


class TestTheRefreshStoresWhatItRead:
    def test_a_refresh_records_a_reading_for_every_card_it_read(self, tmp_path):
        from db.queries import get_listing_observations
        from hunter.deals import refresh

        session = _fresh_session_factory(tmp_path)()
        try:
            cards = [_card("116529177245"), _card("204925572731")]
            result = refresh(
                session=session,
                scraper=_FakeScraper(
                    cards, payload={**LIVE_PAYLOAD, "price": {"value": "12.00"}}
                ),
            )

            assert result["observations"]["recorded"] == 2
            assert result["observations"]["unchanged"] == 0
            assert len(get_listing_observations(session, "116529177245")) == 1
            assert len(get_listing_observations(session, "204925572731")) == 1
        finally:
            session.close()

    def test_a_second_identical_refresh_records_nothing_new(self, tmp_path):
        from hunter.deals import refresh

        session = _fresh_session_factory(tmp_path)()
        try:
            scraper = _FakeScraper([_card()])
            refresh(session=session, scraper=scraper)
            again = refresh(session=session, scraper=scraper)
            assert again["observations"]["recorded"] == 0
            assert again["observations"]["unchanged"] == 1
        finally:
            session.close()

    def test_a_broken_observation_write_never_fails_the_refresh(
        self, tmp_path, monkeypatch
    ):
        """A silent failure here would look exactly like "nothing changed"."""
        from db.models import DealItem as DealItemRow
        from hunter.deals import refresh

        def boom(session, readings, observed_at=None):
            raise RuntimeError("disk full")

        monkeypatch.setattr("hunter.deals.save_listing_observations", boom)

        session = _fresh_session_factory(tmp_path)()
        try:
            result = refresh(session=session, scraper=_FakeScraper([_card()]))
            assert "error" in result["observations"]
            # The board itself still landed: observations are not load-bearing.
            assert session.query(DealItemRow).count() == 1
        finally:
            session.close()

    def test_an_unreadable_reading_is_reported_as_empty_not_as_a_change(
        self, tmp_path
    ):
        """The counts are the only signal that observations are working, so an
        unreadable payload has to show up as itself."""
        from hunter.deals import refresh

        session = _fresh_session_factory(tmp_path)()
        try:
            result = refresh(
                session=session,
                scraper=_FakeScraper([_card()], payload={"errors": []}),
            )
            assert result["observations"] == {
                "readings": 1,
                "recorded": 0,
                "unchanged": 0,
                "empty": 1,
                "duplicate": 0,
            }
        finally:
            session.close()


# ---------------------------------------------------------------------------
# 6. History replay
# ---------------------------------------------------------------------------

@pytest.fixture()
def history_client(tmp_path, monkeypatch):
    factory = _fresh_session_factory(tmp_path)
    monkeypatch.setattr("db.database.SessionLocal", factory)

    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        yield client, factory


def _product(factory, *, listing_id="116529177245"):
    from db.models import Product

    session = factory()
    try:
        product = Product(
            ebay_url=f"https://www.ebay.co.uk/itm/{listing_id or '0'}",
            ebay_listing_id=listing_id,
            title="Dyson Ball Animal - Refurbished",
            price=169.0,
        )
        session.add(product)
        session.commit()
        session.refresh(product)
        return product.id
    finally:
        session.close()


class TestHistoryReplaysWhatWasMeasured:
    def test_the_readings_are_replayed_for_the_products_listing(self, history_client):
        from db.queries import save_listing_observations

        client, factory = history_client
        product_id = _product(factory)

        session = factory()
        try:
            save_listing_observations(
                session,
                [("116529177245", LIVE_PAYLOAD, SOURCE_ITEM)],
                observed_at=datetime(2026, 10, 19, 12, 0, 0),
            )
        finally:
            session.close()

        block = client.get(f"/api/history/{product_id}").json()["observations"]
        assert block["listing_id"] == "116529177245"
        assert block["returned"] == 1

        reading = block["readings"][0]
        assert reading["seller_account_type"] == "BUSINESS"
        assert reading["seller_feedback_percentage"] == 99.1
        assert reading["seller_feedback_score"] == 152255
        assert reading["item_creation_date"] == "2025-03-21T15:44:11"
        assert reading["shipping_cost"] == 0.0
        assert reading["shipping_type"] == "Standard Delivery"
        assert reading["source"] == SOURCE_ITEM
        assert reading["observed_at"] == "2026-10-19T12:00:00"

    def test_a_null_is_replayed_as_null_not_as_a_zero(self, history_client):
        from db.queries import save_listing_observations

        client, factory = history_client
        product_id = _product(factory)

        session = factory()
        try:
            save_listing_observations(
                session, [("116529177245", LIVE_PAYLOAD, SOURCE_ITEM)]
            )
        finally:
            session.close()

        reading = client.get(f"/api/history/{product_id}").json()["observations"][
            "readings"
        ][0]
        assert reading["item_origin_date"] is None
        assert reading["item_postal_code"] is None
        assert reading["seller_store_name"] is None

    def test_every_extracted_field_is_replayed(self, history_client):
        """The replay reads its key list off the extractor, so a field cannot be
        stored and then never shown."""
        from db.queries import save_listing_observations

        client, factory = history_client
        product_id = _product(factory)

        session = factory()
        try:
            save_listing_observations(
                session, [("116529177245", LIVE_PAYLOAD, SOURCE_ITEM)]
            )
        finally:
            session.close()

        reading = client.get(f"/api/history/{product_id}").json()["observations"][
            "readings"
        ][0]
        assert set(FIELDS) <= set(reading)

    def test_a_product_that_was_never_observed_replays_an_empty_block(
        self, history_client
    ):
        client, factory = history_client
        product_id = _product(factory, listing_id="999999999999")

        block = client.get(f"/api/history/{product_id}").json()["observations"]
        assert block == {"listing_id": "999999999999", "returned": 0, "readings": []}

    def test_a_product_with_no_listing_id_does_not_invent_one(self, history_client):
        client, factory = history_client
        product_id = _product(factory, listing_id=None)

        block = client.get(f"/api/history/{product_id}").json()["observations"]
        assert block == {"listing_id": "", "returned": 0, "readings": []}


# ---------------------------------------------------------------------------
# 7. Which listing a payload belongs to
# ---------------------------------------------------------------------------

class TestListingIdOf:
    def test_the_bare_legacy_id_is_used_when_eBay_sends_it(self):
        assert listing_id_of({"legacyItemId": "116529177245"}) == "116529177245"

    def test_the_restful_item_id_yields_its_middle_segment(self):
        """`itemId` is `v1|<legacy id>|0`, so a reader that took the whole
        string would file the reading under a key no other surface uses."""
        assert listing_id_of({"itemId": "v1|116529177245|0"}) == "116529177245"
        assert listing_id_of({"itemId": "116529177245"}) == "116529177245"

    def test_the_legacy_id_wins_when_both_are_present(self):
        both = {"itemId": "v1|999999999999|0", "legacyItemId": "116529177245"}
        assert listing_id_of(both) == "116529177245"

    def test_a_payload_that_cannot_name_its_listing_is_skipped(self):
        """None rather than a placeholder: two unnameable listings must not end
        up filed under the same row."""
        for payload in ({}, {"itemId": "v1|abc|0"}, {"legacyItemId": ""}, None, []):
            assert listing_id_of(payload) is None

    def test_a_non_numeric_legacy_id_falls_back_to_the_item_id(self):
        assert listing_id_of({"legacyItemId": "junk", "itemId": "v1|123|0"}) == "123"


# ---------------------------------------------------------------------------
# 8. The analysis scraper keeps what it read
# ---------------------------------------------------------------------------

class _FakeResponse:
    """Enough of a `requests.Response` for a Browse read to proceed."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _stub_get(monkeypatch, payload):
    monkeypatch.setattr(
        "scrapers.ebay.requests.get", lambda *a, **k: _FakeResponse(payload)
    )


def _authed_scraper():
    """A scraper with a token already in hand, so no request goes out to get
    one and the tests touch no network at all."""
    from scrapers.ebay import EbayScraper

    scraper = EbayScraper()
    scraper._token = "test-token"
    scraper._token_expiry = time.time() + 3600
    return scraper


class TestTheAnalysisScraperKeepsItsReadings:
    def test_the_search_keeps_every_listing_it_was_handed(self, monkeypatch):
        scraper = _authed_scraper()
        usable = {**LIVE_PAYLOAD, "legacyItemId": "111111111111", "condition": "New"}
        _stub_get(monkeypatch, {"itemSummaries": [usable, LIVE_PAYLOAD]})

        scraper._search_api("dyson ball animal", limit=10, price_band=None)

        assert [r[0] for r in scraper.observations] == [
            "111111111111",
            "116529177245",
        ]
        assert all(r[2] == SOURCE_SUMMARY for r in scraper.observations)

    def test_the_search_still_gates_what_it_returns(self, monkeypatch):
        """Keeping readings must not have moved the C10 gate: the refurbished
        listing is still not a result, even though it is now a reading."""
        scraper = _authed_scraper()
        usable = {
            **LIVE_PAYLOAD,
            "legacyItemId": "111111111111",
            "condition": "New",
            "title": "The New One",
        }
        _stub_get(monkeypatch, {"itemSummaries": [usable, LIVE_PAYLOAD]})

        results = scraper._search_api("dyson ball animal", limit=10, price_band=None)

        assert [p.title for p in results] == ["The New One"]

    def test_the_sold_query_keeps_listings_its_own_gates_reject(self, monkeypatch):
        """The band and condition gates decide what competes with this product.
        They do not make a listing un-read: eBay returned it, so it was seen."""
        scraper = _authed_scraper()
        used_and_way_over_band = {
            **LIVE_PAYLOAD,
            "condition": "Used",
            "price": {"value": "99999.00", "currency": "GBP"},
        }
        _stub_get(monkeypatch, {"itemSummaries": [used_and_way_over_band]})

        demand = scraper._get_sold_api("dyson ball animal")

        assert [r[0] for r in scraper.observations] == ["116529177245"]
        assert demand.active_listings_in_band == 0

    def test_the_url_detail_path_keeps_the_listing_before_the_condition_gate(
        self, monkeypatch
    ):
        """C10 refuses a Used listing entry into an analysis. The reading is
        taken first, because the listing was genuinely read either way."""
        scraper = _authed_scraper()
        _stub_get(monkeypatch, LIVE_PAYLOAD)  # Very Good - Refurbished

        with pytest.raises(ValueError):
            scraper._get_details_api("116529177245")

        assert [r[0] for r in scraper.observations] == ["116529177245"]
        assert scraper.observations[0][2] == SOURCE_ITEM

    def test_a_payload_with_no_usable_id_is_not_kept(self, monkeypatch):
        scraper = _authed_scraper()
        _stub_get(monkeypatch, {"itemSummaries": [{"title": "no id at all"}]})

        scraper._search_api("dyson ball animal", limit=10, price_band=None)

        assert scraper.observations == []

    def test_a_scraper_that_read_nothing_offers_nothing(self):
        assert _authed_scraper().observations == []


# ---------------------------------------------------------------------------
# 9. The pipeline drain - one place, where the session already exists
# ---------------------------------------------------------------------------

def _analysis_results(**overrides) -> dict:
    """The smallest `results` dict `save_analysis_to_db` will accept."""
    product = ScrapedProduct(
        source="ebay_uk",
        title="Dyson Ball Animal - Refurbished",
        price=169.0,
        url="https://www.ebay.co.uk/itm/116529177245",
        condition="New",
        verified=True,
    )
    results = {
        "ebay_product": product,
        "demand": None,
        "supplier_matches": [],
        "llm_analysis": None,
        "verdict": None,
        "observations": [("116529177245", LIVE_PAYLOAD, SOURCE_ITEM)],
    }
    results.update(overrides)
    return results


class TestThePipelineStoresItsReadings:
    def test_a_saved_analysis_stores_the_readings_it_took(self, tmp_path, monkeypatch):
        from analysis_pipeline import save_analysis_to_db
        from db.queries import get_listing_observations

        factory = _fresh_session_factory(tmp_path)
        monkeypatch.setattr("analysis_pipeline.SessionLocal", factory)

        save_analysis_to_db(_analysis_results())

        session = factory()
        try:
            rows = get_listing_observations(session, "116529177245")
            assert len(rows) == 1
            assert rows[0].seller_account_type == "BUSINESS"
        finally:
            session.close()

    def test_a_failing_reading_write_leaves_the_analysis_in_place(
        self, tmp_path, monkeypatch
    ):
        """The readings are evidence about listings, not part of the analysis:
        if they cannot be written, the analysis must still be there - and it
        must not pass in silence, because that would look like "never seen"."""
        from analysis_pipeline import save_analysis_to_db
        from db.models import Product

        def boom(db, readings, observed_at=None):
            raise RuntimeError("disk full")

        factory = _fresh_session_factory(tmp_path)
        monkeypatch.setattr("analysis_pipeline.SessionLocal", factory)
        monkeypatch.setattr("analysis_pipeline.save_listing_observations", boom)

        save_analysis_to_db(_analysis_results())

        session = factory()
        try:
            assert session.query(Product).count() == 1
        finally:
            session.close()

    def test_a_run_that_took_no_readings_writes_nothing(self, tmp_path, monkeypatch):
        from analysis_pipeline import save_analysis_to_db
        from db.models import ListingObservation

        factory = _fresh_session_factory(tmp_path)
        monkeypatch.setattr("analysis_pipeline.SessionLocal", factory)

        save_analysis_to_db(_analysis_results(observations=[]))

        session = factory()
        try:
            assert session.query(ListingObservation).count() == 0
        finally:
            session.close()

    def test_the_reading_list_is_the_scrapers_own(self, tmp_path, monkeypatch):
        """The pipeline aliases the scraper's list rather than copying it, so a
        run that bails early still carries everything it read first. Pinned
        here because it is one line of aliasing that an innocent copy would
        silently break."""
        from analysis_pipeline import save_analysis_to_db
        from scrapers.ebay import EbayScraper

        factory = _fresh_session_factory(tmp_path)
        monkeypatch.setattr("analysis_pipeline.SessionLocal", factory)

        scraper = EbayScraper()
        results = _analysis_results(observations=scraper.observations)
        # Appended AFTER the results dict was built, the way the scrape does it.
        scraper.observations.append(("204925572731", LIVE_PAYLOAD, SOURCE_ITEM))

        save_analysis_to_db(results)

        from db.queries import get_listing_observations

        session = factory()
        try:
            assert len(get_listing_observations(session, "204925572731")) == 1
        finally:
            session.close()
