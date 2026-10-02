"""REGRESSION-006 - a long product title matched no eBay listings at all.

The user saw one competitor store (or none) on every analysis. The cause was
NOT the price band and NOT the 4-store cap - both were tested against the live
API and are fine. The cause is the QUERY:

    "Pasabahce 2 Colorful Cups Saucers Dissolving Skyline Bone China 5oz
     Coffee Tea"          -> 0 items, 0 sellers
    "colorful cups"       -> 50 items, 41 sellers
    "cups and saucers"    -> 50 items, 39 sellers
    "bone china"          -> 50 items, 31 sellers

Analyze passes `ebay_product.title` verbatim as the sold-search query, so a
12-word title matched nothing, the seller tally stayed empty, and the store
list was empty or a single seller. A short query like "cordless drill" already
returned 4 real stores, which is why the symptom looked inconsistent.

`engine/query_extract` fixes it at the seam: reduce a title to the words
worth searching for, and only fall back to them when the exact title returned
nothing - so a precise title is never second-guessed.

ZERO NETWORK here; the live numbers above are recorded in the docstring and
are reproduced by `tests/test_store_live.py -m live`.
"""

from __future__ import annotations

import pytest

from engine.query_extract import (
    extract_query,
    fallback_queries,
    should_reduce,
)


# ---------------------------------------------------------------------------
# The reduction itself
# ---------------------------------------------------------------------------

class TestQueryExtract:
    def test_a_long_title_becomes_searchable_keywords(self):
        title = ("Pasabahce 2 Colorful Cups & Saucers Dissolving Skyline "
                 "Bone China 5oz Coffee Tea")
        q = extract_query(title)

        # The distinctive words survive...
        assert "colorful" in q.lower()
        assert "cups" in q.lower()
        # ...and the marketing filler is gone.
        assert len(q.split()) <= 8

    def test_a_short_title_is_left_alone(self):
        # Already a good query - changing it would only lose precision.
        assert extract_query("cordless drill") == "cordless drill"
        assert extract_query("bone china") == "bone china"

    def test_filler_words_are_removed(self):
        q = extract_query(
            "NEW Genuine Bosch Blue 18V Cordless Combi Drill with 2 Batteries "
            "and Case - Free Delivery"
        ).lower()
        for filler in ("new ", "genuine", "free delivery", " - "):
            assert filler not in q, filler

    def test_the_brand_is_never_dropped(self):
        # Dropping the brand is how a Bosch drill starts matching a Faithfull.
        q = extract_query(
            "Bosch Professional GSB 13 RE 18V Cordless Combi Drill Body Only"
        )
        assert "bosch" in q.lower()

    def test_model_numbers_survive(self):
        # The model is the single most identifying token in the title.
        q = extract_query("Bosch GSB 13 RE 18V Combi Drill")
        assert "gsb" in q.lower()
        assert "13" in q

    def test_a_title_that_is_all_filler_still_yields_something(self):
        # Never return an empty query: that would search eBay for "" and look
        # like a broken feature rather than a rare product.
        assert extract_query("NEW TOP QUALITY BRAND NEW") != ""

    def test_empty_input_stays_empty(self):
        assert extract_query("") == ""
        assert extract_query(None) == ""

    def test_quantity_multipliers_are_kept(self):
        # "6 piece set" changes what the buyer gets; dropping it can match a
        # single-item listing.
        q = extract_query("Garden Tools Set 6 Piece Stainless Steel Trowel")
        assert "6" in q or "piece" in q.lower()

    def test_the_result_is_deterministic(self):
        t = "Bosch 18V Cordless Combi Drill 2 Batteries Case New"
        assert extract_query(t) == extract_query(t)


# ---------------------------------------------------------------------------
# When to reduce at all
# ---------------------------------------------------------------------------

class TestShouldReduce:
    @pytest.mark.parametrize("q, expect", [
        ("cordless drill", False),
        ("garden tools", False),
        ("bone china", False),
    ])
    def test_short_useful_queries_are_never_reduced(self, q, expect):
        """Reducing an already-good query only loses precision."""
        assert should_reduce(q) is expect

    def test_a_long_title_should_be_reduced(self):
        long_title = ("Pasabahce 2 Colorful Cups & Saucers Dissolving "
                      "Skyline Bone China 5oz Coffee Tea")
        assert should_reduce(long_title) is True

    def test_the_decision_is_about_word_count_not_characters(self):
        # A long single word is still one query; many words is the problem.
        assert should_reduce("supercalifragilisticexpialidocious") is False
        assert should_reduce("one two three four five six seven eight") is True


# ---------------------------------------------------------------------------
# The fallback ladder
# ---------------------------------------------------------------------------

class TestFallbackQueries:
    def test_a_short_query_has_no_fallback(self):
        assert fallback_queries("cordless drill") == []

    def test_a_long_title_produces_a_broadening_ladder(self):
        # The exact title is tried FIRST; only these come after it fails.
        ladder = fallback_queries(
            "Pasabahce 2 Colorful Cups & Saucers Dissolving Skyline Bone China 5oz"
        )
        assert len(ladder) >= 1
        # Each rung is shorter than the title (eBay matches all terms, so a
        # shorter query is the broader one). Length is not capped: shedding
        # terms only as needed is the point.
        counts = [len(q.split()) for q in ladder]
        assert all(c < 12 for c in counts), counts

    def test_the_ladder_never_repeats_the_original(self):
        original = "Bosch 18V Cordless Combi Drill with Batteries and Case"
        assert original not in fallback_queries(original)


# ---------------------------------------------------------------------------
# The store ladder - the behaviour that actually fixes the user's bug
# ---------------------------------------------------------------------------

class TestStoreSearchLadder:
    """`search_stores` widens the PRICE BAND first, then the query.

    Both causes of the user's single-store bug were measured against the live
    Browse API, so both are reproduced here:

        "Greenhouse 6ft Polycarbonate"
            active band 5-35 -> 0 sellers     <- the bug
            band 1-100      -> 6 sellers
            no band         -> 24 sellers

        "Pasabahce 2 Colorful Cups Saucers ... Bone China 5oz"
            full title      -> 0 sellers
            shortened       -> 24 sellers
    """

    def _fake_ebay(self, monkeypatch, rules):
        """rules: callable(query, price_clause) -> (item_count, seller_names)

        A callable rather than a dict, because the band is part of the query
        and the point of the fix is which band was asked for.
        """
        import base64
        import types as _types
        import requests as _rq
        import scrapers.ebay as ebay_mod
        import scrapers.ebay_sold as sold_mod

        types = _types
        calls: list[tuple[str, str]] = []

        class _Resp:
            def __init__(self, payload):
                self._p = payload
                self.status_code = 200
                self.text = "<html></html>"

            def raise_for_status(self):
                return None

            def json(self):
                return self._p

        def _post(url, **kw):
            return _Resp({"access_token": "test-token"})

        def _get(url, params=None, **kw):
            if "oauth2/token" in str(url):
                return _Resp({"access_token": "test-token"})
            q = (params or {}).get("q", "")
            f = (params or {}).get("filter", "")
            # Recover the price clause eBay was asked for, so the fake can
            # behave differently per band exactly as the real API does.
            band = "none" if "price:[" not in f else f.split("price:[")[1].split("]")[0]
            calls.append((q, band))
            # The HTML-scrape fallback carries the query in the URL, not in
            # params, so q is "" here. It is NOT a widening step and must not
            # be able to produce a spurious hit.
            if not q and "_nkw=" in str(url):
                return _Resp({"itemSummaries": []})
            n, sellers = rules(q, band)
            return _Resp({
                "itemSummaries": [
                    {"price": {"value": 12.0 if band == "none" else 12.0},
                     "condition": "New", "seller": {"username": s},
                     "title": f"item {i}", "itemWebUrl": f"https://x/{i}",
                     "itemId": str(i), "itemLocation": {"country": "GB"},
                     "thumbnailImages": [{"imageUrl": "https://x/i.jpg"}]}
                    for i, s in enumerate(sellers)
                ][:n]
            })

        class _FakeSession:
            def __init__(self):
                self.headers = {}

            def get(self, *a, **kw):
                return _get(*a, **kw)

            def close(self):
                return None

        # Both scraper modules do `import requests` then call `requests.get`,
        # so both resolve to the SAME global module object. Patching
        # `mod.requests.get` therefore patches the real requests library, and
        # replacing `requests.Session` there breaks requests' own internals
        # ("'function' object has no attribute 'get'"). So each scraper gets
        # its own stand-in module object holding only get/post/Session.
        for mod in (ebay_mod, sold_mod):
            fake_requests = types.SimpleNamespace(
                get=_get, post=_post, Session=lambda *a, **kw: _FakeSession()
            )
            monkeypatch.setattr(mod, "requests", fake_requests)

        # Both scrapers fetch an OAuth token lazily and cache it. The cached
        # token would leak between tests and, worse, would be fetched through
        # the real requests library on the first call. Short-circuit it.
        for cls in (ebay_mod.EbayScraper, sold_mod.EbaySoldScraper):
            monkeypatch.setattr(
                cls, "_get_token", lambda self: "test-token", raising=False
            )
        for mod in (ebay_mod, sold_mod):
            monkeypatch.setattr(mod, "EBAY_CLIENT_ID", "id")
            monkeypatch.setattr(mod, "EBAY_CLIENT_SECRET", "secret")
        return calls

    def test_the_widened_band_is_actually_requested(self, monkeypatch):
        """The ROOT CAUSE, asserted directly: a wider band is sent to eBay.

        MUTATION TESTED: deleting the band rungs from `_store_ladder` left
        every other test in this file green, because they all checked what
        the ladder DOES with a hit, never that the wider band is REQUESTED.
        This test fails when the band rungs are removed, which is the defect
        the user actually reported.
        """
        from engine.stores import _store_ladder

        title = "Greenhouse 6ft Polycarbonate"
        rungs = _store_ladder(title)
        bands = {b for _q, b in rungs if _q == title}

        # The exact title must be tried in a band wider than the 5-35 buy
        # range, or a product priced above the band can never find a
        # competitor.
        assert (1.0, 500.0) in bands or None in bands, bands
        assert any(b is None or b[1] > 35 for b in bands), bands

    def test_a_product_above_the_band_still_finds_competitors(self, monkeypatch):
        """The measured bug, reproduced end to end: 0 sellers -> 4.

        "Greenhouse 6ft Polycarbonate" has nothing at all in the GBP5-35
        buying band and 24 sellers once the band is dropped. Without the
        ladder the block was empty; this asserts the fix from the outside.
        """
        from engine.stores import search_stores

        title = "Greenhouse 6ft Polycarbonate"
        self._fake_ebay(monkeypatch, lambda q, band: (
            (0, []) if band == "5..35" else (42, [f"s{i}" for i in range(9)])
        ))

        rows, provenance = search_stores(title)

        assert len(rows) == 4
        assert provenance["provenance"] == "unverified"

    def test_the_band_is_widened_before_the_query_is(self, monkeypatch):
        """The dominant cause, and the order that fixes it.

        "Greenhouse 6ft Polycarbonate" finds 0 sellers inside the buying band
        and 6 with the band widened - while keeping its exact title. Shortening
        the query instead is a bigger claim (it may be a different product) for
        a worse result, so the band goes first.
        """
        from engine.stores import search_stores

        title = "Greenhouse 6ft Polycarbonate"
        calls = self._fake_ebay(monkeypatch, lambda q, band: (
            (0, []) if band == "5..35" else (20, [f"s{i}" for i in range(6)])
        ))

        rows, provenance = search_stores(title)

        assert len(rows) == 4
        # The band went first: the first API query that returned rows still
        # used the exact title, and its band was the wide one.
        first_hit = next((c for c in calls if c[0] == title and c[1] != "5..35"), None)
        assert first_hit is not None, calls
        assert provenance["broadened"] is True
        assert "band" in provenance["reason"].lower()

    def test_widening_the_band_is_not_claimed_as_an_exact_match(self, monkeypatch):
        """C13: those stores sell outside our budget, so we say so."""
        from engine.stores import search_stores

        self._fake_ebay(monkeypatch, lambda q, band: (
            (0, []) if band == "5..35" else (20, [f"s{i}" for i in range(6)])
        ))

        _rows, provenance = search_stores("Greenhouse 6ft Polycarbonate")

        assert provenance["provenance"] == "unverified"
        # The band actually searched must be WIDER than the 5-35 buying band.
        assert provenance["price_band_used"][0] < 5 or provenance["price_band_used"][1] > 35

    def test_an_in_band_hit_is_verified_and_costs_one_call(self, monkeypatch):
        from engine.stores import search_stores

        title = "cordless drill"
        calls = self._fake_ebay(monkeypatch, lambda q, band: (
            (50, [f"s{i}" for i in range(9)]) if band == "5..35" else (0, [])
        ))

        rows, provenance = search_stores(title)

        assert len(rows) == 4
        assert len(calls) == 1, calls
        assert provenance["broadened"] is False
        assert provenance["provenance"] == "verified"

    def test_procurement_band_is_untouched(self, monkeypatch):
        """Only store discovery widens. What you may BUY is unchanged."""
        from scrapers.ebay_sold import EbaySoldScraper

        calls = self._fake_ebay(monkeypatch, lambda q, band: (50, ["a", "b"]))

        # No price_band argument = the original behaviour, active band only.
        EbaySoldScraper().get_sold_data("cordless drill")

        assert {band for _q, band in calls} == {"5..35"}

    def test_an_explicit_none_band_sends_no_price_clause(self, monkeypatch):
        """`price_band=None` must mean NO price filter, not the active one."""
        from scrapers.ebay_sold import EbaySoldScraper

        calls = self._fake_ebay(monkeypatch, lambda q, band: (50, ["a", "b"]))

        EbaySoldScraper().get_sold_data("cordless drill", price_band=None)

        assert "none" in {band for _q, band in calls}

    def test_a_title_that_matched_nothing_is_broadened(self, monkeypatch):
        """The secondary cause: a 12-word title matches nothing at any band."""
        from engine.stores import _store_ladder, search_stores

        title = "Pasabahce 2 Colorful Cups Saucers Dissolving Skyline Bone China 5oz"
        # The winning rung is one the ladder really builds, so this cannot
        # pass by accident on a string that is never queried.
        rungs = _store_ladder(title)
        winner = rungs[-1][0]
        calls = self._fake_ebay(monkeypatch, lambda q, band: (
            (50, [f"s{i}" for i in range(5)]) if q == winner else (0, [])
        ))

        rows, provenance = search_stores(title)

        assert len(rows) == 4
        assert calls[0][0] == title, "the exact title is always tried first"
        assert provenance["query_original"] == title
        assert provenance["query_used"] != title

    def test_it_stops_at_the_first_rung_that_works(self, monkeypatch):
        from engine.stores import _store_ladder, search_stores

        title = "Bosch Professional GSB 13 RE 18V Cordless Combi Drill Body Only"
        # Take a rung the ladder actually builds, so this cannot pass by
        # accident on a string the capped ladder never tries.
        rungs = _store_ladder(title)
        winner = rungs[-1][0]
        calls = self._fake_ebay(monkeypatch, lambda q, band: (
            (50, [f"s{i}" for i in range(5)]) if q == winner else (0, [])
        ))

        search_stores(title)

        hit_queries = {q for q, _band in calls}
        assert winner in hit_queries

    def test_a_thin_rung_does_not_end_the_search(self, monkeypatch):
        """C11 asks for UP TO 4 stores - one seller has not answered that.

        Measured: the Bosch drill yields 1 seller in the buying band and 4
        once the band widens. Stopping at the first hit would have preserved
        the exact single-store symptom this ladder exists to fix.
        """
        from engine.stores import search_stores

        title = "Bosch Professional GSB 13 RE 18V Cordless Combi Drill Body Only"
        self._fake_ebay(monkeypatch, lambda q, band: (
            (1, ["lonely_seller"]) if band == "5..35"
            else (42, [f"s{i}" for i in range(7)])
        ))

        rows, _provenance = search_stores(title)

        assert len(rows) == 4, [r["name"] for r in rows]
        assert "lonely_seller" in {r["name"] for r in rows}

    def test_the_ladder_is_bounded_so_a_rare_product_is_cheap(self, monkeypatch):
        """eBay bills per call; an unbounded walk cost 15 calls / 67s."""
        from engine.stores import MAX_LADDER_RUNGS, _store_ladder

        rungs = _store_ladder(
            "Pasabahce 2 Colorful Cups Saucers Dissolving Skyline Bone China 5oz"
        )
        assert len(rungs) <= MAX_LADDER_RUNGS
        # The cap must drop the BROADEST rungs, never the most precise.
        assert rungs[0][0].startswith("Pasabahce 2 Colorful Cups Saucers")

    def test_it_reports_that_the_search_was_broadened(self, monkeypatch):
        """C13: competitors from a broadened search must say so."""
        from engine.stores import search_stores

        title = "Pasabahce 2 Colorful Cups Saucers Dissolving Skyline Bone China 5oz"
        self._fake_ebay(monkeypatch, lambda q, band: (
            (50, [f"s{i}" for i in range(4)])
            if q != title else (0, [])
        ))

        rows, provenance = search_stores(title)

        assert rows
        assert provenance["broadened"] is True
        assert provenance["query_used"]
        assert provenance["reason"]

    def test_giving_up_returns_nothing_honestly(self, monkeypatch):
        from engine.stores import search_stores

        title = "Zzzqqq Nonexistent Product Xyzzy 12345"
        self._fake_ebay(monkeypatch, lambda q, band: (0, []))

        rows, provenance = search_stores(title)

        assert rows == []
        assert provenance["provenance"] == "unverified"
        assert provenance["reason"]

    def test_ladder_entries_are_unique(self):
        ladder = fallback_queries(
            "Pasabahce 2 Colorful Cups Saucers Dissolving Skyline Bone China"
        )
        assert len(ladder) == len(set(ladder))

    def test_the_ladder_runs_from_most_terms_to_fewest(self):
        """eBay matches ALL terms, so fewer terms = more results.

        Measured live: a 6-word reduction of a working title returned 0 items
        while the 4-word version returned 50. The caller stops at the first
        rung that hits, so the most precise rung must come first.
        """
        ladder = fallback_queries(
            "Greenhouse 6ft Polycarbonate Seed Starter with Ventilation"
        )
        counts = [len(q.split()) for q in ladder]
        assert counts == sorted(counts, reverse=True), counts

    def test_a_working_title_is_never_replaced_by_the_reduction(self):
        """The reduction is a LAST resort, not the primary query.

        The exact title is the most precise query available; reducing it first
        would throw away matches that already work.
        """
        title = "Greenhouse 6ft Polycarbonate Seed Starter with Ventilation"
        # The reduction exists as a function, but callers must try the title
        # first. This test pins the intent that started the regression.
        assert extract_query(title) != title or should_reduce(title) is False
