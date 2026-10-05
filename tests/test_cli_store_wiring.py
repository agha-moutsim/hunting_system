"""C11 + C13 for the CLI surface: `pipeline.py`.

`pipeline.py` is the one consumer of DecisionEngine that never asked for
competitor stores. It therefore reported no Competition row at all - honest,
but inconsistent with the other four surfaces, and the CLI is what you would
use for a nightly bulk run, where "am I already competing against anyone" is
the question that decides whether an opportunity is real.

The wiring mirrors `analysis_pipeline`:

  * `resolve_stores(demand=..., query=..., provenance=...)` is preferred, so
    sellers already on the sold response cost nothing extra;
  * a network failure degrades to [] + UNVERIFIED and must NOT take the
    analysis down - stores are additive, not load-bearing;
  * the count reaches the verdict as an ADVISORY row via the shared provenance
    block, so a short or widened search stays a floor rather than a total;
  * the CLI's own filter serializer must carry the `advisory` flag, or a
    consumer of its JSON cannot tell an information row from a rule.

ZERO NETWORK: every `requests` call is killed and the band pinned to defaults,
so an unstubbed collaborator fails loudly instead of quietly reaching eBay.
"""

import pytest

import pipeline as pl
from engine.decisions import DecisionEngine
from engine.provenance import Provenance
from engine.stores import store_provenance_block
from scrapers.base import DemandData, ScrapedProduct


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    import json

    import requests
    import utils.filters as uf

    def _no_network(*a, **k):
        raise AssertionError("the CLI test reached the network")

    monkeypatch.setattr(requests, "get", _no_network)
    monkeypatch.setattr(requests, "post", _no_network)

    target = tmp_path / "custom_filters.json"
    target.write_text(json.dumps({"active": {}, "presets": {}}))
    monkeypatch.setattr(uf, "FILTERS_FILE", target)
    uf._cache["mtime"] = None
    uf._cache["data"] = None
    yield
    uf._cache["mtime"] = None
    uf._cache["data"] = None


def _store(name, sold=3):
    return {
        "name": name,
        "url": f"https://www.ebay.co.uk/str/{name}",
        "url_derived": True,
        "sold_count": sold,
        "sold_count_label": f"{sold} listings observed in the search window",
    }


def _product():
    return ScrapedProduct(
        source="ebay_uk", title="Greenhouse 6ft", price=30.0,
        url="https://www.ebay.co.uk/itm/1", condition="New", verified=True,
    )


def _demand():
    return DemandData(
        sold_count_30d=40, sold_count_7d=12, verified=True, verified_7d=True,
    )


def _pipeline():
    return pl.Pipeline(filters={"price_min": 5.0, "price_max": 35.0})


class TestTheCliRecordsRealStores:
    def test_stores_are_attached_to_the_result(self, monkeypatch):
        stores = [_store("outsunny"), _store("k.jon2020")]
        monkeypatch.setattr(
            pl, "resolve_stores",
            lambda **kw: stores, raising=False,
        )

        result = pl.PipelineResult()
        _pipeline()._attach_stores(_demand(), "greenhouse 6ft", result)

        assert [s["name"] for s in result.ebay_stores] == ["outsunny", "k.jon2020"]

    def test_the_provenance_stamp_travels_with_them(self, monkeypatch):
        monkeypatch.setattr(pl, "resolve_stores", lambda **kw: [_store("a")],
                            raising=False)

        result = pl.PipelineResult()
        _pipeline()._attach_stores(_demand(), "greenhouse 6ft", result)

        assert result.ebay_stores_provenance["store_count"] == 1
        # a short list is a floor, not a total
        assert result.ebay_stores_provenance["provenance"] == Provenance.UNVERIFIED.value

    def test_a_search_failure_degrades_instead_of_killing_the_analysis(self, monkeypatch):
        """Stores are additive. A network error must cost the store block and
        nothing else - the product still gets its verdict."""
        def boom(**kw):
            raise RuntimeError("eBay is down")

        monkeypatch.setattr(pl, "resolve_stores", boom, raising=False)

        result = pl.PipelineResult()
        _pipeline()._attach_stores(_demand(), "greenhouse 6ft", result)

        assert result.ebay_stores == []
        assert result.ebay_stores_provenance["provenance"] == Provenance.UNVERIFIED.value
        assert result.errors == [], "a store failure must not be reported as a run error"

    def test_no_stores_found_is_unverified_not_verified(self, monkeypatch):
        monkeypatch.setattr(pl, "resolve_stores", lambda **kw: [], raising=False)

        result = pl.PipelineResult()
        _pipeline()._attach_stores(_demand(), "greenhouse 6ft", result)

        assert result.ebay_stores_provenance["provenance"] == Provenance.UNVERIFIED.value


class TestTheCliVerdictSeesTheCount:
    def test_the_stored_count_is_what_reaches_the_engine(self, monkeypatch):
        """End to end through _evaluate_and_profit: the number on the result is
        the number the verdict row quotes."""
        stores = [_store("outsunny"), _store("k.jon2020")]
        monkeypatch.setattr(pl, "resolve_stores", lambda **kw: stores,
                            raising=False)

        pipeline = _pipeline()
        result = pl.PipelineResult()
        pipeline._attach_stores(_demand(), "greenhouse 6ft", result)

        supplier = ScrapedProduct(
            source="Toolstation", title="6ft Greenhouse", price=10.0,
            url="https://www.toolstation.com/p/1", condition="", verified=True,
        )
        pipeline._evaluate_and_profit(
            _product(), _demand(), {"Toolstation": [supplier]}, None, result,
        )

        row = next(
            f for f in result.verdict["filters"] if f["name"] == "Competition"
        )
        assert "2" in row["actual"]
        assert row["advisory"] is True, (
            "the CLI serializer must mark the row advisory, or a JSON consumer "
            "cannot tell an information row from a rule that decides"
        )

    def test_zero_stores_reaches_the_engine_as_a_demand_warning(self, monkeypatch):
        monkeypatch.setattr(pl, "resolve_stores", lambda **kw: [],
                            raising=False)

        pipeline = _pipeline()
        result = pl.PipelineResult()
        pipeline._attach_stores(_demand(), "greenhouse 6ft", result)

        supplier = ScrapedProduct(
            source="Toolstation", title="6ft Greenhouse", price=10.0,
            url="https://www.toolstation.com/p/1", condition="", verified=True,
        )
        pipeline._evaluate_and_profit(
            _product(), _demand(), {"Toolstation": [supplier]}, None, result,
        )

        row = next(
            f for f in result.verdict["filters"] if f["name"] == "Competition"
        )
        assert "no competitor stores" in row["actual"].lower()
        assert row["verified"] is False

    def test_the_stores_reach_the_cli_json_output(self, monkeypatch):
        """The CLI returns dicts, not objects - the stores have to be in
        to_dict() or they are invisible to whoever runs it."""
        monkeypatch.setattr(pl, "resolve_stores", lambda **kw: [_store("outsunny")],
                            raising=False)

        result = pl.PipelineResult()
        _pipeline()._attach_stores(_demand(), "greenhouse 6ft", result)

        payload = result.to_dict()
        assert payload["ebay_stores"][0]["name"] == "outsunny"
        assert "store_count" in payload["ebay_stores_provenance"]


class TestTheCountStillCannotDecide:
    def test_the_verdict_is_identical_with_and_without_competitors(self, monkeypatch):
        """Advisory means advisory. If the store count could move the verdict,
        this would be a threshold nobody set."""
        def run_with(stores):
            monkeypatch.setattr(pl, "resolve_stores", lambda **kw: stores,
                                raising=False)
            pipeline = _pipeline()
            result = pl.PipelineResult()
            pipeline._attach_stores(_demand(), "greenhouse 6ft", result)
            supplier = ScrapedProduct(
                source="Toolstation", title="6ft Greenhouse", price=10.0,
                url="https://www.toolstation.com/p/1", condition="", verified=True,
            )
            pipeline._evaluate_and_profit(
                _product(), _demand(), {"Toolstation": [supplier]}, None, result,
            )
            return result.verdict["verdict"]

        assert run_with([]) == run_with([_store(f"s{i}") for i in range(4)])