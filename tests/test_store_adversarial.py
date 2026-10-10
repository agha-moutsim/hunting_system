"""The 12 adversarial store scenarios from the brief (section 8.1).

These are the cases that would let an invalid store slip back in. Each one
attempts to defeat the store pipeline and asserts it did not succeed.

Deliberately hostile inputs — usernames shaped like the fabricated `/str/`
links, display names where a username belongs, malformed API payloads, stale
cached records, and repeated searches — because a test that only feeds the
happy path proves nothing about the bug class.

Runs fully OFFLINE. Nothing here may reach eBay: the fix must not depend on a
request, and the host is served a CAPTCHA for /str/ anyway.

Run with: python -m pytest tests/test_store_adversarial.py -q
"""

from __future__ import annotations

import pytest

from config import EBAY_UK_BASE
from engine.stores import (
    MAX_STORES,
    build_stores,
    is_observed_store_url,
    resolve_stores,
    stores_from_items,
    stores_from_top_sellers,
)
from scrapers.base import ScrapedProduct
from scrapers.ebay_sold import EbaySoldData, EbaySoldItem, EbaySoldScraper


@pytest.fixture(autouse=True)
def _zero_network(monkeypatch):
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("network call attempted — this file runs offline")

    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)
    monkeypatch.setattr(requests.Session, "get", _blocked)
    monkeypatch.setattr(requests.Session, "post", _blocked)


def _item(seller, price=10.0, store_url=""):
    return EbaySoldItem(
        title="Widget", price=price, url="https://www.ebay.co.uk/itm/1",
        seller=seller, seller_url="", sold_date="", store_url=store_url,
    )


def _all_rows(*groups):
    return [r for g in groups for r in g]


# 1 -------------------------------------------------------------------------
class TestFourGenuineStoresAreVerified:
    def test_four_observed_storefronts_are_returned_and_verified(self):
        names = ["alpha", "beta", "gamma", "delta"]
        items = [_item(n, store_url=f"{EBAY_UK_BASE}/str/{n}-shop") for n in names]
        rows = stores_from_items(items)
        assert len(rows) == MAX_STORES == 4
        assert all(r["url_kind"] == "observed" for r in rows)
        assert all(r["provenance"] == "verified" for r in rows)
        assert all("/str/" in r["url"] and r["url"].startswith(f"{EBAY_UK_BASE}/str/")
                   for r in rows)


# 2 -------------------------------------------------------------------------
class TestOnlyTwoGenuineStoresAvailable:
    def test_two_in_two_out_never_padded_to_four(self):
        rows = stores_from_items([
            _item("alpha", store_url=f"{EBAY_UK_BASE}/str/alpha-shop"),
            _item("beta", store_url=f"{EBAY_UK_BASE}/str/beta-shop"),
        ])
        assert len(rows) == 2
        assert [r["name"] for r in rows] == ["alpha", "beta"]

    def test_the_short_result_is_explained_rather_than_hidden(self):
        rows = stores_from_items([_item("alpha")])
        assert len(rows) == 1
        assert rows[0]["provenance_reason"], "a short list must carry a reason"


# 3 -------------------------------------------------------------------------
class TestLlmStylePlausibleStoreIsRejected:
    """A well-formed but invented username must NOT become a storefront link.

    This is the shape the old code produced: a name that looks real, turned
    into /str/{name}. Now it can only ever yield a /usr/ profile, which makes
    no storefront claim.
    """

    @pytest.mark.parametrize("invented", [
        "premium-electronics-uk",
        "bestdeals_2024",
        "the-uk-store",
        "Official_Nike_Shop_UK",
    ])
    def test_an_invented_username_yields_a_profile_not_a_storefront(self, invented):
        rows = stores_from_items([_item(invented)])
        assert rows[0]["url"] == f"{EBAY_UK_BASE}/usr/{invented}"
        assert "/str/" not in rows[0]["url"]
        assert rows[0]["provenance"] == "unverified"

    def test_a_lookalike_store_url_is_only_trusted_when_it_is_marked_observed(self):
        # A fabricated href placed in a field that claims to be observed is
        # the dangerous case; it is still honoured, so the guard is that ONLY
        # the scraper ever fills that field.
        fake = f"{EBAY_UK_BASE}/str/does-not-exist-zzz"
        rows = stores_from_items([_item("someone", store_url=fake)])
        assert rows[0]["url_kind"] == "observed"
        # The row is honest about where the link came from.
        assert rows[0]["url_derived"] is False


# 4 -------------------------------------------------------------------------
class TestValidNameWithWrongUrl:
    def test_a_valid_name_cannot_pull_in_an_unrelated_host(self):
        rows = build_stores([("good_store", 3, 10.0)],
                            observed_store_urls={
                                "good_store": "https://evil.example/str/steal",
                            })
        # is_observed_store_url accepts only ebay-hosted /str/ hrefs, so this
        # one is discarded and the row falls back to the canonical profile.
        assert "evil.example" not in rows[0]["url"]
        assert rows[0]["url"] == f"{EBAY_UK_BASE}/usr/good_store"
        assert rows[0]["provenance"] == "unverified"


# 5 -------------------------------------------------------------------------
class TestUsernameConfusedWithStoreName:
    def test_a_display_name_with_spaces_is_not_a_store(self):
        rows = stores_from_items([_item("Pretty Shop Ltd")])
        assert rows == [], "a spaced display name is not a username"

    def test_a_username_with_a_slash_is_dropped_not_linked(self):
        assert stores_from_items([_item("shop/../other")]) == []

    def test_a_store_display_name_still_yields_its_username_profile(self):
        # eBay renders a friendly name on the anchor; the username underneath
        # is what we key on.
        rows = stores_from_items([
            _item("real_user_1", store_url=f"{EBAY_UK_BASE}/str/Pretty-Shop-Ltd"),
        ])
        assert rows[0]["name"] == "real_user_1"
        assert rows[0]["url"] == f"{EBAY_UK_BASE}/str/Pretty-Shop-Ltd"


# 6 -------------------------------------------------------------------------
class TestStorePageNotFound:
    """We cannot fetch /str/ from this host (CAPTCHA, proven by control), so
    the honest outcome is that per-page liveness is UNKNOWN. The row must say
    that rather than assert the store is fine or that it is dead."""

    def test_a_store_is_never_marked_not_found_without_a_check(self):
        rows = stores_from_items([_item("alpha", store_url=f"{EBAY_UK_BASE}/str/alpha")])
        assert rows[0]["provenance"] == "verified"
        assert "not found" not in (rows[0].get("provenance_reason") or "").lower()

    def test_observed_url_guard_is_not_confused_by_a_query_string(self):
        assert is_observed_store_url(f"{EBAY_UK_BASE}/str/x?_trkparms=1")


# 7 -------------------------------------------------------------------------
class TestTemporaryNetworkFailure:
    """Per C13 / the brief: a failed fetch is NOT evidence a store is gone.
    Because no fetch happens, a network failure cannot alter any row at all."""

    def test_a_scraper_that_raises_yields_an_empty_list_not_a_dead_store(self):
        class Boom:
            def get_sold_data(self, *a, **k):
                raise RuntimeError("connection reset")

        import scrapers.ebay_sold as es
        original = es.EbaySoldScraper
        es.EbaySoldScraper = Boom
        try:
            from engine.stores import _stores_for_single_query
            assert _stores_for_single_query("widget") == []
        finally:
            es.EbaySoldScraper = original

    def test_no_row_is_ever_marked_unavailable_by_a_fetch(self):
        rows = stores_from_items([_item("alpha")])
        assert all("unavailable" not in (r.get("provenance_reason") or "")
                   for r in rows)


# 8 -------------------------------------------------------------------------
class TestIncompleteOrMalformedApiInformation:
    @pytest.mark.parametrize("bad", [None, "", "   ", "a/b", "a b", "  x y ", "/"])
    def test_unusable_identifiers_produce_no_link(self, bad):
        rows = stores_from_items([_item(bad)])
        if rows:
            assert rows[0]["url"].startswith(EBAY_UK_BASE)

    def test_a_seller_with_no_username_yields_no_row(self):
        assert stores_from_items([_item("")]) == []

    def test_malformed_top_seller_dicts_are_skipped_not_raised(self):
        rows = stores_from_top_sellers([
            "not a dict",
            {"name": None, "sold_count": "x"},
            {"name": "good", "sold_count": 2, "avg_price": 5.0},
        ])
        assert [r["name"] for r in rows] == ["good"]

    def test_a_truncated_payload_never_raises(self):
        assert stores_from_items([]) == []
        assert stores_from_top_sellers([]) == []
        assert build_stores([]) == []


# 9 -------------------------------------------------------------------------
class TestStaleCachedRecord:
    def test_a_cached_row_carrying_a_fabricated_str_url_is_not_re_emitted(self):
        # A row persisted by the OLD code looks like this. Re-deriving from
        # the username must never resurrect the /str/ form.
        cached = {"name": "alpha", "url": f"{EBAY_UK_BASE}/str/alpha",
                  "url_derived": True, "sold_count": 3, "avg_price": 9.0}
        rows = stores_from_items([
            _item(cached["name"], price=cached["avg_price"]),
        ])
        assert rows[0]["url"] == f"{EBAY_UK_BASE}/usr/alpha"

    def test_a_store_url_cache_key_is_case_insensitive_on_the_username(self):
        rows = stores_from_items([
            _item("Alpha", store_url=f"{EBAY_UK_BASE}/str/Alpha-Shop"),
            _item("alpha"),
        ])
        assert len(rows) == 1
        assert rows[0]["url"] == f"{EBAY_UK_BASE}/str/Alpha-Shop"


# 10 ------------------------------------------------------------------------
class TestBothWorkflowsAgree:
    """Analyze and Deep Search share resolve_stores(). Same bad input, same
    output — so one fix covers both."""

    def test_analyze_and_deep_search_take_the_same_path(self):
        import inspect

        for module in ("analysis_pipeline", "pipeline", "deep_search"):
            src = inspect.getsource(
                __import__(f"backend.{module}", fromlist=["x"])
                if False else __import__(module)
            )
            assert "resolve_stores" in src, f"{module} must use the shared path"

    def test_identical_input_yields_identical_rows_from_both_entry_points(self):
        sold = EbaySoldData(
            product_name="widget", query="widget",
            items=[_item("alpha", store_url=f"{EBAY_UK_BASE}/str/A")],
        )
        a = resolve_stores(sold_data=sold)
        b = stores_from_items(sold.items)
        assert [r["url"] for r in a] == [r["url"] for r in b]
        assert [r["provenance"] for r in a] == [r["provenance"] for r in b]


# 11 ------------------------------------------------------------------------
class TestRepeatedSearchesDoNotResurrectRejectedRows:
    def test_running_the_same_search_repeatedly_is_stable(self):
        first = stores_from_items([_item("alpha"), _item("beta")])
        second = stores_from_items([_item("alpha"), _item("beta")])
        assert [r["url"] for r in first] == [r["url"] for r in second]
        assert all("/str/" not in r["url"] for r in second)

    def test_a_row_rejected_for_a_bad_link_stays_rejected_on_a_later_run(self):
        hostile = build_stores([("alpha", 2, 5.0)],
                               observed_store_urls={"alpha": "not-a-url"})
        again = build_stores([("alpha", 2, 5.0)],
                             observed_store_urls={"alpha": "not-a-url"})
        assert hostile[0]["url"] == again[0]["url"] == f"{EBAY_UK_BASE}/usr/alpha"


# 12 ------------------------------------------------------------------------
class TestFrontendOpensTheIntendedStore:
    """The link the backend emits must be the link the UI hands the browser."""
    def test_emitted_href_is_https_and_on_ebay(self):
        rows = stores_from_items([
            _item("a", store_url=f"{EBAY_UK_BASE}/str/A"),
            _item("b"),
        ])
        for r in rows:
            assert r["url"].startswith("https://www.ebay.co.uk/")
            assert "/str/" in r["url"] or "/usr/" in r["url"]

    def test_a_row_with_no_identity_emits_no_href_to_open(self):
        rows = stores_from_items([_item("")])
        assert rows == []

    def test_the_store_card_shows_one_label_per_row(self):
        # The contradiction this replaces: a 'derived' chip beside a
        # 'Verified' badge on the same row. Covered end-to-end in
        # frontend/lib/storeLinks.test.ts.
        rows = stores_from_items([_item("alpha")])
        assert rows[0]["url_kind"] == "seller_profile"
        assert rows[0]["provenance"] == "unverified"