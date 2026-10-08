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
    def test_in_band_new_sales_become_chart_points(self, monkeypatch):
        scraper = _scraper(
            monkeypatch, _payload((9.99, "New"), (12.5, "New"), (30.0, "New"))
        )

        demand = scraper._get_sold_api("widget")

        assert demand.sold_prices == [9.99, 12.5, 30.0]
        assert demand.avg_sold_price == pytest.approx((9.99 + 12.5 + 30.0) / 3)
        assert demand.lowest_sold_price == 9.99
        assert demand.highest_sold_price == 30.0

    def test_used_sales_are_not_chart_points(self, monkeypatch):
        """C10 is absolute: a Used sale is not a New-condition sale, so it
        cannot become a point in a distribution labelled New."""
        scraper = _scraper(
            monkeypatch, _payload((9.99, "New"), (8.0, "Used"))
        )

        demand = scraper._get_sold_api("widget")

        assert demand.sold_prices == [9.99]
        assert demand.sold_count_30d == 1

    def test_out_of_band_prices_are_not_chart_points(self, monkeypatch):
        """The band (£5–£35) is what sold_count and avg were already built
        on; a £99 sale plotted next to them would silently widen the axis."""
        scraper = _scraper(
            monkeypatch, _payload((9.99, "New"), (99.0, "New"), (30.0, "New"))
        )

        demand = scraper._get_sold_api("widget")

        assert demand.sold_prices == [9.99, 30.0]
        assert demand.excluded_over_band == 1

    def test_a_response_with_no_sales_holds_no_points(self, monkeypatch):
        """Empty means "we hold no observations" — not "no sales". The
        count and the list stay separate measures."""
        scraper = _scraper(monkeypatch, {"itemSummaries": []})

        demand = scraper._get_sold_api("widget")

        assert demand.sold_prices == []
        assert demand.sold_count_30d is None
