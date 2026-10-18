r"""The individual sale prices must survive, or the chart is a guess.

A3. `DemandData` used to carry only min/avg/max — the list those three are
computed from was built inside `_get_sold_api` and thrown away, so nothing
drawn on screen could ever be more than a re-derivation. The list is now a
column, and three separate hops have to agree on it:

    _get_sold_api  ->  save_demand_data  ->  /history/{id}  ->  Scorecard

Every hop below is pinned here, plus the one case that must NOT be filled in:
a row saved before the column existed. It holds no observations, so the front
end has to get an empty list — never a synthetic distribution standing in for
one. That is C1's "unknown shown as known" failure wearing a chart's clothes.
"""

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import db.database as dbmod
from db.database import Base


# ---------------------------------------------------------------------------
# Offline guarantees (same stance as test_store_wiring: nothing here is free)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _zero_network(monkeypatch):
    """Every test here stubs its own collaborator. A path that reaches a
    scraper without one dies loudly instead of quietly hitting eBay."""
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("network call attempted — this file runs offline")

    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)
    monkeypatch.setattr(requests.Session, "get", _blocked)
    monkeypatch.setattr(requests.Session, "post", _blocked)


@pytest.fixture(autouse=True)
def _pristine_range(monkeypatch, tmp_path):
    """Pin the ACTIVE band to the config defaults (£5–£35): out-of-band
    pricing must be excluded from the chart, so the boundary has to be known."""
    import utils.filters as uf

    target = tmp_path / "custom_filters.json"
    target.write_text(json.dumps({"active": {}, "presets": {}}))
    monkeypatch.setattr(uf, "FILTERS_FILE", target)
    uf._cache["mtime"] = None
    uf._cache["data"] = None
    yield
    uf._cache["mtime"] = None
    uf._cache["data"] = None


# ---------------------------------------------------------------------------
# Helpers (plain functions — a class-scoped fixture resolves `self` first
# under pytest 9, so these take monkeypatch/tmp_path directly)
# ---------------------------------------------------------------------------

def _session(tmp_path, monkeypatch):
    """A throwaway database, wired to every consumer that will read it."""
    import db.models  # noqa: F401

    engine = create_engine(f"sqlite:///{tmp_path/'sold_prices.db'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(dbmod, "SessionLocal", factory)
    monkeypatch.setattr(dbmod, "engine", engine)
    return factory, engine


def _save_demand(factory, prices):
    from db.queries import save_demand_data, save_product
    from scrapers.base import DemandData, ScrapedProduct

    db = factory()
    try:
        product_id = save_product(db, ScrapedProduct(
            source="ebay_uk", title="Generic widget", price=12.0,
            url="https://www.ebay.co.uk/itm/1", condition="New", verified=True,
        ))
        save_demand_data(db, product_id, DemandData(
            sold_count_30d=len(prices),
            avg_sold_price=(sum(prices) / len(prices)) if prices else None,
            lowest_sold_price=min(prices) if prices else None,
            highest_sold_price=max(prices) if prices else None,
            sold_prices=list(prices),
            verified=True,
        ))
        return product_id
    finally:
        db.close()


def _stored_prices(engine, product_id):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT sold_prices FROM demand_data WHERE product_id = :p"),
            {"p": product_id},
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return json.loads(row[0])


PRICES = [9.99, 12.5, 30.0, 7.0, 21.25]


# ---------------------------------------------------------------------------
# 1. Persistence round-trip
# ---------------------------------------------------------------------------

class TestTheObservationsSurviveStorage:
    def test_the_list_is_stored_as_observed(self, tmp_path, monkeypatch):
        factory, engine = _session(tmp_path, monkeypatch)

        product_id = _save_demand(factory, PRICES)

        assert _stored_prices(engine, product_id) == PRICES

    def test_a_rerun_with_nothing_observed_clears_the_chart(
        self, tmp_path, monkeypatch
    ):
        """A re-run that found no sales must EMPTY the previous chart, not
        keep redrawing the old one — an old distribution beside a current
        sold_count of 0 is a lie about today."""
        factory, engine = _session(tmp_path, monkeypatch)
        product_id = _save_demand(factory, PRICES)

        _save_demand(factory, [])

        assert _stored_prices(engine, product_id) == []

    def test_the_summary_figures_are_derived_from_the_same_list(
        self, tmp_path, monkeypatch
    ):
        """The chart and the headline numbers are two views of one
        measurement; if they could disagree the page would be asserting two
        different sets of sales."""
        factory, engine = _session(tmp_path, monkeypatch)

        product_id = _save_demand(factory, PRICES)

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT avg_sold_price, lowest_sold_price,"
                    " highest_sold_price FROM demand_data WHERE product_id = :p"
                ),
                {"p": product_id},
            ).fetchone()
        assert row[0] == pytest.approx(sum(PRICES) / len(PRICES))
        assert row[1] == min(PRICES)
        assert row[2] == max(PRICES)


# ---------------------------------------------------------------------------
# 2. History replay, and the legacy row
# ---------------------------------------------------------------------------

class TestHistoryReplay:
    def test_the_list_reaches_the_frontend_payload(self, tmp_path, monkeypatch):
        from api.history import product_detail

        factory, _ = _session(tmp_path, monkeypatch)
        product_id = _save_demand(factory, PRICES)

        demand = product_detail(product_id)["demand"]

        assert demand["sold_prices"] == PRICES
        assert demand["sold_count_30d"] == len(PRICES)

    def test_a_row_that_never_had_the_column_renders_nothing(
        self, tmp_path, monkeypatch
    ):
        """This is the whole file's reason to exist. The column was added to
        an existing table, so every pre-A3 row holds NULL. NULL means "we
        hold no observations" — the front end gets [] and draws no chart. It
        must never interpolate a plausible-looking curve across a gap it has
        no data for."""
        from api.history import product_detail

        factory, engine = _session(tmp_path, monkeypatch)
        product_id = _save_demand(factory, PRICES)
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE demand_data SET sold_prices = NULL"
                     " WHERE product_id = :p"),
                {"p": product_id},
            )

        demand = product_detail(product_id)["demand"]

        assert demand["sold_prices"] == []
        # The count is a separate measurement and still stands — the two are
        # reported together, never substituted for one another.
        assert demand["sold_count_30d"] == len(PRICES)


# ---------------------------------------------------------------------------
# 3. The scraper carries the prices it actually observed
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _payload(*rows):
    return {
        "itemSummaries": [
            {
                "price": {"value": str(price), "currency": "GBP"},
                "condition": condition,
                "seller": {"username": f"store_{i}"},
            }
            for i, (price, condition) in enumerate(rows)
        ]
    }


def _scraper(monkeypatch, payload):
    from scrapers.ebay import EbayScraper

    scraper = EbayScraper()
    monkeypatch.setattr(scraper, "_api_headers", lambda: {})
    monkeypatch.setattr(
        "scrapers.ebay.requests.get", lambda *a, **k: _Resp(payload)
    )
    return scraper


class TestTheScraperCarriesWhatItObserved:
    def test_in_band_new_listings_become_chart_points(self, monkeypatch):
        """These are the asking prices of the LIVE listings the query returned,
        so they become chart points under the active-price names — and every
        sold-price field stays empty, because nothing sold."""
        scraper = _scraper(
            monkeypatch, _payload((9.99, "New"), (12.5, "New"), (30.0, "New"))
        )

        demand = scraper._get_sold_api("widget")

        assert demand.active_prices == [9.99, 12.5, 30.0]
        assert demand.avg_active_price == pytest.approx((9.99 + 12.5 + 30.0) / 3)
        assert demand.lowest_active_price == 9.99
        assert demand.highest_active_price == 30.0
        # The same three numbers must never appear as SOLD prices. This is the
        # assertion that fails if anyone points the sold fields back at this
        # list, which is what they held until 2026-10-19.
        assert demand.sold_prices == []
        assert demand.avg_sold_price is None
        assert demand.lowest_sold_price is None
        assert demand.highest_sold_price is None

    def test_used_listings_are_not_chart_points(self, monkeypatch):
        """C10 is absolute: a Used listing is not a New-condition listing, so
        it cannot become a point in a distribution labelled New."""
        scraper = _scraper(
            monkeypatch, _payload((9.99, "New"), (8.0, "Used"))
        )

        demand = scraper._get_sold_api("widget")

        assert demand.active_prices == [9.99]
        assert demand.sold_prices == []
        # One in-band New listing came back. That is a LISTING count, not a
        # sale: Browse cannot see sold items, so the sold count stays
        # unmeasured rather than borrowing this number (C1/C4). The old
        # assertion here read `sold_count_30d == 1`, which is precisely the
        # mislabelling this test now guards against.
        assert demand.sold_count_30d is None
        assert demand.active_listings_in_band == 1

    def test_out_of_band_prices_are_not_chart_points(self, monkeypatch):
        """The band (£5–£35) is what the listing count and the average were
        already built on; a £99 listing plotted next to them would silently
        widen the axis."""
        scraper = _scraper(
            monkeypatch, _payload((9.99, "New"), (99.0, "New"), (30.0, "New"))
        )

        demand = scraper._get_sold_api("widget")

        assert demand.active_prices == [9.99, 30.0]
        assert demand.excluded_over_band == 1

    def test_a_response_with_no_listings_holds_no_points(self, monkeypatch):
        """Empty means "we hold no observations" — not "no sales". The
        count and the list stay separate measures, and an empty run leaves
        BOTH lists empty rather than moving a price across to the other one."""
        scraper = _scraper(monkeypatch, {"itemSummaries": []})

        demand = scraper._get_sold_api("widget")

        assert demand.sold_prices == []
        assert demand.active_prices == []
        # An empty response is marked untrusted (verified=False) rather than
        # read as "zero competition", so the count stays None — not measured —
        # exactly as the sold count does. None never means zero (C1/C4).
        assert demand.active_listings_in_band is None
        assert demand.sold_count_30d is None


# ---------------------------------------------------------------------------
# 4. SUPPLY is not DEMAND (2026-10-18)
# ---------------------------------------------------------------------------

class TestAListingCountIsNeverASoldCount:
    """eBay offers this app no sold-listing search: findCompletedItems was
    decommissioned on 2025-02-04, Marketplace Insights is closed to new
    applications, and the Browse API returns ACTIVE listings only.

    `_get_sold_api` therefore reads SUPPLY. It used to write that number into
    `sold_count_30d`, which made the demand verdict, the "hot" badge and the
    configured demand floors all report a figure that had never been measured
    as sales. The whole honesty chain above rests on this one function not
    lying, so the separation is pinned here rather than assumed.
    """

    def test_supply_lands_in_its_own_field(self, monkeypatch):
        scraper = _scraper(monkeypatch, _payload((9.99, "New"), (12.5, "New")))

        demand = scraper._get_sold_api("widget")

        assert demand.active_listings_in_band == 2
        assert demand.sold_count_30d is None

    def test_a_listing_count_is_never_verified_demand(self, monkeypatch):
        """`verified` is what the verdict engine reads to decide that a demand
        row is evidence rather than PENDING. It must be False when nothing
        about sales was observed, however many listings came back."""
        scraper = _scraper(monkeypatch, _payload((9.99, "New")))

        demand = scraper._get_sold_api("widget")

        assert demand.verified is False

    def test_the_source_label_says_outright_that_these_are_not_sales(
        self, monkeypatch
    ):
        """The label is rendered in the UI and may be string-matched, so it
        must state what the count is AND what it is not. Banning the word
        "sold" would be the wrong test: an honest label has to be able to
        mention sales in order to deny them."""
        scraper = _scraper(monkeypatch, _payload((9.99, "New")))

        demand = scraper._get_sold_api("widget")

        label = demand.data_source.lower()
        assert "active" in label           # says what the count IS
        assert "not sales" in label        # says what it is NOT


# ---------------------------------------------------------------------------
# 3. The asking prices, and the columns they used to be written into
# ---------------------------------------------------------------------------

def _save_browse_demand(factory, count, prices):
    """A demand row exactly as the Browse path writes it: the live-listing
    evidence in the active columns, and nothing at all in the sold ones."""
    from db.queries import save_demand_data, save_product
    from scrapers.base import DemandData, ScrapedProduct

    db = factory()
    try:
        product_id = save_product(db, ScrapedProduct(
            source="ebay_uk", title="Generic widget", price=12.0,
            url="https://www.ebay.co.uk/itm/1", condition="New", verified=True,
        ))
        save_demand_data(db, product_id, DemandData(
            active_listings_in_band=count,
            avg_active_price=(sum(prices) / len(prices)) if prices else None,
            lowest_active_price=min(prices) if prices else None,
            highest_active_price=max(prices) if prices else None,
            active_prices=list(prices),
            verified=False,
            data_source="eBay Browse API (active listings, not sales)",
        ))
        return product_id
    finally:
        db.close()


class TestTheAskingPricesAreStoredApart:
    """`_get_sold_api` used to write the live listings' ASKING prices into
    `avg_sold_price` / `lowest_sold_price` / `highest_sold_price` /
    `sold_prices`. Every number was real; the word describing it was not. It
    is the same defect Phase 1 fixed for the count, one field over, and it is
    fixed the same way: the value moves to a name that says what it is, and
    the sold field is left empty rather than merely renamed."""

    def test_the_asking_set_lands_in_its_own_columns(
        self, tmp_path, monkeypatch
    ):
        factory, engine = _session(tmp_path, monkeypatch)

        product_id = _save_browse_demand(factory, 50, PRICES)

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT active_prices, avg_active_price,"
                    " lowest_active_price, highest_active_price,"
                    " active_listings_in_band FROM demand_data"
                    " WHERE product_id = :p"
                ),
                {"p": product_id},
            ).fetchone()
        assert json.loads(row[0]) == PRICES
        assert row[1] == pytest.approx(sum(PRICES) / len(PRICES))
        assert row[2] == min(PRICES)
        assert row[3] == max(PRICES)
        assert row[4] == 50

    def test_nothing_reaches_the_sold_columns(self, tmp_path, monkeypatch):
        """The half that is easy to forget: the sold columns must stay EMPTY.
        Copying the prices across as well would leave the same numbers sitting
        under a name that claims a sale happened, and the sold chart — which
        is the one a reader trusts — would plot live asking prices."""
        factory, engine = _session(tmp_path, monkeypatch)

        product_id = _save_browse_demand(factory, 50, PRICES)

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT avg_sold_price, lowest_sold_price,"
                    " highest_sold_price, sold_prices, sold_count_30d"
                    " FROM demand_data WHERE product_id = :p"
                ),
                {"p": product_id},
            ).fetchone()
        assert row[0] is None
        assert row[1] is None
        assert row[2] is None
        # The list is present and EMPTY rather than NULL: nothing was observed,
        # and an empty list is how that is recorded. Both shapes render no
        # chart (see TestHistoryReplay), so neither can invent one.
        assert json.loads(row[3]) == []
        assert row[4] is None

    def test_the_listing_count_survives_storage(self, tmp_path, monkeypatch):
        """Phase 1 computed `active_listings_in_band` and never persisted it,
        so a live Analyze run carried the count and a replayed History run did
        not — one product, two screens, two different answers."""
        from api.history import product_detail

        factory, _ = _session(tmp_path, monkeypatch)
        product_id = _save_browse_demand(factory, 50, PRICES)

        demand = product_detail(product_id)["demand"]

        assert demand["active_listings_in_band"] == 50
        assert demand["avg_active_price"] == pytest.approx(
            sum(PRICES) / len(PRICES)
        )
        assert demand["lowest_active_price"] == min(PRICES)
        assert demand["highest_active_price"] == max(PRICES)
        assert demand["active_prices"] == PRICES
        # ...and the sold set still reads as unmeasured, not as the same data
        # arriving a second time under a different name.
        assert demand["sold_prices"] == []
        assert demand["avg_sold_price"] is None

    def test_a_rescrape_that_saw_nothing_clears_the_asking_set(
        self, tmp_path, monkeypatch
    ):
        """The same all-or-nothing rule the sold list follows: an old
        asking-price chart beside a count of zero is a lie about today."""
        factory, engine = _session(tmp_path, monkeypatch)
        product_id = _save_browse_demand(factory, 50, PRICES)

        _save_browse_demand(factory, 0, [])

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT active_prices, active_listings_in_band"
                    " FROM demand_data WHERE product_id = :p"
                ),
                {"p": product_id},
            ).fetchone()
        assert json.loads(row[0]) == []
        assert row[1] == 0


# ---------------------------------------------------------------------------
# 4. Which list a price belongs to is decided by its SOURCE
# ---------------------------------------------------------------------------

class TestTheScraperSortsPricesBySource:
    """`_calculate_stats` is handed one `items` list that means two different
    things depending on where it came from, so the prices are sorted by
    `items_source` rather than by position — exactly as the count already
    was."""

    def _stats(self, source, prices):
        from scrapers.ebay_sold import (
            EbaySoldData, EbaySoldItem, EbaySoldScraper,
        )

        result = EbaySoldData(
            product_name="widget",
            query="widget",
            items_source=source,
            items=[
                EbaySoldItem(
                    title="Generic widget", price=price,
                    url=f"https://www.ebay.co.uk/itm/{i}",
                    seller="", seller_url="", sold_date="",
                )
                for i, price in enumerate(prices)
            ],
        )
        EbaySoldScraper()._calculate_stats(result)
        return result

    def test_live_listings_become_asking_prices(self):
        result = self._stats("ebay_browse_active", [9.99, 12.5, 30.0])

        assert result.active_prices == [9.99, 12.5, 30.0]
        assert result.sold_prices == []
        assert result.total_sold_30d is None
        assert result.active_listings_in_band == 3

    def test_scraped_sales_become_sold_prices(self):
        result = self._stats("ebay_sold_scrape", [9.99, 12.5, 30.0])

        assert result.sold_prices == [9.99, 12.5, 30.0]
        assert result.active_prices == []
        assert result.total_sold_30d == 3
        assert result.active_listings_in_band is None

    def test_an_unlabelled_source_is_not_read_as_sales(self):
        """`items_source` defaults to "" — an unknown origin. The prices still
        have to go somewhere, and the safe direction is the one that does not
        assert a sale. If this inverts, every price from an unlabelled source
        becomes a "sold" price on screen."""
        result = self._stats("", [9.99, 12.5])

        assert result.sold_prices == []
        assert result.active_prices == [9.99, 12.5]
        assert result.total_sold_30d is None

    def test_the_summary_describes_whichever_list_was_filled(self):
        """price_min/max/avg/median come from the same list the chart draws,
        so the tiles and the distribution can never describe two different
        markets."""
        result = self._stats("ebay_browse_active", [8.0, 11.5, 15.0])

        assert (result.price_min, result.price_max) == (8.0, 15.0)
        assert result.price_avg == pytest.approx((8.0 + 11.5 + 15.0) / 3)
        assert result.price_median == 11.5
