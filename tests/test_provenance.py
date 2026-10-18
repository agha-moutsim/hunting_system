"""C12 + C13: provenance foundation, verify-or-drop, no LLM-invented facts.

C13 — every factual value carries one of four labels:
      verified / estimated / unverified / ai_insight
      ai_insight is structurally barred from factual fields and from verdicts.

C12 — supplier rows are capped at what we could actually confirm; never
      padded with model guesses.

Regression targets (all real bugs found during review):
  * deep_search used to assign parsed["suppliers"] verbatim, so an invented
    price reached best_supplier_price -> profit -> verdict.
  * deep_search used to read parsed["ebay_top_sellers"], rendering an
    invented seller name with an invented eBay URL.
"""

import ast
import json

import pytest

import deep_search as ds
from engine.provenance import (
    FACT_FIELDS,
    Fact,
    Provenance,
    ProvenanceError,
    annotate,
    assert_not_ai_fact,
    estimated,
    unverified,
    verified,
)


# ---------------------------------------------------------------------------
# The enum itself
# ---------------------------------------------------------------------------

class TestProvenanceEnum:
    def test_four_tiers_only(self):
        assert {p.value for p in Provenance} == {
            "verified", "estimated", "unverified", "ai_insight"
        }

    @pytest.mark.parametrize("prov,label", [
        (Provenance.VERIFIED, "Verified"),
        (Provenance.ESTIMATED, "Estimated"),
        (Provenance.UNVERIFIED, "Unverified"),
        (Provenance.AI_INSIGHT, "AI Insight"),
    ])
    def test_human_labels(self, prov, label):
        assert prov.label == label

    @pytest.mark.parametrize("prov", list(Provenance))
    def test_every_tier_has_a_badge(self, prov):
        assert isinstance(prov.badge, str) and prov.badge

    def test_enum_is_string_valued(self):
        # Must serialise straight to JSON for the exporters.
        assert Provenance.VERIFIED == "verified"
        assert json.dumps({"p": Provenance.VERIFIED.value}) == '{"p": "verified"}'


# ---------------------------------------------------------------------------
# Fact — the guard rails
# ---------------------------------------------------------------------------

class TestFactGuards:
    def test_verified_fact_carries_source_url(self):
        f = verified(9.99, source_url="https://ebay.example/item/1")
        assert f.provenance is Provenance.VERIFIED
        assert f.source_url == "https://ebay.example/item/1"
        assert f.captured_at  # stamped automatically

    def test_estimate_without_method_is_refused(self):
        # An estimate with no stated method is just a guess wearing a label.
        with pytest.raises(ProvenanceError, match="method"):
            Fact(value=12.5, provenance="estimated")

    def test_estimate_with_method_is_allowed(self):
        f = estimated(12.5, method="median of 14 sold listings")
        assert f.provenance is Provenance.ESTIMATED
        assert "median" in f.method

    def test_fact_may_never_be_constructed_as_ai_insight(self):
        # AI insight is analysis, not data — it lives outside Fact entirely.
        with pytest.raises(ProvenanceError, match="ai_insight"):
            Fact(value="low competition", provenance="ai_insight")

    def test_only_verified_and_estimated_may_gate_a_verdict(self):
        assert verified(1).is_usable_for_verdict is True
        assert estimated(1, method="m").is_usable_for_verdict is True
        assert unverified(1).is_usable_for_verdict is False

    def test_unverified_never_silently_becomes_verified(self):
        f = unverified(None, reason="page fetch timed out")
        assert f.provenance is Provenance.UNVERIFIED
        assert f.value is None

    def test_string_provenance_is_coerced(self):
        f = Fact(value="x", provenance="unverified")
        assert f.provenance is Provenance.UNVERIFIED

    def test_to_dict_is_json_serialisable(self):
        f = verified("abc", source_url="https://u", source_name="eBay")
        payload = f.to_dict()
        assert json.loads(json.dumps(payload))["provenance"] == "verified"
        assert payload["label"] == "Verified"


# ---------------------------------------------------------------------------
# The C13 bar: ai_insight can never occupy a factual field
# ---------------------------------------------------------------------------

class TestAiInsightCannotBeAFact:
    @pytest.mark.parametrize("field", ["price", "url", "stock", "seller",
                                       "store_name", "supplier_name",
                                       "sold_count_30d", "condition"])
    def test_factual_fields_are_declared(self, field):
        assert field in FACT_FIELDS

    @pytest.mark.parametrize("field", ["price", "url", "supplier_name"])
    def test_ai_insight_in_a_fact_field_raises(self, field):
        payload = {field: "£5.99", "provenance": "ai_insight"}
        with pytest.raises(ProvenanceError, match="factual field"):
            assert_not_ai_fact(payload, field)

    def test_ai_insight_in_an_analysis_field_is_allowed(self):
        # competition_level / notes etc. ARE the model's job.
        assert assert_not_ai_fact(
            {"competition_level": "low", "provenance": "ai_insight"},
            "competition_level",
        ) is None

    def test_nested_payloads_are_walked(self):
        nested = {"suppliers": [{"price": 1, "provenance": "ai_insight"}]}
        with pytest.raises(ProvenanceError):
            assert_not_ai_fact(nested, "suppliers")

    def test_clean_payload_passes(self):
        assert assert_not_ai_fact({"price": 5, "url": "https://x"}, "price") is None

    def test_non_ai_provenance_in_fact_field_passes(self):
        assert assert_not_ai_fact(
            {"price": 5, "provenance": "verified"}, "price") is None


# ---------------------------------------------------------------------------
# Deep Search — the LLM must not be a source of sellers or supplier prices
# ---------------------------------------------------------------------------

_HALLUCINATED_LLM = json.dumps({
    "product_name": "Widget",
    "product_category": "widgets",
    "ebay_items_sold_month": "900-1100",
    "ebay_top_sellers": [
        {"name": "TOTALLY_MADE_UP_STORE",
         "url": "https://www.ebay.co.uk/itm/999999999999",
         "price": "£12.34"},
    ],
    "suppliers": [
        {"name": "FAKE_SUPPLIER_LTD",
         "price": 1.01,
         "url": "https://not-a-real-site.example/product",
         "supplier_type": "wholesaler"},
    ],
    "ebay_price_range": "£10.00 - £15.00 (avg £12.50)",
    "ebay_avg_price": 12.50,
    "supplier_candidates": [],
    "competition_level": "low",
    "profit_potential": "high",
    "delivery_info": "3-5 days",
    "notes": "looks good",
})


@pytest.fixture
def offline_deep_search(monkeypatch):
    """Run deep_search_product with every network/LLM dependency stubbed."""
    from scrapers.ebay_sold import EbaySoldScraper

    class _EmptySold:
        items = []
        total_sold_30d = 0
        total_sold_7d = 0
        top_sellers = []
        price_min = price_max = price_avg = price_median = 0.0
        # Real EbaySoldData always carries this (ebay_sold.py:69); the run
        # reads it to plot the distribution, so the fake must declare it.
        sold_prices: list = []

    monkeypatch.setattr(EbaySoldScraper, "get_sold_data",
                        lambda self, q: _EmptySold())
    monkeypatch.setattr(ds, "_web_search", lambda *a, **k: [])
    monkeypatch.setattr(ds, "_fetch_page_text", lambda *a, **k: "")
    monkeypatch.setattr(ds, "_ollama_generate",
                        lambda *a, **k: _HALLUCINATED_LLM)
    # Nothing the model proposed could be confirmed against a live page.
    monkeypatch.setattr(ds, "_verify_supplier_candidates",
                        lambda query, cands, deadline=None: [])
    return ds.deep_search_product("widget")


@pytest.fixture
def full_deep_search(monkeypatch):
    """Same stubs, but sold data and suppliers are NON-EMPTY.

    The empty fixture never enters the branches that stamp provenance with
    source_name/source_url, which is exactly how a signature mismatch on
    set_fact_provenance() survived P2. This one must not raise.
    """
    from scrapers.ebay_sold import EbaySoldScraper

    class _FullSold:
        items = [type("I", (), {"url": "https://ebay.co.uk/itm/1"})()]
        total_sold_30d = 42
        total_sold_7d = 9
        top_sellers = [{"name": "good_store", "url": "https://ebay.co.uk/str/good_store",
                        "sold_count": 42, "total_price": 500.0, "avg_price": 11.9}]
        price_min = 8.0
        price_max = 15.0
        price_avg = 11.9
        price_median = 11.5
        # The rows behind those four numbers (ebay_sold.py:417 derives them
        # from exactly this list). Chosen so the list reproduces them:
        # min 8, max 15, mean 59.5/5 = 11.9, median 11.5. The run reads it
        # to plot the distribution, so the fake must carry it.
        sold_prices = [8.0, 11.5, 11.5, 13.5, 15.0]
        # This fake models the SOLD-page path — total_sold_30d is a real 42 —
        # so the live-listing list is empty, exactly as the real dataclass
        # leaves it. Present-but-empty rather than absent, so the stand-in
        # keeps the same shape as EbaySoldData.
        active_prices = []

    monkeypatch.setattr(EbaySoldScraper, "get_sold_data",
                        lambda self, q: _FullSold())
    monkeypatch.setattr(ds, "_web_search", lambda *a, **k: [])
    monkeypatch.setattr(ds, "_fetch_page_text", lambda *a, **k: "")
    monkeypatch.setattr(ds, "_ollama_generate",
                        lambda *a, **k: _HALLUCINATED_LLM)
    monkeypatch.setattr(ds, "_verify_supplier_candidates",
                        lambda query, cands, deadline=None: [
        # C14 — a real row always carries the title read off its own page,
        # which is what the matcher scores against. The stub must too, or
        # the row has nothing to match on and gets dropped.
        {"name": "shop.example", "price": 5.0, "url": "https://shop.example/p",
         "product_title": "widget",
         "supplier_type": "retailer", "provenance": "verified",
         "source_url": "https://shop.example/p", "source_name": "shop.example"},
    ])
    return ds.deep_search_product("widget")


class TestProvenanceStampingWithRealData:
    """Regression: set_fact_provenance() was called with a source_name kwarg
    its signature did not accept. The empty-data fixture never reached those
    call sites, so the suite stayed green while Deep Search 500'd the moment
    eBay returned anything."""

    def test_non_empty_branch_does_not_raise(self, full_deep_search):
        result = full_deep_search
        assert result.ebay_total_sold_30d == 42
        assert result.ebay_top_sellers  # real data present
        assert result.suppliers          # real data present

    def test_source_name_reaches_the_stamp(self, full_deep_search):
        stamp = full_deep_search.field_provenance["ebay_total_sold_30d"]
        assert stamp["provenance"] == Provenance.VERIFIED.value
        assert "eBay" in stamp.get("source_name", "")

    def test_supplier_stamp_carries_source_name(self, full_deep_search):
        stamp = full_deep_search.field_provenance["suppliers"]
        assert stamp["provenance"] == Provenance.VERIFIED.value
        assert stamp.get("source_name")

    def test_real_stores_survive_the_llm_pop(self, full_deep_search):
        # Real retrieval-layer stores must NOT be wiped by the C13 pop,
        # which only ever targets the LLM's key.
        assert [s["name"] for s in full_deep_search.ebay_top_sellers] == ["good_store"]

    def test_estimated_profit_stamp_states_method(self, full_deep_search):
        for name, entry in full_deep_search.field_provenance.items():
            if entry.get("provenance") == Provenance.ESTIMATED.value:
                assert entry.get("method") or entry.get("reason"), name


class TestEveryNumberCarriesItsLabel:
    """B3. C13 says the label travels with the number.

    `ebay_items_sold_month` was stamped only on the NO-DATA branch. On the
    branch where eBay did answer, the value is `{n} items` read straight
    off the API (deep_search.py:776) but the field is never stamped, so
    build_provenance_block falls back to "no data retrieved" for a number
    we are holding - a lie in the direction that makes good data look
    absent.
    """

    def test_monthly_sales_is_stamped_when_ebay_answered(self, full_deep_search):
        assert full_deep_search.ebay_items_sold_month, "fixture must hold a value"
        stamp = full_deep_search.field_provenance.get("ebay_items_sold_month")
        assert stamp is not None, (
            "unstamped fields report 'no data retrieved' while holding the value"
        )
        assert stamp.get("provenance") == Provenance.VERIFIED.value

    def test_monthly_sales_is_stamped_unverified_when_ebay_had_nothing(
        self, offline_deep_search
    ):
        """The LLM may have filled it in; it must never read as verified."""
        stamp = offline_deep_search.field_provenance.get("ebay_items_sold_month", {})
        assert stamp.get("provenance") == Provenance.UNVERIFIED.value

    def test_avg_price_is_stamped_when_ebay_answered(self, full_deep_search):
        stamp = full_deep_search.field_provenance.get("ebay_avg_price")
        assert stamp is not None
        assert stamp.get("provenance") == Provenance.VERIFIED.value


class TestNoUnknownKwargsReachStampers:
    """Static guard: every kwarg passed to set_fact_provenance() and
    Fact-style helpers must exist on the definition. Catches this whole
    bug class without needing a live branch."""

    @staticmethod
    def _kwargs_for_call(call: ast.Call) -> set:
        return {k.arg for k in call.keywords if k.arg}

    @staticmethod
    def _def_args(func: ast.FunctionDef) -> set:
        return {a.arg for a in func.args.args} | {a.arg for a in func.args.kwonlyargs}

    def test_set_fact_provenance_kwargs_are_all_declared(self):
        with open(ds.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        defs = {n.name: TestNoUnknownKwargsReachStampers._def_args(n)
                for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert "set_fact_provenance" in defs
        accepted = defs["set_fact_provenance"] - {"self"}
        bad = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                if n.func.attr == "set_fact_provenance":
                    extra = TestNoUnknownKwargsReachStampers._kwargs_for_call(n) - accepted
                    if extra:
                        bad.append((n.lineno, sorted(extra)))
        assert not bad, f"unexpected kwargs passed to set_fact_provenance: {bad}"


class TestLLMIsNotASourceOfSellers:
    def test_invented_store_name_never_reaches_the_result(self, offline_deep_search):
        names = [s.get("name") for s in offline_deep_search.ebay_top_sellers]
        assert "TOTALLY_MADE_UP_STORE" not in names
        assert offline_deep_search.ebay_top_sellers == []

    def test_invented_ebay_url_never_reaches_the_result(self, offline_deep_search):
        urls = [s.get("url") for s in offline_deep_search.ebay_top_sellers]
        assert "https://www.ebay.co.uk/itm/999999999999" not in urls

    def test_top_sellers_stamp_is_not_verified_when_empty(self, offline_deep_search):
        stamp = offline_deep_search.field_provenance.get("ebay_top_sellers", {})
        assert stamp.get("provenance") == Provenance.UNVERIFIED.value


class TestLLMIsNotASourceOfSupplierPrices:
    def test_invented_supplier_row_is_dropped(self, offline_deep_search):
        names = [s.get("name") for s in offline_deep_search.suppliers]
        assert "FAKE_SUPPLIER_LTD" not in names
        assert offline_deep_search.suppliers == []

    def test_invented_price_cannot_reach_best_supplier_price(self, offline_deep_search):
        # The regression: 1.01 fed profit and could manufacture a PASS.
        assert offline_deep_search.best_supplier_price == 0.0

    def test_supplier_stamp_reads_unverified_when_nothing_confirmed(
            self, offline_deep_search):
        stamp = offline_deep_search.field_provenance.get("suppliers", {})
        assert stamp.get("provenance") == Provenance.UNVERIFIED.value


class TestProvenanceStamping:
    def test_analysis_fields_are_tagged_ai_insight(self, offline_deep_search):
        fp = offline_deep_search.field_provenance
        for name in ("competition_level", "profit_potential",
                     "delivery_info", "notes"):
            assert fp[name]["provenance"] == Provenance.AI_INSIGHT.value

    def test_ai_insight_stamp_never_appears_on_a_factual_field(
            self, offline_deep_search):
        for name, entry in offline_deep_search.field_provenance.items():
            if entry.get("provenance") == Provenance.AI_INSIGHT.value:
                assert name not in FACT_FIELDS, name

    def test_estimates_state_their_method(self, offline_deep_search):
        # profit_analysis is estimated — see export; here confirm no bare
        # 'estimated' label escapes without one somewhere in the map.
        for name, entry in offline_deep_search.field_provenance.items():
            if entry.get("provenance") == Provenance.ESTIMATED.value:
                assert entry.get("method") or entry.get("reason")


# ---------------------------------------------------------------------------
# Verify-or-drop: a candidate row exists only if its page was read
# ---------------------------------------------------------------------------

def _fake_page(price_json=None, title="Some Product", html=""):
    if price_json:
        return f'<html><head><title>{title}</title></head>' \
               f'<script type="application/ld+json">{json.dumps(price_json)}</script>' \
               f'<body><h1>{title}</h1></body></html>'
    return f'<html><head><title>{title}</title></head><body>{html}</body></html>'


class TestVerifySupplierCandidates:
    def _patch(self, monkeypatch, pages):
        """pages: url -> html ('' means the fetch failed)."""
        class _Resp:
            def __init__(self, text):
                self.text = text
            def raise_for_status(self):
                return None

        def _get(url, headers=None, timeout=None):
            if url not in pages:
                raise ds.requests.RequestException("nope")
            return _Resp(pages[url])

        monkeypatch.setattr(ds.requests, "get", _get)

    def test_confirmed_page_becomes_a_verified_row(self, monkeypatch):
        html = _fake_page({"offers": {"price": "19.99"}}, title="Drill 18V")
        self._patch(monkeypatch, {"https://shop.example/drill": html})
        rows = ds._verify_supplier_candidates(
            "drill",
            [{"url": "https://shop.example/drill", "why": "same model"}],
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["price"] == 19.99
        assert row["product_title"] == "Drill 18V"
        assert row["url"] == "https://shop.example/drill"
        assert row["provenance"] == Provenance.VERIFIED.value
        assert row["source_url"] == row["url"]
        assert row["supplier_type"] == "unknown"

    def test_unreachable_page_is_dropped_not_shown(self, monkeypatch):
        self._patch(monkeypatch, {})
        rows = ds._verify_supplier_candidates(
            "drill", [{"url": "https://gone.example/x"}])
        assert rows == []

    def test_page_with_no_price_is_dropped(self, monkeypatch):
        self._patch(monkeypatch, {
            "https://shop.example/noprice": "<html><title>Hi</title></html>",
        })
        rows = ds._verify_supplier_candidates(
            "drill", [{"url": "https://shop.example/noprice"}])
        assert rows == []

    def test_page_with_no_title_is_dropped(self, monkeypatch):
        self._patch(monkeypatch, {
            "https://shop.example/notitle": "<html><body>£9.99</body></html>",
        })
        # Title extraction falls back to og:title/h1 — provide neither.
        rows = ds._verify_supplier_candidates(
            "drill", [{"url": "https://shop.example/notitle"}])
        assert rows == []

    def test_non_http_candidate_is_ignored(self, monkeypatch):
        self._patch(monkeypatch, {})
        assert ds._verify_supplier_candidates(
            "drill", [{"url": "javascript:alert(1)"}, {"url": ""}]) == []

    def test_duplicate_urls_are_collapsed(self, monkeypatch):
        html = _fake_page({"offers": {"price": 5}}, title="T")
        self._patch(monkeypatch, {"https://a.example/p": html})
        rows = ds._verify_supplier_candidates(
            "x", [{"url": "https://a.example/p"}, {"url": "https://a.example/p"}])
        assert len(rows) == 1

    def test_never_pads_past_seven(self, monkeypatch):
        pages, cands = {}, []
        for i in range(12):
            url = f"https://s{i}.example/p"
            pages[url] = _fake_page({"offers": {"price": 5 + i}}, title=f"P{i}")
            cands.append({"url": url})
        self._patch(monkeypatch, pages)
        rows = ds._verify_supplier_candidates("x", cands)
        assert len(rows) == 7  # C12 hard cap
        assert len({r["url"] for r in rows}) == 7

    def test_malformed_candidate_entries_are_skipped(self, monkeypatch):
        self._patch(monkeypatch, {})
        assert ds._verify_supplier_candidates("x", ["just-a-string", None, 42]) == []

    def test_retailer_domains_are_classified_as_retailers(self):
        from engine.source_type import supplier_type_from_url, supplier_type
        assert supplier_type_from_url("https://www.amazon.co.uk/dp/B0") == "retailer"
        assert supplier_type_from_url("https://www.toolstation.com/x") == "retailer"
        assert supplier_type_from_url("https://www.aliexpress.com/item/1") == "dropshipper"
        assert supplier_type_from_url("https://cjdropshipping.com/p") == "dropshipper"
        # An unrecognised host is unknown — never assumed dropshipper (C13).
        assert supplier_type_from_url("https://random-shop.example/p") == "unknown"
        assert supplier_type_from_url("") == "unknown"
        # Falls back to the name when no URL exists, else unknown.
        assert supplier_type(name="Amazon UK") == "retailer"
        assert supplier_type(name="some shop") == "unknown"


class TestSystemPromptProhibitsFacts:
    """The prompt must not ASK the model for sellers/suppliers any more."""

    def test_prompt_has_no_seller_array(self):
        assert '"ebay_top_sellers"' not in ds._SYSTEM_PROMPT

    def test_prompt_has_no_supplier_price_array(self):
        assert '"suppliers":' not in ds._SYSTEM_PROMPT

    def test_prompt_asks_for_candidates_only(self):
        assert "supplier_candidates" in ds._SYSTEM_PROMPT

    def test_prompt_tells_the_model_not_to_invent_names_or_prices(self):
        assert "NEVER return a supplier name" in ds._SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Export carries provenance (C13)
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self):
        self.product_name = "Widget"
        self.product_category = "tools"
        self.ebay_items_sold_month = "100 items"
        self.ebay_top_sellers = []
        self.ebay_price_range = ""
        self.ebay_avg_price = 12.5
        self.ebay_price_min = 10.0
        self.ebay_price_max = 15.0
        self.ebay_price_median = 12.5
        self.ebay_total_sold_30d = 100
        self.ebay_total_sold_7d = 25
        self.ebay_condition = "New"
        self.suppliers = [{
            "name": "shop.example",
            "full_name": "shop.example",
            "price": 5.0,
            "url": "https://shop.example/p",
            "supplier_type": "retailer",
            "delivery_days": "3-5",
            "provenance": "verified",
            "source_url": "https://shop.example/p",
            "source_name": "shop.example",
        }]
        self.best_supplier_price = 5.0
        self.verdict = "PASS"
        self.competition_level = "low"
        self.profit_potential = "high"
        self.delivery_info = "3-5"
        self.notes = "n"
        self.sources = []
        self.raw_analysis = ""
        self.field_provenance = {
            "ebay_total_sold_30d": {"provenance": "verified",
                                    "label": "Verified",
                                    "source_name": "eBay Browse API"},
            "ebay_top_sellers": {"provenance": "unverified",
                                 "label": "Unverified",
                                 "reason": "no eBay sold data retrieved"},
            "ebay_avg_price": {"provenance": "verified", "label": "Verified"},
            "ebay_condition": {"provenance": "verified", "label": "Verified"},
            "suppliers": {"provenance": "verified", "label": "Verified",
                          "source_name": "live product pages (fetched)"},
            "competition_level": {"provenance": "ai_insight",
                                  "label": "AI Insight",
                                  "method": "LLM analysis"},
        }


class TestJsonExportProvenance:
    def test_top_level_provenance_block_present(self):
        from export.format import format_to_schema
        out = format_to_schema(_FakeResult())
        prov = out["provenance"]
        assert prov["demand"]["provenance"] == "verified"
        assert prov["suppliers"]["provenance"] == "verified"
        assert prov["top_eBay_sellers"]["provenance"] == "unverified"

    def test_profit_analysis_is_labelled_an_estimate_with_a_method(self):
        from export.format import format_to_schema
        prov = format_to_schema(_FakeResult())["provenance"]["profit_analysis"]
        assert prov["provenance"] == "estimated"
        assert prov["method"]  # C13: estimates state their method

    def test_every_entry_in_provenance_block_has_label(self):
        from export.format import format_to_schema
        prov = format_to_schema(_FakeResult())["provenance"]
        for key, entry in prov.items():
            if key == "fields":
                continue
            assert entry["label"], key

    def test_supplier_rows_carry_provenance_and_source_url(self):
        from export.format import format_to_schema
        sup = format_to_schema(_FakeResult())["suppliers"][0]
        assert sup["provenance"] == "verified"
        assert sup["provenance_label"] == "Verified"
        assert sup["source_url"] == sup["link"]

    def test_field_map_is_exported(self):
        from export.format import format_to_schema
        out = format_to_schema(_FakeResult())
        assert out["provenance"]["fields"]["ebay_avg_price"]["provenance"] == "verified"

    def test_missing_stamp_reports_unverified_never_verified(self):
        # A result built before this change must not read as confirmed.
        from export.format import format_to_schema
        bare = _FakeResult()
        bare.field_provenance = {}
        prov = format_to_schema(bare)["provenance"]
        assert prov["demand"]["provenance"] == "unverified"
        assert prov["suppliers"]["provenance"] == "unverified"

    def test_garbage_stamp_is_coerced_to_unverified(self):
        from export.format import format_to_schema
        bare = _FakeResult()
        bare.field_provenance = {"ebay_total_sold_30d": {"provenance": "banana"}}
        prov = format_to_schema(bare)["provenance"]
        assert prov["demand"]["provenance"] == "unverified"

    def test_empty_top_seller_row_is_marked_unverified(self):
        from export.format import format_to_schema
        res = _FakeResult()
        res.ebay_top_sellers = [{"name": "no-url-store", "url": ""}]
        seller = format_to_schema(res)["top_eBay_sellers"][0]
        assert seller["provenance"] == "unverified"

    def test_top_seller_with_url_is_verified(self):
        from export.format import format_to_schema
        res = _FakeResult()
        res.ebay_top_sellers = [{"name": "store", "url": "https://ebay.co.uk/i/1"}]
        seller = format_to_schema(res)["top_eBay_sellers"][0]
        assert seller["provenance"] == "verified"


class TestCsvExportProvenance:
    def test_single_header_carries_provenance_columns(self):
        from export.csv_export import export_to_csv
        header = export_to_csv(_FakeResult()).splitlines()[0].split(",")
        for col in ("Demand Provenance", "Top Sellers Provenance",
                    "Suppliers Provenance", "Profit Provenance"):
            assert col in header, col

    def test_single_row_reports_labels(self):
        from export.csv_export import export_to_csv
        lines = export_to_csv(_FakeResult()).splitlines()
        row = lines[1]
        assert "Verified" in row
        assert "Unverified" in row
        assert "Estimated" in row  # profit is always an estimate

    def test_bulk_header_carries_provenance_columns(self):
        from export.csv_export import export_bulk_to_csv
        header = export_bulk_to_csv([_FakeResult()]).splitlines()[0].split(",")
        assert "Demand Provenance" in header
        assert "Suppliers Provenance" in header

    def test_unstamped_result_reports_unverified_not_verified(self):
        from export.csv_export import export_to_csv
        bare = _FakeResult()
        bare.field_provenance = {}
        row = export_to_csv(bare).splitlines()[1]
        assert "Unverified" in row


class TestAnnotateShim:
    def test_annotate_adds_keys(self):
        out = annotate({}, Provenance.VERIFIED, source_url="https://x",
                       source_name="eBay")
        assert out["provenance"] == "verified"
        assert out["provenance_label"] == "Verified"
        assert out["source_url"] == "https://x"

    def test_annotate_tolerates_missing_optionals(self):
        out = annotate({"a": 1}, Provenance.UNVERIFIED)
        assert out["provenance"] == "unverified"
        assert "source_url" not in out


# ---------------------------------------------------------------------------
# The analyzer LLM's "best supplier" choice must bind to a real row (C12/C13)
# ---------------------------------------------------------------------------

_SUPPLIERS = [
    {"name": "AliExpress - StoreA", "full_name": "StoreA",
     "source": "AliExpress", "url": "https://aliexpress.com/item/1", "price": 4.5},
    {"name": "Amazon UK", "full_name": "Amazon UK",
     "source": "Amazon UK", "url": "https://amazon.co.uk/dp/B0", "price": 7.99},
]


class TestResolveSupplierChoice:
    def test_exact_name_resolves(self):
        from pipeline import _resolve_supplier_choice
        got = _resolve_supplier_choice("Amazon UK", _SUPPLIERS)
        assert got is not None and got["url"] == "https://amazon.co.uk/dp/B0"

    def test_case_insensitive_resolves(self):
        from pipeline import _resolve_supplier_choice
        assert _resolve_supplier_choice("amazon uk", _SUPPLIERS) is not None

    def test_compound_display_name_resolves_to_its_row(self):
        from pipeline import _resolve_supplier_choice
        got = _resolve_supplier_choice("AliExpress - StoreA", _SUPPLIERS)
        assert got is not None and got["source"] == "AliExpress"

    def test_invented_name_is_dropped(self):
        # The regression: a plausible name that was never on the list.
        from pipeline import _resolve_supplier_choice
        assert _resolve_supplier_choice("Genuine Wholesalers Ltd", _SUPPLIERS) is None

    def test_empty_or_none_input_is_dropped(self):
        from pipeline import _resolve_supplier_choice
        assert _resolve_supplier_choice("", _SUPPLIERS) is None
        assert _resolve_supplier_choice(None, _SUPPLIERS) is None
        assert _resolve_supplier_choice("Amazon UK", []) is None
        assert _resolve_supplier_choice("Amazon UK", None) is None

    def test_single_character_answer_cannot_match_everything(self):
        # "a" is a substring of every name — must not bind.
        from pipeline import _resolve_supplier_choice
        assert _resolve_supplier_choice("a", _SUPPLIERS) is None
        assert _resolve_supplier_choice("z", _SUPPLIERS) is None

    def test_short_partial_names_stay_unbound(self):
        # Length floor: sub-4-char targets only match on exact equality.
        from pipeline import _resolve_supplier_choice
        assert _resolve_supplier_choice("Am", _SUPPLIERS) is None


class TestAnalyzePromptCannotAssumeNew:
    def test_missing_condition_reads_as_unknown_not_new(self):
        from llm.prompts import build_analysis_prompt
        prompt = build_analysis_prompt(
            {"title": "t", "price": 1, "condition": ""},
            {}, [],
        )
        assert "Condition: unknown" in prompt
        assert "Condition: New" not in prompt

    def test_real_condition_is_passed_through(self):
        from llm.prompts import build_analysis_prompt
        prompt = build_analysis_prompt(
            {"title": "t", "price": 1, "condition": "Used"},
            {}, [],
        )
        assert "Condition: Used" in prompt

    def test_system_prompt_forbids_invented_facts(self):
        from llm.prompts import SYSTEM_PROMPT
        assert "never invent a supplier name" in SYSTEM_PROMPT

    def test_analysis_prompt_binds_choice_to_the_list(self):
        from llm.prompts import ANALYSIS_PROMPT
        assert "copied EXACTLY from the list above" in ANALYSIS_PROMPT
