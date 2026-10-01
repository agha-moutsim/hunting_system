"""C11 + C13 — the competitor-store block: 4 real sellers, derived URLs, honest labels.

C11 — every analysis surfaces up to 4 eBay stores built from REAL
      ``seller.username`` values: a hard cap of 4 (never padded),
      ``sold_count`` labelled as listings observed in the search window
      (cap 50), and URLs DERIVED as ``ebay.co.uk/str/{username}`` with
      ``url_derived=True`` on every row.

C13 — every row carries provenance, and the block stamp FAILS CLOSED: an
      empty store list may never read as ``verified``.

Guards: normalise_username / derive_store_url / build_stores, the five
source adapters (items, top_sellers, products, demand, scan), the
resolve_stores priority ladder, discover_stores' fall-through discovery,
and the C13 provenance block.

ZERO NETWORK — an autouse fixture kills every ``requests`` call, and each
scraper a discovery path can reach is monkeypatched to a probe, so a call
that should not happen fails the test loudly instead of hitting eBay.

Known production gap (reported, NOT fixed here — see the report):
  ``build_stores`` only guards the UNPACKING of an entry (stores.py:126);
  the int()/float() coercion at stores.py:149 sits OUTSIDE that try, so a
  THREE-character string unpacks as a 3-tuple and then raises instead of
  being skipped::

      build_stores(["abc"])                 -> ValueError: invalid literal
      build_stores([("good_store", "x", 1.0)]) -> ValueError: invalid literal

  The malformed-entry table below therefore uses the shapes the spec names
  (long strings, None, wrong arity), which the guard does handle.
"""

from types import SimpleNamespace

import pytest

import config
from config import EBAY_UK_BASE
from engine import stores as stores_mod
from engine.provenance import Provenance
from engine.stores import (
    MAX_STORES,
    OBSERVED_WINDOW,
    build_stores,
    derive_store_url,
    discover_stores,
    normalise_username,
    resolve_stores,
    store_provenance_block,
    stores_from_demand,
    stores_from_items,
    stores_from_products,
    stores_from_scan,
    stores_from_top_sellers,
)
from scrapers.base import DemandData, ScrapedProduct
from scrapers.ebay import EbayScraper
from scrapers.ebay_sold import EbaySoldData, EbaySoldItem, EbaySoldScraper

# Every key a C11/C13 store row must carry (stores.py _row).
REQUIRED_ROW_KEYS = {
    "name", "url", "url_derived", "sold_count", "sold_count_label",
    "avg_price", "provenance", "provenance_label", "source_name",
}


# ---------------------------------------------------------------------------
# Offline guarantee
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _zero_network(monkeypatch):
    """C11 discovery is meant to be FREE — enforce it for the whole file.

    A path that reaches a scraper without its own stub dies here instead of
    quietly issuing a request to eBay."""
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("network call attempted — this file runs offline")

    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)
    monkeypatch.setattr(requests.Session, "get", _blocked)
    monkeypatch.setattr(requests.Session, "post", _blocked)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _item(seller, price=10.0):
    """An ``EbaySoldItem``-shaped object (the sold scraper's row type)."""
    return EbaySoldItem(
        title="Generic widget", price=price,
        url="https://www.ebay.co.uk/itm/1", seller=seller,
        seller_url="", sold_date="",
    )


def _product(seller, price=10.0):
    """A ``ScrapedProduct``-shaped object (the plain search path)."""
    return ScrapedProduct(
        source="ebay_uk", title="Generic widget", price=price,
        url="https://www.ebay.co.uk/itm/1", seller=seller,
    )


def _top_seller(name, sold_count, total_price, avg_price=None):
    """Exactly the dict ``EbaySoldScraper._calculate_stats`` emits.

    ``avg_price`` is omitted when not supplied, mirroring sellers whose
    accumulator never got a final division."""
    entry = {
        "name": name,
        "url": f"{EBAY_UK_BASE}/str/{name}",
        "sold_count": sold_count,
        "total_price": total_price,
    }
    if avg_price is not None:
        entry["avg_price"] = avg_price
    return entry


def _names(rows):
    return [r["name"] for r in rows]


class _ScraperSpy:
    """Stand-in for a scraper method: records the call, then returns
    ``result`` or raises ``error``.

    Patched onto the CLASS it is not a descriptor, so it receives the call
    arguments only (no ``self``) — calls are still recorded either way."""

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
    """Fake for ``discover_stores`` — the one path allowed to spend a request.

    Built with ``rows=None`` it must NEVER be called: reaching it fails the
    test with an AssertionError instead of a silent network call."""

    def __init__(self, rows=None):
        self.rows = rows
        self.calls = []

    def __call__(self, query, limit=None):
        self.calls.append((query, limit))
        if self.rows is None:
            raise AssertionError(f"search fallback reached for {query!r}")
        return self.rows


# ---------------------------------------------------------------------------
# normalise_username
# ---------------------------------------------------------------------------

class TestNormaliseUsername:
    @pytest.mark.parametrize("raw,expected", [
        ("good_store (12345)", "good_store"),   # HTML path glues feedback on
        ("other_shop (1)", "other_shop"),
        ("clean_name", "clean_name"),           # already-clean passes through
        ("seller-42_uk", "seller-42_uk"),
    ])
    def test_feedback_suffix_is_stripped_and_clean_names_pass(self, raw, expected):
        assert normalise_username(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
    def test_emptyish_input_is_the_empty_string(self, raw):
        # '' means "no store" — callers must never be handed None back.
        assert normalise_username(raw) == ""

    @pytest.mark.parametrize("raw", ["has space", "has/slash", "a b/c"])
    def test_scraped_fragments_are_rejected(self, raw):
        # An eBay username holds neither a space nor a slash; a string that
        # does is a scraped page fragment, not a seller.
        assert normalise_username(raw) == ""


# ---------------------------------------------------------------------------
# derive_store_url
# ---------------------------------------------------------------------------

class TestDeriveStoreUrl:
    def test_url_is_derived_from_the_config_base(self):
        # NOT a hardcoded literal: the base must come from config.
        assert derive_store_url("good_store") == f"{EBAY_UK_BASE}/str/good_store"
        assert derive_store_url("good_store") == \
            "https://www.ebay.co.uk/str/good_store"

    @pytest.mark.parametrize("junk", ["", "   ", "has space", "has/slash"])
    def test_empty_or_junk_username_yields_empty_url(self, junk):
        # A URL we cannot construct is '' — never a half-built link (C11).
        assert derive_store_url(junk) == ""


# ---------------------------------------------------------------------------
# build_stores
# ---------------------------------------------------------------------------

class TestBuildStores:
    def test_caps_at_four_given_twelve_candidates(self):
        # C11 hard cap: 12 real sellers must never surface as 12 rows, and
        # the four with the highest observed counts are the ones kept.
        cands = [(f"store_{i:02d}", i + 1, 5.0) for i in range(12)]
        rows = build_stores(cands)
        assert len(rows) == MAX_STORES == 4
        assert _names(rows) == ["store_11", "store_10", "store_09", "store_08"]

    def test_sorted_by_sold_count_descending(self):
        rows = build_stores([("low", 2, 1.0), ("high", 9, 1.0), ("mid", 5, 1.0)])
        assert _names(rows) == ["high", "mid", "low"]

    def test_unusable_names_are_dropped_not_sorted_in(self):
        # The junk rows carry HIGHER counts than the good row, so seeing
        # only good_store proves they were dropped, not merely deprioritised.
        rows = build_stores([
            ("good_store", 5, 1.0),
            ("bad name", 9, 1.0),
            ("bad/name", 8, 1.0),
            ("", 7, 1.0),
            (None, 6, 1.0),
        ])
        assert _names(rows) == ["good_store"]

    def test_never_pads_to_the_cap(self):
        # 2 real sellers => 2 rows. C11 says UP TO 4 — never invented fill.
        rows = build_stores([("first", 4, 1.0), ("second", 2, 1.0)])
        assert len(rows) == 2

    def test_case_insensitive_dedupe_merges_counts(self):
        # eBay usernames are case-insensitive: Store and store are ONE seller.
        rows = build_stores([("Store", 4, 10.0), ("store", 4, 20.0)])
        assert len(rows) == 1
        assert rows[0]["sold_count"] == 8

    def test_merged_avg_price_stays_between_the_two_inputs(self):
        # Guards the re-weighted mean: a broken merge lands ABOVE both
        # inputs (double counting) or BELOW both (one input dropped).
        avg = build_stores([("Store", 4, 10.0), ("store", 4, 20.0)])[0]["avg_price"]
        assert 10.0 < avg < 20.0
        assert avg == 15.0  # equal weights => exact midpoint

    def test_every_row_carries_the_c11_c13_keys(self):
        row = build_stores([("good_store", 3, 12.5)])[0]
        assert REQUIRED_ROW_KEYS <= set(row)
        # The merge bookkeeping is internal and must not leak into payloads.
        assert "_n" not in row

    def test_row_values_match_the_spec(self):
        row = build_stores([("good_store", 3, 12.5)])[0]
        assert row["name"] == "good_store"
        assert row["url"] == f"{EBAY_UK_BASE}/str/good_store"
        assert row["url_derived"] is True      # derived, never observed
        assert row["sold_count"] == 3
        assert row["avg_price"] == 12.5
        assert row["provenance"] == Provenance.VERIFIED.value
        assert row["provenance_label"] == Provenance.VERIFIED.label
        assert row["source_name"]

    def test_sold_count_label_names_the_window_and_cap(self):
        # The count means nothing without its window (C11) — the label
        # travels WITH the number so no consumer can promote it silently.
        label = build_stores([("good_store", 3, 1.0)])[0]["sold_count_label"]
        assert "observed" in label.lower()
        assert f"cap {OBSERVED_WINDOW}" in label
        assert OBSERVED_WINDOW == 50

    def test_rows_built_from_real_names_are_verified(self):
        # 'verified' = read off a real eBay response (C13), not "store exists".
        rows = build_stores([("good_store", 3, 1.0)])
        assert all(r["provenance"] == Provenance.VERIFIED.value for r in rows)

    @pytest.mark.parametrize("bad", [
        "just-a-string", None, 42, ("only_name",), (1, 2, 3, 4),
    ])
    def test_malformed_entries_are_skipped_not_raised(self, bad):
        # Regression target: a bad row in the iterable must never kill the
        # parent analysis. NOTE: a THREE-character string slips past this
        # guard and raises at stores.py:149 — reported, see module docstring.
        assert build_stores([bad]) == []
        assert _names(build_stores([bad, ("good_store", 1, 1.0)])) == ["good_store"]


# ---------------------------------------------------------------------------
# Source adapters
# ---------------------------------------------------------------------------

class TestStoresFromItems:
    def test_aggregates_per_seller_and_sorts(self):
        rows = stores_from_items([
            _item("alpha", 10.0),
            _item("alpha", 20.0),
            _item("beta", 30.0),
        ])
        assert _names(rows) == ["alpha", "beta"]
        assert rows[0]["sold_count"] == 2
        assert rows[0]["avg_price"] == 15.0
        assert rows[1]["sold_count"] == 1

    def test_items_with_empty_seller_are_ignored(self):
        rows = stores_from_items(
            [_item("", 5.0), _item(None, 5.0), _item("real_store", 5.0)])
        assert _names(rows) == ["real_store"]

    @pytest.mark.parametrize("empty", [[], None])
    def test_empty_or_none_input_returns_empty(self, empty):
        assert stores_from_items(empty) == []


class TestStoresFromTopSellers:
    def test_consumes_the_scraper_dict_shape(self):
        rows = stores_from_top_sellers(
            [_top_seller("good_store", 7, 70.0, 10.0)])
        assert _names(rows) == ["good_store"]
        assert rows[0]["sold_count"] == 7
        assert rows[0]["avg_price"] == 10.0

    def test_rederives_avg_price_when_only_total_price_is_present(self):
        rows = stores_from_top_sellers([_top_seller("good_store", 4, 100.0)])
        assert rows[0]["avg_price"] == 25.0

    def test_internal_total_price_is_dropped_from_output(self):
        rows = stores_from_top_sellers([_top_seller("good_store", 4, 100.0)])
        assert "total_price" not in rows[0]

    def test_applies_the_cap_of_four_to_five_scraper_rows(self):
        # EbaySoldScraper tops its list at 5 (ebay_sold.py:364); C11 lets
        # only the first 4 through.
        five = [_top_seller(f"seller_{i}", 5 - i, (5 - i) * 10.0, 10.0)
                for i in range(5)]
        rows = stores_from_top_sellers(five)
        assert len(rows) == MAX_STORES == 4
        assert _names(rows) == ["seller_0", "seller_1", "seller_2", "seller_3"]

    def test_attaches_provenance_the_raw_dicts_do_not_carry(self):
        raw = _top_seller("good_store", 7, 70.0, 10.0)
        # The scraper's own dicts have no C13 stamp at all...
        assert "provenance" not in raw
        assert "provenance_label" not in raw
        row = stores_from_top_sellers([raw])[0]
        # ...the adapter adds it, and derives the URL from the username
        # even though the scraper also sent one.
        assert row["provenance"] == Provenance.VERIFIED.value
        assert row["provenance_label"] == Provenance.VERIFIED.label
        assert row["url"] == f"{EBAY_UK_BASE}/str/good_store"
        assert row["url_derived"] is True


class TestStoresFromProducts:
    def test_counts_one_per_occurrence(self):
        # A plain search gives sellers but NO sold data — each occurrence
        # is one observed listing, nothing more.
        rows = stores_from_products([
            _product("shop_a", 10.0),
            _product("shop_a", 20.0),
            _product("shop_b", 5.0),
        ])
        assert _names(rows) == ["shop_a", "shop_b"]
        assert rows[0]["sold_count"] == 2
        assert rows[0]["avg_price"] == 15.0
        assert rows[1]["sold_count"] == 1

    def test_product_rows_are_still_verified(self):
        # We DID read the username off a real page (C13) — the smaller
        # window changes the count, not the provenance.
        row = stores_from_products([_product("shop_a")])[0]
        assert row["sold_count"] == 1
        assert row["provenance"] == Provenance.VERIFIED.value


class TestStoresFromDemandAndScan:
    def test_demand_reads_top_sellers_off_the_object(self):
        demand = DemandData(
            top_sellers=[_top_seller("demand_seller", 3, 30.0, 10.0)])
        rows = stores_from_demand(demand)
        assert _names(rows) == ["demand_seller"]
        assert rows[0]["provenance"] == Provenance.VERIFIED.value

    @pytest.mark.parametrize("demand", [DemandData(), SimpleNamespace()])
    def test_demand_without_sellers_is_empty(self, demand):
        # Default DemandData has top_sellers=[]; a demand-shaped object
        # with no such attribute at all must behave the same.
        assert stores_from_demand(demand) == []

    def test_scan_is_recapped_to_the_c11_cap(self):
        built = build_stores([(f"store_{i}", i + 1, 1.0) for i in range(6)],
                             limit=10)
        assert len(built) == 6  # pre-built upstream with a wider limit
        rows = stores_from_scan(SimpleNamespace(ebay_stores=built))
        assert len(rows) == MAX_STORES == 4

    @pytest.mark.parametrize("product",
                             [SimpleNamespace(), SimpleNamespace(ebay_stores=[])])
    def test_scan_without_the_attribute_is_empty(self, product):
        assert stores_from_scan(product) == []


# ---------------------------------------------------------------------------
# resolve_stores — priority order (the behavioural test)
# ---------------------------------------------------------------------------

class TestResolveStoresPriority:
    """Free data first, network last: the fallback must NEVER run when the
    caller already holds sellers. The probe raises if it is reached."""

    @staticmethod
    def _fallback(monkeypatch, rows=None):
        probe = _FallbackProbe(rows)
        monkeypatch.setattr(stores_mod, "discover_stores", probe)
        return probe

    @staticmethod
    def _sold(items):
        return EbaySoldData(product_name="widget", query="widget", items=items)

    @staticmethod
    def _demand():
        return DemandData(
            top_sellers=[_top_seller("demand_seller", 3, 30.0, 10.0)])

    @staticmethod
    def _products():
        return [_product("product_seller", 12.0)]

    def test_sold_data_beats_everything_and_never_calls_fallback(
            self, monkeypatch):
        probe = self._fallback(monkeypatch)
        rows = resolve_stores(
            query="widget",
            sold_data=self._sold([_item("sold_seller", 12.0)]),
            demand=self._demand(),
            products=self._products(),
        )
        assert _names(rows) == ["sold_seller"]
        assert probe.calls == []

    def test_demand_beats_products_and_query(self, monkeypatch):
        probe = self._fallback(monkeypatch)
        rows = resolve_stores(query="widget", demand=self._demand(),
                              products=self._products())
        assert _names(rows) == ["demand_seller"]
        assert probe.calls == []

    def test_products_beat_the_query(self, monkeypatch):
        probe = self._fallback(monkeypatch)
        rows = resolve_stores(query="widget", products=self._products())
        assert _names(rows) == ["product_seller"]
        assert probe.calls == []

    def test_query_alone_reaches_the_fallback(self, monkeypatch):
        # Last resort: this is the ONE case allowed to spend a request.
        probe = self._fallback(monkeypatch, rows=[{"name": "from_search"}])
        rows = resolve_stores(query="widget")
        assert rows == [{"name": "from_search"}]
        assert [call[0] for call in probe.calls] == ["widget"]

    def test_nothing_at_all_returns_empty_without_fallback(self, monkeypatch):
        probe = self._fallback(monkeypatch)
        assert resolve_stores() == []
        assert probe.calls == []


# ---------------------------------------------------------------------------
# discover_stores — fall-through, never raises
# ---------------------------------------------------------------------------

class TestDiscoverStores:
    def test_empty_query_returns_empty_and_touches_no_scraper(self, monkeypatch):
        sold = _ScraperSpy()
        search = _ScraperSpy()
        monkeypatch.setattr(EbaySoldScraper, "get_sold_data", sold)
        monkeypatch.setattr(EbayScraper, "search", search)
        assert discover_stores("") == []
        assert sold.calls == []
        assert search.calls == []

    def test_sold_path_failure_falls_through_to_search(self, monkeypatch):
        # Discovery must never kill the analysis: a dead sold search falls
        # through to the plain search instead of raising.
        sold = _ScraperSpy(error=RuntimeError("sold search down"))
        monkeypatch.setattr(EbaySoldScraper, "get_sold_data", sold)
        monkeypatch.setattr(EbayScraper, "search",
                            _ScraperSpy(result=[_product("fallback_seller", 12.0)]))
        assert _names(discover_stores("widget")) == ["fallback_seller"]
        assert sold.calls  # the sold path WAS tried first

    def test_both_paths_failing_returns_empty_and_never_raises(self, monkeypatch):
        monkeypatch.setattr(EbaySoldScraper, "get_sold_data",
                            _ScraperSpy(error=RuntimeError("sold down")))
        monkeypatch.setattr(EbayScraper, "search",
                            _ScraperSpy(error=RuntimeError("search down")))
        assert discover_stores("widget") == []

    def test_no_sellers_from_either_path_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            EbaySoldScraper, "get_sold_data",
            _ScraperSpy(result=EbaySoldData(product_name="widget",
                                             query="widget")))
        monkeypatch.setattr(EbayScraper, "search", _ScraperSpy(result=[]))
        assert discover_stores("widget") == []


# ---------------------------------------------------------------------------
# C13 — the store block stamp
# ---------------------------------------------------------------------------

class TestStoreProvenanceBlock:
    def test_non_empty_block_is_verified_with_source_and_method(self):
        block = store_provenance_block([{"name": "good_store"}])
        assert block["provenance"] == Provenance.VERIFIED.value
        assert block["source_name"]
        assert block["method"]
        assert "observed" in block["method"]

    @pytest.mark.parametrize("empty", [[], None])
    def test_empty_block_is_unverified_with_a_reason(self, empty):
        block = store_provenance_block(empty)
        assert block["provenance"] == Provenance.UNVERIFIED.value
        assert block["reason"]

    def test_empty_block_never_reads_verified(self):
        # C13 — the rule the whole feature depends on: "we found no stores"
        # and "we could not look" are BOTH unconfirmed, so an empty list may
        # never be stamped verified.
        assert store_provenance_block([])["provenance"] != \
            Provenance.VERIFIED.value
        assert store_provenance_block(None)["provenance"] != \
            Provenance.VERIFIED.value
        assert store_provenance_block([])["provenance"] == "unverified"


# ---------------------------------------------------------------------------
# Config — one cap, one source
# ---------------------------------------------------------------------------

class TestConfigCap:
    def test_max_stores_is_the_config_value_and_is_four(self):
        # C11: the cap lives in config so no renderer can hardcode its own.
        assert MAX_STORES == config.STORE_COUNT == 4
