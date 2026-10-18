"""The deals board must show real listings, and claim nothing it did not measure.

eBay publishes no best-seller or sold-volume data to this app. That was
measured, not assumed:

  * getMostWatchedItems (Merchandising API) — decommissioned 2025-01-06
  * findCompletedItems (Finding API)        — decommissioned 2025-02-04
  * Marketplace Insights                    — HTTP 403, scope not granted
  * Deals API                               — HTTP 400, scope not granted
  * Browse API                              — no watchCount, no quantitySold,
                                              no bidCount, and all nineteen
                                              `sort` values that could have
                                              proxied for popularity return
                                              byte-identical ordering to no
                                              sort at all

So this board cannot be a best-seller list, and the tests below exist to stop it
drifting into one. It reads eBay's own curated discount page and must therefore
say "curated by eBay", carry no sold count, and never turn an unread price into
a number.

The parser is pinned against `tests/fixtures/ebay_deals_cards.html` — real card
objects captured from the live page — because a parser tested only against JSON
the author wrote proves the author's imagination, not the parser.
"""

import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import db.database as dbmod
from db.database import Base
from db.models import DealItem as DealItemRow
from hunter import deals
from scrapers.ebay_deals import (
    SOURCE_LABEL,
    DealItem,
    EbayDealsScraper,
    _CARD_RE,
    parse_deals_page,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ebay_deals_cards.html"


# ---------------------------------------------------------------------------
# Offline guarantees. Nothing in this file may reach the network: the board's
# whole reason for existing is that a scheduled job fetches and the API reads,
# so a test that fetched would be testing the thing that is deliberately not
# on the request path.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("this test must not reach the network")

    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)


@pytest.fixture(autouse=True)
def _no_auto_refresh(monkeypatch):
    """The API's background refresh is off unless a test asks for it."""
    monkeypatch.setenv("DEALS_AUTO_REFRESH", "0")


def _session(tmp_path, monkeypatch):
    """A throwaway database, wired into BOTH the session factory the tests use
    and the one the API route opens for itself — otherwise the route reads the
    real database and the test proves nothing."""
    path = (tmp_path / "deals.db").as_posix()
    engine = create_engine(f"sqlite:///{path}")
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "SessionLocal", factory)
    Base.metadata.create_all(engine)
    return factory, engine


def _card(listing_id="123456789012", title="A Real Thing", image="https://i.ebayimg.com/images/g/x/s-l225.jpg"):
    return (
        '{"listingId":"%s","imageUrl":"%s","title":"%s"}' % (listing_id, image, title)
    )


# ---------------------------------------------------------------------------
# 1. The parser, against the real page
# ---------------------------------------------------------------------------

class TestTheParserReadsTheRealPayload:
    """Pinned against eBay's actual shape, not a shape written to fit."""

    @pytest.fixture(scope="class")
    def cards(self):
        return parse_deals_page(FIXTURE.read_text(encoding="utf-8"))

    def test_it_finds_the_real_cards(self, cards):
        # Not an exact count on purpose: how many items eBay merchandises
        # legitimately changes between refreshes, so pinning the number would
        # make this test fail for a reason that is not a defect.
        assert len(cards) >= 40

    def test_every_card_is_showable(self, cards):
        """A card without a title or an image could not be rendered honestly."""
        assert all(c.title.strip() for c in cards)
        assert all(c.image_url.startswith("https://i.ebayimg.com/") for c in cards)

    def test_every_card_links_to_a_real_item_url_on_ebay(self, cards):
        for card in cards:
            assert re.match(
                r"^https://www\.ebay\.co\.uk/itm/\d+", card.item_url
            ), card.item_url
            assert card.listing_id in card.item_url

    def test_titles_keep_their_real_characters(self, cards):
        """™, ®, £ and curly quotes are decoded through json, not mangled."""
        blob = " ".join(c.title for c in cards)
        assert "\u2122" in blob or "\u00ae" in blob or "\u2013" in blob

    def test_it_asks_ebay_for_a_larger_render(self, cards):
        """The page serves 225px thumbs; the card box is bigger than that, and
        a stretched thumbnail is the blurry look this rewrites away."""
        assert all("/s-l500." in c.image_url for c in cards)


class TestTheParserCannotBeFooled:
    def test_a_card_with_no_title_is_dropped(self):
        """Rendering a blank title would be showing a placeholder as a real
        listing, so the card is left out instead."""
        html = '{"listingId":"123456789012","imageUrl":"https://i.ebayimg.com/a.jpg"}'

        assert parse_deals_page(html) == []

    def test_a_duplicate_listing_occupies_one_slot(self):
        """The page repeats entries across its sections. A duplicate would
        otherwise take two places in the rotation."""
        html = _card("111222333444") + "," + _card("111222333444")

        cards = parse_deals_page(html)

        assert len(cards) == 1
        assert cards[0].listing_id == "111222333444"

    def test_the_earliest_position_is_the_one_kept(self):
        html = _card("111222333444", "First") + "," + _card("111222333444", "Second")

        assert parse_deals_page(html)[0].title == "First"

    def test_nothing_in_means_nothing_out(self):
        assert parse_deals_page("") == []
        assert parse_deals_page("<html>a page with no cards</html>") == []

    def test_a_non_numeric_listing_id_is_not_a_listing(self):
        html = '{"listingId":"not-an-id","imageUrl":"https://i.ebayimg.com/a.jpg","title":"x"}'

        assert parse_deals_page(html) == []


# ---------------------------------------------------------------------------
# 2. The board must not invent a number
# ---------------------------------------------------------------------------

class TestAnUnreadPriceNeverBecomesANumber:
    def test_no_price_renders_as_nothing_at_all(self):
        """'£0.00' is a claim the item is free. The C1 failure in miniature."""
        assert deals.price_label(None, "GBP") == ""

    def test_a_genuine_zero_is_still_shown(self):
        """0 is a real price, so it must not share a representation with
        'not read'."""
        assert deals.price_label(0.0, "GBP") == "£0.00"

    def test_real_prices_keep_their_symbol(self):
        assert deals.price_label(169.0, "GBP") == "£169.00"
        assert deals.price_label(1234.5, "GBP") == "£1,234.50"

    def test_an_unknown_currency_does_not_invent_a_symbol(self):
        assert deals.price_label(10.0, "XYZ") == "10.00 XYZ"

    def test_the_row_reports_whether_the_price_was_read(self, tmp_path, monkeypatch):
        factory, _ = _session(tmp_path, monkeypatch)
        session = factory()
        deals.save_deals([
            DealItem(listing_id="1", title="Priced", item_url="u", price=9.99, currency="GBP"),
            DealItem(listing_id="2", title="Unpriced", item_url="u"),
        ], session)

        rows = {r["listing_id"]: r for r in deals.load_deals(session)}

        assert rows["1"]["price_read"] is True
        assert rows["1"]["price_label"] == "£9.99"
        assert rows["2"]["price_read"] is False
        assert rows["2"]["price_label"] == ""
        session.close()


class TestTheTableCannotHoldAPopularityClaim:
    def test_there_is_no_sold_or_popularity_column(self):
        """A column would be an invitation to fill one in. Nothing measurable
        from this app could go in it, so it does not exist."""
        names = {c.name for c in DealItemRow.__table__.columns}
        banned = {
            "sold_count", "sold_30d", "sold_7d", "sales", "sales_count",
            "popularity", "watch_count", "quantity_sold", "best_seller",
            "hotness", "hot", "rank", "score", "trend",
        }
        assert not (names & banned), f"unmeasurable columns: {names & banned}"

    def test_the_board_labels_itself_as_curated_by_ebay(self):
        """The one claim that IS true, and the one that must survive."""
        assert SOURCE_LABEL == "eBay Deals — curated by eBay"
        assert "best" not in SOURCE_LABEL.lower()
        assert "popular" not in SOURCE_LABEL.lower()


# ---------------------------------------------------------------------------
# 3. Storage
# ---------------------------------------------------------------------------

class TestStorage:
    def test_a_refresh_replaces_what_is_stored(self, tmp_path, monkeypatch):
        factory, _ = _session(tmp_path, monkeypatch)
        session = factory()
        deals.save_deals([DealItem("1", "One", item_url="u")], session)

        deals.save_deals([DealItem("2", "Two", item_url="u")], session)

        assert [r["listing_id"] for r in deals.load_deals(session)] == ["2"]
        session.close()

    def test_an_item_ebay_stopped_featuring_leaves_the_board(
        self, tmp_path, monkeypatch
    ):
        """'Still on the board' has to mean 'was on the page last refresh'. A
        row that lingered would be advertising a deal that may be over."""
        factory, _ = _session(tmp_path, monkeypatch)
        session = factory()
        deals.save_deals(
            [DealItem("1", "One", item_url="u"), DealItem("2", "Two", item_url="u")],
            session,
        )

        result = deals.save_deals([DealItem("1", "One again", item_url="u")], session)

        assert result["removed"] == 1
        assert [r["listing_id"] for r in deals.load_deals(session)] == ["1"]
        session.close()

    def test_a_repeated_item_keeps_its_id(self, tmp_path, monkeypatch):
        """Delete-then-insert would give the row a new primary key, which makes
        the client re-mount the card and lose its place in the rotation."""
        factory, _ = _session(tmp_path, monkeypatch)
        session = factory()
        deals.save_deals([DealItem("1", "One", item_url="u")], session)
        first = session.query(DealItemRow).one().id

        deals.save_deals([DealItem("1", "One, repriced", item_url="u", price=5.0)], session)

        row = session.query(DealItemRow).one()
        assert row.id == first
        assert row.price == 5.0
        session.close()

    def test_the_board_reports_its_own_age(self, tmp_path, monkeypatch):
        """A stale board that says it is stale is honest; one that implies its
        prices are live is not."""
        factory, _ = _session(tmp_path, monkeypatch)
        session = factory()

        empty = deals.board_meta(session)
        assert empty["total"] == 0
        assert empty["stale"] is True
        assert empty["last_fetched"] == ""

        deals.save_deals([DealItem("1", "One", item_url="u", price=1.0)], session)

        fresh = deals.board_meta(session)
        assert fresh["total"] == 1
        assert fresh["priced"] == 1
        assert fresh["unpriced"] == 0
        assert fresh["stale"] is False
        assert fresh["age_seconds"] >= 0
        session.close()

    def test_the_order_ebay_used_is_the_order_kept(self, tmp_path, monkeypatch):
        factory, _ = _session(tmp_path, monkeypatch)
        session = factory()
        deals.save_deals(
            [
                DealItem("9", "Third", item_url="u", position=2),
                DealItem("8", "First", item_url="u", position=0),
                DealItem("7", "Second", item_url="u", position=1),
            ],
            session,
        )

        assert [r["title"] for r in deals.load_deals(session)] == [
            "First", "Second", "Third",
        ]
        session.close()


# ---------------------------------------------------------------------------
# 4. The route is a read
# ---------------------------------------------------------------------------

class TestTheRouteNeverFetchesOnTheRequestPath:
    def test_no_rows_means_no_fetch_when_auto_refresh_is_off(
        self, tmp_path, monkeypatch
    ):
        """The _no_network fixture above turns any fetch into a failure, so
        this passing at all is the assertion."""
        from fastapi.testclient import TestClient

        from main import app

        _session(tmp_path, monkeypatch)  # the route reads THIS database
        client = TestClient(app)
        resp = client.get("/api/deals")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["items"] == []
        assert body["meta"]["refresh_started"] is False
        assert body["meta"]["source_label"] == SOURCE_LABEL

    def test_the_route_serves_what_the_scheduler_stored(
        self, tmp_path, monkeypatch
    ):
        """The API reads the pool the refresh job wrote — it does not fetch."""
        from fastapi.testclient import TestClient

        from main import app

        factory, _ = _session(tmp_path, monkeypatch)
        session = factory()
        deals.save_deals(
            [
                DealItem("1", "Real Deal One", item_url="https://www.ebay.co.uk/itm/1",
                         price=12.5, currency="GBP", position=0),
                DealItem("2", "Real Deal Two", item_url="https://www.ebay.co.uk/itm/2",
                         position=1),
            ],
            session,
        )
        session.close()

        resp = TestClient(app).get("/api/deals")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert [i["title"] for i in body["items"]] == ["Real Deal One", "Real Deal Two"]
        assert body["items"][0]["price_label"] == "£12.50"
        assert body["items"][1]["price_label"] == ""
        assert body["items"][1]["price_read"] is False
        assert body["meta"]["total"] == 2
        assert body["meta"]["priced"] == 1
        assert body["meta"]["unpriced"] == 1


# ---------------------------------------------------------------------------
# 5. Pricing a card the by-id endpoint cannot resolve
# ---------------------------------------------------------------------------

class TestAMultiVariationListingStillGetsItsPrice:
    """Some deals are multi-variation listings: their RESTful id carries a
    non-zero variation (v1|306325186003|606018449347), and for those
    `get_item_by_legacy_id` answers HTTP 400 / errorId 11006 for the bare
    legacy id.

    Measured against one live page: 35 of 73 cards failed that way — half the
    board — and every one of them was a real, live listing with a perfectly
    good price. So the fallback is not a nicety; without it half the cards
    would show "see price on eBay" while the price was sitting in the API the
    whole time.
    """

    def _scraper_with(self, monkeypatch, by_id, by_search):
        scraper = EbayDealsScraper()
        calls: list[str] = []

        def fake_get(path, params):
            calls.append(path)
            if path.endswith("get_item_by_legacy_id"):
                return by_id
            return by_search

        monkeypatch.setattr(scraper, "_api_get", fake_get)
        return scraper, calls

    def test_the_exact_id_lookup_is_tried_first_and_alone(self, monkeypatch):
        """No fallback cost when the by-id endpoint already answered."""
        scraper, calls = self._scraper_with(
            monkeypatch,
            by_id={"price": {"value": "12.00", "currency": "GBP"},
                   "seller": {"username": "a_seller"}},
            by_search=None,
        )
        item = DealItem(listing_id="116529177245", title="Dyson", item_url="u")

        assert scraper.enrich(item) is True
        assert item.price == 12.0
        assert calls == ["/buy/browse/v1/item/get_item_by_legacy_id"]

    def test_it_falls_back_to_a_search_and_matches_the_id_exactly(
        self, monkeypatch
    ):
        scraper, calls = self._scraper_with(
            monkeypatch,
            by_id=None,  # 400/11006: the bare legacy id does not resolve
            by_search={
                "itemSummaries": [
                    # Another seller, near-identical title. Its price belongs
                    # to it, not to our card, so it must be discarded.
                    {"legacyItemId": "999999999999",
                     "price": {"value": "1.00", "currency": "GBP"}},
                    {"legacyItemId": "306325186003",
                     "price": {"value": "9.99", "currency": "GBP"},
                     "seller": {"username": "plate_shop"},
                     "condition": "New"},
                ]
            },
        )
        item = DealItem(listing_id="306325186003", title="Number Plates", item_url="u")

        assert scraper.enrich(item) is True
        assert item.price == 9.99
        assert item.seller == "plate_shop"
        assert len(calls) == 2

    def test_a_search_that_never_shows_our_id_leaves_no_price(self, monkeypatch):
        """Not found is not the same as free, and it is not someone else's
        price either."""
        scraper, _ = self._scraper_with(
            monkeypatch,
            by_id=None,
            by_search={"itemSummaries": [
                {"legacyItemId": "111111111111",
                 "price": {"value": "5.00", "currency": "GBP"}},
            ]},
        )
        item = DealItem(listing_id="306325186003", title="Number Plates", item_url="u")

        assert scraper.enrich(item) is False
        assert item.price is None
        assert item.price_read is False

    def test_a_payload_with_no_price_is_a_failure_not_a_zero(self, monkeypatch):
        scraper, _ = self._scraper_with(
            monkeypatch,
            by_id={"seller": {"username": "whoever"}},
            by_search=None,
        )
        item = DealItem(listing_id="1", title="Thing", item_url="u")

        assert scraper.enrich(item) is False
        assert item.price is None

    def test_a_price_that_arrives_as_a_string_is_still_read(self, monkeypatch):
        """The two item endpoints format `price` differently, and the
        difference has to be absorbed here or a real price silently becomes
        None."""
        scraper, _ = self._scraper_with(
            monkeypatch,
            by_id={"price": "£14.50", "seller": {"username": "s"}},
            by_search=None,
        )
        item = DealItem(listing_id="1", title="Thing", item_url="u")

        assert scraper.enrich(item) is True
        assert item.price == 14.50
        assert item.currency == "GBP"
