"""One timeout value, in one place.

`45.0` was written as a literal in four separate Ollama call sites: the client
default, the analysis_pipeline call, deep_search's wrapper default, and
deep_search's call site. Nothing kept them in step, which is precisely how a
tuning decision has to be made four times and then missed in two of them.

These tests read the source rather than the objects, because the failure being
prevented is textual: a fifth call site with its own number. Asserting on the
imported objects would still pass with a stray literal somewhere.
"""

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"

# Modules that talk to Ollama. A timeout literal in any of them is the smell.
OLLAMA_CALLERS = [
    "llm/ollama_client.py",
    "llm/analyzer.py",
    "deep_search.py",
    "analysis_pipeline.py",
]


class TestTheConstantExistsAndIsLongEnough:
    def test_the_shared_constant_is_defined(self):
        from config import OLLAMA_TIMEOUT_S

        assert isinstance(OLLAMA_TIMEOUT_S, float)

    def test_it_clears_the_analyses_that_were_being_cut_off(self):
        """The 45s wall was discarding brand and condition extraction on slow
        runs. It must not be back to a value that truncates real work."""
        from config import OLLAMA_TIMEOUT_S

        assert OLLAMA_TIMEOUT_S >= 120.0, (
            f"timeout is {OLLAMA_TIMEOUT_S}s - that is what timed out before"
        )

    def test_it_is_env_overridable(self, monkeypatch):
        """Tunable without a code edit, like every other Ollama setting."""
        import importlib

        import config

        monkeypatch.setenv("OLLAMA_TIMEOUT_S", "90")
        reloaded = importlib.reload(config)
        try:
            assert reloaded.OLLAMA_TIMEOUT_S == 90.0
        finally:
            monkeypatch.delenv("OLLAMA_TIMEOUT_S", raising=False)
            importlib.reload(config)


class TestNoCallSiteHardcodesItsOwn:
    """Scoped to the Ollama entry points, deliberately.

    A first version of this test banned every `timeout=` literal in these four
    modules and immediately flagged deep_search's 30/20/15s scraper and
    store-ladder timeouts, which have nothing to do with the LLM. The rule
    worth enforcing is narrow: the Ollama budget comes from the constant. The
    HTTP budgets are separate policies and stay where they are.
    """

    def test_the_client_default_is_the_constant(self):
        import inspect

        from config import OLLAMA_TIMEOUT_S
        from llm.ollama_client import OllamaClient

        default = inspect.signature(OllamaClient.__init__).parameters["timeout"].default
        assert default == OLLAMA_TIMEOUT_S

    def test_the_deep_search_wrapper_default_is_the_constant(self):
        import inspect

        from config import OLLAMA_TIMEOUT_S
        from deep_search import _ollama_generate

        default = inspect.signature(_ollama_generate).parameters["timeout"].default
        assert default == OLLAMA_TIMEOUT_S

    def test_the_deep_search_call_site_derives_its_budget_from_the_constant(self):
        """A1.4 — the wait is capped by what is left of the run's own budget,
        so the site passes `min(OLLAMA_TIMEOUT_S, remaining)` rather than the
        constant itself. Two things still hold: nothing here may be a literal,
        and the CEILING must still be the shared constant — otherwise the
        model is handed the route's whole 120 s again and the overrun this
        file exists to prevent comes straight back.
        """
        source = (BACKEND / "deep_search.py").read_text(encoding="utf-8")
        code = re.sub(r"#.*", "", source)
        calls = re.findall(r"(?<!def )_ollama_generate\(([^)]*)\)", code, re.S)
        assert calls, "no _ollama_generate call found - did the call site change?"
        for args in calls:
            assert "timeout=OLLAMA_TIMEOUT_S" not in args, (
                "passing the constant outright gives the model the whole route "
                "budget; cap it by what the run has left"
            )
            assert re.search(r"timeout\s*=\s*[A-Za-z_]", args), (
                f"an Ollama call site hardcodes its budget: {args.strip()[:70]}"
            )
        assert "min(OLLAMA_TIMEOUT_S" in code, (
            "the capped budget is no longer derived from the shared constant"
        )

    def test_the_analysis_pipeline_does_not_call_the_model(self):
        """Phase A1 — the synchronous path stopped talking to Ollama.

        The rule this replaced was narrower ("the wait uses the constant").
        The honest form is stronger: there is no call here at all, so there
        is no budget to police. `analyzer.analyze` is the model entry point;
        a fifth call site appearing in this module would be the regression,
        not merely the timeout it carried.
        """
        source = (BACKEND / "analysis_pipeline.py").read_text(encoding="utf-8")
        code = re.sub(r"#.*", "", source)

        assert "analyzer.analyze(" not in code, (
            "analysis_pipeline calls the model on the synchronous path"
        )

    @pytest.mark.parametrize("relpath", OLLAMA_CALLERS)
    def test_a_bare_45_is_never_an_ollama_budget(self, relpath):
        """45s is the SCRAPER budget now, expressed as a named constant. A bare
        numeric 45 in a timeout position can only be the old LLM wall creeping
        back in."""
        source = (BACKEND / relpath).read_text(encoding="utf-8")
        code = re.sub(r"#.*", "", source)
        bare = re.findall(r"timeout\s*[:=]\s*45(\.0)?\b", code)
        assert not bare, (
            f"{relpath} sets a bare 45s timeout - that was the LLM wall. "
            f"Use OLLAMA_TIMEOUT_S, or SCRAPER_TIMEOUT_S for web requests."
        )


class TestTheScraperTimeoutIsUntouched:
    """The scraper budget is a NAMED constant, not the old LLM wall.

    2026-10: the value moved 45.0 -> 70.0. The original 45 was written to keep
    this constant distinct from OLLAMA_TIMEOUT_S (which is 120), and that is
    still the property worth guarding. Its old docstring claimed raising it
    "would have made eBay calls hang for two minutes" - which was never true:
    this constant governs only the parallel supplier fan-out in
    analysis_pipeline, and eBay requests carry their own 15-20s timeouts.

    What changed the value was measurement: AliExpress returns 20 products in
    61.46s and was being discarded at 45s, so the fan-out was throwing away the
    one supplier that reliably works.
    """

    def test_scrape_budget_stays_a_named_constant(self):
        source = (BACKEND / "analysis_pipeline.py").read_text(encoding="utf-8")
        assert "SCRAPER_TIMEOUT_S = 70.0" in source

    def test_scrape_budget_clears_the_measured_slowest_supplier(self):
        """If this ever drops below the slowest supplier we measured, that
        supplier is silently cut off again and the fan-out returns less than
        it actually found."""
        import re

        source = (BACKEND / "analysis_pipeline.py").read_text(encoding="utf-8")
        match = re.search(r"SCRAPER_TIMEOUT_S\s*=\s*([0-9.]+)", source)
        assert match, "SCRAPER_TIMEOUT_S must stay a named constant"
        value = float(match.group(1))
        # AliExpress: 61.46s in the 2026-10 health check, and it WORKS.
        assert value >= 65.0, (
            f"SCRAPER_TIMEOUT_S is {value}s but AliExpress needs ~61.5s - it "
            f"would be discarded before it returns anything"
        )

    def test_scrape_budget_never_exceeds_the_pipeline_budget(self):
        """The fan-out runs inside PIPELINE_TIMEOUT_S, so the per-scraper cap
        must leave room for the eBay query and the supplier scoring stage."""
        import re

        source = (BACKEND / "analysis_pipeline.py").read_text(encoding="utf-8")
        scraper = float(re.search(r"SCRAPER_TIMEOUT_S\s*=\s*([0-9.]+)", source).group(1))
        pipeline = float(re.search(r"PIPELINE_TIMEOUT_S\s*=\s*([0-9.]+)", source).group(1))
        assert scraper < pipeline, (
            f"per-scraper cap ({scraper}s) must leave room inside the pipeline "
            f"budget ({pipeline}s)"
        )

    def test_scrape_budget_does_not_bound_the_llm_budget(self):
        """The property the 45 originally existed to protect."""
        source = (BACKEND / "analysis_pipeline.py").read_text(encoding="utf-8")
        assert "SCRAPER_TIMEOUT_S = 70.0" in source
        assert "SCRAPER_TIMEOUT_S = 45.0" not in source
        assert "OLLAMA_TIMEOUT_S" not in source, (
            "the supplier budget must never be where the LLM budget lives"
        )