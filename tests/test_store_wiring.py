"""C11 + C13 — the store block, wired through every analysis surface.

C11 — Analyze, URL-hunt, Deep Search (full and fast/Bulk) and Category
      Hunter all surface up to 4 REAL eBay competitor stores built from
      real ``seller.username`` values: ``sold_count`` labelled as listings
      observed in the search window (cap 50) — it is NOT eBay's sold
      count — and a DERIVED ``ebay.co.uk/str/{username}`` URL carried as
      ``url_derived=True`` on every row.

C13 — the block stamp FAILS CLOSED: ``verified`` when non-empty,
      ``unverified`` (with a reason) when empty. An empty block may never
      read verified.

This file tests the WIRING — ``run_analysis_pipeline``, the /api/analyze
serializer (success AND timeout), both deep_search paths plus the
deep-search endpoints' timeout, the Browse-API seller capture in
scrapers/ebay.py, the CSV/JSON exporters and the Hunter batch path.
engine.stores' own units (normalise_username, build_stores,
store_provenance_block in isolation) are covered by tests/test_stores.py
and are deliberately NOT repeated here.

ZERO NETWORK — two autouse fixtures kill every ``requests`` call and pin
the active price band to the config defaults; every collaborator a path
can reach is stubbed with monkeypatch, so an unstubbed call fails loudly
instead of reaching eBay.
"""

import csv
import io
import json

import pytest

import analysis_pipeline as ap
import deep_search as ds
from config import EBAY_UK_BASE
from engine import stores as stores_mod
from engine.price_gate import active_bounds
from engine.provenance import Provenance
from engine.stores import (
    MAX_STORES,
    OBSERVED_WINDOW,
    store_provenance_block,
    stores_from_top_sellers,
)
from scrapers.base import DemandData, ScrapedProduct
from scrapers.ebay import EbayScraper
from scrapers.ebay_sold import EbaySoldData, EbaySoldItem, EbaySoldScraper

# Every key a C11/C13 store row must carry (stores._row).
REQUIRED_ROW_KEYS = {
    "name", "url", "url_derived", "sold_count", "sold_count_label",
    "avg_price", "provenance", "provenance_label", "source_name",
}


# ---------------------------------------------------------------------------
# Offline guarantees
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _zero_network(monkeypatch):
    """C11 discovery is meant to be FREE — enforce offline for the whole file.

    A path that reaches a scraper without its own stub dies here instead of
    quietly issuing a request to eBay."""
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("network call attempted — this file runs offline")

    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)
    monkeypatch.setattr(requests.Session, "get", _blocked)
    monkeypatch.setattr(requests.Session, "post", _blocked)


@pytest.fixture(autouse=True)
def _pristine_range(monkeypatch, tmp_path):
    """Pin the ACTIVE band to the config defaults (£5–£35) so price-band
    assumptions below cannot drift with whoever last edited the UI."""
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
# Fixtures / helpers
# ---------------------------------------------------------------------------

class _Stub:
    """Stand-in for a collaborator method: records the call, then returns
    ``result`` or raises ``error``.

    Patched onto the CLASS it is not a descriptor, so it receives the call
    arguments only (no ``self``) — calls are recorded either way."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


class _FallbackProbe:
    """Fake for ``discover_stores`` — the ONE path allowed to spend a
    request. Records the call, then raises: a fallback reached by a path
    that promised to be free must fail the test, not spend a request."""

    def __init__(self, rows=None):
        self.rows = rows
        self.calls = []

    def __call__(self, query, limit=None):
        self.calls.append((query, limit))
        if self.rows is None:
            raise AssertionError(f"store discovery reached for {query!r} — must be free")
        return self.rows


def _top_sellers(n=6):
    """Exactly the dict shape ``DemandData.top_sellers`` carries — six
    stores so the C11 cap of 4 has something to cut."""
    return [
        {"name": f"store_{i:02d}", "sold_count": n - i, "avg_price": 9.99}
        for i in range(n)
    ]


def _demand(top_sellers):
    return DemandData(
        sold_count_30d=40, sold_count_7d=10, avg_sold_price=9.99,
        verified=True, top_sellers=top_sellers,
    )


def _ebay_product():
    # seller=None: the plain-search discovery fallback must not invent a
    # store out of the analysed listing itself.
    return ScrapedProduct(
        source="ebay_uk", title="Generic widget", price=12.0,
        url="https://www.ebay.co.uk/itm/1", condition="New",
        seller=None, verified=True,
    )


def _sold_items(n=6):
    return [
        EbaySoldItem(
            title="Generic widget", price=9.99,
            url=f"https://www.ebay.co.uk/itm/{i}", seller=f"store_{i:02d}",
            seller_url="", sold_date="", condition="New",
        )
        for i in range(n)
    ]


def _sold_data(top=True):
    """An ``EbaySoldData`` shaped like the real sold query's return value."""
    return EbaySoldData(
        product_name="widget", query="widget",
        total_sold_30d=42, total_sold_7d=9,
        price_min=8.0, price_max=15.0, price_avg=9.99, price_median=9.99,
        top_sellers=_top_sellers() if top else [],
        items=_sold_items() if top else [],
    )


def _assert_store_row(row):
    """C11/C13 — the row contract, asserted wherever a row surfaces."""
    assert REQUIRED_ROW_KEYS <= set(row)
    assert row["url_derived"] is True                     # derived, never observed
    assert row["url"].startswith(f"{EBAY_UK_BASE}/str/")  # config base + /str/
    label = row["sold_count_label"]
    assert "observed" in label.lower()                    # never eBay's sold count
    assert f"cap {OBSERVED_WINDOW}" in label              # window travels with it
    assert row["provenance"] in {"verified", "unverified"}
    assert row["provenance_label"] == Provenance(row["provenance"]).label


def _names(rows):
    return [r["name"] for r in rows]


class _FakeAnalyzer:
    """Stand-in for llm.analyzer.ProductAnalyzer — no Ollama, no 45s hang."""

    async def analyze(self, *args, **kwargs):
        return None

    async def close(self):
        return None


# ---------------------------------------------------------------------------
# A. run_analysis_pipeline (Analyze + URL-hunt)
# ---------------------------------------------------------------------------

def _run_pipeline(monkeypatch, *, is_url, top_sellers):
    """Drive run_analysis_pipeline end-to-end with collaborators stubbed.

    Step 1 (eBay product), Step 2 (demand), Step 3 (7 supplier scrapers),
    Step 4 (LLM) and the purchase-history DB override are all replaced;
    engine code (price gate, condition gate, verdict, scorecard) runs for
    real, because that is what the store block has to survive."""

    async def _no_suppliers(query, progress=None):
        return []

    monkeypatch.setattr(ap, "apply_purchase_history",
                        lambda demand, url, db=None: demand)
    monkeypatch.setattr(ap, "search_all_suppliers", _no_suppliers)
    monkeypatch.setattr(ap, "ProductAnalyzer", _FakeAnalyzer)
    monkeypatch.setattr(EbayScraper, "search", _Stub(result=[_ebay_product()]))
    monkeypatch.setattr(EbayScraper, "get_details", _Stub(result=_ebay_product()))
    monkeypatch.setattr(EbayScraper, "get_sold_data",
                        _Stub(result=_demand(top_sellers)))
    # Discovery fallback (the only path allowed to spend a request) stays
    # offline: empty sold search + a search result with no seller.
    monkeypatch.setattr(EbaySoldScraper, "get_sold_data",
                        _Stub(result=_sold_data(top=False)))

    query = "https://www.ebay.co.uk/itm/1" if is_url else "generic widget"
    return ap.run_async(ap.run_analysis_pipeline(query, is_url=is_url))


class TestAnalyzeAndUrlHuntStores:
    """C11 — the store block on the Analyze and URL-hunt paths."""

    @pytest.mark.parametrize("is_url", [False, True], ids=["analyze", "url-hunt"])
    def test_store_keys_exist_even_when_discovery_finds_nothing(
            self, monkeypatch, is_url):
        results = _run_pipeline(monkeypatch, is_url=is_url, top_sellers=[])
        assert results["errors"] == []
        # C11 — present-but-empty reads as "we found none", never as N/A.
        assert "ebay_stores" in results
        assert "ebay_stores_provenance" in results
        assert results["ebay_stores"] == []

    @pytest.mark.parametrize("is_url", [False, True], ids=["analyze", "url-hunt"])
    def test_six_top_sellers_surface_as_at_most_four_stores(
            self, monkeypatch, is_url):
        results = _run_pipeline(monkeypatch, is_url=is_url,
                                top_sellers=_top_sellers(6))
        assert results["errors"] == []
        stores = results["ebay_stores"]
        assert 0 < len(stores) <= MAX_STORES
        assert len(stores) == MAX_STORES == 4
        # C11 — the four with the highest observed counts survive the cap.
        assert _names(stores) == ["store_00", "store_01", "store_02", "store_03"]
        for row in stores:
            _assert_store_row(row)

    @pytest.mark.parametrize("is_url", [False, True], ids=["analyze", "url-hunt"])
    def test_non_empty_block_is_stamped_verified(self, monkeypatch, is_url):
        results = _run_pipeline(monkeypatch, is_url=is_url,
                                top_sellers=_top_sellers(6))
        block = results["ebay_stores_provenance"]
        # C13 — read off a real eBay response, and the stamp says HOW.
        assert block["provenance"] == Provenance.VERIFIED.value
        assert block["method"]

    @pytest.mark.parametrize("is_url", [False, True], ids=["analyze", "url-hunt"])
    def test_empty_block_is_never_stamped_verified(self, monkeypatch, is_url):
        # C13 — "we found no stores" and "we could not look" are both
        # unconfirmed, so an empty list may never be shown as verified.
        results = _run_pipeline(monkeypatch, is_url=is_url, top_sellers=[])
        block = results["ebay_stores_provenance"]
        assert block["provenance"] == "unverified"
        assert block["provenance"] != Provenance.VERIFIED.value
        assert block["reason"]


# ---------------------------------------------------------------------------
# B. /api/analyze serialization
# ---------------------------------------------------------------------------

class TestAnalyzeEndpointSerialization:
    """C11 — the response carries the store block on success AND timeout."""

    @staticmethod
    def _raw(stores):
        return {
            "ebay_product": None, "demand": None, "supplier_matches": [],
            "llm_analysis": None, "verdict": None, "scorecard": "",
            "errors": [],
            "ebay_stores": stores,
            "ebay_stores_provenance": store_provenance_block(stores),
        }

    def test_success_response_carries_stores_and_stamp(self, monkeypatch):
        import api.analyze as api_analyze
        from api.schemas import AnalyzeRequest

        stores = stores_from_top_sellers(_top_sellers())

        async def _pipeline(query, is_url=False, progress=None, filters=None):
            return self._raw(stores)

        monkeypatch.setattr(api_analyze, "run_analysis_pipeline", _pipeline)
        resp = api_analyze.analyze(AnalyzeRequest(query="widget"))

        assert "ebay_stores" in resp
        assert "ebay_stores_provenance" in resp
        assert 0 < len(resp["ebay_stores"]) == MAX_STORES
        assert resp["ebay_stores_provenance"]["provenance"] == \
            Provenance.VERIFIED.value
        for row in resp["ebay_stores"]:
            _assert_store_row(row)

    def test_timeout_response_still_carries_the_keys(self, monkeypatch):
        # C11 — a timeout discovered no stores; say so rather than omitting
        # the key (an absent list would read as "not applicable").
        import api.analyze as api_analyze
        from api.schemas import AnalyzeRequest

        def _timeout(coro, timeout=None):
            coro.close()  # never awaited — don't leak a RuntimeWarning
            raise TimeoutError("budget exhausted")

        monkeypatch.setattr(api_analyze, "run_async", _timeout)
        resp = api_analyze.analyze(AnalyzeRequest(query="widget"))

        assert resp["ebay_stores"] == []
        block = resp["ebay_stores_provenance"]
        assert block["provenance"] == "unverified"
        assert block["reason"]
        assert any("timed out" in e for e in resp["errors"])


# ---------------------------------------------------------------------------
# C. deep_search — full path AND fast path (Bulk)
# ---------------------------------------------------------------------------

_LLM_JSON = json.dumps({
    "product_name": "Widget",
    "product_category": "widgets",
    "ebay_avg_price": 9.99,
    "supplier_candidates": [],
})


def _stub_deep_search(monkeypatch, sold_data):
    """All network/LLM dependencies of the deep-search paths, per the
    fixtures in tests/test_provenance.py."""
    monkeypatch.setattr(EbaySoldScraper, "get_sold_data",
                        _Stub(result=sold_data))
    monkeypatch.setattr(ds, "_web_search", lambda *a, **k: [])
    monkeypatch.setattr(ds, "_fetch_page_text", lambda *a, **k: "")
    monkeypatch.setattr(ds, "_ollama_generate", lambda *a, **k: _LLM_JSON)
    monkeypatch.setattr(ds, "_verify_supplier_candidates",
                        lambda query, cands: [])
    # The search loop sleeps between queries even with zero hits — no
    # reason to spend 2s per test on a stub.
    monkeypatch.setattr(ds.time, "sleep", lambda seconds: None)
    # Discovery fallback must stay offline even for the empty-sold case.
    monkeypatch.setattr(EbayScraper, "search", _Stub(result=[]))


def _stub_fast_path(monkeypatch, sold_data):
    """deep_search_fast = the Bulk path (C11 names Bulk explicitly): sold
    data plus three supplier scrapes, no LLM, no web search."""
    from scrapers.aliexpress import AliExpressScraper
    from scrapers.amazon_uk import AmazonUKScraper
    from scrapers.cjdropshipping import CJDropshippingScraper

    async def _no_scrape(self, query):
        return []

    _stub_deep_search(monkeypatch, sold_data)
    for cls in (CJDropshippingScraper, AliExpressScraper, AmazonUKScraper):
        monkeypatch.setattr(cls, "search", _no_scrape)


@pytest.fixture
def full_deep_search(monkeypatch):
    """Full path with NON-EMPTY sold data (same stubs as test_provenance)."""
    _stub_deep_search(monkeypatch, _sold_data(top=True))
    return ds.deep_search_product("widget")


@pytest.fixture
def offline_deep_search(monkeypatch):
    """Full path with EMPTY sold data — stores must fail closed."""
    _stub_deep_search(monkeypatch, _sold_data(top=False))
    return ds.deep_search_product("widget")


@pytest.fixture
def fast_deep_search(monkeypatch):
    """Fast path with non-empty sold data — the Bulk path."""
    _stub_fast_path(monkeypatch, _sold_data(top=True))
    return ds.deep_search_fast("widget")


class TestDeepSearchStores:
    def test_full_path_stores_come_from_the_sold_query(self, full_deep_search):
        stores = full_deep_search.ebay_stores
        assert 0 < len(stores) <= MAX_STORES
        assert len(stores) == MAX_STORES == 4
        for row in stores:
            _assert_store_row(row)

    def test_fast_path_populates_stores_for_bulk(self, fast_deep_search):
        # C11 — Bulk runs fast once per line; it must still surface stores.
        stores = fast_deep_search.ebay_stores
        assert 0 < len(stores) <= MAX_STORES
        assert len(stores) == MAX_STORES == 4
        for row in stores:
            _assert_store_row(row)

    @pytest.mark.parametrize("fixture_name", ["full_deep_search",
                                              "fast_deep_search"])
    def test_non_empty_stamp_is_verified(self, request, fixture_name):
        result = request.getfixturevalue(fixture_name)
        assert result.ebay_stores_provenance["provenance"] == \
            Provenance.VERIFIED.value

    def test_empty_stamp_is_unverified_with_a_reason(self, offline_deep_search):
        block = offline_deep_search.ebay_stores_provenance
        assert offline_deep_search.ebay_stores == []
        assert block["provenance"] == "unverified"
        assert block["provenance"] != Provenance.VERIFIED.value
        assert block["reason"]

    @pytest.mark.parametrize("fixture_name", ["full_deep_search",
                                              "offline_deep_search",
                                              "fast_deep_search"])
    def test_field_provenance_mirrors_the_store_stamp(
            self, request, fixture_name):
        # C13 — an export consumer reading provenance.fields must see the
        # same stamp as the top-level block, not a second opinion.
        result = request.getfixturevalue(fixture_name)
        mirrored = result.field_provenance["ebay_stores"]
        assert mirrored == result.ebay_stores_provenance
        assert mirrored["provenance"] == result.ebay_stores_provenance["provenance"]

    @pytest.mark.parametrize("top", [True, False],
                             ids=["sold-data-has-stores", "sold-data-empty"])
    def test_fast_path_never_spends_a_search(self, monkeypatch, top):
        # C11 — attach_stores is called with sold_data= and NO query= on
        # the fast path, so the discovery fallback must never run. The
        # probe raises if it is reached. The EMPTY variant is the one that
        # proves no query= was passed: with sold data exhausted and no
        # query in hand, resolve_stores must stop instead of searching.
        probe = _FallbackProbe()
        monkeypatch.setattr(stores_mod, "discover_stores", probe)
        _stub_fast_path(monkeypatch, _sold_data(top=top))

        result = ds.deep_search_fast("widget")

        assert probe.calls == []
        if top:
            # Zero extra network, and the stores still come back from
            # the sold data this run already fetched.
            assert len(result.ebay_stores) == MAX_STORES
            assert "FALLBACK" not in " ".join(_names(result.ebay_stores)).upper()
        else:
            assert result.ebay_stores == []
            assert result.ebay_stores_provenance["provenance"] == "unverified"


# ---------------------------------------------------------------------------
# D. The row contract, wherever a row surfaces
# ---------------------------------------------------------------------------

def _run_demand_check(monkeypatch):
    """batch_demand_check with the sold scraper stubbed and the discovery
    fallback wired to a probe. Returns (products, kept, sold_stub, probe)."""
    from hunter.category_scan import CategoryProduct
    from hunter.demand_check import batch_demand_check

    sold = _Stub(result=_sold_data(top=True))
    probe = _FallbackProbe()
    monkeypatch.setattr(EbaySoldScraper, "get_sold_data", sold)
    monkeypatch.setattr(stores_mod, "discover_stores", probe)

    products = [
        CategoryProduct(title=f"widget {i}", price=12.0,
                        url=f"https://www.ebay.co.uk/itm/{i}")
        for i in range(2)
    ]
    kept = batch_demand_check(products)
    return products, kept, sold, probe


class TestStoreRowContract:
    """C11/C13 — same contract on every surface a row can escape through."""

    def test_rows_from_the_analyze_pipeline(self, monkeypatch):
        results = _run_pipeline(monkeypatch, is_url=False,
                                top_sellers=_top_sellers())
        assert results["ebay_stores"]
        for row in results["ebay_stores"]:
            _assert_store_row(row)

    def test_rows_from_deep_search(self, full_deep_search):
        assert full_deep_search.ebay_stores
        for row in full_deep_search.ebay_stores:
            _assert_store_row(row)

    def test_rows_from_category_hunter(self, monkeypatch):
        products, _, _, _ = _run_demand_check(monkeypatch)
        assert products[0].ebay_stores
        for row in products[0].ebay_stores:
            _assert_store_row(row)


# ---------------------------------------------------------------------------
# E. ebay.py::_get_sold_api — seller capture off the Browse API response
# ---------------------------------------------------------------------------

class _FakeResponse:
    """Canned Browse-API response — raise_for_status/json only."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _api_item(seller=None, price=12.0, condition="New"):
    item = {"price": {"value": f"{price:.2f}", "currency": "GBP"},
            "condition": condition}
    if seller:
        item["seller"] = {"username": seller}
    return item


def _stub_browse_api(monkeypatch, items):
    """Hand _get_sold_api a canned item_summary response: no network and
    no OAuth round-trip (the token fetch is a request of its own)."""
    import requests

    def _get(url, params=None, headers=None, timeout=None):
        assert "item_summary/search" in url, f"unexpected GET {url}"
        return _FakeResponse({"itemSummaries": items})

    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(EbayScraper, "_api_headers",
                        lambda self: {"Authorization": "Bearer stub"})


class TestGetSoldApiSellerCapture:
    """C11 — the seller rides along on the response we already paid for."""

    @staticmethod
    def _run(monkeypatch, items):
        _stub_browse_api(monkeypatch, items)
        scraper = EbayScraper()
        try:
            return scraper._get_sold_api("widget")
        finally:
            scraper.close()

    def test_sellers_are_tallied_capped_and_gated_only_by_condition(
            self, monkeypatch):
        hi = active_bounds()[1]
        items = (
            # Out of YOUR band — still a competitor, so it IS tallied,
            # and heavily enough to survive the cap.
            [_api_item("outside_store", price=hi + 500.0)] * 3
            + [_api_item("store_a", price=12.0)] * 2
            + [_api_item(name) for name in
               ("store_b", "store_c", "store_d", "store_e")]
            # C10 is absolute for stores too — a Used seller never tallies.
            + [_api_item("used_store", price=12.0, condition="Used")] * 4
            # No seller on the row at all — nothing to tally.
            + [_api_item(price=12.0)] * 2
        )
        demand = self._run(monkeypatch, items)

        names = [s["name"] for s in demand.top_sellers]
        assert 0 < len(demand.top_sellers) == MAX_STORES == 4
        assert "used_store" not in names          # C10 — absolute
        assert "outside_store" in names           # price band does NOT gate
        assert "store_d" not in names and "store_e" not in names  # cap bit
        for row in demand.top_sellers:
            _assert_store_row(row)

    def test_response_with_no_seller_at_all_yields_no_stores(self, monkeypatch):
        demand = self._run(
            monkeypatch, [_api_item(price=12.0) for _ in range(5)])
        assert demand.top_sellers == []

    def test_used_only_response_yields_no_stores(self, monkeypatch):
        # C10 — every row Used means zero New-condition competitors.
        demand = self._run(
            monkeypatch,
            [_api_item(f"used_{i}", price=12.0, condition="Used")
             for i in range(5)])
        assert demand.top_sellers == []


# ---------------------------------------------------------------------------
# F. CSV column alignment (regression)
# ---------------------------------------------------------------------------

class _ExportResult:
    """A deep-search-shaped object carrying ``ebay_stores`` for the
    exporters — only the attributes csv_export/format actually read."""

    def __init__(self, stores):
        self.product_name = "Generic widget"
        self.product_category = "tools"
        self.ebay_items_sold_month = "100 items"
        self.ebay_top_sellers = []
        self.ebay_price_min = 8.0
        self.ebay_price_max = 15.0
        self.ebay_avg_price = 9.99
        self.ebay_price_median = 9.99
        self.ebay_total_sold_30d = 100
        self.ebay_total_sold_7d = 25
        self.suppliers = []
        self.best_supplier_price = 0.0
        self.verdict = "PENDING"
        self.field_provenance = {}
        self.ebay_stores = stores


def _stores(n):
    return stores_from_top_sellers(_top_sellers(n)) if n else []


def _store_cols(header):
    """(count columns, url columns) of the C11 store block, in order."""
    count_cols = [i for i, h in enumerate(header)
                  if h.startswith("Store ") and "observed" in h]
    url_cols = [i for i, h in enumerate(header)
                if h.startswith("Store ") and h.endswith(" URL")]
    return count_cols, url_cols


def _assert_alignment(header, row, result):
    """len(header) == len(row) plus the store cells sitting under their
    own headers — a short list must blank-pad, never shift columns."""
    assert len(header) == len(row)
    count_cols, url_cols = _store_cols(header)
    assert len(count_cols) == MAX_STORES
    assert len(url_cols) == MAX_STORES
    # C11 — the header IS the required count label.
    for i in count_cols:
        assert "observed listings (search window, cap 50)" in header[i]
    n = len(result.ebay_stores)
    counts = [row[i] for i in count_cols]
    urls = [row[i] for i in url_cols]
    assert counts[:n] == [str(s["sold_count"]) for s in result.ebay_stores]
    assert counts[n:] == [""] * (MAX_STORES - n)
    assert urls[n:] == [""] * (MAX_STORES - n)


class TestCsvStoreColumnAlignment:
    """C11 — a short store list must still emit MAX_STORES cells (blank-
    padded), or every later column silently shifts left."""

    @pytest.mark.parametrize("n_stores", [4, 2, 0])
    def test_single_export_header_and_row_stay_aligned(self, n_stores):
        from export.csv_export import export_to_csv

        result = _ExportResult(_stores(n_stores))
        rows = list(csv.reader(io.StringIO(export_to_csv(result))))
        header, row = rows[0], rows[1]
        _assert_alignment(header, row, result)

    @pytest.mark.parametrize("n_stores", [4, 2, 0])
    def test_bulk_export_header_and_row_stay_aligned(self, n_stores):
        from export.csv_export import export_bulk_to_csv

        result = _ExportResult(_stores(n_stores))
        rows = list(csv.reader(io.StringIO(export_bulk_to_csv([result]))))
        header, row = rows[0], rows[1]
        _assert_alignment(header, row, result)

    def test_bulk_rows_align_even_when_stores_differ_per_row(self):
        from export.csv_export import export_bulk_to_csv

        results = [_ExportResult(_stores(4)), _ExportResult(_stores(2)),
                   _ExportResult([])]
        rows = list(csv.reader(io.StringIO(export_bulk_to_csv(results))))
        header = rows[0]
        assert len(rows) == 4  # header + 3 rows
        for result, row in zip(results, rows[1:]):
            _assert_alignment(header, row, result)


# ---------------------------------------------------------------------------
# G. Category Hunter
# ---------------------------------------------------------------------------

class TestCategoryHunterStores:
    def test_ebay_stores_defaults_to_empty_list(self):
        from hunter.category_scan import CategoryProduct

        first = CategoryProduct(title="t", price=12.0, url="u")
        second = CategoryProduct(title="t", price=12.0, url="u")
        assert first.ebay_stores == []
        # default_factory, never a shared mutable default.
        first.ebay_stores.append({"name": "leaked"})
        assert second.ebay_stores == []

    def test_generate_report_carries_ebay_stores(self):
        from hunter.category_scan import CategoryProduct
        from hunter.report import export_report_json, generate_report

        stores = _stores(3)
        product = CategoryProduct(title="t", price=12.0, url="u",
                                  ebay_stores=stores)
        report = generate_report([product], "Electronics", 5.0, 35.0,
                                 total_scanned=1)

        assert report.products[0]["ebay_stores"] == stores
        payload = json.loads(export_report_json(report))
        assert payload["products"][0]["ebay_stores"] == stores

    def test_batch_demand_check_populates_stores_without_a_second_call(
            self, monkeypatch):
        products, kept, sold, probe = _run_demand_check(monkeypatch)

        # Both products clear 30/30d and 8/7d, so neither is pruned.
        assert len(kept) == len(products) == 2
        for product in products:
            stores = product.ebay_stores
            assert 0 < len(stores) <= MAX_STORES
            assert len(stores) == MAX_STORES == 4
        # C11 — zero extra network: no discovery call, and exactly one
        # sold query per product (the one the demand check needs anyway).
        assert probe.calls == []
        assert len(sold.calls) == len(products)


# ---------------------------------------------------------------------------
# F2. JSON export schema (export/format.py)
# ---------------------------------------------------------------------------

class TestJsonSchemaStoreBlock:
    """C11/C13 — the JSON schema carries the store block AND its stamp."""

    @staticmethod
    def _result(n_stores, stamped=False):
        result = _ExportResult(_stores(n_stores))
        if stamped:
            result.ebay_stores_provenance = store_provenance_block(
                result.ebay_stores)
        return result

    @pytest.mark.parametrize("n_stores", [4, 0])
    def test_schema_carries_the_block(self, n_stores):
        from export.format import format_to_schema

        out = format_to_schema(self._result(n_stores, stamped=True))

        assert len(out["ebay_stores"]) == n_stores
        for row in out["ebay_stores"]:
            _assert_store_row(row)
        # C13 — the producer's stamp passes through untouched.
        assert out["provenance"]["ebay_stores"] == store_provenance_block(
            out["ebay_stores"])

    def test_empty_and_unstamped_never_reads_verified(self):
        from export.format import format_to_schema

        out = format_to_schema(self._result(0))

        block = out["provenance"]["ebay_stores"]
        assert block["provenance"] == Provenance.UNVERIFIED.value
        assert block["reason"]  # an unverified block must say WHY

    def test_real_rows_without_a_stamp_derive_verified(self):
        from export.format import format_to_schema

        out = format_to_schema(self._result(4))

        assert out["provenance"]["ebay_stores"]["provenance"] == (
            Provenance.VERIFIED.value)


# ---------------------------------------------------------------------------
# Deep Search endpoints — timeout path (api/deep_search.py)
# ---------------------------------------------------------------------------

class TestDeepSearchTimeoutResponse:
    """C11 — the deep-search endpoints surface the store key even when the
    budget expires; C13 — an unstamped empty block is never 'verified'."""

    @pytest.mark.parametrize("endpoint", ["deep_search", "deep_search_fast"])
    def test_timeout_keeps_the_store_key_and_never_claims_verified(
            self, monkeypatch, endpoint):
        import api.deep_search as api_ds
        from api.schemas import DeepSearchRequest

        async def _hang(fn, *args):
            raise TimeoutError("budget exhausted")

        monkeypatch.setattr(api_ds, "_to_thread", _hang)
        resp = getattr(api_ds, endpoint)(DeepSearchRequest(query="widget"))

        assert resp["ebay_stores"] == []
        assert resp["ebay_stores_provenance"].get("provenance") != (
            Provenance.VERIFIED.value)
