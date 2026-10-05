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

    def test_the_deep_search_call_site_passes_the_constant(self):
        source = (BACKEND / "deep_search.py").read_text(encoding="utf-8")
        code = re.sub(r"#.*", "", source)
        calls = re.findall(r"(?<!def )_ollama_generate\(([^)]*)\)", code, re.S)
        assert calls, "no _ollama_generate call found - did the call site change?"
        for args in calls:
            assert "timeout=OLLAMA_TIMEOUT_S" in args, (
                f"an Ollama call site does not use the constant: {args.strip()[:70]}"
            )

    def test_the_analysis_pipeline_call_site_passes_the_constant(self):
        source = (BACKEND / "analysis_pipeline.py").read_text(encoding="utf-8")
        code = re.sub(r"#.*", "", source)
        assert "timeout=OLLAMA_TIMEOUT_S" in code, (
            "analysis_pipeline's LLM wait does not use the shared constant"
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
    def test_scrape_budget_stays_at_45(self):
        """45s is still correct for a web scrape - only the LLM budget moved.
        Changing this too would have made eBay calls hang for two minutes."""
        source = (BACKEND / "analysis_pipeline.py").read_text(encoding="utf-8")
        assert "SCRAPER_TIMEOUT_S = 45.0" in source