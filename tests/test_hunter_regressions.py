"""Regression ledger for the bugs found in the running app (2026-10-02).

Every test here corresponds to a defect the user hit in the real UI. The
comments record WHY each one exists, so a future change that reintroduces the
bug has something to fail against. Tests are written at public seams
(`scan_category`, the API), never against internals.

ZERO NETWORK: `requests` is replaced per test.
"""

from __future__ import annotations

import pytest

from hunter import category_scan as ccs


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture
def ebay(monkeypatch):
    """Stub eBay OAuth + search; return the dict that records the last query."""
    captured: dict = {}
    monkeypatch.setattr(ccs, "EBAY_CLIENT_ID", "test-id")
    monkeypatch.setattr(ccs, "EBAY_CLIENT_SECRET", "test-secret")

    def _post(url, **kwargs):
        return _Resp({"access_token": "test-token"})

    def _get(url, params=None, **kwargs):
        captured["params"] = dict(params or {})
        captured["url"] = url
        return _Resp({"itemSummaries": []})

    monkeypatch.setattr(ccs.requests, "post", _post)
    monkeypatch.setattr(ccs.requests, "get", _get)
    return captured


# ---------------------------------------------------------------------------
# REGRESSION-001 — an unrecognised category silently scanned Electronics
#
# The user typed "garden tools" and received electronics. The cause was a
# single line:  EBAY_CATEGORIES.get(category_name, "293")
# an exact, case-sensitive dict lookup whose fallback was Electronics, with
# no query ever sent to eBay. "Garden Tools" is not one of the 15 keys, so
# every unknown input became category 293 - and the rows were then stamped
# with the user's own text, so the page read "garden tools" above electronics.
# ---------------------------------------------------------------------------

class TestRegression001CategoryResolution:
    def test_an_unrecognised_search_is_sent_to_ebay_as_a_real_query(self, ebay):
        """A search we have no category for must become a keyword search."""
        ccs.scan_category("garden tools")

        params = ebay["params"]
        assert params.get("q") == "garden tools"
        assert "category_ids" not in params

    def test_a_recognised_category_still_browses_that_category(self, ebay):
        """The 15 real categories must keep working exactly as before."""
        ccs.scan_category("Electronics")

        params = ebay["params"]
        assert params.get("category_ids") == "293"
        assert "q" not in params

    def test_matching_ignores_case_and_surrounding_space(self, ebay):
        # The frontend hint said "e.g. Garden Tools, Kitchen, Home Decor";
        # users type lowercase and leave spaces. Neither may lose the match.
        for text in ("electronics", "ELECTRONICS", "  Electronics  "):
            ccs.scan_category(text)
            assert ebay["params"].get("category_ids") == "293", text

    def test_empty_search_returns_nothing_rather_than_a_default_category(self, ebay):
        """An empty box must not quietly become Electronics."""
        assert ccs.scan_category("") == []
        assert ccs.scan_category("    ") == []
        assert "params" not in ebay


# ---------------------------------------------------------------------------
# REGRESSION-001b — the response lied about what had been searched
#
# Every row carried `category=<the user's raw text>`, so the report header
# read "garden tools" above electronics listings. The row now records the
# mode and the text that was really sent to eBay.
# ---------------------------------------------------------------------------

class TestRegression001bResponseTellsTheTruth:
    def test_a_keyword_search_labels_itself_as_a_search(self, monkeypatch, ebay):
        from hunter.category_scan import CategoryProduct

        monkeypatch.setattr(
            ccs, "_scan_via_api",
            lambda resolved, *a, **k: [
                CategoryProduct(
                    title="Greenhouse 6ft", price=19.99, url="https://x/1",
                    category=resolved.label or resolved.text,
                    search_mode=resolved.mode, search_query=resolved.text,
                )
            ],
        )

        rows = ccs.scan_category("garden tools")

        assert rows[0].search_mode == "keyword"
        assert rows[0].search_query == "garden tools"
        assert rows[0].category == "garden tools"

    def test_a_category_browse_says_so(self, monkeypatch, ebay):
        from hunter.category_scan import CategoryProduct

        monkeypatch.setattr(
            ccs, "_scan_via_api",
            lambda resolved, *a, **k: [
                CategoryProduct(
                    title="USB-C hub", price=12.0, url="https://x/2",
                    category=resolved.label or resolved.text,
                    search_mode=resolved.mode, search_query=resolved.text,
                )
            ],
        )

        rows = ccs.scan_category("Electronics")

        assert rows[0].search_mode == "category"
        assert rows[0].search_query == "Electronics"


# ---------------------------------------------------------------------------
# REGRESSION-001c — the API accepted a blank search
# ---------------------------------------------------------------------------

class TestRegression001cApiSeam:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from main import app

        return TestClient(app)

    @pytest.mark.parametrize("text", ["", "   ", "\t\n "])
    def test_a_blank_search_is_rejected_not_defaulted(self, client, text):
        r = client.post("/api/hunter/scan", json={"category": text})
        assert r.status_code == 422, r.text

    def test_the_response_states_what_was_actually_searched(self, client, monkeypatch):
        from hunter import category_scan as ccs_mod

        monkeypatch.setattr(ccs_mod, "_scan_via_api", lambda *a, **k: [])
        monkeypatch.setattr(ccs_mod, "_scan_via_scrape", lambda *a, **k: [])
        monkeypatch.setattr(
            "hunter.demand_check.batch_demand_check", lambda p: p
        )

        r = client.post("/api/hunter/scan", json={"category": "garden tools"})

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["search"]["mode"] == "keyword"
        assert body["search"]["text"] == "garden tools"

    def test_a_picked_category_is_reported_as_a_category(self, client, monkeypatch):
        from hunter import category_scan as ccs_mod

        monkeypatch.setattr(ccs_mod, "_scan_via_api", lambda *a, **k: [])
        monkeypatch.setattr(ccs_mod, "_scan_via_scrape", lambda *a, **k: [])
        monkeypatch.setattr(
            "hunter.demand_check.batch_demand_check", lambda p: p
        )

        r = client.post("/api/hunter/scan", json={"category": "Electronics"})

        body = r.json()
        assert body["search"]["mode"] == "category"
        assert body["search"]["label"] == "Electronics"

    def test_the_ui_can_offer_the_real_category_list(self, client):
        r = client.get("/api/hunter/categories")

        assert r.status_code == 200
        labels = [c["label"] for c in r.json()["categories"]]
        assert "Electronics" in labels
        assert "Home & Garden" in labels


# ---------------------------------------------------------------------------
# REGRESSION-002 — the Hunter sourced suppliers from scrapers that do not
# match. 60 of the 109 supplier rows recorded in the real database sat
# outside the 1.6x price veto, e.g. an eBay listing at GBP35.99 "Wireless
# Bluetooth Earbuds" matched to an AliExpress row at GBP641.48. Those are
# not the same product; the matcher was right to reject them and the Hunter
# therefore showed nothing. The fix is the SOURCE, not a looser matcher:
# SerpApi discovery returns genuinely matching offers with real product URLs
# (verified live), so it becomes the primary source and the direct scrapers
# are the fallback.
# ---------------------------------------------------------------------------

def _product(title="Bosch 18V Combi Drill", price=24.99, **kw):
    from hunter.category_scan import CategoryProduct

    return CategoryProduct(title=title, price=price, url="https://x/itm", **kw)


def _serpapi_row(title="Bosch 18V Combi Drill", price=9.99, source="Toolstation"):
    from scrapers.base import ScrapedProduct

    return ScrapedProduct(
        source=source, title=title, price=price,
        url="https://www.toolstation.com/p1", condition="", verified=True,
    )


@pytest.fixture(autouse=True)
def _no_direct_scrapers(monkeypatch):
    """The three direct marketplace scrapers contribute nothing in this file.

    Two reasons: REGRESSION-002 is specifically about what happens when
    discovery is the only source, and leaving them live would make the suite
    hit the real CJ/AliExpress/Amazon endpoints (20s of timeouts per product)
    and turn a unit test into a network test.
    """
    from hunter import supplier_lookup as sl  # noqa: F401  (import check)

    async def _none(self, query):
        return []

    async def _hang(self, query):
        raise __import__("asyncio").TimeoutError()

    for mod, cls in (("scrapers.cjdropshipping", "CJDropshippingScraper"),
                     ("scrapers.aliexpress", "AliExpressScraper"),
                     ("scrapers.amazon_uk", "AmazonUKScraper")):
        try:
            m = __import__(mod, fromlist=[cls])
            monkeypatch.setattr(getattr(m, cls), "search", _none)
        except Exception:
            pass


class TestRegression002SupplierSource:
    def test_discovery_supplies_the_price(self, monkeypatch):
        from hunter import supplier_lookup as sl
        from scrapers import serpapi_discovery as sd

        monkeypatch.setattr(
            sd, "discover",
            lambda q: [_serpapi_row(title=q)],
        )

        p = _product()
        kept, _excluded = sl.batch_supplier_lookup([p])

        assert p.supplier_price == pytest.approx(9.99)
        assert p.supplier_name == "Toolstation"
        assert p.supplier_url.startswith("https://www.toolstation.com/")
        assert p in kept

    def test_the_matcher_still_decides_whether_the_offer_counts(self, monkeypatch):
        """Discovery is a better source, not a licence to accept anything.

        The offer is a real, reachable Toolstation listing — it is simply far
        too expensive to be a source for this eBay item, so the C14 price veto
        must still reject it. The row comes back MARKED, not deleted.
        """
        from hunter import supplier_lookup as sl
        from scrapers import serpapi_discovery as sd

        monkeypatch.setattr(
            sd, "discover",
            lambda q: [_serpapi_row(title=q, price=400.0)],
        )

        p = _product()
        sl.batch_supplier_lookup([p])

        assert p.supplier_price == 0.0
        assert p.supplier_status == "no_supplier"
        assert p.supplier_status != "found"

    def test_no_key_means_no_discovery_and_no_crash(self, monkeypatch):
        from hunter import supplier_lookup as sl
        from scrapers import serpapi_discovery as sd

        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        monkeypatch.setattr(sd, "discover", lambda q: [])

        p = _product()
        kept, _excluded = sl.batch_supplier_lookup([p])

        assert p.supplier_status == "no_supplier"
        assert p.supplier_price == 0.0


# ---------------------------------------------------------------------------
# REGRESSION-003 — the outer timeout was shorter than the work inside it
#
# LOOKUP_TIMEOUT was 15s, but the lookup could take 10s on CJ and then a
# further 10s on the AliExpress/Amazon fallback — 20s of work inside a 15s
# budget. Whenever CJ came back empty the outer kill fired, `supplier` was
# None, and every remaining product was dropped with no explanation.
# ---------------------------------------------------------------------------

class TestRegression003TimeoutBudget:
    def test_the_outer_budget_covers_the_worst_case_inside_it(self):
        from hunter.supplier_lookup import (
            LOOKUP_TIMEOUT,
            SUPPLIER_FETCH_TIMEOUT,
        )

        # Worst case is sequential: CJ (fetch timeout) then the
        # AliExpress/Amazon gather (another fetch timeout).
        assert LOOKUP_TIMEOUT >= SUPPLIER_FETCH_TIMEOUT * 2

    def test_a_timeout_is_recorded_not_silently_dropped(self, monkeypatch):
        """The OUTER budget firing must be reported, not silently dropped.

        `discover` is dispatched with `asyncio.to_thread`, so a genuinely
        blocking stub is what makes the outer `asyncio.wait_for` fire — this
        is the exact shape of the production failure, where 20s of scraper
        work sat inside a 15s budget.
        """
        import time as _time

        from hunter import supplier_lookup as sl
        from scrapers import serpapi_discovery as sd

        def _slow_discover(query):
            _time.sleep(2.0)
            return []

        monkeypatch.setattr(sd, "discover", _slow_discover)
        monkeypatch.setattr(sl, "LOOKUP_TIMEOUT", 0.05)

        p = _product()
        kept, _excluded = sl.batch_supplier_lookup([p])

        assert p.supplier_status == "timeout"
        assert p in kept, "a timed-out row is reported, not deleted"

    def test_a_discovery_failure_is_reported_as_no_supplier_not_a_timeout(
        self, monkeypatch
    ):
        """Discovery fails closed: an error is 'no supplier', not a timeout.

        Both are honest, but conflating them would hide a broken key behind a
        vague "timed out".
        """
        from hunter import supplier_lookup as sl
        from scrapers import serpapi_discovery as sd

        def _boom(query):
            raise RuntimeError("serpapi is down")

        monkeypatch.setattr(sd, "discover", _boom)

        p = _product()
        sl.batch_supplier_lookup([p])

        assert p.supplier_status == "no_supplier"


# ---------------------------------------------------------------------------
# REGRESSION-004 — "no supplier" was displayed as a real 0.00
#
# profit_calc wrote `product.profit = 0` / `margin = 0` when there was no
# supplier, and the frontend rendered 0 as a confident red "GBP0.00 (0.0%)".
# A missing value is not a zero, and this is C13/C1: it must be shown as
# unverified, never claimed. Each row now records WHY it has no supplier.
# ---------------------------------------------------------------------------

class TestRegression004NoSupplierIsNotZero:
    def test_a_product_with_no_supplier_says_so(self, monkeypatch):
        from hunter import supplier_lookup as sl
        from scrapers import serpapi_discovery as sd

        monkeypatch.setattr(sd, "discover", lambda q: [])

        p = _product()
        sl.batch_supplier_lookup([p])

        assert p.supplier_status == "no_supplier"
        assert p.supplier_price == 0.0   # the raw value stays 0 ...
        assert p.supplier_status != ""   # ... but it is no longer reported as a fact

    def test_an_out_of_band_product_is_marked_separately(self, monkeypatch):
        from hunter import supplier_lookup as sl

        p = _product(price=2.0)   # below the GBP5 active band
        kept, excluded = sl.batch_supplier_lookup([p])

        assert p.supplier_status == "out_of_band"
        assert excluded == 1
        assert kept == []

    def test_a_found_supplier_is_marked_found(self, monkeypatch):
        from hunter import supplier_lookup as sl
        from scrapers import serpapi_discovery as sd

        monkeypatch.setattr(sd, "discover", lambda q: [_serpapi_row(title=q)])

        p = _product()
        sl.batch_supplier_lookup([p])

        assert p.supplier_status == "found"


# ---------------------------------------------------------------------------
# REGRESSION-005 — "no data" was rendered as a real GBP0.00
#
# profit_calc wrote `product.profit = 0` / `margin = 0` when there was no
# supplier, and the frontend rendered 0 (not null) as a confident red
# "GBP0.00 (0.0%)". A missing value is not a zero (C1/C13), and every other
# analysis endpoint already stamps provenance - the Hunter was the only one
# that did not.
# ---------------------------------------------------------------------------

class TestRegression005ProfitIsHonest:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from main import app

        return TestClient(app)

    def test_a_product_with_no_supplier_claims_no_profit(self, monkeypatch):
        from hunter import profit_calc as pc

        p = _product(price=24.99)
        p.supplier_status = "no_supplier"

        pc._calc_single(p, {"margin_min": 25.0})

        # The raw numbers stay 0 because that is all we know - but the row now
        # says WHY, and that the figure is not a measurement.
        assert p.profit_provenance == "unverified"
        assert p.profit_provenance_reason
        assert p.profit_status == "no_supplier"

    def test_a_real_profit_is_stamped_estimated_not_verified(self, monkeypatch):
        from hunter import profit_calc as pc

        p = _product(price=24.99)
        p.supplier_price = 9.99
        p.supplier_status = "found"
        p.sold_30d, p.sold_7d = 40, 10

        pc._calc_single(p, {"margin_min": 25.0})

        assert p.profit_provenance == "estimated"
        assert p.profit_provenance_method

    def test_profit_accounts_for_shipping_when_it_is_known(self):
        """Shipping was dropped on the floor, so profit was overstated."""
        from engine.profit import calculate_profit

        without = calculate_profit(24.99, 9.99)
        with_shipping = calculate_profit(24.99, 9.99, shipping_cost=3.50)

        assert with_shipping["profit"] < without["profit"]
        assert with_shipping["shipping_cost"] == 3.50

    def test_unknown_shipping_is_reported_not_assumed(self):
        """0.0 means UNKNOWN, never free - so it must not quietly vanish."""
        from engine.profit import calculate_profit

        result = calculate_profit(24.99, 9.99, shipping_cost=0.0)

        assert result["shipping_cost"] == 0.0
        assert result["shipping_known"] is False
        assert result["profit_is_complete"] is False

    def test_an_empty_result_says_why_it_is_empty(self, client, monkeypatch):
        """A run where every lookup timed out must NOT look like an empty
        category. The counts are real, so the user can tell them apart."""
        import time as _time

        from hunter import supplier_lookup as sl
        from scrapers import serpapi_discovery as sd

        def _slow(query):
            _time.sleep(1.0)
            return []

        monkeypatch.setattr(sd, "discover", _slow)
        monkeypatch.setattr(sl, "LOOKUP_TIMEOUT", 0.05)

        r = client.post("/api/hunter/lookup", json={
            "products": [{
                "title": "Greenhouse 6ft", "price": 24.99, "url": "https://x/1",
                "_total_scanned": 12, "_price_min": 5.0, "_price_max": 35.0,
            }],
        })

        assert r.status_code == 200, r.text
        summary = r.json()["summary"]
        assert summary["scanned"] == 12
        assert summary["with_supplier"] == 0
        assert summary["timed_out"] == 1
        assert summary["price_min"] == 5.0 and summary["price_max"] == 35.0

    def test_a_genuinely_empty_scan_reports_zero_honestly(self, client, monkeypatch):
        from hunter import category_scan as ccs

        monkeypatch.setattr(ccs, "_scan_via_api", lambda *a, **k: [])
        monkeypatch.setattr(ccs, "_scan_via_scrape", lambda *a, **k: [])

        r = client.post("/api/hunter/scan", json={"category": "garden tools"})

        body = r.json()
        assert body["products"] == []
        assert body["total_scanned"] == 0
        # The search was still resolved and reported, so an empty result is
        # visibly "we looked for this and eBay had nothing" - not a silent
        # fallback to some other category.
        assert body["search"]["text"] == "garden tools"

    def test_hot_needs_accelerating_demand_not_just_a_big_number(self):
        """'Hot' means the 7-day pace beats the 30-day pace.

        A product selling a steady 40/month is not hot; one that went from
        5/month to 30/month is. The badge is computed from the counts, never
        assigned.
        """
        from hunter.demand_hotness import hotness

        # Steady: 40 over 30d is ~9.2/week, so 9 in the last 7 days is the
        # same pace - nothing has changed, so nothing is "hot".
        steady = hotness(sold_30d=40, sold_7d=9, demand_min_30d=30,
                         demand_min_7d=8)
        # Accelerating: 25 in 7 days is ~25/week against a ~9/week baseline.
        accelerating = hotness(sold_30d=40, sold_7d=25, demand_min_30d=30,
                               demand_min_7d=8)

        assert steady["hot"] is False
        assert accelerating["hot"] is True
        assert accelerating["pace_7d_per_week"] > steady["pace_7d_per_week"]

    def test_hot_requires_clearing_the_demand_thresholds(self):
        from hunter.demand_hotness import hotness

        fast_but_thin = hotness(sold_30d=10, sold_7d=9, demand_min_30d=30,
                                demand_min_7d=8)
        assert fast_but_thin["hot"] is False
        assert fast_but_thin["meets_demand"] is False

    def test_no_demand_data_means_not_hot_and_says_why(self):
        """Zero sold is unknown, not 'cold'. Never a confident badge."""
        from hunter.demand_hotness import hotness

        result = hotness(sold_30d=0, sold_7d=0, demand_min_30d=30,
                         demand_min_7d=8)

        assert result["hot"] is False
        assert result["provenance"] == "unverified"
        assert result["reason"]

    def test_the_report_marks_hot_products(self, client, monkeypatch):
        from hunter import profit_calc as pc
        from hunter import report as rp
        from hunter import supplier_lookup as sl
        from hunter import demand_hotness
        from scrapers import serpapi_discovery as sd

        monkeypatch.setattr(sd, "discover", lambda q: [_serpapi_row(title=q)])

        hot = _product(title="Cordless Drill", price=24.99)
        hot.sold_30d, hot.sold_7d = 40, 25
        cold = _product(title="Wall Clock", price=12.0)
        cold.sold_30d, cold.sold_7d = 5, 0

        for p in (hot, cold):
            sl.batch_supplier_lookup([p])
            pc._calc_single(p, {"margin_min": 25.0})

        rep = rp.generate_report([hot, cold], "Electronics", 5.0, 35.0,
                                 total_scanned=2)
        rows = rep.to_dict()["products"]

        assert rows[0]["hot"] is True
        assert rows[0]["hot_basis"]
        assert rows[1]["hot"] is False

    def test_hot_for_a_30d_window_uses_only_real_30d_data(self):
        """A product selling steadily is 30d-hot even with no 7d signal.

        The 7-day count needs a fresh extension capture to exist at all, so a
        30d decision must not require it.
        """
        from hunter.demand_hotness import hotness_for_window

        result = hotness_for_window(
            sold_30d=40, sold_7d=None, window="30d",
            demand_min_30d=30, demand_min_7d=8,
        )
        assert result["hot"] is True
        assert result["provenance"] == "verified"
        assert result["window"] == "30d"
        # The 7d facts are simply absent, not fabricated.
        assert result["pace_7d_per_week"] is None

    def test_a_7d_window_says_it_has_no_data_when_none_exists(self):
        """No fresh capture => the 7d view says UNKNOWN, never a fake 7d."""
        from hunter.demand_hotness import hotness_for_window

        result = hotness_for_window(
            sold_30d=40, sold_7d=None, window="7d",
            demand_min_30d=30, demand_min_7d=8,
        )
        assert result["hot"] is False
        assert result["provenance"] == "unverified"
        assert "no 7-day data" in result["reason"].lower()

    def test_a_7d_window_only_uses_real_7d_count(self):
        from hunter.demand_hotness import hotness_for_window

        result = hotness_for_window(
            sold_30d=40, sold_7d=10, window="7d",
            demand_min_30d=30, demand_min_7d=8,
        )
        assert result["provenance"] == "verified"
        assert result["hot"] is True
        assert result["pace_7d_per_week"] == round(10.0 / 7.0, 1)

    def test_a_7d_hot_row_is_not_called_30d_hot_falsely(self):
        """Clearing the 7d bar does not mean it cleared the 30d bar."""
        from hunter.demand_hotness import hotness_for_window

        r7 = hotness_for_window(sold_30d=12, sold_7d=10, window="7d",
                                demand_min_30d=30, demand_min_7d=8)
        r30 = hotness_for_window(sold_30d=12, sold_7d=10, window="30d",
                                 demand_min_30d=30, demand_min_7d=8)
        assert r7["provenance"] == "verified"
        assert r30["provenance"] == "verified"
        # 10 in 7d may clear the 7d floor; 12 in 30d does NOT clear the 30d one.
        assert r30["hot"] is False
        # The 7d verdict is decided by real 7d data alone.
        assert r7["hot"] in (True, False)

    def test_the_report_carries_a_provenance_block(self):
        """The Hunter was the only analysis endpoint with none (C13)."""
        from hunter import profit_calc as pc
        from hunter import report as rp

        # A row's profit provenance is written by profit calc, so the report
        # is exercised the way it runs in production rather than with a
        # hand-built half-state.
        p = _product(price=24.99)
        p.supplier_status = "no_supplier"
        pc._calc_single(p, {"margin_min": 25.0})

        rep = rp.generate_report([p], "Electronics", 5.0, 35.0, total_scanned=1)

        body = rep.to_dict()
        assert body["provenance"]["profit"]["provenance"] == "unverified"
        assert body["provenance"]["profit"]["rows_unverified"] == 1
        assert body["products"][0]["profit_provenance"] == "unverified"
        assert body["products"][0]["supplier_status"] == "no_supplier"

    def test_a_supplier_shipping_cost_reaches_the_profit(self, monkeypatch):
        """The scraper reads shipping; it must not be discarded before profit."""
        from hunter import profit_calc as pc
        from hunter import supplier_lookup as sl
        from scrapers import serpapi_discovery as sd

        row = _serpapi_row(title="Bosch 18V Combi Drill", price=9.99)
        row.shipping_cost = 3.50
        row.shipping_raw = "GBP3.50 delivery"
        monkeypatch.setattr(sd, "discover", lambda q: [row])

        p = _product(price=24.99)
        sl.batch_supplier_lookup([p])
        pc._calc_single(p, {"margin_min": 25.0})

        assert p.shipping_cost == pytest.approx(3.50)
        assert p.shipping_raw == "GBP3.50 delivery"

    def test_a_fully_sourced_report_is_estimated_not_verified(self):
        from hunter import profit_calc as pc
        from hunter import report as rp

        p = _product(price=24.99)
        p.supplier_price = 9.99
        p.supplier_status = "found"
        p.sold_30d, p.sold_7d = 40, 10
        pc._calc_single(p, {"margin_min": 25.0})

        rep = rp.generate_report([p], "Electronics", 5.0, 35.0, total_scanned=1)

        block = rep.to_dict()["provenance"]["profit"]
        # Arithmetic on two prices is an estimate. Calling it "verified" would
        # overstate what any of this system actually knows.
        assert block["provenance"] == "estimated"
        assert block["rows_unverified"] == 0
