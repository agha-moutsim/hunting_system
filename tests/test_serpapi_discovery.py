"""P4 — SerpApi supplier discovery, and the deep_search wiring that uses it.

ZERO NETWORK: `requests.get` is replaced for the whole file, so every test
spends zero SerpApi quota and the suite stays offline.

The fixtures mirror the API's REAL payload, which is why this file exists:
`google_shopping` results carry NO merchant URL at all — `link` is absent and
`product_link` is `https://www.google.com/...`. The module was originally
written against an assumed shape and returned zero rows against the live API.
These tests lock in the three-stage fix (search -> resolve -> build).

See docs/HANDOFF.md §4.2.
"""

from __future__ import annotations

import types
from urllib.parse import urlparse

import pytest

import deep_search as ds
from scrapers import serpapi_discovery as sd
from scrapers.base import ScrapedProduct


# ---------------------------------------------------------------------------
# Fixtures shaped like the live payload
# ---------------------------------------------------------------------------

def _shopping_item(
    *,
    source: str = "Toolstation",
    title: str = "Bosch 18V Cordless Combi Drill 2 x 4.0Ah",
    price: float = 129.99,
    token: str | None = "TOK-1",
    link: str | None = None,   # the API supplies NONE; tests pass one only
) -> dict:                     # when exercising the domain-match branch
    item = {
        "position": 1,
        "title": title,
        "product_id": "11639305556242553093",
        # Real shape: Google's own redirect, never the merchant.
        "product_link": "https://www.google.com/search?ibp=oshop&q=x",
        "thumbnail": "https://encrypted-tbn0.gstatic.com/shopping?q=tbn:x",
        "source": source,
        "extracted_price": price,
        "price": f"£{price:.2f}",
        "delivery": "Free delivery",
    }
    if link is not None:
        item["link"] = link
    if token is not None:
        item["immersive_product_page_token"] = token
    return item


def _store(
    *,
    name: str = "Toolstation",
    link: str = "https://www.toolstation.com/bosch-18v-combi-drill/p123",
    title: str = "Bosch 18V Cordless Combi Drill 2 x 4.0Ah",
    price: float = 129.99,
    shipping: str = "Free",
    details: list | None = None,
) -> dict:
    return {
        "name": name,
        "link": link,
        "title": title,
        "price": f"£{price:.2f}",
        "extracted_price": price,
        "shipping": shipping,
        "details_and_offers": ["In stock online"] if details is None else details,
    }


def _store_response(stores: list) -> dict:
    return {"product_results": {"stores": stores}}


class _FakeResponse:
    # The real `_get_json` reads `status_code` BEFORE `raise_for_status()`
    # (A4 — a 429 has to be inspected for the exhaustion message, which
    # raise_for_status would discard). The double needs the same surface.
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Router:
    """Replaces requests.get inside the module.

    Routes on the `engine` param so search and resolve calls are
    independently controllable, and records every call for budget tests.
    """

    def __init__(self, shopping=None, immersive=None, fail_engine=None):
        self.shopping = shopping if shopping is not None else []
        self.immersive = immersive if immersive is not None else {}
        self.fail_engine = fail_engine
        self.calls: list[dict] = []

    def __call__(self, url, params=None, timeout=None, **kw):
        params = dict(params or {})
        self.calls.append(params)
        engine = params.get("engine")
        if self.fail_engine == engine:
            raise sd.requests.RequestException("simulated transport failure")
        if engine == "google_shopping":
            return _FakeResponse({"shopping_results": self.shopping})
        if engine == "google_immersive_product":
            token = params.get("page_token")
            return _FakeResponse(self.immersive.get(token, {}))
        return _FakeResponse({})


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    """The suite must prove discovery fails closed without a key too."""
    monkeypatch.setenv("SERPAPI_KEY", "test-key-not-a-real-key")


def _patch(monkeypatch, router):
    monkeypatch.setattr(sd.requests, "get", router)
    return router


# ---------------------------------------------------------------------------
# Failing closed
# ---------------------------------------------------------------------------

class TestFailsClosed:
    def test_no_key_returns_no_rows_and_makes_no_request(self, monkeypatch):
        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        router = _patch(monkeypatch, _Router())

        assert sd.discover("bosch drill") == []
        assert router.calls == []

    @pytest.mark.parametrize("query", ["", "   ", None])
    def test_blank_query_returns_no_rows(self, monkeypatch, query):
        router = _patch(monkeypatch, _Router())

        assert sd.discover(query) == []
        assert router.calls == []

    def test_transport_failure_returns_no_rows(self, monkeypatch):
        router = _patch(monkeypatch, _Router(fail_engine="google_shopping"))

        assert sd.discover("bosch drill") == []

    def test_a_failed_search_never_spends_the_rest_of_the_budget(self, monkeypatch):
        # One attempt, then stop — not one attempt per supplier.
        router = _patch(monkeypatch, _Router(fail_engine="google_shopping"))

        sd.discover("bosch drill")

        assert len(router.calls) == 1


# ---------------------------------------------------------------------------
# The shape bug this file exists to prevent
# ---------------------------------------------------------------------------

class TestMerchantUrlComesFromResolve:
    """`google_shopping` gives the SUPPLIER; only the immersive call gives
    the product URL."""

    def test_a_shopping_result_with_no_link_still_yields_a_row(self, monkeypatch):
        # Exactly the live payload: no `link`, `product_link` is Google's.
        item = _shopping_item()
        assert "link" not in item

        router = _patch(monkeypatch, _Router(
            shopping=[item],
            immersive={"TOK-1": _store_response([_store()])},
        ))

        rows = sd.discover("bosch drill")

        assert len(rows) == 1
        assert rows[0].url.startswith("https://www.toolstation.com/")
        assert urlparse(rows[0].url).hostname != "www.google.com"

    def test_the_resolved_url_comes_from_the_offer_not_the_shopping_result(
        self, monkeypatch
    ):
        router = _patch(monkeypatch, _Router(
            shopping=[_shopping_item()],
            immersive={"TOK-1": _store_response(
                [_store(link="https://www.toolstation.com/real-product/p9")]
            )},
        ))

        rows = sd.discover("bosch drill")

        assert rows[0].url == "https://www.toolstation.com/real-product/p9"

    def test_an_offer_without_a_link_is_dropped_never_invented(self, monkeypatch):
        router = _patch(monkeypatch, _Router(
            shopping=[_shopping_item()],
            immersive={"TOK-1": _store_response([_store(link="")])},
        ))

        assert sd.discover("bosch drill") == []

    def test_a_missing_immersive_token_means_no_row(self, monkeypatch):
        router = _patch(monkeypatch, _Router(
            shopping=[_shopping_item(token=None)],
            immersive={},
        ))

        assert sd.discover("bosch drill") == []

    def test_the_shopping_titles_price_never_stands_in_for_a_real_offer(
        self, monkeypatch
    ):
        # No resolve -> no row, even though the shopping result was perfect.
        router = _patch(monkeypatch, _Router(
            shopping=[_shopping_item()],
            immersive={},  # every resolve fails
        ))

        assert sd.discover("bosch drill") == []


# ---------------------------------------------------------------------------
# Only the 7 approved suppliers
# ---------------------------------------------------------------------------

class TestApprovedSuppliersOnly:
    def test_an_unapproved_source_is_never_padded_in(self, monkeypatch):
        router = _patch(monkeypatch, _Router(
            shopping=[
                _shopping_item(source="Toolchimp.co.uk"),
                _shopping_item(source="Some Other Shop"),
                _shopping_item(source="eBay"),
            ],
            immersive={},
        ))

        assert sd.discover("drill") == []

    def test_every_returned_row_is_one_of_the_seven(self, monkeypatch):
        router = _patch(monkeypatch, _Router(
            shopping=[
                _shopping_item(source="Toolstation"),
                _shopping_item(source="Toolchimp.co.uk"),
                _shopping_item(source="B&Q"),
            ],
            immersive={
                "TOK-1": _store_response([_store()]),
                # Same token is reused by the fixture, so give B&Q its own.
            },
        ))

        rows = sd.discover("drill")
        labels = {cfg["label"] for cfg in sd._SUPPLIERS.values()}

        assert rows
        assert all(r.source in labels for r in rows)

    def test_a_domain_match_wins_over_the_displayed_source(self, monkeypatch):
        # A link on an approved host, displayed under a stranger's name.
        item = _shopping_item(
            source="Random Merchant",
            link="https://www.toolstation.com/something/p1",
        )
        router = _patch(monkeypatch, _Router(
            shopping=[item],
            immersive={"TOK-1": _store_response(
                [_store(link="https://www.toolstation.com/something/p1")]
            )},
        ))

        rows = sd.discover("drill")

        assert [r.source for r in rows] == ["Toolstation"]

    def test_an_offer_belonging_to_a_different_approved_supplier_is_rejected(
        self, monkeypatch
    ):
        # Filed under Toolstation, but the resolved offer is a B&Q page.
        router = _patch(monkeypatch, _Router(
            shopping=[_shopping_item(source="Toolstation")],
            immersive={"TOK-1": _store_response(
                [_store(name="B&Q", link="https://www.diy.com/departments/x/p1")]
            )},
        ))

        assert sd.discover("drill") == []


# ---------------------------------------------------------------------------
# Budget — discovery can never spend whatever it likes
# ---------------------------------------------------------------------------

class TestMarketplaceBench:
    def test_au_returns_only_the_two_dropship_sources(self, monkeypatch):
        shopping = [
            _shopping_item(source="AliExpress", title="AU Ali item", token="AE0"),
            _shopping_item(source="CJ Dropshipping", title="AU CJ item", token="CJ0"),
            _shopping_item(source="B&Q", title="UK B&Q item", token="BQ0"),
            _shopping_item(source="Toolstation", title="UK TS item", token="TS0"),
            _shopping_item(source="Joybuy", title="UK Joybuy item", token="JY0"),
        ]
        _patch(monkeypatch, _Router(
            shopping=shopping,
            immersive={
                "AE0": _store_response([_store(
                    name="AliExpress",
                    link="https://www.aliexpress.com/item/1.html",
                    title="AU Ali item",
                )]),
                "CJ0": _store_response([_store(
                    name="CJ Dropshipping",
                    link="https://www.cjdropshipping.com/product-p-1.html",
                    title="AU CJ item",
                )]),
                "BQ0": _store_response([_store(
                    name="B&Q", link="https://www.diy.com/d/p1",
                    title="UK B&Q item")]),
                "TS0": _store_response([_store(
                    name="Toolstation",
                    link="https://www.toolstation.com/p1",
                    title="UK TS item")]),
                "JY0": _store_response([_store(
                    name="Joybuy", link="https://www.joybuy.com/p1",
                    title="UK Joybuy item")]),
            },
        ))

        rows = sd.discover("drill", marketplace="EBAY_AU")

        assert {row.source for row in rows} == {"AliExpress", "CJ Dropshipping"}
        assert all(row.source not in {"B&Q", "Toolstation", "Joybuy UK"} for row in rows)

    def test_au_searches_google_australia(self, monkeypatch):
        router = _patch(monkeypatch, _Router())

        sd.discover("drill", marketplace="EBAY_AU")

        assert router.calls
        assert router.calls[0]["location"] == "Australia"
        assert router.calls[0]["gl"] == "au"
        assert router.calls[0]["hl"] == "en"

    def test_uk_keeps_its_retail_bench_and_scope(self, monkeypatch):
        router = _patch(monkeypatch, _Router(
            shopping=[_shopping_item(source="Toolstation")],
            immersive={"TOK-1": _store_response([_store()])},
        ))

        rows = sd.discover("drill")

        assert rows and rows[0].source == "Toolstation"
        assert router.calls[0]["location"] == "United Kingdom"
        assert router.calls[0]["gl"] == "uk"


class TestCallBudget:
    def test_discovery_never_exceeds_the_cap(self, monkeypatch):
        # 7 suppliers x 2 rows of perfectly good offers would be a lot.
        shopping = [
            _shopping_item(source="Toolstation", token=f"T{i}")
            for i in range(12)
        ]
        router = _patch(monkeypatch, _Router(
            shopping=shopping,
            immersive={f"T{i}": _store_response([_store()]) for i in range(12)},
        ))

        sd.discover("drill")

        assert len(router.calls) <= sd.MAX_CALLS

    def test_the_budget_is_shared_by_search_and_resolve_calls(self, monkeypatch):
        router = _patch(monkeypatch, _Router(
            shopping=[_shopping_item(token=f"T{i}") for i in range(20)],
            immersive={f"T{i}": _store_response([_store()]) for i in range(20)},
        ))

        sd.discover("drill")

        engines = [c.get("engine") for c in router.calls]
        assert len(engines) <= sd.MAX_CALLS
        assert "google_shopping" in engines          # stage 1 ran
        assert "google_immersive_product" in engines  # stage 2 ran


# ---------------------------------------------------------------------------
# Row contents — C10 / C13
# ---------------------------------------------------------------------------

class TestRowContents:
    def test_condition_is_never_invented(self, monkeypatch):
        _patch(monkeypatch, _Router(
            shopping=[_shopping_item()],
            immersive={"TOK-1": _store_response([_store()])},
        ))

        row = sd.discover("drill")[0]

        # C10 — Google Shopping states no condition; '' means "we read none".
        assert row.condition == ""
        assert row.verified is True

    def test_stock_is_read_from_the_offer(self, monkeypatch):
        _patch(monkeypatch, _Router(
            shopping=[_shopping_item()],
            immersive={"TOK-1": _store_response([_store(
                details=["In stock online", "Free next-day delivery"],
            )])},
        ))

        row = sd.discover("drill")[0]

        assert row.in_stock == "in_stock"
        assert row.stock_raw == "In stock online"

    def test_free_shipping_keeps_zero_cost_and_the_source_words(self, monkeypatch):
        # 0.0 means UNKNOWN (C13) — the raw line is what says "Free".
        _patch(monkeypatch, _Router(
            shopping=[_shopping_item()],
            immersive={"TOK-1": _store_response([_store(shipping="Free")])},
        ))

        row = sd.discover("drill")[0]

        assert row.shipping_cost == 0.0
        assert row.shipping_raw == "Free"

    def test_no_stock_wording_leaves_stock_unknown(self, monkeypatch):
        _patch(monkeypatch, _Router(
            shopping=[_shopping_item()],
            immersive={"TOK-1": _store_response([_store(
                details=["30-day returns"],  # no stock claim at all
            )])},
        ))

        row = sd.discover("drill")[0]

        assert row.in_stock == ""
        assert row.stock_raw == ""

    def test_a_priced_offer_reaches_the_row(self, monkeypatch):
        _patch(monkeypatch, _Router(
            shopping=[_shopping_item()],
            immersive={"TOK-1": _store_response([_store(price=74.5)])},
        ))

        assert sd.discover("drill")[0].price == pytest.approx(74.5)


# ---------------------------------------------------------------------------
# C12 — coverage first, then the cap
# ---------------------------------------------------------------------------

class TestCoverageAndCap:
    def test_every_supplier_gets_its_first_row_before_any_second_row(
        self, monkeypatch
    ):
        toolstation = [
            _shopping_item(source="Toolstation", title=f"Toolstation item {i}",
                           token=f"TS{i}")
            for i in range(4)
        ]
        bandq = _shopping_item(source="B&Q", title="B&Q item", token="BQ0")
        router = _patch(monkeypatch, _Router(
            shopping=toolstation + [bandq],
            immersive={
                **{f"TS{i}": _store_response([_store(
                    title=f"Toolstation item {i}")]) for i in range(4)},
                "BQ0": _store_response([_store(
                    name="B&Q", link="https://www.diy.com/d/p1",
                    title="B&Q item")]),
            },
        ))

        rows = sd.discover("drill")
        sources = [r.source for r in rows]

        # B&Q's first row lands before Toolstation's second one.
        assert sources.index("B&Q") < sources.index("Toolstation", 1)

    def test_the_result_never_exceeds_max_suppliers(self, monkeypatch):
        shopping = [
            _shopping_item(source="Toolstation", token=f"T{i}") for i in range(20)
        ]
        _patch(monkeypatch, _Router(
            shopping=shopping,
            immersive={f"T{i}": _store_response([_store()]) for i in range(20)},
        ))

        assert len(sd.discover("drill")) <= sd.MAX_SUPPLIERS

    def test_one_supplier_cannot_crowd_the_others_out(self, monkeypatch):
        # 10 Toolstation rows and nothing else: still at most 2 of them.
        shopping = [_shopping_item(source="Toolstation", token=f"T{i}")
                    for i in range(10)]
        _patch(monkeypatch, _Router(
            shopping=shopping,
            immersive={f"T{i}": _store_response([_store()]) for i in range(10)},
        ))

        rows = sd.discover("drill")

        assert len(rows) <= sd.MAX_PER_SUPPLIER


# ---------------------------------------------------------------------------
# deep_search wiring — _discover_approved_suppliers
# ---------------------------------------------------------------------------

class TestDeepSearchDiscovery:
    """The rows must be the same dict shape `_verify_supplier_candidates`
    builds, or `score_candidates` silently drops them (it skips non-dicts and
    reads `product_title`)."""

    @pytest.fixture(autouse=True)
    def _shopping_stub(self, monkeypatch):
        self.router = _patch(monkeypatch, _Router(
            shopping=[_shopping_item()],
            immersive={"TOK-1": _store_response([_store()])},
        ))

    def test_returns_dicts_not_dataclasses(self, monkeypatch):
        rows = ds._discover_approved_suppliers("bosch drill")

        assert rows and all(isinstance(r, dict) for r in rows)

    def test_carries_every_field_the_gate_reads(self, monkeypatch):
        (row,) = ds._discover_approved_suppliers("bosch drill")

        assert row["product_title"]          # score_candidates reads this
        assert row["price"] > 0
        assert row["url"].startswith("https://")
        assert row["provenance"] == "verified"
        assert row["supplier_type"]
        assert row["name"]

    def test_image_hash_is_none_rather_than_a_guessed_hash(self, monkeypatch):
        (row,) = ds._discover_approved_suppliers("bosch drill")

        # C14 — pHash only when both images exist; never invented.
        assert row["image_hash"] is None

    def test_availability_keys_are_present_so_nothing_is_guessed(self, monkeypatch):
        (row,) = ds._discover_approved_suppliers("bosch drill")

        for key in ("in_stock", "stock_raw", "shipping_cost",
                    "shipping_days", "shipping_raw"):
            assert key in row
        assert row["shipping_cost"] == 0.0          # unknown, not "free"

    def test_a_row_survives_the_real_match_gate(self, monkeypatch):
        rows = ds._discover_approved_suppliers("bosch drill")

        gated = ds._gate_suppliers(
            rows, "Bosch 18V Cordless Combi Drill 2 x 4.0Ah", ebay_price=95.0
        )

        assert gated, "an approved offer matching the query must pass C14"
        assert all(g["match_tier"] in ("verified", "unverified") for g in gated)

    def test_discovery_failure_returns_no_rows_not_an_error(self, monkeypatch):
        _patch(monkeypatch, _Router(fail_engine="google_shopping"))

        assert ds._discover_approved_suppliers("bosch drill") == []

    def test_no_key_returns_no_rows(self, monkeypatch):
        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        router = _patch(monkeypatch, _Router())

        assert ds._discover_approved_suppliers("bosch drill") == []
        assert router.calls == []
