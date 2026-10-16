"""
REGRESSION-009 — the browser semaphore must survive a second event loop.

The API builds a fresh event loop per request (`run_async`). `asyncio.Semaphore`
binds itself to the first loop that awaits it, so a module-level one made
every request after the first lose half its supplier scrapers.
"""

import asyncio

import pytest

import analysis_pipeline as ap


@pytest.fixture(autouse=True)
def _no_real_scrapers(monkeypatch):
    """Replace every scraper class with a stub that records concurrency."""
    state = {"active": 0, "peak": 0, "calls": []}

    class _Stub:
        def __init__(self):
            pass

        async def search(self, query):
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            state["calls"].append(query)
            try:
                await asyncio.sleep(0.02)
                return []
            finally:
                state["active"] -= 1

        async def close(self):
            return None

    import scrapers.aliexpress as ae
    import scrapers.bandq as bq
    import scrapers.cjdropshipping as cj
    import scrapers.toolstation as ts

    monkeypatch.setattr(ae, "AliExpressScraper", _Stub)
    monkeypatch.setattr(bq, "BandQScraper", _Stub)
    monkeypatch.setattr(cj, "CJDropshippingScraper", _Stub)
    monkeypatch.setattr(ts, "ToolstationScraper", _Stub)

    # Discovery is not under test and would spend SerpApi budget.
    import scrapers.serpapi_discovery as sd

    monkeypatch.setattr(sd, "discover", lambda q: [])

    state["stub"] = _Stub
    return state


class TestSemaphoreSurvivesANewLoop:

    def test_a_second_call_on_a_new_loop_still_runs_every_scraper(self, _no_real_scrapers):
        """The bug: run 1 = 4 scrapers, runs 2+ = 2."""
        for _ in range(3):
            _no_real_scrapers["calls"].clear()
            rows = ap.run_async(ap.search_all_suppliers("garden hose"))
            assert rows == []
            assert len(_no_real_scrapers["calls"]) == 4, (
                "a scraper was dropped by a stale semaphore: "
                f"{_no_real_scrapers['calls']}"
            )

    def test_three_consecutive_calls_are_identical(self, _no_real_scrapers):
        counts = []
        for _ in range(3):
            _no_real_scrapers["calls"].clear()
            ap.run_async(ap.search_all_suppliers("cordless drill"))
            counts.append(len(_no_real_scrapers["calls"]))
        assert counts == [4, 4, 4], f"scraper count changed between calls: {counts}"

    def test_a_scraper_error_is_still_reported_not_raised(self, _no_real_scrapers):
        """A semaphore fault must never look like a scraper fault."""
        stub = _no_real_scrapers["stub"]

        class _Boom(stub):
            async def search(self, query):
                raise RuntimeError("site is down")

        import scrapers.toolstation as ts

        import scrapers.aliexpress  # noqa: F401
        # Patch only the module attribute the pipeline imports at call time.
        original = ts.ToolstationScraper
        ts.ToolstationScraper = _Boom
        try:
            rows = ap.run_async(ap.search_all_suppliers("yoga mat"))
            assert rows == []
        finally:
            ts.ToolstationScraper = original


class TestConcurrencyCapStillApplies:

    def test_the_cap_is_still_two_concurrent_browsers(self, _no_real_scrapers):
        ap.run_async(ap.search_all_suppliers("led desk lamp"))
        assert _no_real_scrapers["peak"] <= ap.BROWSER_CONCURRENCY, (
            f"peak concurrency {_no_real_scrapers['peak']} exceeded the cap"
        )

    def test_the_cap_is_two_not_seven(self, _no_real_scrapers):
        """The cap exists to stop 7 Chromium instances OOMing the process."""
        assert ap.BROWSER_CONCURRENCY == 2

    def test_no_module_level_semaphore_remains(self):
        """Guards the regression directly: anything named like the old
        constant must not come back at module scope."""
        offenders = [
            n for n in dir(ap)
            if "SEMAPHORE" in n.upper() and not callable(getattr(ap, n))
        ]
        assert offenders == [], f"module-level semaphore(s) reintroduced: {offenders}"