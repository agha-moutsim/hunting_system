r"""Phase 0 â€” every pipeline run reports where its seconds went.

Nothing about the 150s Analyze timeout could be diagnosed without this: the
only way to learn that the LLM was taking 86.6s and supplier search 51.5s was
to run the pipeline by hand with a stopwatch. A result that does not carry
its own timings makes every future timeout a guessing game again.

The seam is `run_analysis_pipeline`'s returned dict â€” the same object
`POST /api/analyze` hands to the client â€” so the timings are observable
wherever the analysis is observed, without reaching into the pipeline.
"""

import asyncio
import time

import pytest

import analysis_pipeline as ap
import api.analyze as analyze_api
from scrapers.ebay import EbayScraper
from scrapers.ebay_sold import EbaySoldScraper

from tests.test_store_wiring import (
    _FakeAnalyzer,
    _Stub,
    _demand,
    _ebay_product,
    _sold_data,
)

# Steps the pipeline is required to account for. A step that is skipped
# still reports itself (with 0.0) so its absence is a choice, not a hole.
REQUIRED_STEPS = ("ebay", "demand", "suppliers", "llm")


def _stub_network(monkeypatch):
    """Stub every network collaborator so nothing external is needed.

    A plain function, not a fixture: the codebase's other end-to-end drivers
    (`_run_analysis`, `_run_pipeline`) take `monkeypatch` and call their
    stubbing directly, and class-scoped fixtures cannot see this file's
    module-scoped one.
    """
    async def _no_suppliers(query, progress=None):
        return []

    monkeypatch.setattr(ap, "apply_purchase_history",
                        lambda demand, url, db=None: demand)
    monkeypatch.setattr(ap, "search_all_suppliers", _no_suppliers)
    monkeypatch.setattr(ap, "ProductAnalyzer", _FakeAnalyzer)
    monkeypatch.setattr(EbayScraper, "search", _Stub(result=[_ebay_product()]))
    monkeypatch.setattr(EbayScraper, "get_details", _Stub(result=_ebay_product()))
    monkeypatch.setattr(EbayScraper, "get_sold_data", _Stub(result=_demand([])))
    monkeypatch.setattr(EbaySoldScraper, "get_sold_data",
                        _Stub(result=_sold_data(top=False)))


@pytest.fixture()
def _quiet(monkeypatch):
    _stub_network(monkeypatch)
    print("QUIET RAN ->", EbayScraper.search)


@pytest.fixture()
def run(_quiet):
    """Run the pipeline with every network collaborator stubbed."""
    def _go():
        return ap.run_async(ap.run_analysis_pipeline("generic widget"))

    return _go


class TestTheRunReportsItsOwnTiming:
    def test_the_result_carries_a_timing_block(self, run):
        """Red: today the result has no timings at all, so a timeout can
        only ever be explained by re-running with a stopwatch."""
        result = run()

        assert "timing" in result, "results must report where the time went"
        assert isinstance(result["timing"], dict)

    def test_every_step_accounts_for_itself(self, run):
        result = run()

        timing = result["timing"]
        for step in REQUIRED_STEPS:
            assert step in timing, f"step {step!r} did not report a duration"
            assert timing[step] >= 0.0

    def test_the_durations_are_plausible_not_guessed(self, run):
        """They must be measured (small, non-zero for work actually done),
        not a constant dressed up as a measurement."""
        timing = run()["timing"]

        assert all(isinstance(v, float) for v in timing.values())
        # A stubbed run finishes fast; anything claiming seconds of real work
        # here would be a fabricated number, which is the failure C13 exists
        # to prevent.
        assert timing["ebay"] < 10.0

    def test_the_result_carries_the_budget_it_was_given(self, run):
        result = run()

        assert "budget" in result
        budget = result["budget"]
        assert budget["budget_s"] > 0
        # Wall clock: it must cover every step it accounted for, and report
        # the difference rather than hiding time it cannot explain.
        assert budget["total_s"] >= sum(result["timing"].values()) - 0.01
        assert budget["unaccounted_s"] >= 0.0
        assert budget["total_s"] == pytest.approx(
            budget["unaccounted_s"] + sum(result["timing"].values()), abs=0.01
        )

    def test_an_impossible_budget_is_reported_as_an_overrun(self, monkeypatch):
        """Not tautological: the budget is the input here, so the assertion
        comes from outside the code that computes `overrun`."""
        monkeypatch.setattr(ap, "PIPELINE_TIMEOUT_S", 0.0)

        async def _no_suppliers(query, progress=None):
            return []

        monkeypatch.setattr(ap, "apply_purchase_history",
                            lambda demand, url, db=None: demand)
        monkeypatch.setattr(ap, "search_all_suppliers", _no_suppliers)
        monkeypatch.setattr(ap, "ProductAnalyzer", _FakeAnalyzer)
        monkeypatch.setattr(EbayScraper, "search", _Stub(result=[_ebay_product()]))
        monkeypatch.setattr(EbayScraper, "get_details", _Stub(result=_ebay_product()))
        monkeypatch.setattr(EbayScraper, "get_sold_data", _Stub(result=_demand([])))
        monkeypatch.setattr(EbaySoldScraper, "get_sold_data",
                            _Stub(result=_sold_data(top=False)))

        budget = ap.run_async(ap.run_analysis_pipeline("generic widget"))["budget"]

        assert budget["budget_s"] == 0.0
        assert budget["overrun"] is True

    def test_a_generous_budget_is_not_an_overrun(self, run):
        budget = run()["budget"]

        assert budget["overrun"] is False


_TIMING = {
    "ebay": 3.0,
    "demand": 1.7,
    "suppliers": 51.5,
    "llm": 86.6,
}
_BUDGET = {
    "total_s": 143.0,
    "budget_s": 150.0,
    "unaccounted_s": 0.2,
    "overrun": False,
}


class TestTheEndpointCarriesTheAccounting:
    """The pipeline's timings are only useful if they reach the client â€”
    a timeout is diagnosed from the HTTP response, not from the process."""

    @pytest.fixture()
    def client(self, monkeypatch):
        from fastapi.testclient import TestClient
        from main import app

        async def _fake(query, is_url=False, filters=None, progress=None,
                        timing_sink=None):
            return {
                "ebay_product": None,
                "demand": None,
                "supplier_matches": [],
                "llm_analysis": None,
                "verdict": None,
                "scorecard": "",
                "errors": [],
                "ebay_stores": [],
                "ebay_stores_provenance": None,
                "timing": dict(_TIMING),
                "budget": dict(_BUDGET),
            }

        monkeypatch.setattr(analyze_api, "run_analysis_pipeline", _fake)
        return TestClient(app)

    def test_a_finished_run_reaches_the_client_intact(self, client):
        """The serializer must not drop it â€” a field nobody receives is a
        field that explains nothing."""
        out = client.post("/api/analyze", json={"query": "generic widget"}).json()

        assert out["timing"] == _TIMING
        assert out["budget"] == _BUDGET

    def test_a_timed_out_run_says_it_overran(self, monkeypatch):
        """On the path that actually needs diagnosing, the client must still
        be told the budget was blown rather than being handed silence."""
        from fastapi.testclient import TestClient
        from main import app

        def _boom(coro, timeout=None):
            coro.close()  # nothing awaits it â€” silence the warning
            raise TimeoutError("analysis timed out")

        monkeypatch.setattr(analyze_api, "run_async", _boom)
        out = TestClient(app).post(
            "/api/analyze", json={"query": "generic widget"}
        ).json()

        assert out["budget"]["overrun"] is True
        assert out["budget"]["budget_s"] > 0
        assert out["ebay_stores_provenance"]["provenance"] == "unverified"


class TestTheMeasurementsSurviveTheCancellation:
    """The whole point is diagnosing a run that NEVER FINISHES. A timing
    block only written into the returned dict is discarded by the very
    timeout it exists to explain â€” the one case where it is needed, it is
    gone. So the caller hands the pipeline a sink it keeps a reference to."""

    def test_a_cancelled_run_still_writes_its_timings(self, _quiet, monkeypatch):
        async def _hang(query, progress=None):
            await asyncio.Event().wait()  # never returns â€” we cancel instead

        monkeypatch.setattr(ap, "search_all_suppliers", _hang)

        async def _scenario():
            sink: dict = {}
            task = asyncio.create_task(
                ap.run_analysis_pipeline("generic widget", timing_sink=sink)
            )
            await asyncio.sleep(0.3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return sink

        sink = ap.run_async(_scenario())

        # Steps completed before the cancellation are reported...
        assert sink.get("timing", {}).get("ebay", 0.0) > 0.0
        assert sink.get("timing", {}).get("demand", 0.0) > 0.0
        # ...and the budget is stated even though nothing was returned.
        assert sink["budget"]["overrun"] in (True, False)

    def test_the_endpoint_reports_the_steps_it_finished(self, monkeypatch):
        """A real timeout, the real runner, no stubbed exception â€” the
        response must carry the per-step accounting of the run that died."""
        from fastapi.testclient import TestClient
        from main import app

        async def _slow(query, is_url=False, filters=None, progress=None,
                        timing_sink=None):
            if timing_sink is not None:
                timing_sink["timing"] = dict(_TIMING)
                timing_sink["budget"] = dict(_BUDGET)
            await asyncio.Event().wait()

        monkeypatch.setattr(analyze_api, "run_analysis_pipeline", _slow)
        monkeypatch.setattr(analyze_api, "PIPELINE_TIMEOUT_S", 0.2)

        out = TestClient(app).post(
            "/api/analyze", json={"query": "generic widget"}
        ).json()

        assert out["timing"] == _TIMING, "the timings must outlive the run"
        assert out["budget"]["overrun"] is True


_STORES = [
    {
        "username": f"seller{i}",
        "url": f"https://www.ebay.co.uk/str/seller{i}",
        "url_derived": True,
        "source": "top_seller",
    }
    for i in range(4)
]


def _ebay_with_image():
    """The analysed listing, carrying an image so C14 has a reference hash to
    compare candidate supplier images against."""
    product = _ebay_product()
    product.image_url = "https://i.ebayimg.example/reference.jpg"
    return product


def _widget_row(i: int):
    from scrapers.base import ScrapedProduct

    return ScrapedProduct(
        source=f"supplier_{i}",
        title="Generic widget",
        price=9.99 + i,
        url=f"https://supplier.example/{i}",
        condition="New",
        image_url=f"https://supplier.example/{i}.jpg",
    )


def _run_sync_path(monkeypatch):
    """Drive the pipeline the way POST /api/analyze does, with every network
    collaborator stubbed and the model client booby-trapped."""
    async def _suppliers(query, progress=None):
        return [_widget_row(0)]

    class _MustNotBeBuilt:
        def __init__(self, *a, **k):
            raise AssertionError(
                "the synchronous path must not construct a model client"
            )

    _stub_network(monkeypatch)
    monkeypatch.setattr(ap, "search_all_suppliers", _suppliers)
    monkeypatch.setattr(ap, "resolve_stores", lambda *a, **k: list(_STORES))
    monkeypatch.setattr(ap, "ProductAnalyzer", _MustNotBeBuilt)
    monkeypatch.setattr(ap, "PIPELINE_TIMEOUT_S", 5.0)

    return ap.run_async(
        ap.run_analysis_pipeline("generic widget", timing_sink={}),
        timeout=ap.PIPELINE_TIMEOUT_S,
    )


class TestTheSyncPathNeverWaitsOnTheModel:
    """A1 — the synchronous path does not ask the model at all.

    Measured on this machine the 8B model has nowhere to sit: the GPU is a
    GT 430 with 1 GB, so llama3.1:8b runs on the CPU and took 43.7s of a
    150s budget. The verdict did not need it — engine/match.py and
    engine/source_type.py fix match_score/supplier_type/provenance without
    the LLM, and DecisionEngine.evaluate takes no LLM parameter.

    So this is not "a shorter timeout". No client is built, and the AI
    comes back absent rather than as the dataclass default that reads like
    a verdict nobody gave (brand_verdict="ambiguous").
    """

    def test_the_stores_and_suppliers_still_survive(self, monkeypatch):
        """The work the run actually did is the point of removing the wait —
        four real stores and the suppliers must come back, not be cancelled."""
        results = _run_sync_path(monkeypatch)

        assert len(results["ebay_stores"]) == 4
        assert results["supplier_matches"]

    def test_the_model_client_is_never_built(self, monkeypatch):
        """RED today: `_MustNotBeBuilt` raises the instant a client is
        constructed, and the pipeline's catch-all records it as an error.
        So an error-free run is the proof that this path never asks."""
        results = _run_sync_path(monkeypatch)

        assert results["errors"] == [], (
            "the synchronous path constructed a model client: "
            f"{results['errors']}"
        )

    def test_the_ai_is_absent_not_invented(self, monkeypatch):
        from llm.analyzer import UNVERIFIED_DEFAULT

        results = _run_sync_path(monkeypatch)

        assert results["llm_analysis"] is None
        # The default dataclass is what used to be written to the database
        # as though an AI had said it, with no flag marking it a default.
        assert results["llm_analysis"] is not UNVERIFIED_DEFAULT

    def test_no_message_claims_the_ai_said_something(self, monkeypatch):
        results = _run_sync_path(monkeypatch)

        assert not any("AI analysis" in e for e in results["errors"])
        # Accounted for, at zero — the step is budgeted and spent nothing,
        # which is different from being missing from the accounting.
        assert results["timing"]["llm"] >= 0.0

    def test_it_finished_inside_the_budget_it_was_given(self, monkeypatch):
        started = time.monotonic()
        results = _run_sync_path(monkeypatch)
        elapsed = time.monotonic() - started

        assert elapsed < 5.0, f"took {elapsed:.1f}s of a 5.0s budget"
        assert results["budget"]["overrun"] is False


def _run_slow_images(monkeypatch, **budget):
    """Six supplier rows whose images each cost 0.4s to hash, so the step's
    budget is observable as wall-clock time rather than as an internal call."""
    def _slow(url):
        if not url:
            return None
        time.sleep(0.4)   # stands in for the image download
        return 12345      # a real hash, so the matcher keeps the row

    async def _suppliers(query, progress=None):
        return [_widget_row(i) for i in range(6)]

    _stub_network(monkeypatch)
    monkeypatch.setattr(ap, "search_all_suppliers", _suppliers)
    monkeypatch.setattr(ap, "resolve_stores", lambda *a, **k: [])
    monkeypatch.setattr(ap, "image_hash_for", _slow)
    monkeypatch.setattr(ap, "PIPELINE_TIMEOUT_S", 20.0)
    monkeypatch.setattr(EbayScraper, "search", _Stub(result=[_ebay_with_image()]))
    monkeypatch.setattr(EbayScraper, "get_details",
                        _Stub(result=_ebay_with_image()))
    for name, value in budget.items():
        monkeypatch.setattr(ap, name, value)

    return ap.run_async(ap.run_analysis_pipeline("generic widget"))


class TestTheSuppliersStepCannotConsumeTheWholeBudget:
    """A1.3 â€” the 90s guard covers only the search.

    `asyncio.wait_for(search_all_suppliers, 90.0)` returns at
    analysis_pipeline and the step keeps going: the reference image is
    hashed, then every surviving row downloads its own image
    (engine/match.py image_hash_for, 5s per distinct URL, uncached across
    hosts). That tail is what took the step to 101.2s of a 150s budget
    while every guard in the search reported it was behaving.

    The step therefore owns a budget, and a run decides ONCE whether image
    verification is on: a C12 ranking that compared image-verified rows
    against text-only rows would not be a ranking at all.
    """

    def test_a_scoring_budget_of_zero_stops_the_downloads(self, monkeypatch):
        """RED today: the reference hash plus six rows download regardless of
        what the step was allowed to spend."""
        results = _run_slow_images(monkeypatch, SUPPLIER_SCORE_BUDGET_S=0.0)

        assert results["timing"]["suppliers"] < 1.0, (
            "with no scoring budget the step must not be paying for images "
            f"(took {results['timing']['suppliers']:.1f}s)"
        )
        # The rows are still there â€” scored on title and price, which is
        # exactly what C1 says an unavailable component costs.
        assert len(results["supplier_matches"]) == 6

    def test_the_run_says_it_scored_without_the_image(self, monkeypatch):
        results = _run_slow_images(monkeypatch, SUPPLIER_SCORE_BUDGET_S=0.0)

        assert any(
            "image" in e.lower() and "skipped" in e.lower()
            for e in results["errors"]
        ), "a run that dropped image verification must say so"

    def test_a_normal_budget_still_buys_image_verification(self, monkeypatch):
        results = _run_slow_images(monkeypatch, SUPPLIER_SCORE_BUDGET_S=30.0)

        assert not any("image" in e.lower() and "skipped" in e.lower()
                       for e in results["errors"])
        # Proof the downloads really happened, rather than a note that is
        # simply never emitted either way.
        assert results["timing"]["suppliers"] > 1.5

    def test_the_step_reports_a_duration_that_fits_its_budget(self, monkeypatch):
        results = _run_slow_images(monkeypatch, SUPPLIER_SCORE_BUDGET_S=0.0)

        assert results["timing"]["suppliers"] < 1.0
        assert results["budget"]["overrun"] is False



def _make_session(tmp_path, monkeypatch):
    """A throwaway database, swapped in for the real one the pipeline opens."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db.database import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'a1.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    monkeypatch.setattr(ap, "SessionLocal", session)
    return session


def _prior_run_with_ai(session):
    """An earlier analysis that DID have an AI behind it."""
    from db.queries import save_analysis_data, save_product

    db = session()
    try:
        product_id = save_product(db, _ebay_product())
        save_analysis_data(db, product_id, {
            "brand_verdict": "generic",
            "brand_reasoning": "prior run",
            "demand_assessment": "strong",
            "demand_reasoning": "prior run",
            "supplier_match_notes": "prior run",
            "llm_raw_response": "{}",
        })
        return product_id
    finally:
        db.close()


def _run_persist(**overrides):
    results = {
        "ebay_product": _ebay_product(),
        "demand": None,
        "supplier_matches": [],
        "llm_analysis": None,
        "verdict": None,
        "scorecard": "",
    }
    results.update(overrides)
    ap.save_analysis_to_db(results)


class TestAnAbsentAiLeavesNoOldVerdictBehind:
    """A1.2 - `save_product` reuses the existing Product row for the same eBay
    URL, and `save_analysis_data` only writes when it is called. So a run with
    no AI leaves the PREVIOUS run's Analysis row standing, and History reads
    that verdict as this run's - an AI verdict for an analysis that had no AI.

    The row is cleared instead: absent has to look absent."""

    def test_the_old_verdict_is_cleared_when_the_ai_did_not_run(
            self, tmp_path, monkeypatch):
        from db.models import Analysis

        session = _make_session(tmp_path, monkeypatch)
        product_id = _prior_run_with_ai(session)
        _run_persist(llm_analysis=None)

        db = session()
        try:
            row = db.query(Analysis).filter_by(product_id=product_id).first()
        finally:
            db.close()

        assert row is None, (
            "a run with no AI left the previous run's verdict standing, and "
            "History would show it as this run's"
        )

    def test_a_run_that_did_have_an_ai_still_writes_one(
            self, tmp_path, monkeypatch):
        from db.models import Analysis
        from llm.analyzer import LLMAnalysis

        session = _make_session(tmp_path, monkeypatch)
        product_id = _prior_run_with_ai(session)
        _run_persist(llm_analysis=LLMAnalysis(
            brand_verdict="generic",
            brand_reasoning="this run",
            demand_assessment="strong",
            demand_reasoning="this run",
            supplier_type_reasoning="this run",
            raw_response="{}",
        ))

        db = session()
        try:
            row = db.query(Analysis).filter_by(product_id=product_id).first()
        finally:
            db.close()

        assert row is not None
        assert row.brand_reasoning == "this run"
