"""Store URL verification - REGRESSION-007, closing the loop.

The identity fix (Phase 2) stopped FABRICATING `/str/{username}` links. That
removed the fabrication, but it could not tell whether an observed `/str/`
href was a real shop: eBay serves a CAPTCHA for `/str/` to a plain request,
so a naive HTTP check reports every store as unverified - and a naive 200
check reports a CAPTCHA as fine.

ScrapingBee renders the page, which clears the CAPTCHA. Measured 2026-10-10
with a deliberate negative control:

    /str/zzqx-nonexistent-store-99887766  -> 410  "eBay Home"        0 items
    /str/har_476199                       -> 410  "eBay Home"        0 items
    /str/pravivity                        -> 200  "pravivity | eBay UK Stores"  48 items
    /str/juicebitz                        -> 200  "JuicEBitz | eBay UK Stores"  54 items

`har_476199` is a seller USER ID presented as a store slug - the original
defect, reproduced live. So the contract is:

    200 + "eBay UK Stores" + items   -> verified   (it is a shop)
    410 / 404                         -> not_found  (the shop is not there)
    anything else (5xx, timeout, no key) -> unavailable  (we could not look)

`unavailable` is deliberately NOT `not_found`: a failed check says nothing
about whether the store exists, and C13 forbids presenting one as the other.

Runs offline by default - verification needs an explicit key.
"""

from __future__ import annotations

import pytest

from engine.verify import (
    StoreCheck,
    classify_store_response,
    is_store_url,
    verify_store_url,
)

EBAY_STORE = "https://www.ebay.co.uk/str/rexgadgets"
DEAD_STORE = "https://www.ebay.co.uk/str/zzqx-nonexistent-store-99887766"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Nothing here may reach the network. The API is injected."""
    import requests

    def _blocked(*a, **k):
        raise AssertionError("network call attempted — inject the API instead")

    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests.Session, "get", _blocked)


@pytest.fixture(autouse=True)
def _fresh_verifier():
    """The verifier caches per URL and meters a per-process budget. Both would
    otherwise leak between tests and make a later test read a verdict that an
    earlier one recorded."""
    import engine.verify as V

    V.clear_cache()
    V.reset_budget()
    yield
    V.clear_cache()
    V.reset_budget()


class _Resp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def _page(title: str, items: int = 50) -> str:
    links = "".join(f'<a href="https://www.ebay.co.uk/itm/{i}">x</a>' for i in range(items))
    return f"<html><head><title>{title}</title></head><body>{links}</body></html>"


# ---------------------------------------------------------------------------
# Classification — the part that must never be wrong
# ---------------------------------------------------------------------------

class TestClassification:

    def test_a_real_store_is_verified(self):
        got = classify_store_response(200, _page("REX GADGETS | eBay UK Stores", 54))
        assert got.status == "verified"

    def test_the_410_control_is_not_found(self):
        got = classify_store_response(410, _page("eBay Home", 0))
        assert got.status == "not_found"

    def test_a_username_offered_as_a_slug_is_not_found(self):
        # The live /str/har_476199 case: 410 and no listings.
        got = classify_store_response(410, _page("eBay Home", 0))
        assert got.status == "not_found"

    def test_a_200_without_store_markers_is_not_a_store(self):
        """eBay serves its homepage body with 200 for some dead slugs."""
        got = classify_store_response(200, _page("eBay Home", 0))
        assert got.status == "not_found"

    def test_a_captcha_is_unavailable_not_found(self):
        got = classify_store_response(200, "<html><head><title>Security measure | eBay"
                                          "</title></head><body>robot</body></html>")
        assert got.status == "unavailable"
        assert "captcha" in (got.reason or "").lower()

    def test_a_server_error_is_unavailable(self):
        assert classify_store_response(503, "").status == "unavailable"

    def test_unknown_status_is_unavailable(self):
        assert classify_store_response(418, "").status == "unavailable"


# ---------------------------------------------------------------------------
# URL shape
# ---------------------------------------------------------------------------

class TestIsStoreUrl:

    def test_accepts_an_https_ebay_store_url(self):
        assert is_store_url(EBAY_STORE) is True

    @pytest.mark.parametrize("bad", [
        "",
        "https://www.ebay.co.uk/usr/someone",
        "https://evil.example/str/x",
        "http://www.ebay.co.uk/str/x",       # http, not https
        "not a url",
    ])
    def test_rejects_everything_that_is_not_an_ebay_store_url(self, bad):
        assert is_store_url(bad) is False


# ---------------------------------------------------------------------------
# verify_store_url — budget, cache, and honest failure
# ---------------------------------------------------------------------------

class TestVerifyStoreUrl:

    def test_without_a_key_it_reports_unavailable_and_never_calls_out(self, monkeypatch):
        monkeypatch.delenv("SCRAPINGBEE_API_KEY", raising=False)
        got = verify_store_url(EBAY_STORE, api_key="")
        assert got.status == "unavailable"
        assert "key" in (got.reason or "").lower()

    def test_a_verified_store_is_reported(self, monkeypatch):
        import engine.verify as V

        monkeypatch.setattr(V, "_fetch", lambda url, **k: _Resp(
            200, _page("REX GADGETS | eBay UK Stores", 54)), raising=False)
        got = verify_store_url(EBAY_STORE, api_key="k", use_cache=False)
        assert got.status == "verified"
        assert got.http_status == 200

    def test_a_dead_store_is_reported_not_found(self, monkeypatch):
        import engine.verify as V

        monkeypatch.setattr(V, "_fetch", lambda url, **k: _Resp(
            410, _page("eBay Home", 0)), raising=False)
        got = verify_store_url(DEAD_STORE, api_key="k", use_cache=False)
        assert got.status == "not_found"

    def test_a_transport_failure_is_unavailable_not_not_found(self, monkeypatch):
        import engine.verify as V

        def _boom(url, **k):
            raise OSError("connection reset")

        monkeypatch.setattr(V, "_fetch", _boom, raising=False)
        got = verify_store_url(EBAY_STORE, api_key="k", use_cache=False)
        assert got.status == "unavailable"
        assert "not found" not in got.status

    def test_a_non_store_url_is_never_checked(self, monkeypatch):
        import engine.verify as V

        called = []
        monkeypatch.setattr(V, "_fetch", lambda url, **k: called.append(url) or _Resp(200, ""),
                            raising=False)
        got = verify_store_url("https://www.ebay.co.uk/usr/someone", api_key="k",
                               use_cache=False)
        assert called == []
        assert got.status == "unavailable"

    def test_results_are_cached_so_a_second_check_costs_nothing(self, monkeypatch):
        import engine.verify as V

        calls = []

        def _count(url, **k):
            calls.append(url)
            return _Resp(200, _page("REX GADGETS | eBay UK Stores", 54))

        monkeypatch.setattr(V, "_fetch", _count, raising=False)
        V.clear_cache()
        first = verify_store_url(EBAY_STORE, api_key="k")
        second = verify_store_url(EBAY_STORE, api_key="k")
        assert first.status == second.status == "verified"
        assert len(calls) == 1, "the second check must hit the cache"

    def test_the_budget_stops_a_run_from_spending_the_whole_account(self, monkeypatch):
        import engine.verify as V

        monkeypatch.setattr(V, "_fetch", lambda url, **k: _Resp(
            200, _page("X | eBay UK Stores", 40)), raising=False)
        V.clear_cache()
        V.reset_budget()
        urls = [f"https://www.ebay.co.uk/str/shop{i}" for i in range(5)]
        results = [verify_store_url(u, api_key="k", max_checks=2, use_cache=False)
                   for u in urls]
        assert [r.status for r in results[:2]] == ["verified", "verified"]
        assert results[2].status == "unavailable"
        assert "budget" in (results[2].reason or "").lower()

    def test_status_values_are_only_the_four_supported_ones(self):
        assert {s.value for s in StoreCheck} == {
            "verified", "not_found", "unavailable"
        }


# ---------------------------------------------------------------------------
# Annotating rows - where the check reaches the product
# ---------------------------------------------------------------------------

class TestAnnotateStoreChecks:

    def _row(self, **kw):
        base = {"name": "s", "url": EBAY_STORE, "url_kind": "observed",
                "url_derived": False, "provenance": "verified",
                "provenance_label": "Verified", "sold_count": 3,
                "avg_price": 10.0}
        base.update(kw)
        return base

    def _stub(self, monkeypatch, status_code, title="X | eBay UK Stores", items=40):
        import engine.verify as V

        monkeypatch.setattr(V, "_fetch", lambda url, **k: _Resp(
            status_code, _page(title, items)), raising=False)

    def test_a_dead_storefront_is_demoted_from_verified(self, monkeypatch):
        from engine.stores import annotate_store_checks

        self._stub(monkeypatch, 410, "eBay Home", 0)
        rows = annotate_store_checks([self._row()])
        assert rows[0]["store_check"] == "not_found"
        assert rows[0]["provenance"] == "unverified"
        assert "no storefront" in rows[0]["provenance_reason"].lower()

    def test_a_dead_storefront_is_demoted_not_dropped(self, monkeypatch):
        """The seller is still a real competitor; only the shop is missing."""
        from engine.stores import annotate_store_checks

        self._stub(monkeypatch, 410, "eBay Home", 0)
        rows = annotate_store_checks([self._row()])
        assert len(rows) == 1

    def test_a_live_storefront_keeps_its_verified_stamp(self, monkeypatch):
        from engine.stores import annotate_store_checks

        self._stub(monkeypatch, 200, "REX GADGETS | eBay UK Stores", 54)
        rows = annotate_store_checks([self._row()])
        assert rows[0]["store_check"] == "verified"
        assert rows[0]["provenance"] == "verified"

    def test_an_uncheckable_store_keeps_its_stamp(self, monkeypatch):
        """A blocked check is not evidence of absence (C13)."""
        import engine.verify as V
        from engine.stores import annotate_store_checks

        monkeypatch.setattr(V, "_fetch", lambda url, **k: _Resp(
            503, ""), raising=False)
        rows = annotate_store_checks([self._row()])
        assert rows[0]["store_check"] == "unavailable"
        assert rows[0]["provenance"] == "verified", \
            "we did not learn it is dead, so we may not claim it is"

    def test_a_seller_profile_row_is_never_checked(self, monkeypatch):
        """Profile links never claimed to be a shop, so there is nothing to
        verify - and no budget to spend on them."""
        import engine.verify as V
        from engine.stores import annotate_store_checks

        called = []
        monkeypatch.setattr(V, "_fetch", lambda url, **k: called.append(url)
                            or _Resp(200, ""), raising=False)
        rows = annotate_store_checks([self._row(
            url="https://www.ebay.co.uk/usr/s", url_kind="seller_profile",
            url_derived=True, provenance="unverified")])
        assert called == []
        assert "store_check" not in rows[0]

    def test_a_check_that_raises_never_breaks_the_row(self, monkeypatch):
        import engine.verify as V
        from engine.stores import annotate_store_checks

        def _boom(url, **k):
            raise OSError("reset")

        monkeypatch.setattr(V, "_fetch", _boom, raising=False)
        rows = annotate_store_checks([self._row()])
        assert rows[0]["store_check"] == "unavailable"
        assert rows[0]["provenance"] == "verified"

    def test_verify_false_leaves_rows_untouched(self, monkeypatch):
        from engine.stores import annotate_store_checks

        rows = annotate_store_checks([self._row()], verify=False)
        assert "store_check" not in rows[0]